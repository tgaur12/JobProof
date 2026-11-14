"""Step 4 entry point combining URL, text, and recruiter-email findings."""

import argparse
import json
import re
from urllib.parse import parse_qs, urlsplit

from security.domain_checker import normalize_hostname
from security.email_analyzer import analyze_email
from security.scam_detector import analyze_text
from security.security_score import summarize_risk
from security.url_analyzer import analyze_url


# Small, manually curated reference map seeded from tests/jobs.html.
# Company names come from listings. Trusted domains come from this configuration.
COMPANY_DOMAINS = {"microsoft": "microsoft.com", "cisco": "cisco.com"}
DOMAIN_RULE_CODES = {"direct_ip", "unknown_suffix", "company_domain_mismatch", "possible_typosquatting"}


def validate_listing_url(listing_url: str) -> str:
    """Validate an Indeed posting URL independently of caller platform labels."""
    if not isinstance(listing_url, str) or not listing_url:
        raise ValueError("Provide a supported platform listing URL.")
    if "\\" in listing_url or any(
        character.isspace() or ord(character) < 33 or ord(character) == 127
        for character in listing_url
    ):
        raise ValueError("The listing URL contains unsupported characters.")

    parsed = urlsplit(listing_url)
    hostname, is_ip = normalize_hostname(parsed.hostname or "")
    if (
        parsed.scheme != "https" or is_ip
        or not (hostname == "indeed.com" or hostname.endswith(".indeed.com"))
        or parsed.netloc.rsplit("@", 1)[-1].startswith("[")
        or parsed.username is not None or parsed.password is not None
        or parsed.port not in (None, 443) or parsed.netloc.endswith(":")
        or parsed.path not in ("/viewjob", "/m/viewjob")
    ):
        raise ValueError("Use an HTTPS Indeed viewjob URL on its standard port.")

    job_keys = parse_qs(parsed.query, keep_blank_values=True).get("jk", [])
    if len(job_keys) != 1 or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_keys[0]) is None:
        raise ValueError("The listing URL needs one nonempty, supported jk job identifier.")
    return listing_url


def _unavailable_application_url(official_domain: str | None) -> dict:
    """Represent absent application data without treating it as a bad URL."""
    return {
        "url": None,
        "analyzed": False,
        "valid_url": None,
        "hostname": None,
        "registered_domain": None,
        "uses_https": None,
        "is_ip_address": None,
        "is_shortener": None,
        "shortener_check": {"status": "not_checked"},
        "official_domain": official_domain,
        "matches_official_domain": None,
        "domain_similarity": None,
        "possible_typosquatting": None,
        "risk_score": 0,
        "risk_level": "Needs further verification",
        "color": "yellow",
        "findings": [],
        "skipped_checks": [
            "application_url", "https", "ip_address", "registered_domain", "shortener",
            "official_domain_match", "typosquatting",
        ],
    }


def analyze_job(job: dict, company_domains: dict | None = None) -> dict:
    """Analyze the extension's jobData object and expose pending coverage."""
    company = job.get("company", "")
    if not isinstance(company, str):
        raise ValueError("The job company must be a string.")
    if company_domains is None:
        company_domains = COMPANY_DOMAINS
    official_domain = company_domains.get(company.strip().casefold())

    title = job.get("title", "")
    description = job.get("description", "")
    for name, value in (("title", title), ("description", description)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"The job {name} must be a string or None.")
    text = "\n".join(value for value in (title, description) if value)

    listing_url = job.get("listing_url")
    if listing_url is not None:
        validate_listing_url(listing_url)
    description_complete = job.get("description_complete", True)
    if not isinstance(description_complete, bool):
        raise ValueError("description_complete must be a boolean.")
    description_complete = description_complete and bool(description and description.strip())
    application_url = job.get("url")
    application_url_missing = application_url is None or (
        isinstance(application_url, str) and not application_url.strip()
    )
    preliminary = application_url_missing or not description_complete
    if listing_url is not None and application_url_missing:
        url_check = _unavailable_application_url(official_domain)
    else:
        url_check = analyze_url(application_url, official_domain)
        url_check["analyzed"] = True

    checks = {
        "url": url_check,
        "social_engineering": analyze_text(text),
        "email": analyze_email(job.get("recruiter_email"), official_domain),
    }
    findings = []
    domain_findings = {}
    for source, check in checks.items():
        for finding in check["findings"]:
            combined_finding = {"source": source, **finding}
            rule_code = finding["code"].removeprefix("email_")
            if rule_code in DOMAIN_RULE_CODES:
                observed_domain = (
                    check.get("registered_domain") or check.get("hostname") or check.get("email_domain")
                )
                key = (rule_code, observed_domain, check.get("official_domain"))
                if key in domain_findings:
                    domain_findings[key].setdefault("also_reported_by", []).append(source)
                    continue
                domain_findings[key] = combined_finding
            findings.append(combined_finding)

    if listing_url is not None and preliminary:
        findings.append({
            "source": "coverage", "code": "preliminary_listing_data", "points": 0,
            "message": "This preliminary assessment uses the visible listing data. Full description or application details still need verification.",
        })
        if application_url_missing:
            findings.append({
                "source": "coverage", "code": "application_destination_unavailable", "points": 0,
                "message": "The external application destination is unavailable, so its URL and company-domain checks are pending.",
            })

    summary = summarize_risk(findings)
    if listing_url is not None and preliminary and summary["color"] == "green":
        summary.update({"color": "yellow", "risk_level": "Needs further verification"})

    pending_checks = [
        "domain_registration_verification",
        "recruiter_mailbox_verification",
        "machine_learning_prediction",
    ]
    if not description_complete:
        pending_checks.append("job_description_analysis")
    if not checks["social_engineering"]["analyzed"]:
        pending_checks.append("social_engineering_detection")
    if not checks["email"]["analyzed"]:
        pending_checks.append("recruiter_email_analysis")
    if official_domain is None:
        pending_checks.append("company_domain_reference")
    if listing_url is not None and application_url_missing:
        pending_checks.append("application_url_analysis")
    elif checks["url"]["is_shortener"] is None:
        pending_checks.append("url_shortener_detection")

    return {
        "company": company,
        **summary,
        "score_type": "heuristic",
        "analysis_scope": "url_text_and_email",
        "assessment_status": "preliminary" if preliminary else "complete",
        "listing_url": listing_url,
        "description_complete": description_complete,
        "application_url_available": not application_url_missing,
        "url_role": "unavailable" if application_url_missing else "application",
        "findings": findings,
        "checks": checks,
        "pending_checks": pending_checks,
        "notice": "Green indicates lower risk from the checks performed. Job legitimacy still requires verification.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="An absolute application URL.")
    parser.add_argument("--company", default="", help="The company name extracted from the listing.")
    parser.add_argument("--title", default="", help="The title extracted from the listing.")
    parser.add_argument("--description", default="", help="The description extracted from the listing.")
    parser.add_argument("--recruiter-email", help="An optional bare recruiter email address.")
    args = parser.parse_args()
    job = {
        "company": args.company, "url": args.url,
        "title": args.title, "description": args.description,
        "recruiter_email": args.recruiter_email,
    }
    print(json.dumps(analyze_job(job), indent=2))
