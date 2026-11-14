import html
import re
import pandas as pd
from sklearn.model_selection import train_test_split

CSV_PATH = '/Users/ridhimereddy/Documents/DevHacks/JobProof/ai/data/fake_job_postings.csv'
TEXT_COLS = ['title', 'company_profile', 'description', 'requirements', 'benefits']


def clean_text(text):
    if not isinstance(text, str):
        return ""
    """Decode HTML entities, strip tags, collapse whitespace."""
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'mso-[\w-]+:[^;]*;?', ' ', text)
    return text.strip()


def combine_text(df):
    """Fill blanks, clean each text column, join them into one 'text' column."""
    df = df.copy()
    df[TEXT_COLS] = df[TEXT_COLS].fillna('')
    for col in TEXT_COLS:
        df[col] = df[col].apply(clean_text)
    df['text'] = df[TEXT_COLS].agg(' '.join, axis=1)
    return df


def load_and_split():
    """Load the CSV, build the text column, return a stratified 80/20 split."""
    df = pd.read_csv(CSV_PATH)
    df = combine_text(df)
    X = df['text']
    y = df['fraudulent']
    return train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
