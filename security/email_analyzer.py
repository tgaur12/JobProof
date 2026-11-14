"""Analyze one bare recruiter email address and its domain locally.

The MVP accepts an unquoted ASCII local part and an IDNA domain. Mailbox
ownership and domain registration are reported as unknown.
"""

import argparse
import json
import re

if __package__:
    from .domain_checker import (
        analyze_domain, normalize_hostname, normalize_official_domain,
    )
    from .security_score import summarize_risk
else:
    from domain_checker import (
        analyze_domain, normalize_hostname, normalize_official_domain,
    )
    from security_score import summarize_risk


LOCAL_PART = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
)
# Small reference list for the MVP. A personal mailbox needs further checking.
FREE_EMAIL_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "live.com", "aol.com", "icloud.com", "proton.me", "protonmail.com",
    "gmx.com", "mail.com",
}


def _parse_email(email: str) -> tuple[str, str]:
    """Validate the supported address format and normalize only its domain."""
    if not isinstance(email, str) or email.count("@") != 1:
        raise ValueError("Provide one bare email address, such as hiring@example.com.")
    if any(ord(character) < 32 or ord(character) == 127 for character in email):
        raise ValueError("The email address contains control characters.")
    local_part, hostname = email.strip().split("@")
    if len(local_part) > 64 or LOCAL_PART.fullmatch(local_part) is None:
        raise ValueError("Use an unquoted ASCII local part, such as Jane.Doe+jobs.")
    hostname, is_ip = normalize_hostname(hostname, allow_trailing_dot=False)
    if is_ip:
        raise ValueError("The supported email format requires a domain name.")
    if len(local_part) + 1 + len(hostname) > 254:
        raise ValueError("The email address exceeds the supported 254-character limit.")
    return local_part, hostname


def analyze_email(email: str | None, official_domain: str | None = None) -> dict:
    """Return format, domain facts, findings, and explicitly skipped checks."""
    official_domain = normalize_official_domain(official_domain)
    findings = []
    result = {
        "email": email,
        "normalized_email": None,
        "analyzed": False,
        "valid_format": None,
        "email_domain": None,
        "registered_domain": None,
        "is_free_email_provider": None,
        "official_domain": official_domain,
        "matches_official_domain": None,
        "domain_similarity": None,
        "possible_typosquatting": None,
        "mailbox_verified": None,
        "domain_registration_verified": None,
        "verification_scope": "format_and_domain",
        "findings": findings,
        "skipped_checks": [],
    }
    unavailable_checks = ["email_domain", "official_domain_match", "typosquatting"]
    if email is None or (isinstance(email, str) and not email.strip()):
        result["skipped_checks"] = ["email_format", *unavailable_checks]
        result.update(summarize_risk(findings))
        return result

    result["analyzed"] = True
    try:
        local_part, hostname = _parse_email(email)
    except ValueError as error:
        result["valid_format"] = False
        findings.append({"code": "invalid_email_format", "points": 20, "message": str(error)})
        result["skipped_checks"] = unavailable_checks
        result.update(summarize_risk(findings))
        return result

    domain = analyze_domain(hostname, official_domain)
    result.update({
        "valid_format": True,
        "normalized_email": f"{local_part}@{hostname}",
        "email_domain": hostname,
        "is_free_email_provider": hostname in FREE_EMAIL_PROVIDERS,
    })
    for name in (
        "registered_domain", "matches_official_domain", "domain_similarity", "possible_typosquatting",
    ):
        result[name] = domain[name]
    result["skipped_checks"].extend(domain["skipped_checks"])

    if result["is_free_email_provider"]:
        findings.append({
            "code": "free_email_provider", "points": 20,
            "message": "The recruiter uses a known personal-email provider. Independently verify their company affiliation.",
        })
    for finding in domain["findings"]:
        findings.append({**finding, "code": "email_" + finding["code"]})
    result.update(summarize_risk(findings))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", nargs="?", help="One bare recruiter email address.")
    parser.add_argument("--official-domain", help="A trusted bare company domain.")
    args = parser.parse_args()
    if args.email is None:
        result = analyze_email("hiring@microsoft.com", args.official_domain or "microsoft.com")
    else:
        result = analyze_email(args.email, args.official_domain)
    print(json.dumps(result, indent=2))
