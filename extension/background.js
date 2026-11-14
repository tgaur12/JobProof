const ANALYSIS_ENDPOINT = "http://127.0.0.1:8000/analyze";

function isValidResult(result) {
    return result !== null && typeof result === "object"
        && ["green", "yellow", "red"].includes(result.color)
        && Number.isFinite(result.risk_score)
        && result.risk_score >= 0 && result.risk_score <= 100
        && typeof result.risk_level === "string"
        && typeof result.notice === "string"
        && Array.isArray(result.findings)
        && result.findings.every(finding => finding !== null
            && typeof finding.message === "string"
            && (finding.evidence === undefined || typeof finding.evidence === "string"))
        && Array.isArray(result.pending_checks)
        && result.pending_checks.every(check => typeof check === "string");
}

async function requestAnalysis(job) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
        // The destination belongs to the extension. The listing URL is data.
        const response = await fetch(ANALYSIS_ENDPOINT, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(job),
            signal: controller.signal,
            credentials: "omit",
            cache: "no-store",
            redirect: "error"
        });
        if (!response.ok) {
            throw new Error(`The analysis service returned HTTP ${response.status}. Check the job data and retry.`);
        }
        const result = await response.json();
        if (!isValidResult(result)) {
            throw new Error("The analysis service returned an unexpected result format.");
        }
        return result;
    } catch (error) {
        if (error.name === "AbortError") {
            throw new Error("Analysis timed out. Check the local API and retry.");
        }
        if (error instanceof SyntaxError) {
            throw new Error("The analysis service returned invalid JSON.");
        }
        if (error instanceof TypeError) {
            throw new Error("Start the local API on port 8000, then retry.");
        }
        throw error;
    } finally {
        clearTimeout(timeout);
    }
}

// Returning true keeps the message channel open until fetch completes.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== "JOBPROOF_ANALYZE_JOB") {
        return false;
    }
    if (sender.id !== chrome.runtime.id || !sender.tab) {
        sendResponse({ ok: false, error: "Analysis requests must come from a JobProof content script." });
        return false;
    }
    requestAnalysis(message.job).then(
        result => sendResponse({ ok: true, result }),
        error => sendResponse({ ok: false, error: error.message })
    );
    return true;
});
