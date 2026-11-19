"""Test combined scoring with real security checks and a controlled ML boundary."""

import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from analysis_service import analyze_job_with_ml, get_analysis_status


def prediction(probability):
    predicted = int(probability >= 0.5)
    return {
        "classification": "Likely Fraudulent" if predicted else "Likely Legitimate",
        "prediction": predicted,
        "fraud_probability": probability,
        "ml_score": round(probability * 100),
    }


class CombinedAnalysisTests(unittest.TestCase):
    def setUp(self):
        catalog = patch("security.url_analyzer.SHORTENER_CATALOG.check", return_value={
            "is_shortener": False, "status": "fresh",
        })
        catalog.start()
        self.addCleanup(catalog.stop)
        self.predictor = Mock(return_value=prediction(0.1))
        self.model_status = Mock(return_value={"status": "ready"})
        self.module = SimpleNamespace(predict_fraud=self.predictor, get_model_status=self.model_status)
        importer = patch("analysis_service.import_module", return_value=self.module)
        self.import_module = importer.start()
        self.addCleanup(importer.stop)

    def job(self, **overrides):
        job = {
            "title": "Software Engineer", "company": "Microsoft",
            "description": "Develop and test cloud applications.",
            "url": "https://careers.microsoft.com",
            "recruiter_email": "hiring@microsoft.com",
        }
        job.update(overrides)
        return job

    def assert_fallback(self, result, security_score=0):
        self.assertEqual(result["security_score"], security_score)
        self.assertIsNone(result["ml_score"])
        self.assertEqual(result["final_score"], security_score)
        self.assertEqual(result["risk_score"], security_score)
        self.assertEqual(result["score_type"], "heuristic")
        self.assertEqual(result["score_formula"], "security_score")
        self.assertIn("machine_learning_prediction", result["pending_checks"])
        check = result["checks"]["machine_learning"]
        self.assertFalse(check["analyzed"])
        for field in ("ml_score", "fraud_probability", "prediction", "classification"):
            self.assertIsNone(check[field], field)
        self.assertNotEqual(check["status"], "ready")

    def test_ml_success_exposes_both_sources_and_max_formula(self):
        result = analyze_job_with_ml(self.job())
        self.assertEqual(result["security_score"], 0)
        self.assertEqual(result["security_color"], "green")
        self.assertEqual(result["ml_score"], 10)
        self.assertEqual(result["final_score"], 10)
        self.assertEqual(result["risk_score"], 10)
        self.assertEqual(result["color"], "green")
        self.assertEqual(result["score_type"], "combined")
        self.assertEqual(result["score_formula"], "max(security_score, ml_score)")
        self.assertEqual(result["analysis_scope"], "security_and_ml")
        self.assertNotIn("machine_learning_prediction", result["pending_checks"])
        check = result["checks"]["machine_learning"]
        self.assertTrue(check["analyzed"])
        self.assertEqual(check["status"], "ready")
        self.assertEqual(check["fraud_probability"], 0.1)
        self.assertEqual(check["prediction"], 0)
        self.assertEqual(check["classification"], "Likely Legitimate")

    def test_existing_color_thresholds_apply_to_combined_score(self):
        for probability, color in [(0.19, "green"), (0.2, "yellow"), (0.59, "yellow"), (0.6, "red"), (1.0, "red")]:
            with self.subTest(probability=probability):
                self.predictor.return_value = prediction(probability)
                result = analyze_job_with_ml(self.job())
                self.assertEqual(result["risk_score"], round(probability * 100))
                self.assertEqual(result["color"], color)

    def test_high_ml_score_can_raise_a_low_security_result(self):
        self.predictor.return_value = prediction(0.92)
        result = analyze_job_with_ml(self.job())
        self.assertEqual(result["security_score"], 0)
        self.assertEqual(result["ml_score"], 92)
        self.assertEqual(result["risk_score"], 92)
        self.assertEqual(result["color"], "red")

    def test_low_ml_score_cannot_dilute_security_evidence(self):
        self.predictor.return_value = prediction(0.01)
        result = analyze_job_with_ml(self.job(description="Share your banking password with the recruiter."))
        self.assertEqual(result["security_score"], 60)
        self.assertEqual(result["ml_score"], 1)
        self.assertEqual(result["risk_score"], 60)
        self.assertEqual(result["color"], "red")
        finding = next(item for item in result["findings"] if item["code"] == "credential_request")
        self.assertEqual(finding["source"], "social_engineering")
        self.assertTrue(finding["evidence"])

    def test_preliminary_platform_coverage_remains_yellow_with_low_scores(self):
        self.predictor.return_value = prediction(0.0)
        result = analyze_job_with_ml(self.job(
            url=None, listing_url="https://www.indeed.com/viewjob?jk=job123",
            description_complete=False,
        ))
        self.assertEqual(result["security_score"], 0)
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["color"], "yellow")
        self.assertEqual(result["assessment_status"], "preliminary")
        self.assertNotIn("machine_learning_prediction", result["pending_checks"])
        self.assertIn("application_url_analysis", result["pending_checks"])

    def test_predictor_receives_only_available_training_fields_and_reports_missing_fields(self):
        result = analyze_job_with_ml(self.job(
            company_profile="A software engineering team.",
            requirements="Experience testing applications.",
            benefits="Paid leave.",
        ))
        self.predictor.assert_called_once_with(
            job_description="Develop and test cloud applications.", title="Software Engineer",
            company_profile="A software engineering team.",
            requirements="Experience testing applications.", benefits="Paid leave.",
        )
        check = result["checks"]["machine_learning"]
        self.assertEqual(set(check["input_fields"]), {"title", "company_profile", "description", "requirements", "benefits"})
        self.assertEqual(check["missing_fields"], [])

        result = analyze_job_with_ml(self.job())
        check = result["checks"]["machine_learning"]
        self.assertEqual(set(check["input_fields"]), {"title", "description"})
        self.assertEqual(set(check["missing_fields"]), {"company_profile", "requirements", "benefits"})

    def test_empty_model_text_is_unavailable_instead_of_a_false_zero_prediction(self):
        result = analyze_job_with_ml(self.job(title="  ", description="\n", company_profile="", requirements=" ", benefits=""))
        self.assert_fallback(result)
        self.predictor.assert_not_called()
        self.import_module.assert_not_called()
        self.assertEqual(result["checks"]["machine_learning"]["input_fields"], [])
        self.assertEqual(len(result["checks"]["machine_learning"]["missing_fields"]), 5)

    def test_missing_model_and_prediction_errors_preserve_security_results(self):
        self.model_status.return_value = {"status": "unavailable", "message": "private model path"}
        with self.assertLogs("analysis_service", level="WARNING"):
            result = analyze_job_with_ml(self.job(description="Share your banking password with the recruiter."))
        self.assert_fallback(result, 60)
        self.predictor.assert_not_called()
        self.assertNotIn("private model path", str(result))

        self.model_status.return_value = {"status": "ready"}
        self.predictor.side_effect = RuntimeError("private prediction details")
        with self.assertLogs("analysis_service", level="ERROR") as logs:
            result = analyze_job_with_ml(self.job(description="Share your banking password with the recruiter."))
        self.assert_fallback(result, 60)
        self.assertNotIn("private prediction details", str(result))
        self.assertNotIn("private prediction details", "\n".join(logs.output))

    def test_dependency_import_failure_falls_back_without_fabricating_ml_output(self):
        self.import_module.side_effect = ImportError("internal environment path")
        with self.assertLogs("analysis_service", level="ERROR"):
            result = analyze_job_with_ml(self.job())
        self.assert_fallback(result)
        self.assertNotIn("internal environment path", str(result))

    def test_unusable_cleaned_or_out_of_vocabulary_text_keeps_ml_unavailable(self):
        self.predictor.side_effect = ValueError("The supplied text has no model vocabulary terms.")
        with self.assertLogs("analysis_service", level="ERROR"):
            result = analyze_job_with_ml(self.job())
        self.assert_fallback(result)
        self.assertEqual(result["checks"]["machine_learning"]["status"], "unavailable")

    def test_invalid_numeric_model_results_are_rejected(self):
        bad_fields = {
            "ml_score": [-1, 101, math.nan, math.inf, "10", True, None],
            "fraud_probability": [-0.1, 1.1, math.nan, math.inf, "0.1", True, None],
            "prediction": [-1, 2, "0", True, None],
        }
        for field, values in bad_fields.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.predictor.return_value = {**prediction(0.1), field: value}
                    with self.assertLogs("analysis_service", level="ERROR"):
                        self.assert_fallback(analyze_job_with_ml(self.job()))

    def test_missing_or_non_object_model_output_is_unavailable(self):
        for value in (None, [], {}, {"ml_score": 10}):
            with self.subTest(value=value):
                self.predictor.return_value = value
                with self.assertLogs("analysis_service", level="ERROR"):
                    self.assert_fallback(analyze_job_with_ml(self.job()))

    def test_nontext_optional_model_inputs_do_not_reach_the_predictor(self):
        for field, value in [("company_profile", 42), ("requirements", []), ("benefits", math.nan)]:
            with self.subTest(field=field):
                with self.assertLogs("analysis_service", level="WARNING"):
                    self.assert_fallback(analyze_job_with_ml(self.job(**{field: value})))
        self.predictor.assert_not_called()
        self.import_module.assert_not_called()

    def test_health_reports_model_readiness_and_pending_coverage(self):
        status = get_analysis_status()
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["analysis_mode"], "security_and_ml")
        self.assertEqual(status["machine_learning"]["status"], "ready")
        self.assertNotIn("machine_learning_prediction", status["pending_checks"])
        self.model_status.return_value = {"status": "error", "message": "private details"}
        with self.assertLogs("analysis_service", level="WARNING"):
            status = get_analysis_status()
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["analysis_mode"], "security_only")
        self.assertIn("machine_learning_prediction", status["pending_checks"])
        self.assertNotIn("private details", str(status))


if __name__ == "__main__":
    unittest.main()
