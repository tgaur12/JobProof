// Run with the local FastAPI server on port 8000. Chrome messaging is simulated;
// the adapter, content script, background worker, and HTTP analysis are real.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
const read = relative => fs.readFileSync(path.join(root, relative), "utf8");
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function waitFor(predicate, label) {
    const started = Date.now();
    while (!predicate()) {
        if (Date.now() - started > 18000) throw new Error(`Timed out waiting for ${label}`);
        await pause(25);
    }
}

function assertCombined(card, result, securityScore) {
    const ml = result.checks.machine_learning;
    assert.equal(result.security_score, securityScore);
    assert.equal(ml.status, "ready");
    assert.equal(ml.analyzed, true);
    assert.ok(Number.isFinite(ml.fraud_probability) && ml.fraud_probability >= 0 && ml.fraud_probability <= 1);
    assert.ok(Number.isInteger(result.ml_score) && result.ml_score >= 0 && result.ml_score <= 100);
    assert.ok(Math.abs(result.ml_score - ml.fraud_probability * 100) <= 0.500001);
    assert.equal(ml.ml_score, result.ml_score);
    assert.ok(ml.input_fields.includes("title") && ml.input_fields.includes("description"));
    assert.ok(Array.isArray(ml.missing_fields));
    assert.equal(result.score_type, "combined");
    assert.equal(result.score_formula, "max(security_score, ml_score)");
    assert.equal(result.final_score, Math.max(securityScore, result.ml_score));
    assert.equal(result.risk_score, result.final_score);
    let color = result.final_score >= 60 ? "red" : result.final_score >= 20 ? "yellow" : "green";
    if (result.assessment_status === "preliminary" && color === "green") color = "yellow";
    assert.equal(result.color, color);
    assert.equal(card.dataset.jobproofRisk, color);
    assert.ok(!result.pending_checks.includes("machine_learning_prediction"));
    assert.ok(card.querySelector(".jobproof-status").textContent.includes(`${result.final_score}/100`));
    const scoreRows = [...card.querySelectorAll(".jobproof-scores > div")].map(row => [
        row.querySelector("dt").textContent, row.querySelector("dd").textContent
    ]);
    assert.deepEqual(scoreRows, [["Final score", `${result.final_score}/100`], ["Security score", `${securityScore}/100`], ["ML score", `${result.ml_score}/100`]]);
    assert.ok(card.querySelector(".jobproof-formula").textContent.includes("max(Security, ML)"));
}

(async () => {
    const health = await fetch("http://127.0.0.1:8000/health");
    assert.equal(health.status, 200, "Start the local API before running this test.");
    const readiness = await health.json();
    assert.equal(readiness.analysis_mode, "security_and_ml", "The integrated API must have ready saved-model artifacts.");
    assert.equal(readiness.machine_learning.status, "ready");
    let listener;
    const requests = [];
    const results = new Map();
    const worker = vm.createContext({
        chrome: { runtime: {
            id: "jobproof-test",
            onMessage: { addListener(callback) { listener = callback; } }
        } },
        async fetch(url, options) {
            assert.equal(url, "http://127.0.0.1:8000/analyze");
            const job = JSON.parse(options.body);
            requests.push(job);
            const response = await fetch(url, options);
            results.set(job, await response.clone().json());
            return response;
        },
        AbortController, Error, TypeError, SyntaxError, setTimeout, clearTimeout
    });
    vm.runInContext(read("extension/background.js"), worker);
    const dom = new JSDOM(read("tests/indeed.html"), {
        url: "http://localhost:8080/indeed.html", runScripts: "outside-only"
    });
    const observers = [];
    const NativeObserver = dom.window.MutationObserver;
    dom.window.MutationObserver = class extends NativeObserver {
        constructor(callback) { super(callback); observers.push(this); }
    };
    dom.window.chrome = { runtime: { sendMessage(message) {
        return new Promise((resolve, reject) => {
            if (!listener(message, { id: "jobproof-test", tab: { id: 1 } }, resolve)) {
                reject(new Error("The background worker closed the message channel."));
            }
        });
    } } };
    const document = dom.window.document;
    const first = document.querySelector('[data-jk="fixture_microsoft"]');
    const second = document.querySelector('[data-jk="fixture_cisco"]');
    const allSettled = () => [...document.querySelectorAll(".jobproof-card")].every(card => card.dataset.jobproofRisk
        && card.querySelector(".jobproof-retry")?.disabled === false);
    const latestResult = card => results.get(requests.findLast(job => new URL(job.listing_url).searchParams.get("jk") === card.dataset.jk));
    try {
        dom.window.eval(read("tests/indeed.js"));
        dom.window.eval(read("extension/indeed.js"));
        dom.window.eval(read("extension/content.js"));
        await waitFor(() => requests.length === 2 && allSettled(), "initial preliminary results");
        assert.equal(requests.length, 2);
        assert.ok(requests.every(job => job.url === null && !job.description_complete));
        for (const card of [first, second]) {
            const result = latestResult(card);
            assertCombined(card, result, 0);
            assert.equal(result.assessment_status, "preliminary");
            assert.notEqual(result.color, "green", "Incomplete platform coverage cannot receive green.");
            assert.ok(result.pending_checks.includes("application_url_analysis"));
        }
        console.log("PASS snippet assessments expose real ML scores while incomplete platform coverage remains preliminary");

        first.querySelector("a.jcs-JobTitle").click();
        await waitFor(() => requests.length === 3 && allSettled(), "full Microsoft details");
        assertCombined(first, latestResult(first), 0);
        assert.equal(latestResult(first).assessment_status, "complete");
        assert.equal(latestResult(second).assessment_status, "preliminary");
        assert.equal(requests.at(-1).url, "https://careers.microsoft.com/");
        assert.equal(requests.at(-1).description_complete, true);
        console.log("PASS matching full details and an official destination produce complete max-score assessments");

        document.querySelector("#change-job").click();
        await waitFor(() => requests.length === 4 && allSettled(), "suspicious selected listing");
        assertCombined(first, latestResult(first), 100);
        assert.ok(first.querySelector(".jobproof-body").textContent.includes("upfront"));
        assert.ok(first.querySelector(".jobproof-status").textContent.includes("100/100"));
        console.log("PASS a changed description and HTTP IP-address destination automatically produce red");

        document.querySelector("#load-job").click();
        const added = document.querySelector('[data-jk="fixture_loaded_1"]');
        await waitFor(() => requests.length === 5 && allSettled(), "dynamically loaded result");
        assertCombined(added, latestResult(added), 0);
        assert.equal(latestResult(added).assessment_status, "preliminary");
        assert.equal(added.querySelectorAll(":scope > .jobproof-panel").length, 1);
        console.log("PASS dynamically loaded Indeed-style cards are analyzed without refreshing");

        second.querySelector("a.jcs-JobTitle").click();
        await waitFor(() => requests.length === 7 && allSettled(), "job selection switch");
        assertCombined(second, latestResult(second), 0);
        assertCombined(first, latestResult(first), 0);
        assert.equal(latestResult(second).assessment_status, "complete");
        assert.equal(latestResult(first).assessment_status, "preliminary");
        const latestCisco = requests.findLast(job => job.company === "Cisco" && job.description_complete);
        assert.ok(latestCisco.description.includes("Investigate network incidents"));
        assert.ok(!latestCisco.description.includes("Pay $200"));
        const count = requests.length;
        await pause(350);
        assert.equal(requests.length, count, "Rendering must not trigger additional API requests.");
        console.log("PASS shared detail panes stay bound to the selected job without request loops");
        console.log("Verified 5 Indeed fixture scenarios through the real local API.");
    } finally {
        for (const observer of observers) observer.disconnect();
        dom.window.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
