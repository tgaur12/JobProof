"""Analyze URL structure and explain each heuristic risk finding.

The official domain must come from a trusted company reference. Public Suffix
List extraction identifies a registrable domain, without checking registration.
Shortener detection uses a cached catalog that refreshes from its HTTPS source.
"""

import argparse
import ipaddress
import json
from urllib.parse import urlsplit

# Support both `python security/url_analyzer.py` and package imports.
if __package__:
    from .domain_checker import (
        analyze_domain,
        normalize_hostname as _normalize_hostname,
        normalize_official_domain,
    )
    from .security_score import summarize_risk
    from .shortener_catalog import DEFAULT_CATALOG as SHORTENER_CATALOG
else:
    from domain_checker import (
        analyze_domain,
        normalize_hostname as _normalize_hostname,
        normalize_official_domain,
    )
    from security_score import summarize_risk
    from shortener_catalog import DEFAULT_CATALOG as SHORTENER_CATALOG


def _parse_http_url(url: str):
    """Reject incomplete or malformed input before applying security rules."""
    if not isinstance(url, str) or not url:
        raise ValueError("Provide a nonempty, absolute HTTP or HTTPS URL.")
    if "\\" in url or any(
        character.isspace() or ord(character) < 33 or ord(character) == 127
        for character in url
    ):
        raise ValueError("The URL contains whitespace, control characters, or backslashes.")

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Provide an absolute URL starting with http:// or https://.")
    if parsed.netloc.rsplit("@", 1)[-1].startswith("["):
        ipaddress.IPv6Address(parsed.hostname)
    # Reading .port also validates malformed and out-of-range ports.
    port = parsed.port
    if port is None and parsed.netloc.endswith(":"):
        raise ValueError("The URL has an empty port.")
    hostname, is_ip = _normalize_hostname(parsed.hostname)
    return parsed, hostname, is_ip


def analyze_url(url: str, official_domain: str | None = None) -> dict:
    """Return URL facts, findings, and a heuristic score between 0 and 100."""
    # Validate configuration separately so a bad reference is visible to developers.
    official_domain = normalize_official_domain(official_domain)

    findings = []
    result = {
        "url": url,
        "valid_url": False,
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
        "findings": findings,
        "skipped_checks": [],
    }

    try:
        parsed, hostname, is_ip = _parse_http_url(url)
    except (ValueError, UnicodeError) as error:
        findings.append({"code": "invalid_url", "points": 60, "message": str(error)})
        result["skipped_checks"] = [
            "https", "ip_address", "registered_domain", "shortener",
            "official_domain_match", "typosquatting",
        ]
        result.update(summarize_risk(findings))
        return result

    domain = analyze_domain(hostname, official_domain)
    registered_domain = domain["registered_domain"]
    for name in ("matches_official_domain", "domain_similarity", "possible_typosquatting"):
        result[name] = domain[name]
    result["skipped_checks"].extend(domain["skipped_checks"])
    result.update({
        "valid_url": True,
        "hostname": hostname,
        "registered_domain": registered_domain,
        "uses_https": parsed.scheme == "https",
        "is_ip_address": is_ip,
    })

    shortener_check = SHORTENER_CATALOG.check(hostname)
    result["shortener_check"] = shortener_check
    result["is_shortener"] = shortener_check["is_shortener"]
    if result["is_shortener"] is None:
        result["skipped_checks"].append("shortener")

    if not result["uses_https"]:
        findings.append({
            "code": "no_https", "points": 20,
            "message": "The application URL uses unencrypted HTTP.",
        })
    if result["is_shortener"]:
        findings.append({
            "code": "url_shortener", "points": 25,
            "message": "A known URL shortener hides the final application destination.",
        })
    if parsed.username is not None or parsed.password is not None:
        findings.append({
            "code": "url_credentials", "points": 20,
            "message": f"The URL includes user information. The destination hostname is {hostname}.",
        })

    findings.extend(domain["findings"])

    result.update(summarize_risk(findings))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="An absolute application URL. Omit to run the Microsoft example.")
    parser.add_argument("--official-domain", help="A trusted bare company domain for comparison.")
    args = parser.parse_args()

    if args.url is None:
        result = analyze_url("https://careers.microsoft.com/apply", args.official_domain or "microsoft.com")
    else:
        result = analyze_url(args.url, args.official_domain)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
