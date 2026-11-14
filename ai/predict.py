import sys
import joblib
from pathlib import Path

# Make 'preprocess' importable whether this file is run from ai/ or imported as ai.predict
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preprocess import clean_text, TEXT_COLS

MODEL_DIR = Path(__file__).resolve().parent / "models"

model = joblib.load(MODEL_DIR / "logistic_model.joblib")
vectorizer = joblib.load(MODEL_DIR / "tfidf_vectorizer.joblib")

THRESHOLD = 0.5


def predict_fraud(job_description, title="", company_profile="", requirements="", benefits=""):
    """Score a job posting. The model was trained on all five fields combined,
    so passing more fields than just the description gives much better results."""
    fields = {
        "title": title,
        "company_profile": company_profile,
        "description": job_description,
        "requirements": requirements,
        "benefits": benefits,
    }

    # Same cleaning and same column order as training (preprocess.combine_text)
    cleaned = " ".join(clean_text(fields[col] or "") for col in TEXT_COLS)
    if not cleaned.strip():
        raise ValueError("Job posting text is empty.")

    features = vectorizer.transform([cleaned])
    probability = float(model.predict_proba(features)[0][1])
    prediction = int(probability >= THRESHOLD)

    return {
        "classification": "Likely Fraudulent" if prediction == 1 else "Likely Legitimate",
        "prediction": prediction,
        "fraud_probability": probability,
        "ml_score": round(probability * 100),   # 0-100 risk score
    }
