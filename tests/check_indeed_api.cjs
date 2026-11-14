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

(async () => {
    const health = await fetch("http://127.0.0.1:8000/health");
    assert.equal(health.status, 200, "Start the local API before running this test.");
    let listener;
    const requests = [];
    const worker = vm.createContext({
        chrome: { runtime: {
            id: "jobproof-test",
            onMessage: { addListener(callback) { listener = callback; } }
        } },
        fetch(url, options) {
            requests.push(JSON.parse(options.body));
            return fetch(url, options);
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
    try {
        dom.window.eval(read("tests/indeed.js"));
        dom.window.eval(read("extension/indeed.js"));
        dom.window.eval(read("extension/content.js"));
        await waitFor(() => [first, second].every(card => card.dataset.jobproofRisk === "yellow"), "initial preliminary results");
        assert.equal(requests.length, 2);
        assert.ok(requests.every(job => job.url === null && !job.description_complete));
        assert.ok(first.querySelector(".jobproof-status").textContent.includes("0/100"));
        console.log("PASS snippets and missing application destinations produce preliminary yellow results");

        first.querySelector("a.jcs-JobTitle").click();
        await waitFor(() => first.dataset.jobproofRisk === "green", "full Microsoft details");
        assert.equal(second.dataset.jobproofRisk, "yellow");
        assert.equal(requests.at(-1).url, "https://careers.microsoft.com/");
        assert.equal(requests.at(-1).description_complete, true);
        console.log("PASS matching full details and an official application destination produce lower risk");

        document.querySelector("#change-job").click();
        await waitFor(() => first.dataset.jobproofRisk === "red", "suspicious selected listing");
        assert.ok(first.querySelector(".jobproof-body").textContent.includes("upfront"));
        assert.ok(first.querySelector(".jobproof-status").textContent.includes("100/100"));
        console.log("PASS a changed description and HTTP IP-address destination automatically produce red");

        document.querySelector("#load-job").click();
        const added = document.querySelector('[data-jk="fixture_loaded_1"]');
        await waitFor(() => added.dataset.jobproofRisk === "yellow", "dynamically loaded result");
        assert.equal(added.querySelectorAll(":scope > .jobproof-panel").length, 1);
        console.log("PASS dynamically loaded Indeed-style cards are analyzed without refreshing");

        second.querySelector("a.jcs-JobTitle").click();
        await waitFor(() => second.dataset.jobproofRisk === "green" && first.dataset.jobproofRisk === "yellow", "job selection switch");
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
