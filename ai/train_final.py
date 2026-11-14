"""Train the final Logistic Regression model on ALL training data and save it.

Run once from the ai/ folder:  python3 train_final.py
The test set is evaluated exactly once, at the end. Do not tune against it.
"""
import joblib
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from preprocess import load_and_split

X_train, X_test, y_train, y_test = load_and_split()

# Same TF-IDF configuration as train_model.py.
vectorizer = TfidfVectorizer(
    stop_words='english',
    max_features=5000,
    ngram_range=(1, 2),
    min_df=5,
    max_df=0.8,
    sublinear_tf=True,
)

# Fit on the FULL training set (fit + validation portions together).
X_train_tfidf = vectorizer.fit_transform(X_train)

model = LogisticRegression(
    class_weight="balanced",
    max_iter=1000,
    random_state=42
)
model.fit(X_train_tfidf, y_train)
print("Trained on", X_train.shape[0], "postings.")

# Save model and vectorizer for predict.py
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_DIR.mkdir(exist_ok=True)
joblib.dump(model, MODEL_DIR / "logistic_model.joblib")
joblib.dump(vectorizer, MODEL_DIR / "tfidf_vectorizer.joblib")
print("Saved model and vectorizer to", MODEL_DIR)

# One-time evaluation on the untouched test set (threshold 0.5).
X_test_tfidf = vectorizer.transform(X_test)
test_predictions = model.predict(X_test_tfidf)
print("\n=== FINAL TEST SET RESULTS (run once) ===")
print(classification_report(y_test, test_predictions, zero_division=0))
print(confusion_matrix(y_test, test_predictions))
