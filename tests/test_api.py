"""Exercise the API contract and real security-engine results offline."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class AnalysisAPITests(unittest.TestCase):
    def setUp(self):
        catalog_patch = patch("security.url_analyzer.SHORTENER_CATALOG.check", return_value={
            "is_shortener": False, "status": "fresh",
        })
        catalog_patch.start()
        self.addCleanup(catalog_patch.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_health_discloses_current_analysis_mode(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["analysis_mode"], "security_only")
        self.assertIn("machine_learning_prediction", response.json()["pending_checks"])

    def test_normal_listing_returns_real_engine_output(self):
        response = self.client.post("/analyze", json={
            "title": "Software Engineer",
            "company": "Microsoft",
            "description": "Develop cloud applications. Bachelor's degree required.",
            "url": "https://careers.microsoft.com",
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["color"], "green")
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["checks"]["url"]["matches_official_domain"])
        self.assertEqual(result["analysis_scope"], "url_text_and_email")
        self.assertIn("machine_learning_prediction", result["pending_checks"])
        self.assertIn("verification", result["notice"])

    def test_payment_request_returns_red_with_explanation(self):
        response = self.client.post("/analyze", json={
            "title": "Remote Data Entry",
            "company": "QuickMoney Careers",
            "description": "Earn $150,000 with no experience. Pay $200 upfront for equipment.",
            "url": "https://quickmoney.example",
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["risk_score"], 70)
        self.assertEqual(result["color"], "red")
        payment = next(finding for finding in result["findings"] if finding["code"] == "upfront_payment")
        self.assertEqual(payment["source"], "social_engineering")
        self.assertEqual(payment["evidence"], "Pay $200 upfront")
        self.assertTrue(payment["message"])

    def test_optional_fields_default_and_missing_coverage_is_visible(self):
        response = self.client.post("/analyze", json={"url": "https://jobs.cisco.com"})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["company"], "")
        self.assertIn("job_description_analysis", result["pending_checks"])
        self.assertIn("recruiter_email_analysis", result["pending_checks"])

    def test_recruiter_email_reaches_email_analyzer(self):
        response = self.client.post("/analyze", json={
            "company": "Microsoft",
            "url": "https://careers.microsoft.com",
            "recruiter_email": "jobs@micros0ft.com",
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(result["color"], "red")
        self.assertEqual(result["checks"]["email"]["email_domain"], "micros0ft.com")

    def test_malformed_url_returns_structured_security_result(self):
        response = self.client.post("/analyze", json={"url": "javascript:alert(1)"})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["color"], "red")
        self.assertFalse(result["checks"]["url"]["valid_url"])
        self.assertEqual(result["findings"][0]["code"], "invalid_url")

    def test_invalid_request_body_returns_validation_error(self):
        for payload in [
            {}, {"url": ""}, {"url": None}, {"url": 42},
            {"url": "https://example.com", "company": []},
            {"url": "x" * 8193},
            {"url": "https://example.com", "description": "x" * 100001},
        ]:
            with self.subTest(payload_keys=list(payload)):
                response = self.client.post("/analyze", json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertIsInstance(response.json()["detail"], list)

    def test_platform_listing_accepts_missing_application_url(self):
        response = self.client.post("/analyze", json={
            "company": "Microsoft",
            "listing_url": "https://www.indeed.com/viewjob?jk=0123456789abcdef",
            "description": "Develop cloud applications...",
            "description_complete": False,
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["color"], "yellow")
        self.assertEqual(result["assessment_status"], "preliminary")
        self.assertIsNone(result["checks"]["url"]["valid_url"])
        self.assertIn("application_url_analysis", result["pending_checks"])
        self.assertIn("job_description_analysis", result["pending_checks"])

    def test_platform_source_is_validated_independently(self):
        for listing_url in [
            "http://www.indeed.com/viewjob?jk=test123",
            "https://www.indeed.com.attacker.net/viewjob?jk=test123",
            "https://notindeed.com/viewjob?jk=test123",
            "https://www.indeed.com@attacker.net/viewjob?jk=test123",
            "https://user:password@www.indeed.com/viewjob?jk=test123",
            "https://www.indeed.com:8443/viewjob?jk=test123",
            "https://www.indeed.com/jobs?jk=test123",
            "https://www.indeed.com/viewjob",
            "https://www.indeed.com/viewjob?jk=",
            "https://www.indeed.com/viewjob?jk=one&jk=two",
            "https://www.indeed.com/viewjob?jk=bad%2Fkey",
        ]:
            with self.subTest(listing_url=listing_url):
                response = self.client.post("/analyze", json={
                    "url": "https://careers.microsoft.com", "listing_url": listing_url,
                    "platform": "indeed",
                })
                self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
