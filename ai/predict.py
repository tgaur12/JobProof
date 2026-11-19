"""Run inference with the finalized TF-IDF and Logistic Regression artifacts."""

import math
import logging
from pathlib import Path
from threading import Lock
import warnings

if __package__:
    from .preprocess import clean_text, TEXT_COLS
else:
    from preprocess import clean_text, TEXT_COLS

MODEL_DIR = Path(__file__).resolve().parent / "models"
THRESHOLD = 0.5
_artifacts = None
_load_lock = Lock()
_logger = logging.getLogger(__name__)


def _load_artifacts():
    """Load the project's saved artifacts once, including concurrent API calls."""
    global _artifacts
    with _load_lock:
        if _artifacts is not None:
            return _artifacts

        import joblib
        import sklearn
        from sklearn.exceptions import InconsistentVersionWarning

        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            model = joblib.load(MODEL_DIR / "logistic_model.joblib")
            vectorizer = joblib.load(MODEL_DIR / "tfidf_vectorizer.joblib")

        if not callable(getattr(model, "predict_proba", None)) or not callable(getattr(vectorizer, "transform", None)):
            raise ValueError("The saved artifacts do not support the inference interface.")
        classes = list(model.classes_)
        if classes != [0, 1] or model.n_features_in_ != len(vectorizer.vocabulary_):
            raise ValueError("The saved model and vectorizer are incompatible.")
        _artifacts = model, vectorizer, sklearn.__version__
        return _artifacts


def get_model_status():
    """Check readiness without exposing file paths or starting training."""
    try:
        _, _, version = _load_artifacts()
        return {"status": "ready", "model": "tfidf_logistic_regression", "sklearn_version": version}
    except ImportError:
        return {"status": "unavailable", "reason": "missing_dependencies"}
    except FileNotFoundError:
        return {"status": "unavailable", "reason": "missing_artifacts"}
    except Exception:
        _logger.exception("Could not load the saved JobProof model artifacts")
        return {"status": "error", "reason": "model_load_failed"}


def predict_fraud(job_description, title="", company_profile="", requirements="", benefits=""):
    """Use the same five-field cleaning and order as final model training.

    The output is an estimated text score. Calibration and real-world evaluation
    are needed before treating it as a reliable fraud probability.
    """
    fields = {
        "title": title,
        "company_profile": company_profile,
        "description": job_description,
        "requirements": requirements,
        "benefits": benefits,
    }

    if any(value is not None and not isinstance(value, str) for value in fields.values()):
        raise ValueError("Model input fields must be text or None.")
    fields = {name: clean_text(value or "") for name, value in fields.items()}
    cleaned = " ".join(fields[name] for name in TEXT_COLS).strip()
    if not cleaned:
        raise ValueError("Job posting text is empty.")

    model, vectorizer, _ = _load_artifacts()
    features = vectorizer.transform([cleaned])
    if features.nnz == 0:
        raise ValueError("The supplied text has no terms in the saved model vocabulary.")
    probability = float(model.predict_proba(features)[0][1])
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("The model returned an invalid score.")
    prediction = int(probability >= THRESHOLD)

    return {
        "classification": "Likely Fraudulent" if prediction == 1 else "Likely Legitimate",
        "prediction": prediction,
        "fraud_probability": probability,
        "ml_score": round(probability * 100),
        "input_fields": [name for name in TEXT_COLS if fields[name]],
        "missing_fields": [name for name in TEXT_COLS if not fields[name]],
    }
