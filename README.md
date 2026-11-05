# MLBFD: Machine Learning-Based Financial Fraud Detection

A demo UPI-style payment platform in which every payment is risk-scored in real time by
**7 ML/DL models + 7 rule layers** (stacking fusion, hard override rules, SHAP explanations).
Risky payments are held until the user enters **two codes: email and Telegram**. Money is virtual.

## Highlights
- Dual-channel OTP (email + Telegram bot) for signup, new-device login, fraud step-up, PIN change/reset and account delete
- Separate 6-digit login and payment PINs; payments only to registered, active users
- 22 engineered features; XGBoost, Random Forest, Logistic Regression, Isolation Forest, DNN (focal loss), LSTM + attention, Autoencoder
- Verdicts: APPROVED / APPROVED_WITH_WARNING / REQUIRES_2FA / BLOCKED, with a signed single-use freeze link
- Web user portal, admin portal, and two Flutter apps (Sender, Receiver)
- Free to run: Flask + SQLite + Waitress, optional Cloudflare tunnel or same-network sharing

## Documentation
- **Complete details (PDF):** `docs/MLBFD_Complete_Project_Details.pdf`
- Setup for email and Telegram: `OTP_SETUP.md` · Hosting: `README_HOSTING.md` · Same-network use: `README_LAN.md` · Mobile apps: `README_APK.md`
- Accuracy and latency report: `ACCURACY_REPORT.md` · Architecture notes: `PROJECT_HANDOFF.md`

## Quick start (Windows)
```
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt
copy .env.example .env        # then fill in the values (never commit .env)
backend\.venv\Scripts\python backend\otp_doctor.py          # checks .env, email and Telegram setup
start_mlbfd.bat                                              # or: python serve.py
```
Open `http://localhost:5000/register` (users) and `http://localhost:5000/admin` (admin, local machine only).

## Not included in this repository
The `.env` file and all secrets, the SQLite database, the trained models (`backend/models/`), and the datasets
(`Datasets/`). Retrain with `train_all_models.py` after placing the datasets (see `DATA_AUDIT.md`).

## Tests
`pytest -q` (206 test cases) and `python scripts/smoke_test.py` (14-step end-to-end flow).
