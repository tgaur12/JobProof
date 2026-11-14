import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from preprocess import load_and_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, precision_score, recall_score
from pathlib import Path
X_train, X_test, y_train, y_test = load_and_split()

# Carve a validation set out of TRAINING data only. Test stays untouched
# until the final model is chosen.
X_fit, X_val, y_fit, y_val = train_test_split(
    X_train, y_train, test_size=0.2, random_state=42, stratify=y_train
)

print("Fit size:  ", X_fit.shape[0])
print("Val size:  ", X_val.shape[0])
print("Test size: ", X_test.shape[0], "(not used in this stage)")
print("Fraud rate in fit: ", y_fit.mean().round(4))
print("Fraud rate in val: ", y_val.mean().round(4))

vectorizer = TfidfVectorizer(
    stop_words='english',
    max_features=5000,
    ngram_range=(1, 2),
    min_df=5,
    max_df=0.8,
    sublinear_tf=True,
)

# Learn vocabulary + IDF from the FIT portion only, then convert it to vectors.
X_fit_tfidf = vectorizer.fit_transform(X_fit)

# Convert VALIDATION text using what the vectorizer already learned. No fitting.
X_val_tfidf = vectorizer.transform(X_val)

print("Fit matrix shape:", X_fit_tfidf.shape)
print("Val matrix shape:", X_val_tfidf.shape)


model = LogisticRegression(
    class_weight="balanced",
    max_iter=1000,
    random_state=42
)

model.fit(X_fit_tfidf, y_fit)

print("Model training complete!")

# Precision / recall / F1 for the fraud class (label 1), measured on VALIDATION.
predictions = model.predict(X_val_tfidf)

print(classification_report(
    y_val,
    predictions,
    zero_division=0
))

print(confusion_matrix(y_val, predictions))

# ===== PyTorch =====
import copy
import numpy as np
import torch

# astype(float32) first, so the dense copy is 4 bytes per number, not 8.
X_fit_t = torch.from_numpy(X_fit_tfidf.astype(np.float32).toarray())
X_val_t = torch.from_numpy(X_val_tfidf.astype(np.float32).toarray())

# Labels become float32 with shape (N, 1) to match the network's output shape.
y_fit_t = torch.tensor(y_fit.to_numpy(), dtype=torch.float32).unsqueeze(1)
y_val_t = torch.tensor(y_val.to_numpy(), dtype=torch.float32).unsqueeze(1)

print("X_fit_t:", X_fit_t.shape, X_fit_t.dtype)
print("y_fit_t:", y_fit_t.shape, y_fit_t.dtype)


# --- Step 2: loss function ---
import torch.nn as nn

# Fraud is rare (about 5%), so weight fraud examples more heavily in the loss.
n_legit = (y_fit_t == 0).sum()
n_fraud = (y_fit_t == 1).sum()
pos_weight = n_legit / n_fraud

loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

print("pos_weight:", round(pos_weight.item(), 2))


# --- Step 3: training loop ---
from pytorch_model import JobFraudNN
from torch.utils.data import TensorDataset, DataLoader

model_nn = JobFraudNN(input_dim=X_fit_t.shape[1])
optimizer = torch.optim.Adam(model_nn.parameters(), lr=1e-3)

train_loader = DataLoader(
    TensorDataset(X_fit_t, y_fit_t), batch_size=64, shuffle=True
)

EPOCHS = 10

# Checkpointing: remember the weights from the epoch with the lowest validation loss.
best_val_loss = float("inf")
best_epoch = 0
best_state = None

for epoch in range(EPOCHS):
    # ---- training pass ----
    model_nn.train()                       # turns Dropout on
    total_loss = 0.0
    for xb, yb in train_loader:
        optimizer.zero_grad()              # reset gradients
        logits = model_nn(xb)              # forward pass
        loss = loss_fn(logits, yb)         # loss
        loss.backward()                    # backward pass
        optimizer.step()                   # update weights
        total_loss += loss.item() * xb.size(0)
    train_loss = total_loss / len(X_fit_t)

    # ---- validation pass (measures only, no learning) ----
    model_nn.eval()                        # turns Dropout off
    with torch.no_grad():                  # no gradient tracking
        val_logits = model_nn(X_val_t)
        val_loss = loss_fn(val_logits, y_val_t).item()

    # ---- checkpoint if validation loss improved ----
    note = ""
    if val_loss < best_val_loss:
        best_val_loss = val_loss
        best_epoch = epoch + 1
        best_state = copy.deepcopy(model_nn.state_dict())   # in-memory snapshot
        note = "  <- best so far"

    print(f"Epoch {epoch+1:2d}: train loss = {train_loss:.4f} | val loss = {val_loss:.4f}{note}")

# Put the best epoch's weights back into the network.
model_nn.load_state_dict(best_state)
print(f"Restored best PyTorch model from epoch {best_epoch} (val loss = {best_val_loss:.4f})")


# ===== Evaluate the best PyTorch model on VALIDATION =====
model_nn.eval()
with torch.no_grad():
    val_logits = model_nn(X_val_t)
    val_probs = torch.sigmoid(val_logits).squeeze(1).numpy()   # fraud scores, 0 to 1

THRESHOLD = 0.5
nn_predictions = (val_probs >= THRESHOLD).astype(int)

print(f"PyTorch (best epoch, threshold {THRESHOLD}) on validation:")
print(classification_report(y_val, nn_predictions, zero_division=0))
print(confusion_matrix(y_val, nn_predictions))


# ===== Compare Logistic Regression and PyTorch (fraud class, validation) =====
lr_predictions = model.predict(X_val_tfidf)

lr_prec = precision_score(y_val, lr_predictions, zero_division=0)
lr_rec = recall_score(y_val, lr_predictions, zero_division=0)
lr_f1 = f1_score(y_val, lr_predictions)

nn_prec = precision_score(y_val, nn_predictions, zero_division=0)
nn_rec = recall_score(y_val, nn_predictions, zero_division=0)
nn_f1 = f1_score(y_val, nn_predictions)

print(f"{'':22}{'precision':>10}{'recall':>10}{'F1':>10}")
print(f"{'Logistic Regression':22}{lr_prec:>10.4f}{lr_rec:>10.4f}{lr_f1:>10.4f}")
print(f"{'PyTorch':22}{nn_prec:>10.4f}{nn_rec:>10.4f}{nn_f1:>10.4f}")

# Treat scores as tied if they match at the 4 decimals we print.
if abs(nn_f1 - lr_f1) < 1e-4:
    print("Both models have the same validation F1.")
elif nn_f1 > lr_f1:
    print("PyTorch performs better on validation F1.")
else:
    print("Logistic Regression performs better on validation F1.")

# Train final Logistic Regression model using all training data
final_vectorizer = TfidfVectorizer(
    stop_words='english',
    max_features=5000,
    ngram_range=(1, 2),
    min_df=5,
    max_df=0.8,
    sublinear_tf=True
)

X_train_final = final_vectorizer.fit_transform(X_train)

final_model = LogisticRegression(
    class_weight="balanced",
    max_iter=1000,
    random_state=42
)

final_model.fit(X_train_final, y_train)

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_DIR.mkdir(exist_ok=True)

joblib.dump(final_model, MODEL_DIR / "logistic_model.joblib")
joblib.dump(final_vectorizer, MODEL_DIR / "tfidf_vectorizer.joblib")

print("Final model saved!")
