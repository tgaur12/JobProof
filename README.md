# JobProof
Job listing risk indicators from machine learning and cybersecurity checks.

## Overview
JobProof is a Manifest V3 Chrome extension that extracts visible job listings, sends them to a local FastAPI service, and highlights the returned risk assessment. It combines a saved TF-IDF and Logistic Regression model with explainable URL, recruiter email, and recruitment-language checks.

## The Problem
Fake job listings waste applicants' time and expose them to phishing, identity theft, and financial scams. 

## Our Solution
JobProof displays three scores on each analyzed listing.

- **Security score** comes from the cybersecurity heuristics, with matched evidence in **Why this result**.
- **ML score** comes from the saved text classifier. Missing training fields are disclosed. It is a model output, not a calibrated probability of fraud.
- **Final score** uses `max(security_score, ml_score)` when ML completes, so a lower model output cannot erase a security warning. The result bands are below 20 for green, 20–59 for yellow, and 60 or above for red. Incomplete platform coverage can retain a yellow verification floor.

If the model, its runtime dependencies, or usable job text are unavailable, JobProof explicitly shows a security-only fallback. An unavailable ML score is not replaced with zero. Green means fewer detected risk signals; it does not establish legitimacy.

## Tech stack

- AI/ML: Python, scikit-learn, TF-IDF, Logistic Regression, joblib, Pandas
- Backend: FastAPI
- Frontend: JavaScript, HTML, CSS; a separate Streamlit model interface
- Browser integration: Chrome Extension, Manifest V3, DOM extraction and MutationObserver
- Cybersecurity: URL parsing, tldextract, email/domain comparison and text heuristics
- Dataset: Real or Fake Job Posting Prediction

## Future Improvements
- Domain registration and recruiter mailbox ownership verification
- Improved detection of modern AI-generated scams
- Bulk job posting analysis

## Disclaimer
JobProof provides risk indicators, not definitive fraud verification. Model scores are not guaranteed probabilities of fraud. 

## Local extension presentation

Open `http://localhost:8080/jobs.html` for the fictional three-scenario demo. See [the presentation guide](tests/PRESENTATION.md) for setup, score interpretation, dynamic updates, and integration limits. Final scores and colors are produced by the API rather than assigned by the page.

## Saved model and training

`ai/train_final.py` fits the final TF-IDF vectorizer and Logistic Regression classifier, then exports `ai/models/tfidf_vectorizer.joblib` and `ai/models/logistic_model.joblib`. `ai/predict.py` loads these artifacts and transforms new listing text without retraining. Running the extension does not rerun training or require the training dataset.

Training combines `title`, `company_profile`, `description`, `requirements`, and `benefits` in that order. The local demo supplies explicit nodes for all five. Indeed extraction supplies the available description and title without inventing company profiles, requirements, or benefits; the response identifies missing model fields. Changes to a live platform's markup may require adapter updates.
