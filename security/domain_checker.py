"""Local hostname and trusted company-domain consistency checks.

Public Suffix List extraction identifies a registrable domain. Registration
and ownership require additional evidence and are recorded as unknown here.
"""

import argparse
import ipaddress
import json
from difflib import SequenceMatcher

import idna
import tldextract

if __package__:
    from .security_score import summarize_risk
else:
    from security_score import summarize_risk


EXTRACT_DOMAIN = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
)


def normalize_hostname(hostname: str, allow_trailing_dot: bool = True) -> tuple[str, bool]:
    """Return a canonical hostname and whether it is an IP address."""
    if not isinstance(hostname, str) or not hostname:
        raise ValueError("Provide a nonempty hostname.")
    hostname = hostname.lower()
    if ":" in hostname:
        ipaddress.ip_address(hostname)
        return hostname, True

    hostname = idna.encode(
        hostname, uts46=True, transitional=False
    ).decode("ascii")
    if hostname.endswith(".") and not allow_trailing_dot:
        raise ValueError("The supported email format requires a domain without a trailing dot.")
    hostname = hostname.removesuffix(".")
    try:
        ipaddress.ip_address(hostname)
        return hostname, True
    except ValueError:
        pass

    # Chrome interprets legacy numeric hosts as IPv4. Require canonical input.
    last_label = hostname.rsplit(".", 1)[-1]
    is_hex_number = last_label.startswith("0x") and all(
        character in "0123456789abcdef" for character in last_label[2:]
    )
    if last_label.isdigit() or is_hex_number:
        raise ValueError("Use a valid dotted-decimal IPv4 address for numeric hostnames.")
    return hostname, False


def normalize_official_domain(official_domain: str | None) -> str | None:
    """Validate developer-supplied company references independently of listings."""
    if official_domain is None:
        return None
    official_domain, is_ip = normalize_hostname(official_domain)
    parts = EXTRACT_DOMAIN(official_domain)
    if is_ip or parts.top_domain_under_public_suffix != official_domain:
        raise ValueError("official_domain must be a bare registrable domain, such as microsoft.com.")
    return official_domain


def analyze_domain(hostname: str, official_domain: str | None = None) -> dict:
    """Compare a hostname's registrable domain with a trusted reference."""
    official_domain = normalize_official_domain(official_domain)
    findings = []
    result = {
        "valid_domain": False,
        "hostname": None,
        "registered_domain": None,
        "is_ip_address": None,
        "official_domain": official_domain,
        "matches_official_domain": None,
        "domain_similarity": None,
        "possible_typosquatting": None,
        "domain_registration_verified": None,
        "findings": findings,
        "skipped_checks": [],
    }
    try:
        hostname, is_ip = normalize_hostname(hostname)
    except ValueError as error:
        findings.append({"code": "invalid_domain", "points": 60, "message": str(error)})
        result["skipped_checks"] = ["registered_domain", "official_domain_match", "typosquatting"]
        result.update(summarize_risk(findings))
        return result

    parts = EXTRACT_DOMAIN(hostname)
    registered_domain = None if is_ip else parts.top_domain_under_public_suffix or None
    result.update({
        "valid_domain": True,
        "hostname": hostname,
        "registered_domain": registered_domain,
        "is_ip_address": is_ip,
    })
    if is_ip:
        findings.append({
            "code": "direct_ip", "points": 35,
            "message": "The hostname is an IP address, making company identity harder to verify.",
        })
    elif registered_domain is None:
        findings.append({
            "code": "unknown_suffix", "points": 25,
            "message": "The bundled Public Suffix List could not identify a registrable domain.",
        })

    if official_domain is None:
        result["skipped_checks"].extend(["official_domain_match", "typosquatting"])
    else:
        result["matches_official_domain"] = registered_domain == official_domain
        if not result["matches_official_domain"]:
            findings.append({
                "code": "company_domain_mismatch", "points": 25,
                "message": f"The destination is outside {official_domain}. Verify any third-party hiring provider.",
            })
        if registered_domain is None:
            result["skipped_checks"].append("typosquatting")
        else:
            similarity = SequenceMatcher(None, registered_domain, official_domain).ratio()
            result["domain_similarity"] = round(similarity, 3)
            possible_typo = registered_domain != official_domain and similarity >= 0.8
            result["possible_typosquatting"] = possible_typo
            if possible_typo:
                findings.append({
                    "code": "possible_typosquatting", "points": 35,
                    "message": f"{registered_domain} resembles {official_domain} (similarity {similarity:.2f}).",
                })

    result.update(summarize_risk(findings))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hostname", nargs="?", help="A hostname, such as careers.microsoft.com.")
    parser.add_argument("--official-domain", help="A trusted bare company domain.")
    args = parser.parse_args()
    if args.hostname is None:
        result = analyze_domain("careers.microsoft.com", args.official_domain or "microsoft.com")
    else:
        result = analyze_domain(args.hostname, args.official_domain)
    print(json.dumps(result, indent=2))
