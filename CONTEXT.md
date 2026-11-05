# CONTEXT.md — MLBFD Project Specification & Constraints

## Project Overview
- **Name:** MLBFD (Machine Learning-Based Financial Fraud Detection) — used consistently everywhere.
- **Core Domain:** Real-time UPI financial transaction fraud detection.
- **Backend Architecture:** Flask REST API + SQLAlchemy ORM backend.
- **Machine Learning Ensemble:** 7 ML/DL models (XGBoost, Random Forest, Logistic Regression, Isolation Forest, Deep Neural Network with Focal Loss, LSTM Sequence Network with Self-Attention, Deep Reconstruction Autoencoder).
- **Rule Engine:** 7-layer weighted risk scoring engine (Behavioral 38%, Velocity 4%, Flow 3%, Payee 28%, Compromise 15%, Amount 10%, Website Trust 2%).
- **Feature Space:** 22 engineered features (`amount`, `hour`, `day_of_week`, `is_holiday`, `is_weekend`, `amount_vs_avg_ratio`, `amount_vs_std_zscore`, `txn_count_last_hour`, `txn_count_last_24h`, `new_payee_flag`, `new_payee_pct_last_7days`, `days_since_account_created`, `known_device_flag`, `device_change_count_30days`, `payee_incoming_txn_count`, `payee_account_age_days`, `is_scam_upi`, `distance_from_home_km`, `is_impossible_travel`, `payee_graph_centrality`, `is_mule_candidate`, `is_high_risk_mcc`).
- **Interfaces:** Web Admin Operations Portal, Web User Self-Service Portal, and Dual Flutter mobile apps (Sender App and Receiver App — currently untested).

## Environment & Infrastructure Constraints
- **Operating System:** Windows.
- **Python Runtime:** Python 3.11.
- **Database:** SQLite locally (`*.sqlite3`), no Redis.
- **Hosting / Serving:** Waitress WSGI server + Cloudflare Tunnel hosted directly from the laptop.
- **Cost Policy:** 100% FREE services only (strictly zero paid APIs or tiers).

## Authentication & Security
- **Dual PIN Authentication:** Separate Login PIN and Payment PIN.
  - Both must be 6 digits.
  - Login PIN and Payment PIN must strictly differ.
- **Multi-Factor OTP Channels:**
  - Channels: Email + Telegram Bot.
  - **BOTH channels are required** for 2FA verification.
  - Strictly **NO SMS** and **NO Twilio**.
- **User Accounts & Balance:**
  - UPI ID format: `<10-digit phone>@mlbfd`.
  - Initial virtual balance: 100,000 INR at account activation.

## Developer Rules & Execution Guidelines
1. **Read Before Editing:** Always read and inspect relevant files before making modifications.
2. **Small, Targeted Diffs:** Make minimal, focused, non-breaking edits.
3. **Preserve Contracts:** Retain the 22 feature names and existing API routes unless explicitly instructed by a part specification.
4. **Secret Management:**
   - Secrets belong strictly in `.env`.
   - Always maintain `.env.example`.
   - Never print, log, or commit secrets.
   - Never log OTP codes in plain text or console output.
5. **Testing:** Write and run `pytest` unit/integration tests for each part.
6. **No Paid Services:** Do not introduce dependencies on paid third-party services.
7. **Progress Tracking & Commits:**
   - At the conclusion of every part, update `PROGRESS.md`.
   - Run `git commit -m "Part N: <summary>"`.
   - Stop after completing the requested part.
