let latestLoadedCard = null;
let loadedCount = 0;

document.querySelector("#load-job").addEventListener("click", () => {
    const fragment = document.querySelector("#dynamic-job").content.cloneNode(true);
    latestLoadedCard = fragment.querySelector(".job-card");
    loadedCount += 1;
    latestLoadedCard.querySelector(".job-title").textContent = `Security Analyst (loaded ${loadedCount})`;
    document.querySelector("#loaded-jobs").append(fragment);
    document.querySelector("#change-job").disabled = false;
    document.querySelector("#demo-status").textContent = "Added a fictional Cisco listing. JobProof should analyze it automatically.";
});

document.querySelector("#change-job").addEventListener("click", () => {
    latestLoadedCard.querySelector(".description").textContent = "Pay $200 upfront for equipment before starting.";
    latestLoadedCard.querySelector(".apply-link").href = "http://192.0.2.1/apply";
    document.querySelector("#demo-status").textContent = "Changed the latest listing's description and application URL. JobProof should update its result.";
});
