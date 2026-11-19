// Presentation demo integration check. Start the local FastAPI API on port 8000.
// Chrome messaging is simulated; fixture controls, extraction, background fetch,
// cybersecurity scoring, and saved-model inference use the real project code.
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

function assertUnanalyzed(document) {
    assert.equal(document.querySelectorAll("[data-jobproof-risk], .jobproof-card, .jobproof-panel").length, 0,
        "The demo must let the extension supply results and risk colors.");
}

function assertCombined(card, result, securityScore) {
    const ml = result.checks.machine_learning;
    assert.equal(result.security_score, securityScore);
    assert.equal(ml.status, "ready");
    assert.equal(ml.analyzed, true);
    assert.equal(typeof ml.fraud_probability, "number");
    assert.ok(Number.isFinite(ml.fraud_probability) && ml.fraud_probability >= 0 && ml.fraud_probability <= 1);
    assert.ok(Number.isInteger(result.ml_score) && result.ml_score >= 0 && result.ml_score <= 100);
    assert.ok(Math.abs(result.ml_score - ml.fraud_probability * 100) <= 0.500001);
    assert.equal(ml.ml_score, result.ml_score);
    assert.ok([0, 1].includes(ml.prediction));
    assert.equal(typeof ml.classification, "string");
    assert.ok(ml.input_fields.includes("title") && ml.input_fields.includes("description"));
    assert.ok(Array.isArray(ml.missing_fields));
    assert.equal(result.score_type, "combined");
    assert.equal(result.analysis_scope, "security_and_ml");
    assert.equal(result.score_formula, "max(security_score, ml_score)");
    assert.equal(result.final_score, Math.max(result.security_score, result.ml_score));
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
    assert.ok(card.querySelector(".jobproof-ml").textContent.includes("completed using the saved model"));
}

(async () => {
    let health;
    try {
        const response = await fetch("http://127.0.0.1:8000/health", { signal: AbortSignal.timeout(4000) });
        assert.equal(response.status, 200);
        health = await response.json();
    } catch (error) {
        throw new Error("Local API unavailable. Start `.venv\\Scripts\\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000`, then rerun this test.", { cause: error });
    }
    assert.equal(health.analysis_mode, "security_and_ml", "Start the integrated API with ready saved-model artifacts.");
    assert.equal(health.machine_learning.status, "ready");

    let listener;
    const requests = [];
    const worker = vm.createContext({
        chrome: { runtime: {
            id: "jobproof-demo-test",
            onMessage: { addListener(callback) { listener = callback; } }
        } },
        async fetch(url, options) {
            assert.equal(url, "http://127.0.0.1:8000/analyze", "Job destinations must remain data sent to the local API.");
            const entry = { job: JSON.parse(options.body), result: null };
            requests.push(entry);
            const response = await fetch(url, options);
            entry.result = await response.clone().json();
            return response;
        },
        AbortController, Error, TypeError, SyntaxError, setTimeout, clearTimeout
    });
    vm.runInContext(read("extension/background.js"), worker);
    const dom = new JSDOM(read("tests/jobs.html"), {
        url: "http://localhost:8080/jobs.html", runScripts: "outside-only"
    });
    const observers = [];
    const NativeObserver = dom.window.MutationObserver;
    dom.window.MutationObserver = class extends NativeObserver {
        constructor(callback) { super(callback); observers.push(this); }
    };
    const document = dom.window.document;
    const cards = () => [...document.querySelectorAll(".job-card")];
    const isSettled = () => cards().every(card => card.dataset.jobproofRisk
        && card.querySelector(".jobproof-retry")?.disabled === false);
    const latestResult = title => requests.findLast(entry => entry.job.title === title)?.result;
    const transmissions = [];
    dom.window.fetch = (...args) => { transmissions.push(args); throw new Error("The practice page must not send external requests."); };
    dom.window.open = (...args) => { transmissions.push(args); throw new Error("The practice page must not open application or mail windows."); };
    dom.window.chrome = { runtime: { sendMessage(message) {
        return new Promise((resolve, reject) => {
            if (!listener(message, { id: "jobproof-demo-test", tab: { id: 1 } }, resolve)) {
                reject(new Error("The background worker closed the message channel."));
            }
        });
    } } };

    try {
        assert.equal(cards().length, 3, "The presentation fixture must contain three initial scenarios.");
        assertUnanalyzed(document);
        dom.window.eval(read("tests/jobs.js"));
        assertUnanalyzed(document);
        dom.window.eval(read("extension/indeed.js"));
        assert.equal(dom.window.JobProofIndeed.active, false, "jobs.html must use the demo extractor.");
        dom.window.eval(read("extension/content.js"));
        await waitFor(() => requests.length === 3 && isSettled(), "three initial real-engine results");

        const [safe, verify, risky] = cards();
        const expected = [[safe, 0], [verify, 45], [risky, 100]];
        for (const [card, securityScore] of expected) {
            const title = card.querySelector(".job-title").textContent.trim();
            const result = latestResult(title);
            assertCombined(card, result, securityScore);
            assert.equal(card.querySelectorAll(":scope > .jobproof-panel").length, 1);
            assert.ok(!Object.hasOwn(requests.find(entry => entry.job.title === title).job, "listing_url"));
            assert.ok(!result.pending_checks.includes("recruiter_email_analysis"), "A supplied recruiter email must be analyzed.");
            for (const check of ["url", "social_engineering", "email"]) assert.equal(result.checks[check].analyzed, true);
            const explanation = card.querySelector(".jobproof-details").textContent;
            const coverage = card.querySelector(".jobproof-coverage").textContent;
            for (const label of ["application URL", "recruitment language", "recruiter email"]) assert.ok(coverage.includes(label));
            assert.ok(!explanation.includes("ML prediction is not connected"));
            assert.ok(!explanation.includes("No recruiter email address"));
        }
        assert.deepEqual(latestResult(safe.querySelector(".job-title").textContent.trim()).findings, []);
        const yellowCodes = latestResult(verify.querySelector(".job-title").textContent.trim()).findings.map(finding => finding.code).sort();
        assert.deepEqual(yellowCodes, ["email_company_domain_mismatch", "free_email_provider"]);
        const redResult = latestResult(risky.querySelector(".job-title").textContent.trim());
        const redCodes = new Set(redResult.findings.map(finding => finding.code));
        for (const code of ["no_https", "direct_ip", "email_possible_typosquatting", "upfront_payment", "credential_request"]) {
            assert.ok(redCodes.has(code), `Missing red-scenario finding ${code}`);
        }
        assert.ok(redResult.findings.filter(finding => ["upfront_payment", "credential_request"].includes(finding.code)).every(finding => finding.evidence));
        console.log("PASS initial demo cards preserve security components 0, 45, and 100, with genuine model inference and max-score results");
        console.log("Demo scores:", JSON.stringify(expected.map(([card]) => {
            const title = card.querySelector(".job-title").textContent.trim();
            const result = latestResult(title);
            return { title, security: result.security_score, ml: result.ml_score, final: result.final_score, color: result.color };
        })));

        for (const card of cards()) {
            const details = card.querySelector(".jobproof-details");
            const summary = details.querySelector("summary");
            summary.click();
            assert.equal(details.open, true);
            assert.ok(details.querySelector(".jobproof-notice").textContent.includes("legitimacy"));
            summary.click();
            assert.equal(details.open, false);
        }
        await pause(350);
        assert.equal(requests.length, 3, "Explanation interaction and rendering must not request analysis.");
        verify.querySelector(".jobproof-retry").click();
        await waitFor(() => requests.length === 4 && isSettled(), "one explicit recheck");
        assertCombined(verify, requests.at(-1).result, 45);
        console.log("PASS explanations open and close without requests, and Recheck performs exactly one fresh analysis");

        const assertDemoLinksAreGuarded = () => {
            const originalUrl = dom.window.location.href;
            const links = [...document.querySelectorAll('.apply-link, .recruiter-email a[href^="mailto:"]')];
            assert.ok(links.length >= cards().length * 2);
            for (const link of links) {
                const href = link.getAttribute("href");
                // Keyboard activation generates a click with detail 0 in a browser.
                for (const [type, button, detail] of [["click", 0, 1], ["click", 0, 0], ["auxclick", 1, 1]]) {
                    const event = new dom.window.MouseEvent(type, { bubbles: true, cancelable: true, button, detail });
                    assert.equal(link.dispatchEvent(event), false, `${type} must cancel the example destination ${href}`);
                    assert.equal(link.getAttribute("href"), href, "Real example destinations must remain available for extraction.");
                }
            }
            assert.equal(dom.window.location.href, originalUrl);
            assert.equal(transmissions.length, 0);
        };
        assertDemoLinksAreGuarded();
        await pause(350);
        assert.equal(requests.length, 4);
        console.log("PASS example application and email links cancel navigation without changing extracted destinations");

        document.querySelector("#load-job").click();
        await waitFor(() => cards().length === 4 && requests.length === 5 && isSettled(), "a dynamically loaded Cisco card");
        const added = document.querySelector("#loaded-jobs .job-card:last-child");
        assertCombined(added, requests.at(-1).result, 0);
        assert.equal(requests.at(-1).job.company, "Cisco");
        document.querySelector("#change-job").click();
        await waitFor(() => requests.length === 6 && added.dataset.jobproofRisk === "red" && isSettled(), "the dynamically changed risky card");
        assertCombined(added, requests.at(-1).result, 100);
        assert.equal(requests.at(-1).job.url, "http://192.0.2.1/apply");
        assert.ok(requests.at(-1).result.findings.some(finding => finding.code === "upfront_payment"));
        assert.equal(added.querySelectorAll(":scope > .jobproof-panel").length, 1);
        assertDemoLinksAreGuarded();
        await pause(350);
        assert.equal(requests.length, 6, "Rendering, links, and observer updates must settle without request loops.");
        assert.equal(document.querySelectorAll(".jobproof-panel").length, 4);
        console.log("PASS loading and changing a listing updates real scores automatically, preserves guarded links, and avoids rendering loops");
        console.log("Verified 4 presentation-demo scenarios through the real integrated security and ML API.");
    } finally {
        for (const observer of observers) observer.disconnect();
        dom.window.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
