(() => {
    if (globalThis.__jobproofContentScriptStarted) {
        return;
    }
    globalThis.__jobproofContentScriptStarted = true;

    const cardStates = new WeakMap();
    const queuedCards = new Set();
    let batchTimer = null;
    const indeed = globalThis.JobProofIndeed?.active ? globalThis.JobProofIndeed : null;

    const PENDING_LABELS = {
        domain_registration_verification: "domain registration",
        recruiter_mailbox_verification: "recruiter mailbox ownership",
        machine_learning_prediction: "ML prediction",
        job_description_analysis: "full job description",
        social_engineering_detection: "recruitment language",
        recruiter_email_analysis: "recruiter email",
        company_domain_reference: "trusted company domain",
        url_shortener_detection: "shortener catalog",
        application_url_analysis: "application destination"
    };

    function extractJob(card) {
        if (indeed) {
            return indeed.extract(card);
        }
        const applyLink = card.querySelector(".apply-link");
        if (!applyLink?.getAttribute("href")?.trim()) {
            throw new Error("This card needs an application link before it can be analyzed.");
        }

        const recruiterField = card.querySelector(".recruiter-email");
        let recruiterEmail = recruiterField?.textContent.trim() || null;
        let emailWarning = "";
        const emailScope = recruiterField || card;
        const emailLink = emailScope.matches('a[href^="mailto:" i]')
            ? emailScope : emailScope.querySelector('a[href^="mailto:" i]');
        if (emailLink) {
            try {
                // Preserve literal '+' characters in email aliases.
                recruiterEmail = decodeURIComponent(emailLink.href.slice(7).split("?")[0]).trim() || null;
            } catch {
                recruiterEmail = null;
                emailWarning = "The recruiter email link has invalid encoding. Email verification is pending.";
            }
        }

        return {
            job: {
                title: card.querySelector(".job-title")?.textContent.trim() || "",
                company: card.querySelector(".company")?.textContent.trim() || "",
                description: card.querySelector(".description")?.textContent.trim() || "",
                url: applyLink.href,
                recruiter_email: recruiterEmail
            },
            emailWarning
        };
    }

    function renderResult(card, body, status, result) {
        card.dataset.jobproofRisk = result.color;
        const label = result.assessment_status === "preliminary" ? "JobProof preliminary" : "JobProof security";
        status.textContent = `${label} · ${result.risk_level} · ${result.risk_score}/100`;

        const details = document.createElement("details");
        details.className = "jobproof-details";
        const summary = document.createElement("summary");
        summary.textContent = "Why this result";
        details.append(summary);

        if (result.findings.length > 0) {
            const reasons = document.createElement("ul");
            for (const finding of result.findings) {
                const item = document.createElement("li");
                item.textContent = finding.message;
                if (finding.evidence) {
                    const evidence = document.createElement("span");
                    evidence.className = "jobproof-evidence";
                    evidence.textContent = `Matched text “${finding.evidence}”`;
                    item.append(evidence);
                }
                reasons.append(item);
            }
            details.append(reasons);
        }

        if (result.pending_checks.length > 0) {
            const pending = document.createElement("p");
            pending.className = "jobproof-pending";
            const names = result.pending_checks.map(name => PENDING_LABELS[name] || name.replaceAll("_", " "));
            pending.textContent = `Pending checks include ${names.join(", ")}.`;
            details.append(pending);
        }

        const notice = document.createElement("p");
        notice.className = "jobproof-notice";
        notice.textContent = result.notice;
        details.append(notice);
        body.append(details);
    }

    function readCard(card) {
        try {
            const extraction = extractJob(card);
            // Only source fields participate. JobProof's panel is excluded.
            return { key: JSON.stringify(extraction), extraction, error: null };
        } catch (error) {
            return { key: JSON.stringify({ error: error.message }), extraction: null, error };
        }
    }

    function isCurrentRequest(card, state, version, inputKey) {
        if (cardStates.get(card) !== state || state.version !== version
            || !card.isConnected || !isJobCard(card) || state.panel.parentElement !== card) {
            return false;
        }
        // A promise can settle before the observer has delivered a source edit.
        if (readCard(card).key !== inputKey) {
            queueCard(card);
            return false;
        }
        return true;
    }

    async function analyzeCard(card, state, snapshot) {
        const { body, status, retry } = state;
        const version = state.version;

        try {
            if (snapshot.error) {
                throw snapshot.error;
            }
            const extraction = snapshot.extraction;
            const response = await chrome.runtime.sendMessage({
                type: "JOBPROOF_ANALYZE_JOB", job: extraction.job
            });
            if (!isCurrentRequest(card, state, version, snapshot.key)) {
                return;
            }
            if (!response?.ok) {
                throw new Error(response?.error || "The extension could not complete this analysis. Reload the page and retry.");
            }
            renderResult(card, body, status, response.result);
            if (extraction.emailWarning) {
                const warning = document.createElement("p");
                warning.className = "jobproof-pending";
                warning.textContent = extraction.emailWarning;
                body.append(warning);
            }
            retry.textContent = "Recheck";
        } catch (error) {
            if (!isCurrentRequest(card, state, version, snapshot.key)) {
                return;
            }
            delete card.dataset.jobproofRisk;
            status.textContent = "JobProof · Analysis unavailable";
            body.textContent = error.message;
            retry.textContent = "Retry";
        } finally {
            if (isCurrentRequest(card, state, version, snapshot.key)) {
                retry.disabled = false;
                retry.hidden = false;
            }
        }
    }

    function createCardState(card) {
        const previous = cardStates.get(card);
        if (previous) {
            previous.version += 1;
            previous.panel.remove();
        }
        // Cloned or recycled card markup may still contain an old panel.
        for (const panel of card.querySelectorAll(":scope > .jobproof-panel")) {
            panel.remove();
        }
        card.classList.add("jobproof-card");
        const panel = document.createElement("section");
        panel.className = "jobproof-panel";
        panel.setAttribute("aria-label", "JobProof risk assessment");

        const status = document.createElement("p");
        status.className = "jobproof-status";
        status.setAttribute("role", "status");
        const body = document.createElement("div");
        body.className = "jobproof-body";
        const retry = document.createElement("button");
        retry.className = "jobproof-retry";
        retry.type = "button";
        retry.textContent = "Retry";
        retry.addEventListener("click", () => {
            if (!retry.disabled) {
                queueCard(card, true);
            }
        });

        panel.append(status, body, retry);
        card.append(panel);
        const state = { panel, body, status, retry, inputKey: null, version: 0 };
        cardStates.set(card, state);
        return state;
    }

    function queueCard(card, force = false) {
        if (!card.isConnected || !isJobCard(card)) {
            return;
        }
        let state = cardStates.get(card);
        if (!state || state.panel.parentElement !== card) {
            state = createCardState(card);
        }
        const snapshot = readCard(card);
        if (!force && snapshot.key === state.inputKey) {
            return;
        }
        state.inputKey = snapshot.key;
        state.version += 1;
        state.retry.disabled = true;
        state.retry.hidden = true;
        delete card.dataset.jobproofRisk;
        state.body.replaceChildren();
        state.status.textContent = "JobProof · Checking security indicators…";
        queuedCards.add(card);

        // A fixed batch window also lets other cards progress during scrolling.
        if (batchTimer === null) {
            batchTimer = setTimeout(flushCards, 150);
        }
    }

    function flushCards() {
        batchTimer = null;
        const cards = [...queuedCards];
        queuedCards.clear();
        for (const card of cards) {
            const state = cardStates.get(card);
            if (!state || !card.isConnected || !isJobCard(card)) {
                continue;
            }
            const snapshot = readCard(card);
            if (snapshot.key !== state.inputKey) {
                queueCard(card);
                continue;
            }
            void analyzeCard(card, state, snapshot);
        }
    }

    function collectCards(node, cards) {
        if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_NODE) {
            return;
        }
        if (indeed) {
            for (const card of indeed.findCards(node)) {
                cards.add(card);
            }
            return;
        }
        if (node.nodeType === Node.ELEMENT_NODE && node.matches(".job-card")) {
            cards.add(node);
        }
        for (const card of node.querySelectorAll(".job-card")) {
            cards.add(card);
        }
    }

    function isJobCard(element) {
        return indeed ? indeed.isCard(element) : element.matches(".job-card");
    }

    function closestJobCard(element) {
        return indeed ? indeed.closestCard(element) : element.closest(".job-card");
    }

    function forgetCard(card) {
        const state = cardStates.get(card);
        state.version += 1;
        state.panel.remove();
        queuedCards.delete(card);
        cardStates.delete(card);
        delete card.dataset.jobproofRisk;
        card.classList.remove("jobproof-card");
    }

    const observer = new MutationObserver(records => {
        const affectedCards = new Set();
        for (const record of records) {
            const element = record.target.nodeType === Node.ELEMENT_NODE
                ? record.target : record.target.parentElement;
            if (!element || element.closest(".jobproof-panel")) {
                continue;
            }
            if (cardStates.has(element) && !isJobCard(element)) {
                forgetCard(element);
            }
            const card = closestJobCard(element);
            if (card) {
                affectedCards.add(card);
            }
            if (indeed?.isDetailMutation(record)) {
                collectCards(document, affectedCards);
            }
            if (indeed && record.type === "attributes") {
                collectCards(element, affectedCards);
            }
            for (const node of record.addedNodes) {
                collectCards(node, affectedCards);
            }
            const removedCards = new Set();
            for (const node of record.removedNodes) {
                if (cardStates.has(node)) {
                    removedCards.add(node);
                }
                if (node.nodeType === Node.ELEMENT_NODE) {
                    for (const tracked of node.querySelectorAll(".jobproof-card")) {
                        if (cardStates.has(tracked)) {
                            removedCards.add(tracked);
                        }
                    }
                }
                collectCards(node, removedCards);
            }
            for (const removedCard of removedCards) {
                const state = cardStates.get(removedCard);
                if (state && !removedCard.isConnected) {
                    forgetCard(removedCard);
                }
            }
        }
        for (const card of affectedCards) {
            queueCard(card);
        }
    });
    observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
        attributeFilter: indeed
            ? ["href", "title", "class", "data-jk", "data-testid", "aria-pressed", "aria-current", "aria-busy", "hidden", "aria-hidden", "style"]
            : ["href", "class"]
    });
    const initialCards = new Set();
    collectCards(document, initialCards);
    for (const card of initialCards) {
        queueCard(card);
    }
})();
