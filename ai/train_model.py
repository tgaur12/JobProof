import csv
import numpy as np 
from sklearn.model_selection import train_test_split
data = np.loadtxt('')
#Read the CSV safely, ignoring hidden Unicode line breaks
with open('/Users/ridhimereddy/Documents/DevHacks/JobProof/data/fake_job_postings.csv', mode='r', encoding='utf-8', newline='') as f:
    reader = csv.reader(f)
    header = next(reader)  # Skips the header row
    rows = [row for row in reader]
data = np.array(rows)
X = data[:, :-1]
y = data[:, -1].astype(int)

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)