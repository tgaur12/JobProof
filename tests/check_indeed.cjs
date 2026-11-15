// Representative synthetic Indeed DOM fixtures. These are not captured live HTML.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..");
const adapterSource = fs.readFileSync(path.join(root, "extension/indeed.js"), "utf8");
const contentSource = fs.readFileSync(path.join(root, "extension/content.js"), "utf8");
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
let passed = 0;
const failures = [];

function escape(value) {
    return String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function cardMarkup({ id = "job001", title = "Software Engineer", company = "Microsoft", snippet = "Develop cloud applications.", extra = "", legacy = false } = {}) {
    const titleLink = legacy
        ? `<a href="/viewjob?jk=${encodeURIComponent(id)}"><span>${escape(title)}</span></a>`
        : `<a class="jcs-JobTitle" data-jk="${escape(id)}" href="/rc/clk?jk=${encodeURIComponent(id)}"><span>${escape(title)}</span></a>`;
    return `<li class="result-item"><div class="slider_item"><div data-testid="fade-in-wrapper"><div class="job_seen_beacon" data-jk="${escape(id)}">
        <h2 class="jobTitle">${titleLink}</h2>
        <span ${legacy ? 'class="companyName"' : 'data-testid="company-name"'}>${escape(company)}</span>
        <div ${legacy ? 'data-testid="jobsnippet_footer"' : 'class="job-snippet"'}>${escape(snippet)}</div>
        ${extra}
    </div></div></div></li>`;
}

function detailMarkup({ id = "job001", title = "Software Engineer", company = "Microsoft", description = "Build and test cloud applications with the engineering team.", descriptionId = null, extra = "" } = {}) {
    const identity = id === null ? "" : ` data-jk="${escape(id)}"`;
    const descriptionIdentity = descriptionId === null ? "" : ` data-jk="${escape(descriptionId)}"`;
    return `<section id="job-full-details"${identity}>
        <h2 class="jobsearch-JobInfoHeader-title">${escape(title)}</h2>
        <div data-testid="inlineHeader-companyName">${escape(company)}</div>
        <div id="jobDescriptionText"${descriptionIdentity}>${escape(description)}</div>
        ${extra}
    </section>`;
}

function result(color = "green", riskScore = 0) {
    return {
        color,
        risk_score: riskScore,
        risk_level: { green: "Lower risk", yellow: "Needs further verification", red: "High risk" }[color],
        findings: [],
        pending_checks: ["machine_learning_prediction"],
        notice: "Job legitimacy still requires verification."
    };
}

function makePage({ markup = cardMarkup(), detail = "", url = "http://localhost:8080/indeed.html", marked = true, integrated = false, deferred = false } = {}) {
    const dom = new JSDOM(`<!doctype html><html${marked ? ' data-jobproof-platform="indeed"' : ""}><body><main id="jobs">${markup}</main><aside id="details">${detail}</aside><footer id="unrelated"></footer></body></html>`, {
        url,
        runScripts: "outside-only"
    });
    const requests = [];
    const observers = [];
    const NativeMutationObserver = dom.window.MutationObserver;
    dom.window.MutationObserver = class extends NativeMutationObserver {
        constructor(callback) {
            super(callback);
            observers.push(this);
        }
    };
    dom.window.chrome = { runtime: { sendMessage(message) {
        assert.equal(message.type, "JOBPROOF_ANALYZE_JOB");
        return new Promise((resolve, reject) => {
            const request = {
                job: JSON.parse(JSON.stringify(message.job)),
                resolveResult(value = result()) { resolve({ ok: true, result: value }); },
                resolveError(error) { resolve({ ok: false, error }); },
                reject
            };
            requests.push(request);
            if (!deferred) request.resolveResult();
        });
    } } };
    dom.window.fetch = () => { throw new Error("The Indeed harness must use mocked runtime messages."); };
    dom.window.eval(adapterSource);
    if (integrated) dom.window.eval(contentSource);
    const document = dom.window.document;
    return {
        dom, document, requests, observers,
        adapter: dom.window.JobProofIndeed,
        cards() { return Array.from(dom.window.JobProofIndeed.findCards(document)); },
        card(id = "job001") { return Array.from(document.querySelectorAll(".job_seen_beacon")).find(node => node.dataset.jk === id); },
        extract(id = "job001") { return dom.window.JobProofIndeed.extract(this.card(id)); }
    };
}

async function withPage(options, callback) {
    const page = makePage(options);
    try { await callback(page); } finally {
        for (const observer of page.observers) observer.disconnect();
        page.dom.window.close();
    }
}

async function waitFor(predicate, description, timeout = 2500) {
    const started = Date.now();
    while (!predicate()) {
        if (Date.now() - started > timeout) throw new Error(`Timed out waiting for ${description}`);
        await pause(10);
    }
}

async function ready(page, expected = 1) {
    await waitFor(() => page.requests.length === expected, `${expected} analysis requests`);
    await waitFor(() => page.cards().every(card => card.dataset.jobproofRisk), "rendered Indeed card results");
}

async function test(name, callback) {
    try {
        await callback();
        passed += 1;
        console.log(`PASS ${name}`);
    } catch (error) {
        failures.push(name);
        console.error(`FAIL ${name}\n${error.stack || error}`);
    }
}

(async () => {
    await test("activation accepts Indeed and marked localhost fixtures, rejects lookalike hosts", async () => {
        for (const [url, marked, active] of [
            ["https://www.indeed.com/jobs?q=engineer", false, true],
            ["https://ca.indeed.com/jobs", false, true],
            ["http://localhost:8080/indeed.html", true, true],
            ["http://localhost:8080/jobs.html", false, false],
            ["https://indeed.com.evil.example/jobs", false, false]
        ]) {
            await withPage({ url, marked }, page => assert.equal(page.adapter.active, active, url));
        }
    });

    await test("nested result wrappers yield one preferred card per title link", () => withPage({ markup: cardMarkup() + cardMarkup({ id: "job002", title: "QA Engineer" }) }, page => {
        const cards = page.cards();
        assert.equal(cards.length, 2);
        assert.ok(cards.every(card => card.classList.contains("job_seen_beacon")));
        assert.equal(page.adapter.isCard(cards[0]), true);
        assert.equal(page.adapter.isCard(cards[0].closest("li")), false);
        assert.equal(page.adapter.closestCard(cards[0].querySelector("h2 span")), cards[0]);
        assert.equal(Array.from(page.adapter.findCards(cards[0])).length, 1);
    }));

    await test("card extraction keeps the listing URL separate from an unknown application URL", () => withPage({}, page => {
        const { job, emailWarning } = page.extract();
        assert.equal(job.title, "Software Engineer");
        assert.equal(job.company, "Microsoft");
        assert.equal(job.description, "Develop cloud applications.");
        assert.equal(job.listing_url, "https://www.indeed.com/viewjob?jk=job001");
        assert.equal(job.url, null);
        assert.equal(job.description_complete, false);
        assert.equal(job.recruiter_email, null);
        assert.equal(emailWarning, "");
    }));

    await test("legacy title, company and snippet hooks remain usable", () => withPage({ markup: cardMarkup({ id: "legacy123", legacy: true, company: "Cisco", snippet: "Maintain network systems." }) }, page => {
        const cards = page.cards();
        assert.equal(cards.length, 1);
        const { job } = page.adapter.extract(cards[0]);
        assert.equal(job.company, "Cisco");
        assert.equal(job.description, "Maintain network systems.");
        assert.equal(new URL(job.listing_url).searchParams.get("jk"), "legacy123");
    }));

    await test("arbitrary external body links and internal Indeed apply links are not application destinations", async () => {
        for (const extra of [
            '<a href="https://example.org/privacy">Employer privacy policy</a>',
            '<a data-testid="apply-button" href="https://www.indeed.com/applystart?jk=job001">Apply</a>',
            '<div id="applyButtonLinkContainer"><a href="/rc/clk?jk=job001">Apply</a></div>'
        ]) {
            await withPage({ markup: cardMarkup({ extra }) }, page => assert.equal(page.extract().job.url, null));
        }
    });

    await test("only explicit external apply anchors supply the application destination", async () => {
        for (const extra of [
            '<a data-testid="apply-button" href="https://careers.microsoft.com/job/123">Apply</a>',
            '<div id="applyButtonLinkContainer"><a href="https://careers.microsoft.com/job/123">Apply</a></div>'
        ]) {
            await withPage({ markup: cardMarkup({ extra }) }, page => assert.equal(page.extract().job.url, "https://careers.microsoft.com/job/123"));
        }
    });

    await test("a malformed explicit apply URL remains available for backend scoring without losing job text", () => withPage({ markup: cardMarkup({ extra: '<a data-testid="apply-button" href="https://[">Apply</a>' }) }, page => {
        const { job } = page.extract();
        assert.equal(job.url, "https://[");
        assert.equal(job.title, "Software Engineer");
        assert.equal(job.company, "Microsoft");
        assert.equal(job.description, "Develop cloud applications.");
        assert.equal(job.description_complete, false);
    }));

    await test("a detail root needs matching job identity, title and company to supply complete text", () => withPage({ detail: detailMarkup() }, page => {
        const { job } = page.extract();
        assert.equal(job.description_complete, true);
        assert.equal(job.description, "Build and test cloud applications with the engineering team.");
    }));

    await test("hidden description nodes cannot supply complete text through a visible detail root", async () => {
        for (const attribute of ['hidden', 'aria-hidden="true"', 'style="display:none"', 'style="visibility:hidden"']) {
            const detail = detailMarkup().replace('id="jobDescriptionText"', `id="jobDescriptionText" ${attribute}`);
            await withPage({ detail }, page => {
                const { job } = page.extract();
                assert.equal(job.description_complete, false, attribute);
                assert.equal(job.description, "Develop cloud applications.", attribute);
            });
        }
    });

    await test("unbound or mismatched detail panes cannot contaminate a card", async () => {
        for (const detail of [
            detailMarkup({ id: null }),
            detailMarkup({ id: "different-job" }),
            detailMarkup({ title: "Accountant" }),
            detailMarkup({ company: "Different Employer" })
        ]) {
            await withPage({ detail }, page => {
                assert.equal(page.extract().job.description_complete, false);
                assert.equal(page.extract().job.description, "Develop cloud applications.");
            });
        }
        await withPage({ detail: detailMarkup({ id: null }), marked: false, url: "https://www.indeed.com/jobs?q=engineer&vjk=job001" }, page => {
            assert.equal(page.extract().job.description_complete, false);
            assert.equal(page.extract().job.description, "Develop cloud applications.");
        });
    });

    await test("description-level job identity can bind an otherwise matching detail pane", () => withPage({ detail: detailMarkup({ id: null, descriptionId: "job001" }) }, page => {
        assert.equal(page.extract().job.description_complete, true);
        assert.ok(page.extract().job.description.includes("engineering team"));
    }));

    await test("a standalone viewjob page can bind its known detail root through the URL identity", () => withPage({ markup: "", detail: detailMarkup({ id: null }), marked: false, url: "https://www.indeed.com/viewjob?jk=standalone001" }, page => {
        const cards = page.cards();
        assert.equal(cards.length, 1);
        const { job } = page.adapter.extract(cards[0]);
        assert.equal(job.title, "Software Engineer");
        assert.equal(job.company, "Microsoft");
        assert.equal(job.description_complete, true);
        assert.equal(new URL(job.listing_url).searchParams.get("jk"), "standalone001");
        assert.equal(job.url, null);
    }));

    await test("selected URL identity binds a pane and rejects an unchanged body when selection changes", () => withPage({ marked: false, url: "https://www.indeed.com/jobs?q=engineer&vjk=job001", markup: cardMarkup() + cardMarkup({ id: "job002" }), detail: detailMarkup({ id: null, description: "Full description only for the first job." }) }, page => {
        page.card("job001").querySelector("a.jcs-JobTitle").setAttribute("aria-current", "true");
        assert.equal(page.extract("job001").job.description_complete, true);
        assert.equal(page.extract("job002").job.description_complete, false);
        page.dom.window.history.replaceState(null, "", "?q=engineer&vjk=job002");
        page.card("job001").querySelector("a.jcs-JobTitle").removeAttribute("aria-current");
        page.card("job002").querySelector("a.jcs-JobTitle").setAttribute("aria-pressed", "true");
        assert.equal(page.extract("job002").job.description_complete, false);
        assert.equal(page.extract("job002").job.description, "Develop cloud applications.");
        page.document.querySelector("#jobDescriptionText").textContent = "Full description only for the second job.";
        assert.equal(page.extract("job002").job.description_complete, true);
        assert.ok(page.extract("job002").job.description.includes("second job"));
    }));

    await test("a remounted description with unchanged old text is rejected after the job identity changes", () => withPage({ marked: false, url: "https://www.indeed.com/jobs?q=engineer&vjk=job001", markup: cardMarkup() + cardMarkup({ id: "job002" }), detail: detailMarkup({ id: null, description: "Full description only for the first job." }) }, page => {
        page.card("job001").querySelector("a.jcs-JobTitle").setAttribute("aria-current", "true");
        assert.equal(page.extract("job001").job.description_complete, true);
        page.dom.window.history.replaceState(null, "", "?q=engineer&vjk=job002");
        page.card("job001").querySelector("a.jcs-JobTitle").removeAttribute("aria-current");
        page.card("job002").querySelector("a.jcs-JobTitle").setAttribute("aria-current", "true");
        const previousDescription = page.document.querySelector("#jobDescriptionText");
        const remountedDescription = previousDescription.cloneNode(true);
        previousDescription.replaceWith(remountedDescription);
        assert.equal(page.extract("job002").job.description_complete, false);
        assert.equal(page.extract("job002").job.description, "Develop cloud applications.");
        remountedDescription.textContent = "The second job has now supplied its own full description.";
        assert.equal(page.extract("job002").job.description_complete, true);
        assert.ok(page.extract("job002").job.description.includes("second job"));
    }));

    await test("a clickable-card capture handler reproduces the native disclosure default-action failure", () => withPage({}, page => {
        const disclosure = page.document.createElement("details");
        disclosure.innerHTML = "<summary>Native disclosure</summary><p>Explanation</p>";
        page.card().append(disclosure);
        page.card().addEventListener("click", event => event.preventDefault(), true);
        disclosure.querySelector("summary").click();
        assert.equal(disclosure.open, false, "Ancestor preventDefault cancels the native summary toggle.");
    }));

    await test("owned explanation clicks open and close despite cancelled defaults without activating the card", () => withPage({ integrated: true }, async page => {
        await ready(page);
        const card = page.card();
        const disclosure = card.querySelector(".jobproof-details");
        const summary = disclosure.querySelector("summary");
        let cardClicks = 0;
        card.addEventListener("click", event => event.preventDefault(), true);
        card.addEventListener("click", () => { cardClicks += 1; });
        summary.click();
        assert.equal(disclosure.open, true);
        summary.click();
        assert.equal(disclosure.open, false);
        assert.equal(cardClicks, 0, "Explanation clicks must not activate the clickable card.");
        await pause(250);
        assert.equal(page.requests.length, 1, "Opening or closing explanations must not request analysis.");

        card.querySelector("a.jcs-JobTitle").click();
        assert.equal(cardClicks, 1, "The original title must still receive its card click handler.");
    }));

    await test("explanation keyboard activation survives cancelled defaults and ignores held-key repeats", () => withPage({ integrated: true }, async page => {
        await ready(page);
        const card = page.card();
        const disclosure = card.querySelector(".jobproof-details");
        const summary = disclosure.querySelector("summary");
        let cardKeyEvents = 0;
        for (const type of ["keydown", "keyup"]) {
            card.addEventListener(type, event => event.preventDefault(), true);
            card.addEventListener(type, () => { cardKeyEvents += 1; });
        }
        const key = (type, value, repeat = false) => summary.dispatchEvent(new page.dom.window.KeyboardEvent(type, {
            key: value, repeat, bubbles: true, cancelable: true
        }));
        summary.focus();
        assert.equal(page.document.activeElement, summary);
        key("keydown", "Enter");
        assert.equal(disclosure.open, true);
        key("keydown", "Enter", true);
        assert.equal(disclosure.open, true, "Holding Enter must not repeatedly toggle the explanation.");
        key("keyup", "Enter");
        assert.equal(disclosure.open, true);
        key("keydown", " ");
        assert.equal(disclosure.open, false);
        key("keydown", " ", true);
        assert.equal(disclosure.open, false, "Holding Space must not repeatedly toggle the explanation.");
        key("keyup", " ");
        assert.equal(disclosure.open, false);
        assert.equal(cardKeyEvents, 0);
        await pause(250);
        assert.equal(page.requests.length, 1);
    }));

    await test("panel pointer events stay isolated while Retry sends exactly one analysis request", () => withPage({ integrated: true }, async page => {
        await ready(page);
        const card = page.card();
        const retry = card.querySelector(".jobproof-retry");
        let cardEvents = 0;
        for (const type of ["click", "dblclick", "pointerdown", "pointerup", "mousedown", "mouseup"]) {
            card.addEventListener(type, () => { cardEvents += 1; });
        }
        card.addEventListener("click", event => event.preventDefault(), true);
        for (const type of ["dblclick", "pointerdown", "pointerup", "mousedown", "mouseup"]) {
            retry.dispatchEvent(new page.dom.window.Event(type, { bubbles: true, cancelable: true }));
        }
        retry.click();
        await ready(page, 2);
        await pause(250);
        assert.equal(page.requests.length, 2, "Retry must send only one additional analysis request.");
        assert.equal(cardEvents, 0);
    }));

    await test("initial analysis and repeated injection create one panel and request per result", () => withPage({ integrated: true, markup: cardMarkup() + cardMarkup({ id: "job002" }) }, async page => {
        await ready(page, 2);
        assert.equal(page.document.querySelectorAll(".jobproof-panel").length, 2);
        page.dom.window.eval(adapterSource);
        page.dom.window.eval(contentSource);
        await pause(250);
        assert.equal(page.requests.length, 2);
        assert.equal(page.document.querySelectorAll(".jobproof-panel").length, 2);
        for (const request of page.requests) assert.equal(request.job.url, null);
    }));

    await test("a dynamically inserted result is analyzed and removal clears its panel", () => withPage({ integrated: true }, async page => {
        await ready(page);
        page.document.querySelector("#jobs").insertAdjacentHTML("beforeend", cardMarkup({ id: "newjob002", title: "Site Reliability Engineer" }));
        await ready(page, 2);
        const card = page.card("newjob002");
        assert.ok(card.querySelector(":scope > .jobproof-panel"));
        const wrapper = card.closest("li");
        wrapper.remove();
        await waitFor(() => !card.querySelector(".jobproof-panel"), "removed card cleanup");
        assert.equal(card.dataset.jobproofRisk, undefined);
    }));

    await test("detail text and identity changes outside cards refresh only changed extraction inputs", () => withPage({ integrated: true, markup: cardMarkup() + cardMarkup({ id: "job002" }), detail: detailMarkup({ id: null, description: "Later loaded full description." }) }, async page => {
        await ready(page, 2);
        page.document.querySelector("#job-full-details").setAttribute("data-jk", "job002");
        await waitFor(() => page.requests.length === 3, "bound detail analysis");
        assert.equal(new URL(page.requests[2].job.listing_url).searchParams.get("jk"), "job002");
        assert.equal(page.requests[2].job.description_complete, true);
        page.document.querySelector("#jobDescriptionText").textContent = "Updated full description for the second card.";
        await waitFor(() => page.requests.length === 4, "updated detail text analysis");
        assert.ok(page.requests[3].job.description.includes("Updated full"));
        page.document.querySelector("#unrelated").textContent = "Unrelated page content";
        await pause(250);
        assert.equal(page.requests.length, 4);
    }));

    await test("recycling a card with a new data-jk triggers a new job request", () => withPage({ integrated: true }, async page => {
        await ready(page);
        const card = page.card();
        card.dataset.jk = "replacement002";
        const titleLink = card.querySelector("a.jcs-JobTitle");
        titleLink.dataset.jk = "replacement002";
        await waitFor(() => page.requests.length === 2, "replacement job analysis");
        assert.equal(new URL(page.requests[1].job.listing_url).searchParams.get("jk"), "replacement002");
        await waitFor(() => card.dataset.jobproofRisk === "green", "replacement result");
        assert.equal(card.querySelectorAll(":scope > .jobproof-panel").length, 1);
    }));

    await test("an older request cannot commit a result after its card is recycled", () => withPage({ integrated: true, deferred: true }, async page => {
        await waitFor(() => page.requests.length === 1, "original deferred request");
        const card = page.card();
        card.dataset.jk = "replacement002";
        card.querySelector("a.jcs-JobTitle").dataset.jk = "replacement002";
        await waitFor(() => page.requests.length === 2, "replacement deferred request");
        page.requests[1].resolveResult(result("green", 0));
        await waitFor(() => card.dataset.jobproofRisk === "green", "current result");
        page.requests[0].resolveResult(result("red", 90));
        await pause(250);
        assert.equal(card.dataset.jobproofRisk, "green");
        assert.ok(card.querySelector(".jobproof-status").textContent.includes("Lower risk"));
        assert.equal(page.requests.length, 2);
    }));

    console.log(`Verified ${passed} Indeed adapter and content-script scenarios.`);
    if (failures.length) throw new Error(`${failures.length} scenario(s) failed: ${failures.join(" | ")}`);
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
