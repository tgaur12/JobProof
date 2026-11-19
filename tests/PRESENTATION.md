# Presenting JobProof

Open `http://localhost:8080/jobs.html` for the main presentation page. All postings are fictional. The Chrome extension sends their extracted fields through the local API and renders the actual security, ML, and final scores.

## Before presenting

Install the project dependencies in the virtual environment, then start the API from the project root if it is not already running. The saved model artifacts must be present under `ai/models` for ML to complete.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In another terminal, serve the fixtures if port 8080 is not already in use.

```powershell
.\.venv\Scripts\python.exe -m http.server 8080 --directory tests
```

Reload JobProof at `chrome://extensions`, refresh the presentation page, and confirm that the extension has rendered a panel on each card. Inspect the Final, Security, and ML score tiles. The initial card backgrounds are neutral; the extension supplies the final result colors after analysis. A page without the extension can display the example postings but cannot produce risk results.

## A short demonstration

| Example | Expected security component | What to explain |
| --- | --- | --- |
| Cisco Security Analyst | 0/100 | HTTPS application URL and email domain match the configured company reference. The available text has no matched security warning signs. |
| Microsoft Project Coordinator | 45/100 | The personal email provider adds 20 points and its mismatch with Microsoft's configured domain adds 25. Further verification is needed. |
| Microsoft Remote Payroll Assistant | 100/100 | An HTTP IP-address application destination, lookalike recruiter domain, upfront payment, and banking-password request produce multiple findings. The total is capped at 100. |

These are security expectations, not fixed final results. The model produces live predictions from the supplied text. Do not promise a particular final score or color before observing the running API.

1. Compare the Final, Security, and ML scores, then open **Why this result** to connect security warnings to the actual evidence.
2. Explain `Final = max(Security, ML)`. A lower ML output cannot cancel a security warning. The result is a risk indicator, not a calibrated fraud probability, and green does not prove legitimacy.
3. Load another job. A new panel should appear without refreshing the page.
4. Change the loaded job. Its URL, recruiter email, and description change, and the extension should update its result automatically.
5. Reset the demo to return to the original examples.

The example application and email links are displayed for extraction and discussion. The demo controls prevent ordinary activation from opening those destinations or sending email.

## Explain model inputs and unavailable checks

- **ML prediction** — the API uses the saved model when it can load the artifacts and runtime dependencies and has usable job text. A completed model prediction removes the ML pending check. Missing text, incompatible or absent artifacts, and missing dependencies produce an explicit security-only fallback with ML unavailable, rather than a made-up zero score.
- **Partial ML input** — training combines title, company profile, description, requirements, and benefits. The fictional demo includes all five as actual fields. Expand **Role details** to inspect the supporting inputs. Real listings may provide fewer fields; the explanation identifies missing inputs without inferring them.
- **Domain registration** — public-suffix parsing extracts the registrable domain name. It does not establish who registered or owns that domain. Registration verification is unfinished.
- **Recruiter mailbox ownership** — format and company-domain checks do not establish who controls a mailbox. Mailbox ownership verification is unfinished.
- **Recruiter email** — this check runs when an address is supplied or extracted. If no address is available, it remains pending. The three presentation examples provide addresses so the email checks can run.

The demo retains incomplete checks in the explanation panels. The model is a text classifier, so it may disagree with security findings or assign a high score to an ordinary-looking fictional posting. Present the observed result and limitations honestly rather than rewriting an example to obtain a desired model score.

## Training and inference are separate

`ai/train_final.py` trains and exports the classifier and vectorizer as `.joblib` artifacts. `ai/predict.py` loads those artifacts for inference and applies the same text cleaning and field order. Starting FastAPI and analyzing a listing do not retrain the model. Retraining is a separate team task that requires the training dataset and its configured path.

## Automated checks

The Python suite exercises the security engine and API contract.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

The JavaScript integration check needs Node.js 24 and the test-only jsdom dependency. The API must be running.

```powershell
npm install --prefix .jobproof-cache/node-tools --no-save --package-lock=false jsdom@29.1.1
$env:NODE_PATH = Join-Path (Get-Location) '.jobproof-cache/node-tools/node_modules'
node tests/check_demo_api.cjs
```

This executes the real demo controls, extraction, background worker, and local HTTP analysis with Chrome messaging simulated. Native browser permissions and visual layout should also be checked in the presentation browser.
