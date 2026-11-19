"""Combine the existing security assessment with the finalized ML predictor."""

from importlib import import_module
import logging
import math
from numbers import Integral, Real
import traceback

from risk_engine import analyze_job
from security.security_score import summarize_risk


logger = logging.getLogger(__name__)
TEXT_FIELDS = ("title", "company_profile", "description", "requirements", "benefits")
UNAVAILABLE_MESSAGE = "ML prediction is unavailable. The security assessment is available."


def _log_failure(operation, error):
    # Traceback frames retain debugging context while exception messages may
    # contain user-supplied posting text from third-party prediction code.
    logger.error(
        "%s (%s)\n%s", operation, type(error).__name__,
        "".join(traceback.format_tb(error.__traceback__)),
    )


def _get_predictor():
    try:
        predictor = import_module("ai.predict")
        readiness = predictor.get_model_status()
        if not isinstance(readiness, dict) or readiness.get("status") not in {"ready", "unavailable", "error"}:
            raise TypeError("The predictor returned an unsupported readiness status.")
        if readiness["status"] != "ready":
            reason = readiness.get("reason")
            if reason not in {"missing_dependencies", "missing_artifacts", "model_load_failed"}:
                reason = "model_not_ready"
            logger.warning("ML readiness is %s (%s).", readiness["status"], reason)
            return None, {"status": readiness["status"], "message": UNAVAILABLE_MESSAGE}
        if not callable(getattr(predictor, "predict_fraud", None)):
            raise TypeError("The predictor has no inference function.")
    except (ImportError, FileNotFoundError) as error:
        _log_failure("ML predictor could not be loaded", error)
        return None, {"status": "unavailable", "message": UNAVAILABLE_MESSAGE}
    except Exception as error:
        _log_failure("ML readiness check failed", error)
        return None, {"status": "error", "message": UNAVAILABLE_MESSAGE}

    status = {"status": "ready"}
    for name in ("model", "sklearn_version"):
        if isinstance(readiness.get(name), str):
            status[name] = readiness[name]
    return predictor, status


def _validated_prediction(prediction, input_fields):
    if not isinstance(prediction, dict):
        raise TypeError("The predictor must return a result object.")
    for name, upper_bound in (("ml_score", 100), ("fraud_probability", 1)):
        value = prediction.get(name)
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or not 0 <= value <= upper_bound:
            raise TypeError("The predictor returned an invalid numeric result.")
    label = prediction.get("prediction")
    classification = prediction.get("classification")
    if isinstance(label, bool) or not isinstance(label, Integral) or label not in (0, 1):
        raise TypeError("The predictor returned an invalid binary label.")
    if not isinstance(classification, str) or not classification.strip():
        raise TypeError("The predictor returned an invalid classification.")

    used_fields = prediction.get("input_fields", input_fields)
    if not isinstance(used_fields, list) or not used_fields or any(name not in TEXT_FIELDS for name in used_fields):
        raise TypeError("The predictor returned invalid input coverage.")
    used_fields = [name for name in TEXT_FIELDS if name in used_fields]
    return {
        "analyzed": True,
        "status": "ready",
        "ml_score": float(prediction["ml_score"]),
        "fraud_probability": float(prediction["fraud_probability"]),
        "prediction": int(label),
        "classification": classification,
        "input_fields": used_fields,
        "missing_fields": [name for name in TEXT_FIELDS if name not in used_fields],
    }


def get_analysis_status() -> dict:
    """Report actual model readiness alongside the running API's health."""
    predictor, model_status = _get_predictor()
    return {
        "status": "ok",
        "analysis_mode": "security_and_ml" if predictor is not None else "security_only",
        "machine_learning": model_status,
        "pending_checks": [] if predictor is not None else ["machine_learning_prediction"],
    }


def analyze_job_with_ml(job: dict) -> dict:
    """Use the higher component score and preserve the security coverage floor."""
    security = analyze_job(job)
    fields = {name: job.get(name, "") for name in TEXT_FIELDS}
    input_fields = [name for name, value in fields.items() if isinstance(value, str) and value.strip()]
    invalid_fields = [name for name, value in fields.items() if value is not None and not isinstance(value, str)]
    machine_learning = {
        "analyzed": False,
        "status": "unavailable",
        "ml_score": None,
        "fraud_probability": None,
        "prediction": None,
        "classification": None,
        "input_fields": input_fields,
        "missing_fields": [name for name in TEXT_FIELDS if name not in input_fields],
        "message": UNAVAILABLE_MESSAGE,
    }

    if invalid_fields:
        logger.warning("ML input has unsupported field types in %s.", ", ".join(invalid_fields))
    elif not input_fields:
        machine_learning["message"] = "Job posting text is unavailable for ML prediction."
    else:
        predictor, model_status = _get_predictor()
        machine_learning.update(model_status)
        if predictor is not None:
            try:
                prediction = predictor.predict_fraud(
                    job_description=fields["description"] or "",
                    title=fields["title"] or "",
                    company_profile=fields["company_profile"] or "",
                    requirements=fields["requirements"] or "",
                    benefits=fields["benefits"] or "",
                )
                machine_learning.update(_validated_prediction(prediction, input_fields))
                machine_learning.pop("message", None)
            except (ImportError, FileNotFoundError, ValueError) as error:
                _log_failure("ML input or model is unavailable", error)
                machine_learning.update({"status": "unavailable", "message": UNAVAILABLE_MESSAGE})
            except Exception as error:
                _log_failure("ML prediction failed", error)
                machine_learning.update({"status": "error", "message": UNAVAILABLE_MESSAGE})

    pending_checks = list(security["pending_checks"])
    result = {
        **security,
        "checks": {**security["checks"], "machine_learning": machine_learning},
        "pending_checks": pending_checks,
        "security_score": security["risk_score"],
        "security_color": security["color"],
        "security_risk_level": security["risk_level"],
        "ml_score": None,
        "final_score": security["risk_score"],
        "score_formula": "security_score",
    }
    if not machine_learning["analyzed"]:
        if "machine_learning_prediction" not in pending_checks:
            pending_checks.append("machine_learning_prediction")
        return result

    final_score = max(security["risk_score"], machine_learning["ml_score"])
    summary = summarize_risk([{"points": final_score}])
    if security["color"] == "yellow" and summary["color"] == "green":
        summary.update({"color": "yellow", "risk_level": "Needs further verification"})
    result.update({
        **summary,
        "ml_score": machine_learning["ml_score"],
        "final_score": final_score,
        "score_type": "combined",
        "score_formula": "max(security_score, ml_score)",
        "analysis_scope": "security_and_ml",
        "pending_checks": [name for name in pending_checks if name != "machine_learning_prediction"],
    })
    return result
