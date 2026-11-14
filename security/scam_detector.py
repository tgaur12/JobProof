"""Explainable English text rules for a first social-engineering detector."""

import argparse
import json
import re
import unicodedata

if __package__:
    from .security_score import summarize_risk
else:
    from security_score import summarize_risk


# Each rule requires all its patterns. The points are provisional MVP weights.
# Repeated wording earns points once per rule.
RULES = (
    {
        "code": "upfront_payment",
        "points": 45,
        "message": "The text requests payment for recruitment, equipment, or training.",
        "patterns": (
            r"\b(?:pay|send|submit)\s+"
            r"(?:(?:us|me|(?:the|our|your)\s+(?:equipment\s+)?(?:vendor|recruiter|company))\s+)?"
            r"(?:(?:a|an|the)\s+)?"
            r"(?:refundable\s+)?(?:[$\u00a3\u20ac]?\s*\d[\d,.]*\s+)?"
            r"(?:up[\s-]*front\b|in advance\b|"
            r"(?:application|registration|processing|training|equipment|starter[\s-]kit)\s+(?:fee|deposit)\b|"
            r"(?:fee|deposit)\s+(?:to apply|to start|before starting|upfront|in advance)\b|"
            r"for\s+(?:equipment|training|certification|a starter kit)\b)"
            r"|\b(?:up[\s-]*front|advance)\s+(?:payment|fee|deposit)\s+(?:is\s+)?required\b",
        ),
    },
    {
        "code": "check_forwarding",
        "points": 60,
        "message": "The text asks you to deposit a check and forward money or buy gift cards.",
        "patterns": (
            r"\b(?:deposit|cash)\s+(?:(?:a|the|our|your|this)\s+)?(?:company\s+)?check\b",
            r"\b(?:send|wire|transfer|return|forward)\b.{0,60}?"
            r"\b(?:money|funds|balance|excess|remainder|difference|rest|overpayment)\b"
            r"|\b(?:buy|purchase)\b.{0,40}?\bgift[\s-]cards?\b",
        ),
    },
    {
        "code": "unusual_payment_request",
        "points": 35,
        "message": "The text requests cryptocurrency, gift cards, or gift-card codes.",
        "patterns": (
            r"\b(?:pay|send|transfer)\b.{0,60}?\b(?:bitcoin|cryptocurrency|crypto|gift[\s-]cards?)\b"
            r"|\b(?:buy|purchase)\b.{0,40}?\bgift[\s-]cards?\b",
        ),
    },
    {
        "code": "credential_request",
        "points": 60,
        "message": "The text requests an account password, banking PIN, or security code.",
        "patterns": (
            r"\b(?:send|share|provide|reveal|give)\b.{0,50}?\b"
            r"(?:(?:bank(?:ing)?|account|email|your|login)\s+(?:login\s+)?password|"
            r"(?:bank(?:ing)?|account)\s+pin|one[\s-]time\s+(?:security\s+)?(?:password|code)|"
            r"verification\s+code)\b",
        ),
    },
    {
        "code": "sensitive_information_before_hiring",
        "points": 30,
        "message": "The text requests sensitive identity information before an interview or offer.",
        "patterns": (
            r"\b(?:send|share|provide|submit)\b.{0,50}?\b"
            r"(?:ssn|social security number|passport(?: number| copy)?|bank account (?:number|details))\b",
            r"\b(?:before|prior to)\s+(?:(?:an?|the|your)\s+)?(?:interview|offer|job offer)\b",
        ),
    },
)

# Limit negation handling to nearby words so a separate reassurance cannot
# suppress an affirmative request elsewhere in the listing.
NEGATED_PREFIX = re.compile(
    r"\b(?:never|not|don't|do not|won't|will not|no need to|without having to)"
    r"(?:\s+(?:ever|have|need|be|required|expected|asked|obligated|ask|require|"
    r"you|applicants?|candidates?|to|under|any|circumstances)){0,6}\s*$"
    r"|\b(?:never|don't|do not|won't|will not)\s+charge\s+(?:[a-z]+\s+){0,2}fees?\s+"
    r"or\s+(?:ask|require)\s+(?:you|applicants|candidates)\s+to\s*$"
    r"|\bno\s*$",
    re.IGNORECASE,
)
WARNING = re.compile(
    r"\bif\s+(?:anyone|someone|a recruiter)\s+(?:asks?|tells?)\s+you\s+to\b"
    r"[^.!?;]{0,160}?,\s*(?:report|ignore|avoid|decline)\s+(?:them|it|the request)\b",
    re.IGNORECASE,
)
EMPLOYER_PREFIX = re.compile(
    r"\b(?:we|(?:the|our)\s+(?:company|employer))\s+"
    r"(?:(?:will|can|may|must|would|also|always|usually)\s+){0,2}$",
    re.IGNORECASE,
)


def _find_request(pattern: str, clause: str):
    """Find an affirmative request while handling common nearby negations."""
    warnings = list(WARNING.finditer(clause))
    for match in re.finditer(pattern, clause, re.IGNORECASE):
        prefix = clause[:match.start()]
        if NEGATED_PREFIX.search(prefix) or EMPLOYER_PREFIX.search(prefix):
            continue
        if any(warning.start() <= match.start() < warning.end() for warning in warnings):
            continue
        return match
    return None


def analyze_text(text: str | None) -> dict:
    """Return findings with matched excerpts using the shared scoring format."""
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise ValueError("Job text must be a string or None.")

    normalized = unicodedata.normalize("NFKC", text).replace("\u2019", "'")
    normalized = " ".join(normalized.split())
    clauses = re.split(
        r"(?<=[.!?;])\s+|\s+(?:but|however|yet)\s+", normalized, flags=re.IGNORECASE
    )

    findings = []
    for rule in RULES:
        for index, clause in enumerate(clauses):
            # A check and its forwarding instruction can span two sentences.
            if rule["code"] == "check_forwarding" and index + 1 < len(clauses):
                clause = clause + " " + clauses[index + 1]
            matches = [_find_request(pattern, clause) for pattern in rule["patterns"]]
            if all(matches):
                findings.append({
                    "code": rule["code"],
                    "points": rule["points"],
                    "message": rule["message"],
                    "evidence": " ... ".join(match.group(0) for match in matches),
                })
                break

    return {
        "analyzed": bool(normalized),
        **summarize_risk(findings),
        "findings": findings,
        "skipped_checks": [] if normalized else ["social_engineering_detection"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "text", nargs="?", default="Pay $200 upfront for equipment.",
        help="The job text to inspect. Omit to run an upfront-payment example.",
    )
    args = parser.parse_args()
    print(json.dumps(analyze_text(args.text), indent=2))
