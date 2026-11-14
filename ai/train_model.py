from sklearn.feature_extraction.text import TfidfVectorizer
from preprocess import load_and_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
X_train, X_test, y_train, y_test = load_and_split()

print("Train size:", X_train.shape[0])
print("Test size: ", X_test.shape[0])
print("Fraud rate in train:", y_train.mean().round(4))
print("Fraud rate in test: ", y_test.mean().round(4))

vectorizer = TfidfVectorizer(
    stop_words='english',
    max_features=5000,
    ngram_range=(1, 2),
    min_df=5,
    max_df=0.8,
    sublinear_tf=True,
)

# Learn vocabulary + IDF from TRAINING text only, then convert it to vectors.
X_train_tfidf = vectorizer.fit_transform(X_train)

# Convert TEST text using what the vectorizer already learned. No fitting.
X_test_tfidf = vectorizer.transform(X_test)

print("Train matrix shape:", X_train_tfidf.shape)
print("Test matrix shape: ", X_test_tfidf.shape)


model = LogisticRegression(
    class_weight="balanced",
    max_iter=1000,
    random_state=42
)

model.fit(X_train_tfidf, y_train)

print("Model training complete!")

predictions = model.predict(X_test_tfidf)

print("First 10 predictions:")
print(predictions[:10])

print("Actual labels:")
print(y_test.iloc[:10].to_numpy())

print(classification_report(
    y_test,
    predictions,
    zero_division=0
))

print(confusion_matrix(y_test, predictions))