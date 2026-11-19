"""Exercise inference behavior with fake artifacts, without loading saved models."""

import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ai import predict


class PredictorTests(unittest.TestCase):
    def setUp(self):
        self.features = SimpleNamespace(nnz=2)
        self.vectorizer = SimpleNamespace(transform=Mock(return_value=self.features))
        self.model = SimpleNamespace(predict_proba=Mock(return_value=[[0.8, 0.2]]))
        loader = patch.object(predict, "_load_artifacts", return_value=(self.model, self.vectorizer, "test-version"))
        self.loader = loader.start()
        self.addCleanup(loader.stop)

    def test_five_fields_use_training_order_and_shared_text_cleaning(self):
        result = predict.predict_fraud(
            "<p>Build cloud APIs</p>", title=" Engineer ", company_profile="Team &amp; Company",
            requirements="Python", benefits="Paid leave",
        )
        self.vectorizer.transform.assert_called_once_with(["Engineer Team & Company Build cloud APIs Python Paid leave"])
        self.model.predict_proba.assert_called_once_with(self.features)
        self.assertEqual(result["ml_score"], 20)
        self.assertEqual(result["fraud_probability"], 0.2)
        self.assertEqual(result["prediction"], 0)
        self.assertEqual(result["classification"], "Likely Legitimate")
        self.assertEqual(result["input_fields"], predict.TEXT_COLS)
        self.assertEqual(result["missing_fields"], [])

    def test_probability_threshold_and_score_come_from_inference(self):
        for probability, label in [(0.49, 0), (0.5, 1), (1.0, 1)]:
            with self.subTest(probability=probability):
                self.model.predict_proba.return_value = [[1 - probability, probability]]
                result = predict.predict_fraud("Develop applications.")
                self.assertEqual(result["prediction"], label)
                self.assertEqual(result["ml_score"], round(probability * 100))

    def test_missing_fields_are_reported_without_inventing_values(self):
        result = predict.predict_fraud("Develop applications.", title=None, benefits=" <p> </p> ")
        self.assertEqual(result["input_fields"], ["description"])
        self.assertEqual(set(result["missing_fields"]), {"title", "company_profile", "requirements", "benefits"})

    def test_empty_or_nontext_input_is_rejected_before_loading_artifacts(self):
        for description, other in [(" <p> </p> ", {}), (None, {}), (42, {}), ("Text", {"requirements": []})]:
            with self.subTest(description=description, other=other):
                with self.assertRaises(ValueError):
                    predict.predict_fraud(description, **other)
        self.loader.assert_not_called()

    def test_all_out_of_vocabulary_text_does_not_produce_false_zero(self):
        self.features.nnz = 0
        with self.assertRaises(ValueError):
            predict.predict_fraud("Unrecognized terms.")
        self.model.predict_proba.assert_not_called()

    def test_nonfinite_or_out_of_range_probability_is_rejected(self):
        for probability in (math.nan, math.inf, -0.1, 1.1):
            with self.subTest(probability=probability):
                self.model.predict_proba.return_value = [[0, probability]]
                with self.assertRaises(ValueError):
                    predict.predict_fraud("Develop applications.")

    def test_model_readiness_is_public_and_failure_details_are_hidden(self):
        status = predict.get_model_status()
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["model"], "tfidf_logistic_regression")
        for exception, expected in [
            (ImportError("private environment path"), "unavailable"),
            (FileNotFoundError("private artifact path"), "unavailable"),
            (RuntimeError("private model details"), "error"),
        ]:
            with self.subTest(exception=type(exception).__name__):
                self.loader.side_effect = exception
                if expected == "error":
                    with self.assertLogs(predict.__name__, level="ERROR"):
                        status = predict.get_model_status()
                else:
                    status = predict.get_model_status()
                self.assertEqual(status["status"], expected)
                self.assertNotIn("private", str(status))


if __name__ == "__main__":
    unittest.main()
