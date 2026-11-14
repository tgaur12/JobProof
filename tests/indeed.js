// Fixture controls only. Chrome loads the actual adapter from extension/indeed.js.
const results = document.querySelector("#results");
const details = document.querySelector("#job-full-details");
const demoStatus = document.querySelector("#demo-status");
let selectedCard = null;
let loadedCount = 0;

results.addEventListener("click", event => {
    const link = event.target.closest("a.jcs-JobTitle");
    if (!link) return;
    event.preventDefault();
    selectedCard = link.closest(".job_seen_beacon");
    for (const titleLink of results.querySelectorAll("a.jcs-JobTitle")) {
        titleLink.setAttribute("aria-pressed", String(titleLink === link));
    }
    const company = selectedCard.querySelector('[data-testid="company-name"]').textContent;
    details.dataset.jk = link.dataset.jk;
    details.querySelector("h2").textContent = link.textContent;
    details.querySelector('[data-testid="inlineHeader-companyName"]').textContent = company;
    details.querySelector("#jobDescriptionText").textContent =
        `${selectedCard.querySelector(".job-snippet").textContent} This fictional full description includes a team interview and a standard employment agreement.`;
    details.querySelector('[data-testid="apply-button"]').href = company === "Microsoft"
        ? "https://careers.microsoft.com" : "https://jobs.cisco.com";
    details.hidden = false;
    document.querySelector("#change-job").disabled = false;
    demoStatus.textContent = "Full details are available for the selected job. Expect lower risk from the checks performed. Other cards still have preliminary assessments.";
});

document.querySelector("#load-job").addEventListener("click", () => {
    loadedCount += 1;
    const fragment = document.querySelector("#dynamic-result").content.cloneNode(true);
    const card = fragment.querySelector("article");
    const id = `fixture_loaded_${loadedCount}`;
    card.dataset.jk = id;
    const link = card.querySelector("a");
    link.dataset.jk = id;
    link.href = `https://www.indeed.com/viewjob?jk=${id}`;
    link.querySelector("span").textContent = `Security Analyst ${loadedCount}`;
    results.append(fragment);
    demoStatus.textContent = "Added a result after page load. Expect an automatic preliminary assessment without refreshing.";
});

document.querySelector("#change-job").addEventListener("click", () => {
    details.querySelector("#jobDescriptionText").textContent = "Pay $200 upfront for equipment before starting this job.";
    details.querySelector('[data-testid="apply-button"]').href = "http://192.0.2.1/apply";
    demoStatus.textContent = "The selected job now requests an upfront payment and uses an HTTP IP-address destination. Expect a red result.";
});

details.addEventListener("click", event => {
    if (event.target.closest('[data-testid="apply-button"]')) {
        event.preventDefault();
        demoStatus.textContent = "This example link is extracted for analysis. The practice page does not open application sites.";
    }
});
