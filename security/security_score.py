"""Shared, explainable scoring for the hackathon security checks."""


def summarize_risk(findings: list[dict]) -> dict:
    """Convert heuristic points to a score and display category."""
    score = min(100, sum(finding["points"] for finding in findings))

    # These are MVP thresholds. Evaluation data is needed to calibrate them.
    if score >= 60:
        level, color = "High risk", "red"
    elif score >= 20:
        level, color = "Needs further verification", "yellow"
    else:
        level, color = "Lower risk", "green"

    return {"risk_score": score, "risk_level": level, "color": color}
