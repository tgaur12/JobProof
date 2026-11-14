"""Identity and compatibility regressions for shared domain and email checks."""

import unittest
from unittest.mock import patch

from risk_engine import analyze_job
from security.domain_checker import analyze_domain
from security.email_analyzer import analyze_email


class DomainCheckerTests(unittest.TestCase):
    def test_company_subdomains(self):
        result = analyze_domain("CAREERS.MICROSOFT.COM.", "microsoft.com")
        self.assertEqual(result["hostname"], "careers.microsoft.com")
        self.assertTrue(result["matches_official_domain"])
        self.assertIsNone(result["domain_registration_verified"])

    def test_invalid_hostname(self):
        result = analyze_domain("https://microsoft.com", "microsoft.com")
        self.assertFalse(result["valid_domain"])
        self.assertEqual(result["findings"][0]["code"], "invalid_domain")

    def test_invalid_trusted_reference_is_configuration_error(self):
        with self.assertRaises(ValueError):
            analyze_domain("careers.microsoft.com", "careers.microsoft.com")

    def test_empty_domain_labels_are_rejected(self):
        for hostname in ["microsoft.com..", "microsoft.com\u3002.", "jobs..microsoft.com"]:
            with self.subTest(hostname=hostname):
                result = analyze_domain(hostname, "microsoft.com")
                self.assertFalse(result["valid_domain"])
                self.assertIsNone(result["matches_official_domain"])


class EmailAnalyzerTests(unittest.TestCase):
    def test_official_email_preserves_local_part_case(self):
        result = analyze_email(" Jane.Doe+jobs@CAREERS.MICROSOFT.COM ", "microsoft.com")
        self.assertTrue(result["valid_format"])
        self.assertTrue(result["matches_official_domain"])
        self.assertEqual(result["normalized_email"], "Jane.Doe+jobs@careers.microsoft.com")
        self.assertEqual(result["risk_score"], 0)
        self.assertIsNone(result["mailbox_verified"])
        self.assertIsNone(result["domain_registration_verified"])

    def test_missing_email_is_skipped(self):
        for email in [None, "", " \n\t"]:
            with self.subTest(email=email):
                result = analyze_email(email, "microsoft.com")
                self.assertFalse(result["analyzed"])
                self.assertIsNone(result["valid_format"])
                self.assertEqual(result["risk_score"], 0)
                self.assertIn("email_format", result["skipped_checks"])

    def test_free_provider_with_company_mismatch(self):
        result = analyze_email("recruiter@gmail.com", "microsoft.com")
        self.assertTrue(result["is_free_email_provider"])
        self.assertFalse(result["matches_official_domain"])
        self.assertEqual(result["risk_score"], 45)
        self.assertEqual(result["color"], "yellow")

    def test_lookalike_is_high_risk(self):
        result = analyze_email("jobs@micros0ft.com", "microsoft.com")
        self.assertTrue(result["possible_typosquatting"])
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(result["color"], "red")

    def test_brand_substring_cannot_establish_identity(self):
        for email in ["jobs@microsoft.com.attacker.net", "jobs@gmail.com.attacker.net"]:
            with self.subTest(email=email):
                result = analyze_email(email, "microsoft.com")
                self.assertEqual(result["registered_domain"], "attacker.net")
                self.assertFalse(result["matches_official_domain"])
                self.assertFalse(result["is_free_email_provider"])

    def test_unicode_domains_stay_distinct(self):
        result = analyze_email("jobs@fa\u00df.de", "fass.de")
        self.assertEqual(result["email_domain"], "xn--fa-hia.de")
        self.assertFalse(result["matches_official_domain"])

    def test_private_hosting_tenants_stay_distinct(self):
        result = analyze_email("jobs@other.github.io", "company.github.io")
        self.assertEqual(result["registered_domain"], "other.github.io")
        self.assertFalse(result["matches_official_domain"])

    def test_unknown_company_reference_is_skipped(self):
        result = analyze_email("jobs@example.com")
        self.assertTrue(result["valid_format"])
        self.assertIsNone(result["matches_official_domain"])
        self.assertIn("official_domain_match", result["skipped_checks"])

    def test_unknown_suffix_is_visible(self):
        result = analyze_email("jobs@quickmoney.example")
        self.assertTrue(result["valid_format"])
        self.assertIsNone(result["registered_domain"])
        self.assertEqual(result["color"], "yellow")

    def test_malformed_or_unsupported_addresses(self):
        for email in [
            "jobs", "a@@microsoft.com", "a..b@microsoft.com", ".jobs@microsoft.com",
            "jobs.@microsoft.com", "jobs@", "jobs@bad_host.com", "jobs@microsoft.com/path",
            "jobs@microsoft.com:443", "jobs@[2001:db8::1]", "jobs@192.0.2.1",
            "jobs@microsoft.com.", "jobs@microsoft.com..", "jobs@microsoft.com\u3002.",
            "jobs@microsoft.com\u3002", "jobs@microsoft.com.\u00ad",
            "jobs@microsoft.com\r\nBcc: attacker@example.com", "jobs@microsoft.com\n",
            "Recruiter <jobs@microsoft.com>", "mailto:jobs@microsoft.com",
            "jobs@microsoft.com,other@microsoft.com", '"quoted local"@microsoft.com',
            "\u00e9quipe@microsoft.com", "a" * 65 + "@microsoft.com", 42,
        ]:
            with self.subTest(email=email):
                result = analyze_email(email, "microsoft.com")
                self.assertTrue(result["analyzed"])
                self.assertFalse(result["valid_format"])
                self.assertEqual(result["color"], "yellow")
                self.assertEqual(result["findings"][0]["code"], "invalid_email_format")


class CombinedEmailRiskTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("security.url_analyzer.SHORTENER_CATALOG.check", return_value={
            "is_shortener": False, "status": "fresh",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_old_jobs_keep_scores_without_email(self):
        for company, url, description, expected in [
            ("Microsoft", "https://careers.microsoft.com", "Develop cloud applications.", 0),
            ("QuickMoney Careers", "https://quickmoney.example", "Pay $200 upfront for equipment.", 70),
            ("Cisco", "https://jobs.cisco.com", "Investigate security incidents.", 0),
        ]:
            with self.subTest(company=company):
                result = analyze_job({"company": company, "url": url, "description": description})
                self.assertEqual(result["risk_score"], expected)
                self.assertIn("recruiter_email_analysis", result["pending_checks"])

    def test_email_findings_are_combined(self):
        result = analyze_job({
            "company": "Microsoft", "url": "https://careers.microsoft.com",
            "description": "Develop cloud applications.", "recruiter_email": "jobs@micros0ft.com",
        })
        self.assertEqual(result["risk_score"], 60)
        self.assertTrue(all(finding["source"] == "email" for finding in result["findings"]))
        self.assertNotIn("recruiter_email_analysis", result["pending_checks"])

    def test_application_domain_evidence_is_counted_once(self):
        result = analyze_job({"company": "Microsoft", "url": "https://careers.micros0ft.com"})
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(len(result["findings"]), 2)
        self.assertTrue(all(finding["source"] == "url" for finding in result["findings"]))

    def test_listing_cannot_supply_its_own_email_reference(self):
        result = analyze_job({
            "company": "Microsoft", "url": "https://careers.microsoft.com",
            "recruiter_email": "jobs@attacker.net", "official_domain": "attacker.net",
        })
        self.assertFalse(result["checks"]["email"]["matches_official_domain"])
        self.assertEqual(result["checks"]["email"]["official_domain"], "microsoft.com")

    def test_same_lookalike_domain_is_scored_once_across_url_and_email(self):
        result = analyze_job({
            "company": "Microsoft", "url": "https://careers.micros0ft.com",
            "recruiter_email": "jobs@micros0ft.com",
        })
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(len(result["findings"]), 2)
        self.assertTrue(all(finding["also_reported_by"] == ["email"] for finding in result["findings"]))
        self.assertEqual(result["checks"]["email"]["risk_score"], 60)

    def test_distinct_mismatched_domains_contribute_separately(self):
        result = analyze_job({
            "company": "Microsoft", "url": "https://attacker.net",
            "recruiter_email": "jobs@unrelated.org",
        })
        self.assertEqual(result["risk_score"], 50)
        self.assertEqual(len(result["findings"]), 2)

    def test_same_unknown_suffix_is_scored_once_across_channels(self):
        result = analyze_job({
            "company": "QuickMoney Careers", "url": "https://quickmoney.example",
            "description": "Pay $200 upfront.", "recruiter_email": "jobs@quickmoney.example",
        })
        self.assertEqual(result["risk_score"], 70)


if __name__ == "__main__":
    unittest.main()
