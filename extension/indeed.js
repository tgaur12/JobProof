(() => {
    const isIndeedHost = hostname => hostname === "indeed.com" || hostname.endsWith(".indeed.com");
    const localFixture = ["localhost", "127.0.0.1"].includes(location.hostname)
        && document.documentElement.dataset.jobproofPlatform === "indeed";
    const active = isIndeedHost(location.hostname) || localFixture;
    const titleLinks = 'a.jcs-JobTitle, a[id^="sj_"][data-jk], h2.jobTitle a, a[data-testid="job-title"]';
    const cardRoots = '.job_seen_beacon, [data-testid="slider_item"], [data-testid="fade-in-wrapper"], li, article, tr';
    const detailRoots = '#job-full-details, [data-testid="jobsearch-ViewjobPaneWrapper"], .jobsearch-ViewJobContainerWrapper';
    const descriptions = '#jobDescriptionText, [data-testid="jobDescriptionText"]';
    const detailTitles = '[data-testid="jobsearch-JobInfoHeader-title"], h1.jobsearch-JobInfoHeader-title, h2.jobsearch-JobInfoHeader-title, h1';
    const detailCompanies = '[data-testid="inlineHeader-companyName"] a, [data-testid="inlineHeader-companyName"]';
    let lastDetail = null;

    function text(element) {
        return (element?.innerText || element?.textContent || "").replace(/\s+/g, " ").trim();
    }

    function jobId(value) {
        return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value) ? value : null;
    }

    function idFromUrl(value) {
        try {
            const url = new URL(value, localFixture ? "https://www.indeed.com/" : location.href);
            return jobId(url.searchParams.get("jk") || url.searchParams.get("vjk") || url.searchParams.get("currentJobId"));
        } catch {
            return null;
        }
    }

    function idFromLink(link) {
        return jobId(link?.getAttribute("data-jk"))
            || jobId(link?.closest("[data-jk]")?.getAttribute("data-jk"))
            || idFromUrl(link?.getAttribute("href"));
    }

    function rootFromLink(link) {
        if (!link || !idFromLink(link)) {
            return null;
        }
        return link.closest(".job_seen_beacon") || link.closest(cardRoots);
    }

    function visible(element) {
        for (let node = element; node; node = node.parentElement) {
            if (node.hidden || node.getAttribute("aria-hidden") === "true") {
                return false;
            }
            const style = getComputedStyle(node);
            if (style.display === "none" || style.visibility === "hidden") {
                return false;
            }
        }
        return true;
    }

    function standalone() {
        return /^\/(?:m\/)?viewjob\/?$/.test(location.pathname) && idFromUrl(location.href);
    }

    function currentDetailRoot() {
        return [...document.querySelectorAll(detailRoots)].find(root => visible(root)
            && [...root.querySelectorAll(descriptions)].some(visible)) || null;
    }

    function isCard(element) {
        if (!(element instanceof Element)) {
            return false;
        }
        if (standalone() && element === currentDetailRoot()) {
            return true;
        }
        return rootFromLink(element.querySelector(titleLinks)) === element;
    }

    function findCards(root) {
        const cards = new Set();
        const links = [...root.querySelectorAll(titleLinks)];
        if (root instanceof Element && root.matches(titleLinks)) {
            links.unshift(root);
        }
        for (const link of links) {
            const card = rootFromLink(link);
            if (card && visible(card)) {
                cards.add(card);
            }
        }
        const detail = standalone() && currentDetailRoot();
        if (detail && (root === detail || root.contains(detail))) {
            cards.add(detail);
        }
        return [...cards];
    }

    function closestCard(element) {
        let candidate = element.closest(`${cardRoots}, ${detailRoots}`);
        while (candidate) {
            if (isCard(candidate)) {
                return candidate;
            }
            candidate = candidate.parentElement?.closest(`${cardRoots}, ${detailRoots}`);
        }
        return null;
    }

    function detailFor(id, title, company, link) {
        const root = currentDetailRoot();
        const description = root && [...root.querySelectorAll(descriptions)].find(visible);
        if (!description || !text(description) || root.closest('[aria-busy="true"]')
            || description.closest('[aria-busy="true"]')) {
            return null;
        }
        const boundId = jobId(root.getAttribute("data-jk")) || jobId(description.getAttribute("data-jk"));
        const selected = link?.getAttribute("aria-pressed") === "true"
            || link?.getAttribute("aria-current") === "true" || link?.getAttribute("aria-current") === "page";
        const selectedId = (standalone() || selected) && idFromUrl(location.href);
        if ((boundId || selectedId) !== id) {
            return null;
        }
        const headerTitle = text([...root.querySelectorAll(detailTitles)].find(visible))
            .replace(/\s*[-–—]\s*job post\s*$/i, "");
        const headerCompany = text([...root.querySelectorAll(detailCompanies)].find(visible));
        if (!headerTitle || !headerCompany || headerTitle.toLowerCase() !== title.toLowerCase()
            || headerCompany.toLowerCase() !== company.toLowerCase()) {
            return null;
        }
        const descriptionText = text(description);
        // A changed header can arrive before the previous job's body is replaced.
        if (lastDetail && lastDetail.id !== id && lastDetail.text === descriptionText) {
            return null;
        }
        lastDetail = { id, text: descriptionText };
        return { root, description, text: descriptionText };
    }

    function readEmail(root, descriptionText) {
        const explicit = root.matches(".recruiter-email") ? root : root.querySelector(".recruiter-email");
        const field = explicit || root;
        const link = field.matches('a[href^="mailto:" i]') ? field : field.querySelector('a[href^="mailto:" i]');
        if (link) {
            try {
                return { email: decodeURIComponent(link.href.slice(7).split("?")[0]).trim() || null, warning: "" };
            } catch {
                return { email: null, warning: "The recruiter email link has invalid encoding. Email verification is pending." };
            }
        }
        const match = descriptionText.match(/\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i);
        return { email: explicit ? text(explicit) || null : match?.[0] || null, warning: "" };
    }

    function externalApplyUrl(root) {
        const link = root?.querySelector('a[data-testid="apply-button"], a#applyButtonLinkContainer, #applyButtonLinkContainer a[href]');
        if (!link?.getAttribute("href")) {
            return null;
        }
        const href = link.getAttribute("href");
        try {
            const url = new URL(href, localFixture ? "https://www.indeed.com/" : location.href);
            return isIndeedHost(url.hostname) || url.protocol === "mailto:" ? null : url.href;
        } catch {
            // Keep malformed explicit destinations so the URL analyzer can explain them.
            return href;
        }
    }

    function extract(card) {
        const isDetail = standalone() && card === currentDetailRoot();
        const link = card.querySelector(titleLinks);
        const id = isDetail ? idFromUrl(location.href) : idFromLink(link);
        const titleNode = isDetail ? card.querySelector(detailTitles) : link?.querySelector("span[title]") || link;
        const title = (titleNode?.getAttribute("title") || text(titleNode)).replace(/\s*[-–—]\s*job post\s*$/i, "");
        const company = text(card.querySelector(isDetail ? detailCompanies : '[data-testid="company-name"], .companyName'));
        if (!id || !title) {
            throw new Error("Indeed job identity or title is still loading.");
        }
        const detail = detailFor(id, title, company, link);
        const snippet = card.querySelector('[data-testid="jobsnippet_footer"], .job-snippet');
        const description = detail ? detail.text : text(snippet);
        const email = readEmail(card.querySelector(".recruiter-email") || detail?.description || snippet || card, description);
        const listing = new URL("/viewjob", localFixture ? "https://www.indeed.com" : location.origin);
        listing.searchParams.set("jk", id);
        return {
            job: {
                title, company, description,
                url: externalApplyUrl(detail?.root || card),
                listing_url: listing.href,
                description_complete: Boolean(detail),
                recruiter_email: email.email
            },
            emailWarning: email.warning
        };
    }

    function isDetailMutation(record) {
        const touchesDetail = node => node instanceof Element
            && (node.matches(`${detailRoots}, ${descriptions}`) || node.closest(detailRoots)
                || node.querySelector(`${detailRoots}, ${descriptions}`));
        const element = record.target instanceof Element ? record.target : record.target.parentElement;
        return touchesDetail(element) || [...record.addedNodes, ...record.removedNodes].some(touchesDetail);
    }

    globalThis.JobProofIndeed = { active, isCard, findCards, closestCard, extract, isDetailMutation };
})();
