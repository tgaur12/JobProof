// These controls change listing inputs. The extension supplies every risk result.
let latestLoadedCard = null;
let loadedCount = 0;
const demoStatus = document.querySelector("#demo-status");
const changeButton = document.querySelector("#change-job");

document.querySelector("#load-job").addEventListener("click", () => {
    const fragment = document.querySelector("#dynamic-job").content.cloneNode(true);
    latestLoadedCard = fragment.querySelector(".job-card");
    loadedCount += 1;
    latestLoadedCard.querySelector(".job-title").textContent = `Security Analyst (loaded ${loadedCount})`;
    latestLoadedCard.querySelector(".scenario-number").textContent = `NEW ${String(loadedCount).padStart(2, "0")} / SAMPLE LISTING`;
    document.querySelector("#loaded-jobs").append(fragment);
    changeButton.disabled = false;
    demoStatus.textContent = "Added a fictional Cisco listing with a matching company domain and recruiter email. JobProof should analyze it automatically.";
});

document.querySelector("#change-job").addEventListener("click", () => {
    if (!latestLoadedCard) return;
    latestLoadedCard.querySelector(".description").textContent = "Pay $200 upfront for equipment before starting. Share your banking password to activate payroll access.";
    const applyLink = latestLoadedCard.querySelector(".apply-link");
    applyLink.href = "http://192.0.2.1/apply";
    applyLink.textContent = "http://192.0.2.1/apply";
    const emailLink = latestLoadedCard.querySelector(".recruiter-email a");
    emailLink.href = "mailto:jobs@cisc0.com";
    emailLink.textContent = "jobs@cisc0.com";
    latestLoadedCard.querySelector(".scenario-number").textContent = `CHANGED ${String(loadedCount).padStart(2, "0")} / SAMPLE LISTING`;
    changeButton.disabled = true;
    demoStatus.textContent = "Changed the latest listing to an HTTP IP address, a lookalike email, an upfront payment request, and a password request. Watch JobProof update its assessment.";
});

document.querySelector("#reset-demo").addEventListener("click", () => {
    window.location.reload();
});

// Keep source hrefs readable by the extension while preventing demo navigation.
function preventDemoNavigation(event) {
    const link = event.target.closest(".apply-link, .recruiter-email a");
    if (!link) return;
    event.preventDefault();
    demoStatus.textContent = "This fictional example stays on the demo page. Its application and email links are available for JobProof to inspect.";
}

document.addEventListener("click", preventDemoNavigation);
document.addEventListener("auxclick", preventDemoNavigation);
