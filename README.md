# JobProof
AI-Powered Job Scam Detection

## Overview
JobProof is a browser extension that helps job seekers identify potentially fraudulent job postings using machine learning and cybersecurity analysis.

## The Problem
Fake job listings waste applicants' time and expose them to phishing, identity theft, and financial scams. 

## Our Solution
JobProof analyzes job postings using:
- Machine Learning: TF-IDF and Logistic Regression to detect suspicious language.
- Cybersecurity: Planned checks for suspicious recruiter emails, URls, and domains.
- Browser Extension: A convenient interface for analyzing job listings.

## Teck Stack 
- AI/ML: Python, scikit-learn, PyTorch, Pandas
- Backend: FastAPI
- Frontend: React, JavaScript, HTML, CSS
- Browser Integration: Chrome Extension
- Dataset: [Real or Fake Job Posting Prediction]https://www.kaggle.com/datasets/shivamb/real-or-fake-fake-jobposting-prediction
- Pipeline: Text Cleaning -> TF-IDF -> Classification -> Fraud Risk Score

## Future Improvements
- Real-time company vertification
- Improved detection of modern AI-generated scams
- Bulk job posting analysis

## Disclaimer
JobProof provides risk indicators, not definitive fraud verification. Model scores are not guaranteed probabilities of fraud. 
