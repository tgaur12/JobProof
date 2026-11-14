"""Preserve application checks while representing incomplete platform data."""

import unittest
from unittest.mock import patch

from risk_engine import analyze_job, validate_listing_url


class PlatformListingTests(unittest.TestCase):
    def setUp(self):
        catalog_patch = patch("security.url_analyzer.SHORTENER_CATALOG.check", return_value={
            "is_shortener": False, "status": "fresh",
        })
        self.catalog_check = catalog_patch.start()
        self.addCleanup(catalog_patch.stop)
        self.listing_url = "https://www.indeed.com/viewjob?jk=0123456789abcdef"

    def listing(self, **overrides):
        job = {
            "title": "Software Engineer", "company": "Microsoft",
            "listing_url": self.listing_url, "url": None,
            "description": "Develop cloud applications...", "description_complete": False,
        }
        job.update(overrides)
        return job

    def test_missing_application_is_unknown_and_snippet_is_preliminary(self):
        result = analyze_job(self.listing())
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["color"], "yellow")
        self.assertEqual(result["assessment_status"], "preliminary")
        self.assertEqual(result["listing_url"], self.listing_url)
        self.assertFalse(result["description_complete"])
        self.assertFalse(result["application_url_available"])
        self.assertEqual(result["url_role"], "unavailable")
        url_check = result["checks"]["url"]
        self.assertFalse(url_check["analyzed"])
        self.assertIsNone(url_check["valid_url"])
        self.assertIsNone(url_check["matches_official_domain"])
        self.assertIsNone(url_check["is_shortener"])
        self.assertEqual(url_check["findings"], [])
        self.assertEqual(url_check["risk_score"], 0)
        self.assertIn("application_url_analysis", result["pending_checks"])
        self.assertIn("job_description_analysis", result["pending_checks"])
        self.assertNotIn("url_shortener_detection", result["pending_checks"])
        self.assertEqual({finding["code"] for finding in result["findings"]}, {
            "preliminary_listing_data", "application_destination_unavailable",
        })
        self.assertTrue(all(finding["points"] == 0 for finding in result["findings"]))
        self.catalog_check.assert_not_called()

    def test_full_description_still_needs_application_destination(self):
        result = analyze_job(self.listing(description_complete=True))
        self.assertEqual(result["color"], "yellow")
        self.assertTrue(result["description_complete"])
        self.assertNotIn("job_description_analysis", result["pending_checks"])
        self.assertIn("application_url_analysis", result["pending_checks"])

    def test_external_official_application_and_full_text_are_complete(self):
        result = analyze_job(self.listing(url="https://careers.microsoft.com", description_complete=True))
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["color"], "green")
        self.assertEqual(result["assessment_status"], "complete")
        self.assertEqual(result["url_role"], "application")
        self.assertTrue(result["application_url_available"])
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["checks"]["url"]["matches_official_domain"])

    def test_external_application_is_analyzed_even_with_valid_platform_source(self):
        result = analyze_job(self.listing(url="https://jobs.micros0ft.com", description_complete=True))
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(result["color"], "red")
        self.assertFalse(result["checks"]["url"]["matches_official_domain"])

    def test_malformed_provided_application_still_has_security_findings(self):
        result = analyze_job(self.listing(url="javascript:alert(1)"))
        self.assertEqual(result["color"], "red")
        self.assertIn("invalid_url", [finding["code"] for finding in result["findings"]])

    def test_recruiter_email_risk_survives_missing_application_url(self):
        result = analyze_job(self.listing(recruiter_email="jobs@micros0ft.com"))
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(result["color"], "red")
        self.assertTrue(result["checks"]["email"]["possible_typosquatting"])

    def test_visible_scam_language_keeps_its_evidence_score(self):
        for description, expected_score, expected_color in [
            ("Pay $200 upfront for equipment.", 45, "yellow"),
            ("Share your banking password with the recruiter.", 60, "red"),
        ]:
            with self.subTest(description=description):
                result = analyze_job(self.listing(description=description))
                self.assertEqual(result["risk_score"], expected_score)
                self.assertEqual(result["color"], expected_color)
                self.assertTrue(result["checks"]["social_engineering"]["findings"])

    def test_blank_description_stays_incomplete_even_with_true_flag(self):
        result = analyze_job(self.listing(
            url="https://careers.microsoft.com", description=" ", description_complete=True,
        ))
        self.assertFalse(result["description_complete"])
        self.assertEqual(result["color"], "yellow")
        self.assertIn("job_description_analysis", result["pending_checks"])

    def test_legacy_missing_url_keeps_existing_red_result(self):
        result = analyze_job({"company": "Microsoft"})
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(result["color"], "red")
        self.assertEqual(result["findings"][0]["code"], "invalid_url")

    def test_legacy_full_job_keeps_existing_green_result(self):
        result = analyze_job({
            "company": "Microsoft", "url": "https://careers.microsoft.com",
            "description": "Develop cloud applications.",
        })
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["color"], "green")
        self.assertEqual(result["assessment_status"], "complete")

    def test_platform_label_cannot_change_application_semantics(self):
        result = analyze_job({
            "company": "Microsoft", "url": "https://jobs.micros0ft.com", "platform": "indeed",
        })
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(result["color"], "red")

    def test_source_validation_accepts_normalized_indeed_hosts(self):
        for url in [
            "https://INDEED.COM/viewjob?jk=test123",
            "https://www.indeed.com:443/m/viewjob?jk=test_123-ABC",
            "https://www.indeed.com./viewjob?jk=test123",
        ]:
            with self.subTest(url=url):
                self.assertEqual(validate_listing_url(url), url)

    def test_direct_engine_also_validates_listing_source(self):
        for url in [
            "https://indeed.com.attacker.net/viewjob?jk=test123",
            "https://www.indeed.com/viewjob?jk=bad%20key",
            "https://www.indeed.com/viewjob?jk=test123\n",
            "https://[v1.indeed.com]/viewjob?jk=test123",
        ]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    analyze_job(self.listing(listing_url=url))

    def test_direct_engine_rejects_nonboolean_completeness(self):
        with self.assertRaises(ValueError):
            analyze_job(self.listing(description_complete="false"))


if __name__ == "__main__":
    unittest.main()
