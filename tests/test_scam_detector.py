"""Regressions for risky requests, benign wording, and combined scoring."""

import unittest
from unittest.mock import patch

from risk_engine import analyze_job
from security.scam_detector import analyze_text


class ScamDetectorTests(unittest.TestCase):
    def test_upfront_payment_with_explanation(self):
        result = analyze_text("Pay $200 upfront\nfor equipment.")
        self.assertEqual(result["risk_score"], 45)
        self.assertEqual(result["findings"][0]["code"], "upfront_payment")
        self.assertEqual(result["findings"][0]["evidence"], "Pay $200 upfront")

    def test_recruitment_fee_variations(self):
        for text in ["Please pay a registration fee.", "You must pay for training.",
                     "An upfront payment is required.", "Pay a refundable deposit to start.",
                     "Pay us $200 upfront for equipment.",
                     "You must pay the equipment vendor $200 upfront."]:
            with self.subTest(text=text):
                self.assertEqual(analyze_text(text)["findings"][0]["code"], "upfront_payment")

    def test_benign_job_language(self):
        for text in [
            "No experience required. Salary $40,000. Company provides equipment.",
            "Earn $150,000 with no experience. Immediate hiring.",
            "We pay you $200 upfront for equipment.",
            "We will pay for equipment and training.",
            "Deposit your paycheck through our payroll system.",
            "Our engineers build cryptocurrency software.",
            "Salary can be paid in cryptocurrency.",
            "We will pay your salary in cryptocurrency.",
            "After accepting an offer, provide bank account details for payroll.",
            "Urgently hiring. Apply before Friday.",
            "If anyone asks you to pay an application fee, report them.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(analyze_text(text)["findings"], [])

    def test_negated_requests(self):
        for text in [
            "We never charge fees or ask applicants to pay for equipment.",
            "You are not required to pay an application fee.",
            "We don\u2019t ask you to pay upfront.",
            "No upfront payment is required.",
            "Never share your banking password.",
            "Deposit the check and never forward any money.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(analyze_text(text)["findings"], [])

    def test_reassurance_cannot_hide_separate_request(self):
        for text in [
            "We never charge fees. You must pay $200 upfront for equipment.",
            "We never charge fees, but you must pay $200 upfront for equipment.",
            "Do not pay upfront, and then pay an application fee.",
            "You will not be hired unless you pay an application fee.",
            "If anyone asks you to pay upfront, report them. You must pay a registration fee.",
            "If anyone asks you to pay upfront, report them, and then pay a registration fee.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(analyze_text(text)["findings"][0]["code"], "upfront_payment")

    def test_fake_check_forwarding(self):
        for text in ["Deposit the check and return the excess funds to our supplier.",
                     "Deposit the check. Then return the excess funds to our supplier."]:
            with self.subTest(text=text):
                result = analyze_text(text)
                self.assertEqual(result["risk_score"], 60)
                self.assertEqual(result["color"], "red")
                self.assertEqual(result["findings"][0]["code"], "check_forwarding")
                self.assertIn("Deposit the check", result["findings"][0]["evidence"])
                self.assertIn("return the excess", result["findings"][0]["evidence"])

    def test_cryptocurrency_or_gift_card_requests(self):
        for text in ["Send us cryptocurrency to secure your position.",
                     "Pay the fee using bitcoin.", "Buy gift cards and send us the codes."]:
            with self.subTest(text=text):
                codes = [finding["code"] for finding in analyze_text(text)["findings"]]
                self.assertIn("unusual_payment_request", codes)

    def test_credentials(self):
        for credential in ["banking password", "account PIN", "one-time code",
                           "one-time security code", "verification code", "password"]:
            with self.subTest(credential=credential):
                result = analyze_text(f"Share your {credential} with the recruiter.")
                self.assertEqual(result["color"], "red")
                self.assertEqual(result["findings"][0]["code"], "credential_request")

    def test_sensitive_information_before_hiring(self):
        for text in ["Provide your SSN before an interview.",
                     "Before your interview, submit your passport number."]:
            with self.subTest(text=text):
                result = analyze_text(text)
                self.assertEqual(result["risk_score"], 30)
                self.assertEqual(result["findings"][0]["code"], "sensitive_information_before_hiring")

    def test_repeated_wording_counts_once(self):
        result = analyze_text("Pay $200 upfront. Pay a registration fee. Pay for training.")
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["risk_score"], 45)

    def test_missing_text_is_visible(self):
        for text in [None, "", " \n\t"]:
            with self.subTest(text=text):
                result = analyze_text(text)
                self.assertFalse(result["analyzed"])
                self.assertIn("social_engineering_detection", result["skipped_checks"])

    def test_invalid_text_type(self):
        with self.assertRaises(ValueError):
            analyze_text(42)


class CombinedTextRiskTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("security.url_analyzer.SHORTENER_CATALOG.check", return_value={
            "is_shortener": False, "status": "fresh",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_quickmoney_combines_url_and_payment_findings(self):
        result = analyze_job({
            "title": "Remote Data Entry", "company": "QuickMoney Careers",
            "description": "Earn $150,000 with no experience. Immediate hiring. Pay $200 upfront for equipment.",
            "url": "https://quickmoney.example",
        })
        self.assertEqual(result["risk_score"], 70)
        self.assertEqual(result["color"], "red")
        self.assertEqual(result["checks"]["url"]["risk_score"], 25)
        self.assertEqual(result["checks"]["social_engineering"]["risk_score"], 45)
        self.assertEqual(result["findings"][1]["source"], "social_engineering")

    def test_title_is_also_analyzed(self):
        result = analyze_job({"title": "Pay a registration fee", "url": "https://jobs.cisco.com"})
        self.assertEqual(result["checks"]["social_engineering"]["risk_score"], 45)
        self.assertIn("job_description_analysis", result["pending_checks"])

    def test_old_url_only_call_still_works(self):
        result = analyze_job({"company": "Cisco", "url": "https://jobs.cisco.com"})
        self.assertEqual(result["risk_score"], 0)
        self.assertIn("social_engineering_detection", result["pending_checks"])

    def test_combined_score_is_capped(self):
        result = analyze_job({
            "url": "http://192.0.2.1",
            "description": "Pay $200 upfront. Share your banking password.",
        })
        self.assertEqual(result["risk_score"], 100)


if __name__ == "__main__":
    unittest.main()
