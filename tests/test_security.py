"""Focused regressions for URL identity checks and the step 4 entry point."""

import unittest
from unittest.mock import patch

from risk_engine import analyze_job
from security.security_score import summarize_risk
from security.url_analyzer import analyze_url


class URLAnalyzerTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("security.url_analyzer.SHORTENER_CATALOG.check", return_value={
            "is_shortener": False, "status": "fresh",
        })
        self.shortener_check = patcher.start()
        self.addCleanup(patcher.stop)

    def test_official_subdomains_and_normalization(self):
        for url in ["https://careers.microsoft.com/apply", "https://CAREERS.MICROSOFT.COM./apply"]:
            with self.subTest(url=url):
                result = analyze_url(url, "microsoft.com")
                self.assertEqual(result["registered_domain"], "microsoft.com")
                self.assertTrue(result["matches_official_domain"])
                self.assertEqual(result["risk_score"], 0)
                self.assertEqual(result["color"], "green")

    def test_multi_part_public_suffix(self):
        result = analyze_url("https://jobs.example.co.uk", "example.co.uk")
        self.assertEqual(result["registered_domain"], "example.co.uk")
        self.assertTrue(result["matches_official_domain"])

    def test_unicode_domain_identity_stays_distinct(self):
        result = analyze_url("https://fa\u00df.de", "fass.de")
        self.assertEqual(result["hostname"], "xn--fa-hia.de")
        self.assertFalse(result["matches_official_domain"])
        self.assertEqual(result["color"], "yellow")

    def test_unicode_dot_normalization(self):
        result = analyze_url("https://careers\u3002microsoft\u3002com", "microsoft.com")
        self.assertTrue(result["matches_official_domain"])
        self.assertEqual(result["hostname"], "careers.microsoft.com")

    def test_http_adds_explained_points(self):
        result = analyze_url("http://careers.microsoft.com", "microsoft.com")
        self.assertFalse(result["uses_https"])
        self.assertEqual(result["risk_score"], 20)
        self.assertEqual(result["color"], "yellow")
        self.assertEqual(result["findings"][0]["code"], "no_https")

    def test_direct_ipv4_and_ipv6(self):
        for url in ["https://192.0.2.1/apply", "https://[2001:db8::1]/apply"]:
            with self.subTest(url=url):
                result = analyze_url(url)
                self.assertTrue(result["is_ip_address"])
                self.assertIsNone(result["registered_domain"])
                self.assertIn("direct_ip", [finding["code"] for finding in result["findings"]])

    def test_typosquatting_is_high_risk(self):
        result = analyze_url("https://careers.micros0ft.com", "microsoft.com")
        self.assertTrue(result["possible_typosquatting"])
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(result["color"], "red")

    def test_brand_text_cannot_establish_company_identity(self):
        for url in [
            "https://microsoft.com.attacker.net/apply",
            "https://microsoft.com@attacker.net/apply",
            "https://attacker.net/microsoft.com?company=microsoft.com",
        ]:
            with self.subTest(url=url):
                result = analyze_url(url, "microsoft.com")
                self.assertEqual(result["registered_domain"], "attacker.net")
                self.assertFalse(result["matches_official_domain"])
                self.assertGreaterEqual(result["risk_score"], 25)

    def test_shortener_requires_verification(self):
        self.shortener_check.return_value = {
            "is_shortener": True, "matched_domain": "bit.ly", "status": "fresh",
        }
        result = analyze_url("https://bit.ly/job")
        self.assertTrue(result["is_shortener"])
        self.assertEqual(result["color"], "yellow")

    def test_unavailable_catalog_marks_shortener_check_as_skipped(self):
        self.shortener_check.return_value = {"is_shortener": None, "status": "unavailable"}
        result = analyze_url("https://example.com/job")
        self.assertIsNone(result["is_shortener"])
        self.assertIn("shortener", result["skipped_checks"])
        self.assertEqual(result["shortener_check"]["status"], "unavailable")

    def test_invalid_url_skips_catalog_access(self):
        analyze_url("javascript:alert(1)")
        self.shortener_check.assert_not_called()

    def test_unrelated_hiring_provider_requires_verification(self):
        result = analyze_url("https://boards.greenhouse.io/example", "microsoft.com")
        self.assertFalse(result["matches_official_domain"])
        self.assertEqual(result["color"], "yellow")

    def test_missing_company_reference_is_visible(self):
        result = analyze_url("https://jobs.cisco.com")
        self.assertIsNone(result["matches_official_domain"])
        self.assertIn("official_domain_match", result["skipped_checks"])
        self.assertIn("typosquatting", result["skipped_checks"])

    def test_unknown_suffix_requires_verification(self):
        result = analyze_url("https://quickmoney.example")
        self.assertIsNone(result["registered_domain"])
        self.assertEqual(result["color"], "yellow")

    def test_private_hosting_tenants_stay_distinct(self):
        result = analyze_url("https://fake.github.io", "company.github.io")
        self.assertEqual(result["registered_domain"], "fake.github.io")
        self.assertFalse(result["matches_official_domain"])

    def test_invalid_urls_produce_structured_findings(self):
        for url in [None, "", "careers.microsoft.com", "javascript:alert(1)",
                    "https://[broken", "https://example.com:99999", "https://example.com:",
                    "https://bad host.com", "https://bad_host.com", "https://example.com\n",
                    "https://microsoft.com\\@attacker.net", "https://[v1.microsoft.com]",
                    "https://microsoft.com..", "https://microsoft.com\u3002."]:
            with self.subTest(url=url):
                result = analyze_url(url)
                self.assertFalse(result["valid_url"])
                self.assertEqual(result["findings"][0]["code"], "invalid_url")
                self.assertEqual(result["color"], "red")

    def test_legacy_numeric_ip_forms_require_canonical_input(self):
        for hostname in ["2130706433", "127.1", "0x7f000001", "0177.0.0.1", "192.168.001.1"]:
            with self.subTest(hostname=hostname):
                result = analyze_url(f"https://{hostname}")
                self.assertFalse(result["valid_url"])
                self.assertEqual(result["findings"][0]["code"], "invalid_url")

    def test_invalid_reference_is_a_configuration_error(self):
        for reference in ["https://microsoft.com", "careers.microsoft.com", "192.0.2.1"]:
            with self.subTest(reference=reference):
                with self.assertRaises(ValueError):
                    analyze_url("https://careers.microsoft.com", reference)


class RiskEngineTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("security.url_analyzer.SHORTENER_CATALOG.check", return_value={
            "is_shortener": False, "status": "fresh",
        })
        self.shortener_check = patcher.start()
        self.addCleanup(patcher.stop)

    def test_unavailable_catalog_is_visible_in_combined_result(self):
        self.shortener_check.return_value = {"is_shortener": None, "status": "unavailable"}
        result = analyze_job({"company": "Microsoft", "url": "https://careers.microsoft.com"})
        self.assertIn("url_shortener_detection", result["pending_checks"])
        self.assertIsNone(result["checks"]["url"]["is_shortener"])

    def test_extension_job_data_and_pending_coverage(self):
        result = analyze_job({
            "title": "Software Engineer", "company": " Microsoft ",
            "description": "Develop cloud applications.", "url": "https://careers.microsoft.com",
        })
        self.assertEqual(result["color"], "green")
        self.assertEqual(result["analysis_scope"], "url_text_and_email")
        self.assertTrue(result["checks"]["social_engineering"]["analyzed"])
        self.assertNotIn("social_engineering_detection", result["pending_checks"])
        self.assertEqual(result["checks"]["url"]["official_domain"], "microsoft.com")

    def test_listing_cannot_supply_its_own_trusted_domain(self):
        result = analyze_job({
            "company": "Microsoft", "url": "https://attacker.net",
            "official_domain": "attacker.net",
        })
        self.assertFalse(result["checks"]["url"]["matches_official_domain"])
        self.assertEqual(result["findings"][0]["source"], "url")

    def test_missing_url(self):
        self.assertEqual(analyze_job({"company": "Microsoft"})["color"], "red")

    def test_score_thresholds_and_cap(self):
        for points, color in [(0, "green"), (19, "green"), (20, "yellow"),
                              (59, "yellow"), (60, "red"), (150, "red")]:
            with self.subTest(points=points):
                result = summarize_risk([{"points": points}])
                self.assertEqual(result["color"], color)
                self.assertLessEqual(result["risk_score"], 100)


if __name__ == "__main__":
    unittest.main()
