# MLBFD: Multi-Layer Behavioral Fraud Detection for UPI
## Comprehensive Technical Project Handoff & Architecture Compendium

**Document Version:** 2.0 (Post-Audit Clean State)  
**Date Generated:** 2026-10-30  
**Target Audience:** Succeeding Engineering Agents, Faculty Evaluators, and Viva Committee  
**Repository Location:** `D:\Major Project\MLBFD`  

---

## 1. PROJECT IDENTITY

| Field | Detail |
| :--- | :--- |
| **Project Name** | **MLBFD** (Multi-Layer Behavioral Fraud Detection) |
| **Former / Legacy Working Title** | BeyondOTP (Purged from all codebase files and UI; retained only in historical paper archives) |
| **Domain** | UPI Financial Transactions, Behavioral Biometrics, Adaptive Friction & Fraud Prevention |
| **Core Objective** | Detect and prevent real-time UPI transaction fraud across 7 analytical layers using adaptive step-up friction (Dual OTP), graph mule detection, and machine learning ensemble without degrading legitimate user experience. |
| **Institution** | **BGS College of Engineering and Technology (BGSCET)** |
| **Affiliation** | Visvesvaraya Technological University (VTU), Belagavi, Karnataka |
| **Department** | Department of Artificial Intelligence and Machine Learning (AIML) |
| **Project Type** | 8th Semester Final-Year Capstone Engineering Project |
| **Target Event** | **AARONAN 2026** Project Exhibition & VTU Final Viva Voce |
| **Project Guide** | **Mrs. Vandana Sardar**, Assistant Professor, Department of AIML, BGSCET |
| **Student Team** | **Chirag P** (Lead Architecture & ML Engine)  <br>**Darshan K** (Data Pipelines & Graph Analytics)  <br>**Rahul R** (Backend APIs & Security Infrastructure)  <br>**Vikyath S** (Mobile Frontends & Web Portals) |

---

## 2. SYSTEM ARCHITECTURE & CODEBASE DIRECTORY

### 2.1 Multi-Tier Architecture

```
+-----------------------------------------------------------------------------------+
|                                  CLIENT TIER                                      |
|  - Flutter Mobile Sender App (Android/iOS)      - Responsive Web User Portal     |
|  - Flutter Mobile Receiver App (Android/iOS)    - Responsive Web Admin Portal    |
+-----------------------------------------------------------------------------------+
                                          |
                                   HTTPS / REST API
                                          |
+-----------------------------------------------------------------------------------+
|                         API & SECURITY GATEWAY TIER                               |
|  - Waitress Production WSGI (8 Worker Threads, 0.0.0.0:5000)                      |
|  - Flask Blueprints (/api/*, /admin/*, /*)                                        |
|  - Security Middleware: Cloudflare Turnstile / Honeypot, 3s Form Timing Check,    |
|    Flask-Limiter IP Rate Limiting (3/day IP, 60/min API), JWT Blocklist           |
+-----------------------------------------------------------------------------------+
                                          |
                                    Transaction
                                          |
+-----------------------------------------------------------------------------------+
|                               ENGINE SCORING TIER                                 |
|  - 7-Layer Analytical Engine (Behavioral, Velocity, Flow, Payee, Device, Amount,  |
|    Website Trust)                                                                 |
|  - 7 Trained Base Classifiers (XGBoost, RF, LogReg, IsoForest, DNN, LSTM, AE)     |
|  - Stacking Meta-Classifier (Learned Logistic Regression Fusion, fusion.json)      |
|  - 8 Hard Override Safety Rules (Scam list, QR mismatch, Travel, Mule, Limits)    |
|  - Explainable AI: Cached SHAP TreeExplainer (<10ms attribution)                  |
+-----------------------------------------------------------------------------------+
                                          |
                                 State & Persistence
                                          |
+-----------------------------------------------------------------------------------+
|                                  DATA TIER                                        |
|  - SQLite (Write-Ahead Logging / WAL mode enabled for high concurrency)           |
|  - Field-Level Security: AES-256 Fernet Encryption (Phone, Email, UPI ID)        |
|  - Searchable Privacy: HMAC-SHA256 Blind Index Hashes with Secret Salt/Pepper     |
|  - Offline Clean Data Parquet Store (80,000 unified rows across 4 datasets)       |
+-----------------------------------------------------------------------------------+
```

### 2.2 End-to-End Request Lifecycle for `/api/transfer`

1. **Client Submission:** Client submits JSON payload containing `user_id`, `sender_upi`, `receiver_upi`, `amount`, `device_id`, `latitude`, `longitude`, `pin` (Payment PIN), `accuracy_m`, and optional QR/merchant metadata.
2. **Abuse Protection:** Middleware validates origin, checks honeypot field, enforces IP rate limits, and validates form timing tokens (minimum 3.0 seconds human duration).
3. **Session Authentication:** Validates JWT access token via `Authorization: Bearer <token>`; confirms token JTI is not in `token_blocklist`.
4. **Independent Payment PIN Verification:** Validates the submitted 6-digit payment PIN against `users.payment_pin_hash` (bcrypt). If invalid, increments `payment_failed_attempts`. Upon 3 consecutive failures, locks payment functionality for 30 minutes. The request is aborted before running the scoring engine.
5. **Receiver Existence & Registration Gate:** Looks up receiver in `users` table using HMAC blind indexing (`compute_lookup_hash(receiver_upi)`). If the receiver does not exist or has `status != 'ACTIVE'`, execution immediately halts and returns HTTP 404 `USER_NOT_REGISTERED`.
6. **State Retrieval:** Queries sender baseline (`UserBehaviorBaseline`), trusted payee status (`TrustedPayee`), scam repository (`ScamUpi`), geofence distance (`geofence.py`), and NetworkX mule centrality (`social_graph.py`).
7. **Canonical Feature Vector Construction:** `feature_builder.build_feature_vector()` generates a 22-dimensional float vector, verified against canonical SHA-256 feature order.
8. **Multi-Model Inference:** Scaler transforms features; 7 models generate fraud probabilities, calibrated via Isotonic Regression.
9. **7-Layer Scoring & Fusion:** Scores computed across 7 layers. Stacking meta-classifier computes unified probability, scaled to 0-100 `weighted_score`.
10. **Hard Overrides Evaluation:** Evaluates 8 canonical rules (`evaluate_overrides`). If triggered, raises score to rule floor and attaches audit reasons.
11. **Threshold Decision:**
    - `0.0 - 39.9`: `APPROVED` -> Balance debited atomically, transaction marked `COMPLETED`.
    - `40.0 - 59.9`: `APPROVED_WITH_WARNING` -> Approved with advisory flags logged.
    - `60.0 - 79.9`: `REQUIRES_2FA` -> Transaction stored as `PENDING`, dual OTPs dispatched to sender's registered Email and Telegram bot.
    - `80.0 - 100.0`: `BLOCKED` -> Transaction rejected, security alert dispatched with 24-hr signed freeze token.
12. **Explainability Attribution:** Cached SHAP TreeExplainer extracts top-5 signed feature contributions and generates plain-language user guidance.

### 2.3 Backend Module Directory

| Module Path | Primary Purpose | Key Exported Functions / Classes |
| :--- | :--- | :--- |
| `backend/app.py` | Flask application factory, blueprint registration, extensions | `create_app()`, `db`, `jwt`, `limiter` |
| `backend/api.py` | Core REST API implementation for auth, transfers, OTP, PINs | `transfer()`, `login()`, `register_start()`, `verify_otp_endpoint()`, `pin_change()` |
| `backend/fraud_detection.py` | 7-layer fraud engine, hard override logic, decision pipeline | `FraudDetectionEngine`, `evaluate_overrides()`, `OVERRIDE_RULES`, `check_geofence()` |
| `backend/predictor.py` | Model loading, memory caching, ensemble inference, SHAP | `predict_fraud_ensemble()`, `explain_prediction_shap()`, `get_plain_language_reason()` |
| `backend/learned_fusion.py` | Stacking meta-classifier execution, static fallback weights | `get_fusion_prediction()`, `train_stacking_meta_classifier()`, `STATIC_WEIGHTS` |
| `backend/feature_builder.py` | Canonical 22-feature vector construction and schema hash | `build_feature_vector()`, `CANONICAL_22_FEATURES`, `FEATURE_ORDER_SHA256` |
| `backend/data_loader.py` | Chunked raw dataset loaders (PaySim, IEEE, BAF), zero-leakage | `load_all_clean_data()`, `process_paysim()`, `process_ieee()`, `process_baf()` |
| `backend/upi_simulator.py` | Realistic UPI behavioral transaction simulation generator | `generate_realistic_upi_dataset()`, `BehavioralSimulator` |
| `backend/train_all_models.py` | Resumable training script for all 7 classifiers under scikit-learn | `train_all()`, `train_xgboost()`, `train_neural_network()`, `train_lstm()` |
| `backend/calibrate_and_tune.py` | TimeSeriesSplit hyperparameter tuning and Isotonic calibration | `tune_and_calibrate_all()`, `find_operating_threshold()` |
| `backend/otp_service.py` | Central dispatch manager for multi-channel dual OTP | `OtpService`, `generate_dual_otp()`, `verify_dual_otp()` |
| `backend/email_sender.py` | SMTP email dispatcher with background retry and dry-run | `EmailOtpSender`, `send_email_otp()`, `send_freeze_alert()` |
| `backend/telegram_bot.py` | Telegram bot daemon, contact verification, link token handler | `TelegramOtpSender`, `start_bot_daemon()`, `send_telegram_otp()` |
| `backend/social_graph.py` | In-memory NetworkX transaction graph for mule fan-in detection | `TransactionGraph`, `is_mule_candidate()`, `get_centrality_score()` |
| `backend/geofence.py` | Haversine distance, speed calculation, Nominatim reverse geocode | `haversine_km()`, `check_impossible_travel()`, `reverse_geocode()` |
| `backend/website_trust.py` | Domain reputation analysis (age, SSL, Safe Browsing, OpenPhish) | `WebsiteTrustScore`, `check()` |
| `backend/qr_parser.py` | UPI QR string parser (`upi://pay`), payee mismatch validator | `parse_upi_qr()`, `validate_qr()` |
| `backend/security.py` | AES-256 Fernet, HMAC blind indexing, bcrypt hashing, timing tokens | `encrypt_val()`, `decrypt_val()`, `compute_lookup_hash()`, `hash_pin()` |
| `backend/database.py` | SQLAlchemy ORM entity definitions for all 18 tables | `User`, `Transaction`, `UserBehaviorBaseline`, `OtpCode`, `ScamUpi` |
| `backend/migrate_db.py` | Idempotent SQLite database schema migration and backup tool | `migrate()`, `backup_database()` |
| `backend/serve.py` | Production Waitress WSGI server launcher with WAL enforcement | `enforce_sqlite_wal()`, `main()` |

### 2.4 Codebase Directory Tree (Depth 3)

```
MLBFD/
|-- ACCURACY_REPORT.md
|-- CONTEXT.md
|-- DATA_AUDIT.md
|-- PROGRESS.md
|-- PROGRESS_REPORT.md
|-- README_APK.md
|-- README_EMAIL.md
|-- README_HOSTING.md
|-- README_TELEGRAM.md
|-- RESULTS_FOR_POSTER.txt
|-- backend/
|   |-- add_user_flask.py
|   |-- api.py
|   |-- app.py
|   |-- audit_logger.py
|   |-- calibrate_and_tune.py
|   |-- config.py
|   |-- data/
|   |   \-- simulator_clean.parquet
|   |-- data_loader.py
|   |-- data_processor.py
|   |-- database.py
|   |-- db.py
|   |-- email_sender.py
|   |-- feature_builder.py
|   |-- fraud_detection.py
|   |-- generate_complete_mlbfd_pdf.py
|   |-- geofence.py
|   |-- instance/
|   |   |-- mlbfd.sqlite3
|   |   \-- mlbfd_backup_*.sqlite3
|   |-- learned_fusion.py
|   |-- lstm_sequence.py
|   |-- migrate_db.py
|   |-- model_trainer.py
|   |-- otp_manager.py
|   |-- otp_service.py
|   |-- predictor.py
|   |-- qr_parser.py
|   |-- rate_limiter.py
|   |-- requirements.txt
|   |-- reset_all_balances.py
|   |-- scenario_tests.py
|   |-- security.py
|   |-- social_graph.py
|   |-- telegram_bot.py
|   |-- test_detector.py
|   |-- train_all_models.py
|   |-- ubts.py
|   |-- upi_simulator.py
|   |-- user_manager.py
|   \-- website_trust.py
|-- dashboard/
|   |-- static/
|   |   |-- css/
|   |   \-- js/
|   \-- templates/
|       |-- alerts.html
|       |-- base.html
|       |-- drift.html
|       |-- index.html
|       |-- models.html
|       |-- transactions.html
|       |-- user_dashboard.html
|       |-- user_login.html
|       |-- user_register.html
|       \-- users.html
|-- data/
|   |-- baf_clean.parquet
|   |-- ieee_clean.parquet
|   |-- paysim_clean.parquet
|   \-- simulator_clean.parquet
|-- docs/
|   |-- MLBFD_Complete_Project_Compendium.pdf
|   |-- MLBFD_Complete_System_Documentation.pdf
|   |-- MLBFD_Model_Training_Report.pdf
|   \-- PROJECT_RESEARCH_REPORT.md
|-- flutter_app/
|   |-- receiver_app/
|   |   |-- android/
|   |   |-- lib/
|   |   \-- pubspec.yaml
|   \-- sender_app/
|       |-- android/
|       |-- lib/
|       \-- pubspec.yaml
|-- latency_benchmark.py
|-- serve.py
|-- start_mlbfd.bat
\-- tests/
    |-- test_part1_baseline.py
    |-- ... (27 test modules)
    \-- test_part28_mobile_responsiveness.py
```

---

## 3. FRAUD DETECTION ENGINE SPECIFICATION

### 3.1 The 7 Analytical Layers & Scoring Rules

| Layer | Name | Static Weight | Core Data Evaluated | Scoring Logic & Points Added |
| :---: | :--- | :---: | :--- | :--- |
| **1** | **Behavioral** | **38%** | Base ensemble ML probability, historical spend Z-score, time of day | - Base: `ensemble_prob * 100`<br>- Z-score > 3.0: `+60.0` points (strictly capped at 60)<br>- Transaction 12 AM - 5 AM: `+15.0` points<br>- First transaction ever: `+10.0` points<br>- Weekend amount > Rs 10,000: `+20.0` points |
| **2** | **Velocity** | **4%** | Short-term and daily transaction burst rates | - > 3 txns in 10 minutes: `+80.0` points<br>- > 10 txns in 1 hour: `+60.0` points<br>- > 30 txns in 24 hours: `+80.0` points |
| **3** | **Flow / Network** | **3%** | Receiver in-degree centrality, mule account topology | - Mule fan-in candidate flag: `+mule_degree_score`<br>- High graph centrality (>0.85): `+40.0` points |
| **4** | **Payee Risk** | **28%** | Known payee history, account age, cooling period | - New payee (not in known list): `+25.0` points<br>- Payee account age < 7 days: `+25.0` points<br>- Payee added < 24h & amount > Rs 5,000: triggers override |
| **5** | **Device & Geo** | **15%** | Device fingerprint, impossible travel, GPS geofencing | - New device ID + unknown payee: `+60.0` points<br>- New device ID + trusted payee: `+15.0` points<br>- Impossible travel (>900 km/h): `+50.0` points<br>- Geofence >500 km: `+40.0` pts, >100 km: `+20.0` pts (skipped if accuracy > 5000m)<br>- Biometric check failed: `+25.0` points |
| **6** | **Amount Deviation**| **10%** | Deviation from baseline average, regulatory boundaries | - Amount > 10x average: `+90.0` points<br>- Amount > 5x average: `+70.0` points<br>- Structuring boundary (Rs 9,999 / 99,999): `+15.0` points |
| **7** | **Website Trust** | **2%** | Domain age, SSL status, Google Safe Browsing, OpenPhish | - Google Safe Browsing / OpenPhish hit: `+100.0` points<br>- Domain age < 30 days: `+30.0` points<br>- Invalid/Self-signed SSL: `+40.0` points |

### 3.2 Decision Matrix

```
Score Range       Operational Verdict        Engine Action Taken
---------------------------------------------------------------------------------------------------
 0.0 – 39.9       APPROVED                   Instant payment clearance; ledger debited.
40.0 – 59.9       APPROVED_WITH_WARNING      Payment cleared; warning flags logged and surfaced.
60.0 – 79.9       REQUIRES_2FA               Transaction held PENDING; Dual OTP (Email+Telegram) sent.
80.0 – 100.0      BLOCKED                    Transaction rejected; security freeze alert dispatched.
```

### 3.3 Verbatim Canonical Override Rules Table

Defined in `backend/fraud_detection.py` (`OVERRIDE_RULES`):

```python
OVERRIDE_RULES = [
    {
        "id": "RULE_SCAM_BLACKLIST",
        "name": "Payee in scam blacklist",
        "min_score": 90.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "Payee in verified scam blacklist -> BLOCKED (at least 90)",
        "reason": "Receiver UPI is flagged on national scam registry (hard override: BLOCKED)"
    },
    {
        "id": "RULE_QR_PAYEE_MISMATCH",
        "name": "QR payee mismatch tampering",
        "min_score": 85.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "QR payee mismatch -> BLOCKED (at least 85)",
        "reason": "QR code payee identifier does not match receiver UPI (hard override: BLOCKED)"
    },
    {
        "id": "RULE_IMPOSSIBLE_TRAVEL_NEW_DEVICE",
        "name": "Impossible travel AND new device",
        "min_score": 85.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "Impossible travel AND new device -> BLOCKED (at least 85)",
        "reason": "Impossible travel speed from an unrecognized device (hard override: BLOCKED)"
    },
    {
        "id": "RULE_MALICIOUS_DOMAIN",
        "name": "Website flagged by Safe Browsing or OpenPhish",
        "min_score": 85.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "Malicious merchant domain -> BLOCKED (at least 85)",
        "reason": "Associated merchant website flagged as malicious or phishing (hard override: BLOCKED)"
    },
    {
        "id": "RULE_MULE_TOPOLOGY",
        "name": "Mule network topology detected",
        "min_score": 80.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "Mule network topology detected -> BLOCKED (at least 80)",
        "reason": "Receiver account exhibits rapid fan-in/fan-out mule laundering patterns (hard override: BLOCKED)"
    },
    {
        "id": "RULE_NEW_DEVICE_NEW_PAYEE_HIGH_AMOUNT",
        "name": "New device AND new payee AND amount over 5x average",
        "min_score": 70.0,
        "forced_status": None,
        "enabled": True,
        "description": "New device AND new payee AND amount over 5x average -> at least 70",
        "reason": "Unrecognized device sending >5x average amount to a new contact (hard override: min score 70)"
    },
    {
        "id": "RULE_EXTREME_AMOUNT_NEW_PAYEE",
        "name": "Amount over 10x average to new payee",
        "min_score": 70.0,
        "forced_status": None,
        "enabled": True,
        "description": "Amount over 10x average to new payee -> at least 70",
        "reason": "Extreme transaction amount (>10x baseline average) to new contact (hard override: min score 70)"
    },
    {
        "id": "RULE_NEW_PAYEE_COOLING_CAP",
        "name": "Amount over Rs 5,000 to a payee added less than 24 hours ago",
        "min_score": 70.0,
        "forced_status": None,
        "enabled": True,
        "description": "Amount over Rs 5,000 to a payee added less than 24 hours ago -> at least 70",
        "reason": "Amount over Rs 5,000 to payee added < 24 hours ago (hard override: min score 70)"
    }
]
```

### 3.4 Fusion Strategy: Learned Stacking vs Static Weights

- **Active Mode:** **Stacking Meta-Classifier** (Configured via `backend/models/fusion.json` with `"selected_fusion": "stacking"`).
- **Validation Metrics Comparison:**
  - Stacking Meta-Classifier: Validation PR-AUC = `0.3562`, Brier Score = `0.0528`.
  - Static Weights: Validation PR-AUC = `0.1801`, Brier Score = `0.0716`.
- **Meta-Features (13 Dimensions):** 7 Model Probabilities (`prob_xgboost`, `prob_random_forest`, `prob_logistic_regression`, `prob_isolation_forest`, `prob_neural_network`, `prob_lstm`, `prob_autoencoder`) + 6 Layer Scores (`velocity`, `flow`, `payee`, `compromise`, `amount`, `website_trust`).
- **Static Fallback Weights:** Kept as configuration fallback if `stacking_meta_classifier.pkl` cannot be read:
  `Behavioral: 0.38, Payee: 0.28, Compromise: 0.15, Amount: 0.10, Velocity: 0.04, Flow: 0.03, Website Trust: 0.02`.

---

## 4. CANONICAL 22-FEATURE VECTOR

Engineered in `backend/feature_builder.py` (`CANONICAL_22_FEATURES`). Verified against SHA-256 hash `9d4dce7e814e9bc406ccdecbda1048cdd575f11be4369ff88d55b1192c46513f`.

| # | Feature Name | Description & Formula | Computation Origin | PaySim | IEEE | BAF | Simulator |
| :-: | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| 1 | `amount` | Transaction value in INR (float) | Payload `amount` | Yes | Yes | Yes | Yes |
| 2 | `hour` | Hour of day (0 to 23) | Timestamp `now.hour` | Yes | Yes | Yes | Yes |
| 3 | `day_of_week` | Day of week (0=Mon, 6=Sun) | Timestamp `now.weekday()` | Yes | Yes | Yes | Yes |
| 4 | `is_holiday` | Indian bank/public holiday flag (0/1) | Static holiday calendar | Masked | Masked | Masked | Yes |
| 5 | `is_weekend` | Saturday or Sunday flag (0/1) | `day_of_week >= 5` | Yes | Yes | Yes | Yes |
| 6 | `amount_vs_avg_ratio`| Ratio of amount to historical average | `amount / max(avg_amount, 1.0)` | Yes | Yes | Yes | Yes |
| 7 | `amount_vs_std_zscore`| Number of standard deviations from mean | `(amount - avg) / max(std, 1.0)` | Yes | Yes | Yes | Yes |
| 8 | `txn_count_last_hour`| Transactions by sender in last 60 mins | DB query `created_at >= 1h ago` | Yes | Yes | Yes | Yes |
| 9 | `txn_count_last_24h` | Transactions by sender in last 24 hours | DB query `created_at >= 24h ago` | Yes | Yes | Yes | Yes |
| 10| `new_payee_flag` | First time sending to this receiver (0/1) | DB query `receiver_upi not in payees` | Yes | Masked | Masked | Yes |
| 11| `new_payee_pct_last_7days`| Ratio of new payees in last 7 days | Historical sender ledger scan | Yes | Masked | Masked | Yes |
| 12| `days_since_account_created`| Sender account age in days | `(now - created_at).days` | Yes | Yes | Yes | Yes |
| 13| `known_device_flag` | Device ID in user's known devices list (0/1) | Baseline `known_devices` list | Masked | Yes | Yes | Yes |
| 14| `device_change_count_30days`| Distinct device IDs seen in last 30 days | Count of unique device tokens | Masked | Yes | Yes | Yes |
| 15| `payee_incoming_txn_count`| Total incoming transactions to receiver | DB query `Transaction.receiver_upi` | Yes | Masked | Masked | Yes |
| 16| `payee_account_age_days`| Receiver account age in days | `(now - payee_created_at).days` | Yes | Masked | Masked | Yes |
| 17| `is_scam_upi` | Receiver present in scam registry (0/1) | DB query `ScamUpi.upi_id` | Masked | Masked | Masked | Yes |
| 18| `distance_from_home_km`| Haversine distance from registered home | `haversine_km(current_loc, home_loc)`| Masked | Masked | Masked | Yes |
| 19| `is_impossible_travel`| Implied speed > 900 km/h from last txn (0/1)| Distance / elapsed time | Masked | Masked | Masked | Yes |
| 20| `payee_graph_centrality`| Degree centrality of receiver in graph | NetworkX in-degree centrality | Yes | Masked | Masked | Yes |
| 21| `is_mule_candidate` | Receiver in-degree >= 5 & out/in >= 0.8 (0/1) | NetworkX mule topology heuristic | Yes | Masked | Masked | Yes |
| 22| `is_high_risk_mcc` | Merchant category in [7995, 6051, 4829] | MCC code lookup (gambling/crypto) | Masked | Yes | Masked | Yes |

*Note on Masked Features:* Public tabular benchmark datasets (PaySim, IEEE-CIS, BAF) lack specialized mobile UPI signals (such as GPS geofencing, QR tampering, and device identifiers). Missing fields are assigned neutral default constants during data ingestion.

---

## 5. MACHINE LEARNING MODELS & TRAINING PIPELINE

### 5.1 The 7 Base Classifiers

All models trained on unified Parquet holdout data via `backend/train_all_models.py`:

1. **XGBoost Classifier (`mlbfd_mega_xgboost_model.pkl`):**  
   - Hyperparameters: `n_estimators=150`, `max_depth=5`, `learning_rate=0.08`, `scale_pos_weight=12.0`, `subsample=0.8`, `colsample_bytree=0.8`.
   - Test Metrics: PR-AUC = `0.3442`, ROC-AUC = `0.7946`, Recall@1%FPR = `17.07%`.
2. **Random Forest Classifier (`mlbfd_mega_random_forest_model.pkl`):**  
   - Hyperparameters: `n_estimators=100`, `max_depth=8`, `min_samples_split=10`, `class_weight='balanced'`.
   - Test Metrics: PR-AUC = `0.2954`, ROC-AUC = `0.7883`, Recall@1%FPR = `13.97%`.
3. **Logistic Regression (`mlbfd_mega_logistic_regression_model.pkl`):**  
   - Hyperparameters: `C=0.1`, `penalty='l2'`, `class_weight='balanced'`, `max_iter=1000`.
   - Test Metrics: PR-AUC = `0.3093`, ROC-AUC = `0.7692`, Recall@1%FPR = `13.86%`.
4. **Isolation Forest (`mlbfd_mega_isolation_forest_model.pkl`):**  
   - Hyperparameters: `n_estimators=100`, `contamination=0.07`, `random_state=42`.
   - Test Metrics: PR-AUC = `0.1040`, ROC-AUC = `0.5899`, Recall@1%FPR = `2.77%`.
5. **Deep Neural Network (`mlbfd_mega_neural_network_model.keras`):**  
   - Architecture: Input(22) -> Dense(64, ReLU, L2=0.001) -> BatchNorm -> Dropout(0.3) -> Dense(32, ReLU) -> BatchNorm -> Dropout(0.2) -> Dense(16, ReLU) -> Dense(1, Sigmoid).
   - Optimizer: Adam(`lr=0.001`), Loss: BinaryCrossentropy, EarlyStopping(`patience=8`).
   - Test Metrics: PR-AUC = `0.3603`, ROC-AUC = `0.8138`, Recall@1%FPR = `18.51%`.
6. **Attention LSTM (`mlbfd_mega_lstm_model.keras`):**  
   - Architecture: Reshape(1, 22) -> Bidirectional LSTM(32, return_sequences=True) -> Dot-Product Attention Layer -> Dense(16, ReLU) -> Dense(1, Sigmoid).
   - Test Metrics: PR-AUC = `0.3769`, ROC-AUC = `0.8287`, Recall@1%FPR = `18.85%`.
7. **Reconstruction Autoencoder (`mlbfd_mega_autoencoder_model.keras`):**  
   - Architecture: Encoder: 22 -> 16 -> 8 -> 4 (bottleneck); Decoder: 4 -> 8 -> 16 -> 22.
   - Anomaly Metric: Mean Squared Error (MSE) reconstruction loss; trained exclusively on normal transactions (`is_fraud == 0`).
   - Test Metrics: PR-AUC = `0.1769`, ROC-AUC = `0.5151`, Recall@1%FPR = `10.75%`.

### 5.2 Training Protocol & Calibration

- **Split Methodology:** Strict time-based chronological split. 70% Train (56,000 samples), 15% Validation (12,000 samples), 15% Test (12,000 samples). No future transactions leak into past training windows.
- **Scaling & Resampling:** RobustScaler fitted strictly on training split; SMOTE oversampling applied strictly to training split (`is_fraud` balance adjusted to 15%). Validation and test splits are never resampled.
- **Probability Calibration:** Isotonic Regression calibrators (`calibrator_<model>.pkl`) fitted on unseen validation predictions to output true empirical probabilities.
- **Operating Thresholds:** Calculated at strict validation False Positive Rate <= 1.0% and persisted in `backend/models/operating_thresholds.json`.

---

## 6. DATA AUDIT & INGESTION PIPELINES

### 6.1 Raw Datasets Overview

Located in `D:\Major Project\Datasets` (Total Raw Size: 3.22 GB across 18 files):

- **PaySim Mobile Money Dataset (`Tier1/PS_...log.csv`, 470 MB):** 6,362,620 raw rows. Financial mobile transfer logs. Mapped to amounts, step-based diurnal hours, and sender/receiver balances.
- **IEEE-CIS Fraud Detection (`Tier1/train_transaction.csv` & `train_identity.csv`, 682 MB):** 590,540 raw rows. E-commerce card transactions with device identity and risk categories.
- **Bank Account Fraud (BAF) Suite (`Tier2/Base.csv`, 318 MB):** 1,000,000 rows. Modern NeurIPS benchmark assessing synthetic identity and account opening fraud.
- **Clean Parquet Data Directory (`D:\Major Project\MLBFD\data`):**
  - `paysim_clean.parquet` (20,000 rows, 1.25 MB)
  - `ieee_clean.parquet` (20,000 rows, 1.34 MB)
  - `baf_clean.parquet` (20,000 rows, 1.32 MB)
  - `simulator_clean.parquet` (20,000 rows, 1.28 MB)

### 6.2 Realistic UPI Behavioral Simulator Design

Implemented in `backend/upi_simulator.py`:
- Generates 20,000 realistic UPI records across distinct user archetypes:
  - *College Students:* Low amounts, irregular late-night hours, high social velocity.
  - *Salaried Professionals:* Periodic rent/utility spikes, business-hour consistency.
  - *Small Merchants:* High-frequency daytime inflows, round sums.
  - *Night Owls:* Late-night activity, variable device locations.
- **Embedded Fraud Archetypes:** Mule topology fan-in, phishing domain links, QR code tampering, rapid velocity bursts, and boundary structuring (e.g. Rs 9,999).
- **Realistic Data Hygiene:** 0.5% random label noise, 3.5% natural fraud incidence. Single-feature AUCs strictly constrained under 0.81 to prevent synthetic feature leakage.

### 6.3 Confirmation of Synthetic Overlay Purge

- **Audit Result:** Lines 142-152 of `backend/data_processor.py` containing synthetic Gaussian overrides (`loc=4.5`, `loc=6.0` conditional on `is_fraud`) have been **completely deleted**.
- **Usage Verification:** `data_processor.py` is not imported or called by `train_all_models.py`, `data_loader.py`, `feature_builder.py`, or `api.py`. Zero synthetic leakage exists in active models.

---

## 7. AUTHENTICATION, PRIVACY & SECURITY INFRASTRUCTURE

### 7.1 Cryptographic Key Management & Storage

- **Fernet AES-256 Symmetric Encryption:** Applied to sensitive PII columns (`phone`, `email`, `upi_id`, `telegram_chat_id`). Key derived from `MLBFD_SECRET_KEY`.
- **HMAC-SHA256 Blind Indexing:** One-way searchable hashes computed using `HASH_PEPPER` (`phone_hash`, `email_hash`, `upi_hash`). Allows fast exact lookups without decrypting user database records.
- **Bcrypt Password & PIN Hashing:** 6-digit Login PIN, 6-digit Payment PIN, and Security Answers hashed with independent random salts (cost factor 12).
- **JWT Authorization:** Access tokens (15-minute expiry) and Refresh tokens (30-day expiry). Revocation maintained via `token_blocklist` database table.

### 7.2 Multi-Channel Dual OTP Protocol

- **Compulsory Channels:** Email (SMTP) AND Telegram Bot (`@mlbfd_otp_bot`). Both channels are **mandatory**; single-channel OTP verification is strictly rejected.
- **Trigger Circumstances:**
  - Initial User Registration activation.
  - Login from an unrecognized Device ID (`X-Device-ID`).
  - Step-up verification for suspicious transactions (`REQUIRES_2FA`).
  - Forgotten PIN reset confirmation.
- **Storage & Security:** OTPs generated as 6-digit cryptographic tokens, hashed via SHA-256 before database insertion (`otp_codes`). Expire in 300 seconds. 3 invalid attempts lock the OTP session.

### 7.3 Dual PIN Architecture & Protection

- **Separation of Concerns:** Independent **Login PIN** (portal and app sign-in) and **Payment PIN** (transfer authorization), mirroring Google Pay / PhonePe production architecture.
- **Lockout Policy:** 3 consecutive incorrect PIN submissions incur a 30-minute lockout on the specific PIN type.
- **PIN Recovery Safeguards:** Forgotten PIN reset requires dual OTP verification + bcrypt security answer validation. Once reset, sets `reduced_limit_until` enforcing a 24-hour reduced transaction cap (Rs 2,000 / txn, Rs 5,000 daily) and revokes all active JWT tokens.

### 7.4 Privacy Controls & Abuse Mitigation

- **Cryptographic Freeze Link:** Transaction alerts include a signed 24-hour single-use token (`/api/freeze?token=...`). Clicking locks the account immediately and invalidates active sessions.
- **Self-Service Data Deletion:** Users can delete accounts with dual OTP confirmation; personal details are wiped and ledger transactions are anonymized (`ANONYMIZED_USER`).
- **Bot & Abuse Throttling:** Cloudflare Turnstile token validation with fallback honeypot input, minimum 3.0-second form timing verification, disposable email provider rejection, and maximum 3 registrations per IP address per 24 hours.

---

## 8. REST API SPECIFICATION TABLE

| Method | Endpoint Route | Auth Required | Request Payload Fields | Response Summary |
| :--- | :--- | :---: | :--- | :--- |
| `POST` | `/api/register/start` | No | `full_name`, `user_id`, `phone`, `email`, `login_pin`, `payment_pin`, `lat`, `lon` | Dispatches dual OTPs; returns 201 with registration token |
| `POST` | `/api/register/verify_email` | No | `user_id`, `otp` | Verifies email OTP for pending registration |
| `POST` | `/api/register/verify_telegram` | No | `user_id`, `otp` | Verifies Telegram OTP; activates account upon dual completion |
| `POST` | `/api/login` | No | `user_id`, `pin` (Login PIN), Header `X-Device-ID` | Returns JWT tokens OR `OTP_REQUIRED` if unrecognized device |
| `POST` | `/api/login/verify` | No | `user_id`, `email_code`, `telegram_code`, `device_id` | Validates dual OTP, binds device, returns JWT tokens |
| `POST` | `/api/logout` | JWT | None | Revokes active JWT JTI into `token_blocklist` |
| `POST` | `/api/refresh` | Refresh | Header `Authorization: Bearer <refresh_token>` | Issues fresh 15-minute access token |
| `POST` | `/api/transfer` | JWT | `user_id`, `sender_upi`, `receiver_upi`, `amount`, `pin`, `device_id`, `lat`, `lon` | Executes payment or flags `REQUIRES_2FA` / `BLOCKED` |
| `POST` | `/api/otp/verify` | JWT | `txn_id`, `email_code`, `telegram_code` | Verifies dual OTP for `REQUIRES_2FA` pending transfers |
| `POST` | `/api/pin/change` | JWT | `pin_type`, `current_pin`, `new_pin` | Initiates PIN change; dispatches dual OTPs |
| `POST` | `/api/pin/change/confirm` | JWT | `pin_type`, `email_code`, `telegram_code` | Confirms PIN update |
| `POST` | `/api/pin/forgot/start` | No | `user_id`, `pin_type` | Initiates reset; dispatches dual OTPs |
| `POST` | `/api/pin/forgot/verify` | No | `user_id`, `email_code`, `telegram_code`, `security_answer` | Verifies identity; issues single-use reset token |
| `POST` | `/api/pin/forgot/reset` | No | `user_id`, `reset_token`, `new_pin` | Resets PIN, revokes JWTs, sets 24h reduced limits |
| `GET`  | `/api/balance/<uid>` | JWT | None | Returns account balance, UPI ID, daily spend limit |
| `GET`  | `/api/transactions/<uid>` | JWT | None | Returns historical transactions with risk details |
| `GET`  | `/api/lookup_payee` | JWT | Query `?query=<upi_or_phone>` | Resolves recipient name; 404 if unregistered |
| `GET`  | `/api/freeze` | No | Query `?token=<freeze_token>` | Instantly freezes account via emergency alert link |
| `POST` | `/api/account/delete` | JWT | `confirm_text`, `email_code`, `telegram_code` | Anonymizes user and marks account deleted |
| `POST` | `/api/account/reset_balance`| JWT | None | Resets virtual balance to Rs 1,00,000 (1/hour demo limit) |
| `POST` | `/api/report-scam` | JWT | `scam_upi`, `description` | Submits scam report to registry |
| `GET`  | `/api/website-check/<domain>`| JWT | None | Evaluates domain reputation score and flags |
| `GET`  | `/api/trusted-payees/<uid>` | JWT | None | Returns user's trusted payee list |
| `POST` | `/api/trusted-payees/add` | JWT | `payee_upi`, `nickname` | Manually registers trusted payee |
| `DELETE`| `/api/trusted-payees/<int:id>`| JWT | None | Removes trusted payee |

---

## 9. DATABASE SCHEMA (18 TABLES)

Stored in SQLite (`backend/instance/mlbfd.sqlite3`) with WAL journal mode:

1. **`users`:** Core user account state.
   - Columns: `id` (INTEGER PK), `user_id` (VARCHAR(50) UNIQUE), `full_name` (VARCHAR(150)), `phone` (TEXT, encrypted), `email` (TEXT, encrypted), `upi_id` (VARCHAR(255), encrypted), `telegram_chat_id` (TEXT, encrypted), `phone_hash` (VARCHAR(64)), `email_hash` (VARCHAR(64)), `upi_hash` (VARCHAR(64)), `status` (VARCHAR(20)), `email_verified` (BOOLEAN), `telegram_verified` (BOOLEAN), `known_devices` (JSON), `security_question` (VARCHAR(255)), `security_answer_hash` (VARCHAR(255)), `consent_at` (DATETIME), `balance` (NUMERIC(12,2)), `login_pin_hash` (VARCHAR(255)), `payment_pin_hash` (VARCHAR(255)), `login_failed_attempts` (INTEGER), `login_locked_until` (DATETIME), `payment_failed_attempts` (INTEGER), `payment_locked_until` (DATETIME), `tokens_revoked_at` (DATETIME), `reduced_limit_until` (DATETIME), `daily_spent_date` (VARCHAR(10)), `daily_spent_amount` (NUMERIC(12,2)), `home_latitude` (NUMERIC(10,8)), `home_longitude` (NUMERIC(11,8)), `home_accuracy_m` (FLOAT), `home_location_source` (VARCHAR(20)), `home_area_name` (VARCHAR(200)), `daily_limit` (NUMERIC(12,2)), `last_balance_reset_at` (DATETIME), `created_at` (DATETIME).
2. **`transactions`:** Transaction ledger and fraud engine logs.
   - Columns: `id` (INTEGER PK), `txn_id` (VARCHAR(100) UNIQUE), `user_id` (VARCHAR(50)), `sender_upi` (VARCHAR(255)), `receiver_upi` (VARCHAR(255)), `amount` (NUMERIC(12,2)), `status` (VARCHAR(30)), `risk_score` (NUMERIC(5,2)), `is_fraud` (BOOLEAN), `device_id` (VARCHAR(100)), `latitude` (NUMERIC(10,8)), `longitude` (NUMERIC(11,8)), `accuracy_m` (FLOAT), `location_source` (VARCHAR(20)), `area_name` (VARCHAR(200)), `hour` (INTEGER), `day_of_week` (INTEGER), `is_holiday` (BOOLEAN), `qr_code` (TEXT), `merchant_name` (VARCHAR(255)), `mcc_code` (VARCHAR(10)), `layer_scores` (JSON), `flags` (JSON), `ensemble_confidence` (NUMERIC(5,4)), `created_at` (DATETIME), `expires_at` (DATETIME), `failed_attempts` (INTEGER).
3. **`user_behavior_baseline`:** Dynamic behavioral baselines per user.
   - Columns: `id` (INTEGER PK), `user_id` (VARCHAR(50) UNIQUE), `avg_amount` (NUMERIC(12,2)), `std_amount` (NUMERIC(12,2)), `avg_hour` (NUMERIC(5,2)), `txn_count` (INTEGER), `known_devices` (JSON), `known_payees` (JSON), `mcc_history` (JSON), `last_updated` (DATETIME).
4. **`otp_codes`:** Ephemeral dual OTP tokens.
   - Columns: `id` (INTEGER PK), `user_id` (VARCHAR(50)), `purpose` (VARCHAR(50)), `channel` (VARCHAR(20)), `code_hash` (VARCHAR(64)), `txn_id` (VARCHAR(100)), `expires_at` (DATETIME), `attempts` (INTEGER), `max_attempts` (INTEGER), `used_at` (DATETIME), `created_at` (DATETIME), `ip_address` (VARCHAR(45)), `dual_group_id` (VARCHAR(64)).
5. **`trusted_payees`:** Whitelisted payee records.
   - Columns: `id` (INTEGER PK), `user_id` (VARCHAR(50)), `payee_upi` (VARCHAR(100)), `nickname` (VARCHAR(100)), `txn_count` (INTEGER), `total_amount` (NUMERIC(12,2)), `added_date` (DATETIME).
6. **`scam_upis`:** Central fraud registry.
   - Columns: `id` (INTEGER PK), `upi_id` (VARCHAR(100) UNIQUE), `reported_count` (INTEGER), `reported_by_count` (INTEGER), `verified` (BOOLEAN), `added_at` (DATETIME).
7. **`account_freeze_tokens`:** Single-use cryptographic freeze links.
   - Columns: `token` (VARCHAR(255) PK), `user_id` (VARCHAR(50)), `expires_at` (DATETIME), `used` (BOOLEAN), `created_at` (DATETIME).
8. **`token_blocklist`:** Revoked JWT token identifiers.
   - Columns: `id` (INTEGER PK), `jti` (VARCHAR(36) UNIQUE), `user_id` (VARCHAR(50)), `created_at` (DATETIME).
9. **`telegram_link_tokens`:** Temporary tokens for Telegram onboarding.
10. **`website_reputation`:** Cached domain reputation results.
11. **`audit_log`:** Immutable compliance and access log.
12. **`feedback`:** User/analyst false positive/negative feedback.
13. **`model_metrics`:** Historical retraining performance track.
14. **`pending_pin_changes`:** Staged PIN change verification states.
15. **`password_reset_tokens`:** Forgot-PIN reset authorization tokens.
16. **`scam_reports`:** Raw crowd-sourced scam submissions.
17. **`signup_ip_logs`:** IP registration rate limiting tracking.
18. **`otp_records`:** Legacy single-channel OTP log table.

---

## 10. FRONTEND APPLICATIONS

### 10.1 Web Applications (Flask + Jinja2 + Bootstrap + Vanilla JS)

- **User Portal (`/user/login`, `/user/register`, `/dashboard`):**
  - Modern signup wizard with HTML5 Leaflet map picker for home geofence.
  - Interactive transfer panel with instant What-If risk preview.
  - Real-time balance card with 1-click test balance reset.
  - SHAP explainability breakdown for reviewed/step-up transactions.
- **Admin Portal (`/admin`, `/admin/transactions`, `/admin/users`, `/admin/alerts`, `/admin/models`, `/admin/drift`):**
  - Live system overview: 24h volume, fraud detection rates, and active lockouts.
  - Interactive network graph explorer visualizing mule clusters.
  - Data drift monitoring: Population Stability Index (PSI) tracking across features.
  - 1-Click NPCI Compliance CSV Export.

### 10.2 Flutter Mobile Applications

Located in `flutter_app/sender_app` and `flutter_app/receiver_app`:
- **Sender App:** Full transaction lifecycle (Registration, Login, Send Money with QR scan, Dual-OTP step-up dialog, Transaction history).
- **Receiver App:** Dynamic QR generation (`upi://pay?pa=...`), real-time incoming transfer notifications, settlement balance view.
- **Dynamic Configuration:** Both apps use `ApiConfig.setBaseUrl(url)` with persistent SharedPreferences storage. Hard-coded loopback `10.0.2.2:5000` is used solely as an initial fallback default.
- **Build Status:** Verified 0 compilation errors via `flutter analyze`. Production release APK generation instructions documented in `README_APK.md`.

---

## 11. CONFIGURATION & SECRETS MANAGEMENT

All configuration is read from the repo-root `.env` by `backend/env_loader.py` (absolute path,
works from any folder and under Waitress). `.env` **overrides** stale Windows variables of the
same name; values are cleaned (quotes, inline `# comments`, spaces in the app password).
`backend/.env` only fills keys the root file lacks. `.env.example` is never read.
**Restart the server after any `.env` change** (a running server keeps old values; `serve.py`
now refuses to start if port 5000 is already taken by an older copy).

### 11.1 Environment Variable Status (2026-10-31, names/status only)

| Category | Variable | Status | Action |
| :--- | :--- | :---: | :--- |
| Database | `DATABASE_URL` | SET (SQLite) | WAL mode enforced by `serve.py` |
| Security keys | `MLBFD_SECRET_KEY` | SET, **guessable + leaked in git (feedf0c, d7f262d)** | Rotate: `scripts/rotate_secrets.py --apply --fresh-db` (see ROTATE_SECRETS.md) |
| | `JWT_SECRET_KEY` | SET, guessable | Rotate with the same script |
| | `HASH_PEPPER` | SET, guessable, **unused by code** | Rotate; lookups use MLBFD_SECRET_KEY |
| | `MLBFD_CLIENT_SECRET` | empty (optional) | Separate APK request-signing key |
| | `ADMIN_API_TOKEN` | empty (optional) | Enables /admin and /api/health/otp through the tunnel |
| Email | `EMAIL_USER`, `EMAIL_FROM` | SET (gmail.com, equal) | OK |
| | `EMAIL_PASSWORD` | SET, 16 letters, **rejected by Gmail (535 5.7.8)** | Create a new Gmail app password |
| | `EMAIL_DRY_RUN` | false | OK |
| | `EMAIL_PORT` / `EMAIL_SMTP_MODE` | 587 / auto | 587 STARTTLS with automatic 465 SSL fallback |
| Telegram | `TELEGRAM_BOT_TOKEN` | SET, getMe 200 | OK (never committed) |
| | `TELEGRAM_BOT_USERNAME` | `mlbfd_otp_bot` (matches getMe) | OK |
| | `TELEGRAM_DRY_RUN` / `TELEGRAM_POLLING_ENABLED` | false / true | OK |
| External | `GOOGLE_SAFE_BROWSING_API_KEY` | SET, live test PASS | OK |
| | `OPENPHISH_API_KEY` | MOCK | Free feed used only when a key is set; keyword simulation otherwise |
| | `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | empty | Honeypot + 3 s timing token fallback (keep empty for app signups) |
| Limits | `REDUCED_TXN_LIMIT` / `REDUCED_DAILY_LIMIT` | 10,000 / 25,000 | 24 h after PIN reset |
| | `VIRTUAL_BALANCE` | 100,000 | On activation |

Diagnostics: `python backend/otp_doctor.py` (env/names/flags/port), `--email-test`,
`--telegram-test`, `--link-telegram`, `--safebrowsing-test`. Never prints secret values.
Secret scan: `python scripts/secret_scan.py --history` (file + commit only).

---

## 12. AUDITED EMPIRICAL RESULTS & BENCHMARKS

Values extracted directly from `ACCURACY_REPORT.md` and `backend/models/mlbfd_mega_metrics.json`:

### 12.1 Holdout Test Split Evaluation (12,000 Unseen Transactions)

- **Total Test Samples:** `12,000` (Chronological 70/15/15 holdout)
- **Total Test Frauds:** `902` (**7.52%** natural test fraud prevalence)
- **Learned Stacking Ensemble PR-AUC:** **0.3840**
- **Learned Stacking Ensemble ROC-AUC:** **0.8342**
- **Recall at 1% False Positive Rate:** **17.07%** (154 of 902 frauds detected at operating threshold `0.4030`)
- **Empirical False Positive Rate:** **0.9731%** (108 false alarms out of 11,098 legitimate transactions)
- **Precision at Operating Threshold:** **58.78%** (154 / 262 positive alerts)
- **F1 Score at Operating Threshold:** **0.2646**
- **Confusion Matrix:**
  ```
                   Predicted Legitimate   Predicted Fraud
  Actual Legitimate        10,990                 108         (FPR: 0.9731%)
  Actual Fraud                748                 154         (Recall: 17.0732%)
  ```

### 12.2 Metrics Disaggregated by Data Source

- **Real-Dataset Rows Only (PaySim, IEEE-CIS, BAF - 9,000 rows, 776 frauds):**
  - PR-AUC: `0.2568`
  - ROC-AUC: `0.7746`
  - Recall at 1% FPR: `6.83%` (53 of 776 frauds detected)
- **Simulator Rows Only (UPI Behavioral Simulator - 3,000 rows, 126 frauds):**
  - PR-AUC: `0.8452`
  - ROC-AUC: `0.9370`
  - Recall at 1% FPR: `80.16%` (101 of 126 frauds detected)

### 12.3 Individual Base Classifier Test Metrics

| Model Architecture | Test PR-AUC | Test ROC-AUC | Recall @ 1% FPR | Accuracy |
| :--- | :---: | :---: | :---: | :---: |
| **XGBoost Classifier** | `0.3442` | `0.7946` | `17.07%` | 87.35% |
| **Attention LSTM** | `0.3769` | `0.8287` | `18.85%` | 93.21% |
| **Deep Neural Network (DNN)** | `0.3603` | `0.8138` | `18.51%` | 93.13% |
| **Logistic Regression** | `0.3093` | `0.7692` | `13.86%` | 61.00% |
| **Random Forest** | `0.2954` | `0.7883` | `13.97%` | 81.33% |
| **Reconstruction Autoencoder** | `0.1769` | `0.5151` | `10.75%` | 92.56% |
| **Isolation Forest** | `0.1040` | `0.5899` | `2.77%` | 83.97% |

### 12.4 Scripted Scenario Suite & Operational Latency

- **Scenario Suite Result:** **21 / 21 Passed (100.0%)** across all scripted payment vectors (Vishing, Mule Rings, ATO, Phishing, QR Tampering, Velocity Bursts, Limit Boundary Structuring).
- **End-to-End Latency (1,000 live requests through 7-layer engine & SQLite WAL):**
  - **p50 Latency:** `497.91 ms`
  - **p95 Latency:** `790.93 ms`
  - **p99 Latency:** `1257.15 ms`
  - **Mean Latency:** `503.33 ms`
- **Automated Test Suite:** **156 passed**, 0 failed, 0 errors.

> [!WARNING]
> **Deprecation of Obsolete Compendium Claims:** Previous documentation iterations contained speculative or synthetic-leaked claims (e.g. "1.05 ms latency", "100% detection rate", "1.0000 ROC-AUC"). These numbers stemmed from mock unit tests and synthetic Gaussian overlays. They are strictly obsolete and must never be cited.

---

## 13. DEPLOYMENT & OPERATIONS MANUAL

### 13.1 Local Development Environment

```bash
# 1. Open project terminal
cd "D:\Major Project\MLBFD"

# 2. Activate virtual environment
backend\.venv\Scripts\activate

# 3. Run full automated test suite
pytest tests -q

# 4. Launch local development server
python backend/app.py
```

### 13.2 Production WSGI Serving with Waitress

```bash
# Serves on 0.0.0.0:5000 with 8 worker threads and SQLite WAL mode enforced
python serve.py
```

### 13.3 Windows Launcher Batch Script (`start_mlbfd.bat`)

Runs automatic environment checks, verifies Cloudflare tunnel binaries, starts the tunnel daemon in a separate window, and launches the Waitress production server.

### 13.4 Free Public Hosting via Cloudflare Tunnel

```bash
# 1. Install cloudflared via Windows Package Manager
winget install --id Cloudflare.cloudflared

# 2. Start quick tunnel (zero port-forwarding, free SSL)
cloudflared tunnel --url http://localhost:5000

# 3. Tunnel generates ephemeral HTTPS public URL:
# https://<random-subdomain>.trycloudflare.com
```

### 13.5 Flutter APK Compilation

```bash
cd "D:\Major Project\MLBFD\flutter_app\sender_app"
flutter clean
flutter pub get
flutter build apk --release
# Output APK location: build/app/outputs/flutter-apk/app-release.apk
```

### 13.6 Git Repository State & Recent Commit Log

Current Branch: `master`  
Last 15 Commits:
```
b6ff8da WIP start retrain: Retrain models under scikit-learn 1.9.1 and update ACCURACY_REPORT
cd9eb74 Part 21: Purged synthetic Gaussian overlay from data_processor.py; 100% check passed
d4f19fb WIP start P21S1: remove synthetic Gaussian overlay from data_processor.py
d7f262d WIP P29: Verified flutter analyze passes, committed dynamic config and security headers
1e851b6 WIP start P29S2: Update flutter apps with dynamic Server URL, X-Device-ID, and branding
a219c22 WIP done P29S1: Ran flutter doctor and created README_APK.md
25b4121 WIP start P29S1: Run flutter doctor and write diagnostics into README_APK.md
62a5446 Part 28: Mobile-friendly web portals, responsive 360px CSS, >=44px touch targets, 6/6 tests pass
2815a9e WIP start P28S4: Add test_part28_mobile_responsiveness.py and verify DONE CHECK
41efdd5 WIP done P28S3: Enhanced template mobile layout wrappers and navigation
bab4074 WIP start P28S3: Update templates with responsive wrappers and mobile navigation
4c7ffb0 WIP done P28S2: Updated user.css and main.css with responsive styles and >=44px touch targets
fdd525e WIP start P28S2: Update user.css and main.css with responsive styles
144edf1 WIP done P28S1: Audited templates and CSS for mobile responsive gaps
c8a3b30 WIP start P28S1: Audit viewport meta tags, input touch targets, and mobile form controls
```

---

## 14. PROGRESS & IMPLEMENTATION SCORECARD

| Part | Description | Status | Evidence / Verified Code Artifact |
| :---: | :--- | :---: | :--- |
| **P0** | State files | **DONE** | `CONTEXT.md`, `PROGRESS.md`, `.gitignore` active |
| **P1** | Rename | **DONE** | Zero BeyondOTP in active code; MLBFD everywhere |
| **P2** | User model | **DONE** | 10 blind-hash columns, AES encryption, idempotent migration |
| **P3** | PINs | **DONE** | Dual PIN separation, weak PIN rejection, lockouts |
| **P4** | OTP core | **DONE** | `otp_codes` table, HMAC verification, dual groups |
| **P5** | Email channel | **DONE** | `email_sender.py`, background retry, dry-run mode |
| **P6** | Telegram channel | **DONE** | `telegram_bot.py`, link token flow, polling daemon |
| **P7** | Signup flow | **DONE** | 4-step wizard, dual OTP activation, 1 lakh balance |
| **P8** | Login flow | **DONE** | `X-Device-ID` header, 30-day trust, refresh tokens |
| **P9** | Fraud step-up | **DONE** | `REQUIRES_2FA` holds `PENDING`, dual OTP atomic verify |
| **P10**| PIN management | **DONE** | Forgot-PIN flow, 24h reduced limits, JWT blocklist |
| **P11**| Registered transfers | **DONE** | 404 before scoring, blind hash lookup, self-transfer block |
| **P12**| Override rules | **DONE** | 8 canonical `OVERRIDE_RULES`, floor scoring, audit flags |
| **P13**| Security alerts | **DONE** | "Was this you?" dual alert, 24h signed freeze token |
| **P14**| Abuse protection | **DONE** | Honeypot, 3s form timing, disposable domain block |
| **P15**| Privacy controls | **DONE** | Consent logging, account deletion ledger anonymization |
| **P16**| Geolocation | **DONE** | Leaflet picker, accuracy_m, >5000m penalty skip |
| **P17**| Data audit | **DONE** | `DATA_AUDIT.md` covering 11 CSVs, zero memory blowup |
| **P18**| Data loaders | **DONE** | `data_loader.py` chunked parquet generation, zero leakage |
| **P19**| Feature builder | **DONE** | Canonical 22 vector, SHA-256 hash check, identity tests |
| **P20**| UPI simulator | **DONE** | Realistic distributions, 0.5% noise, 3.5% fraud rate |
| **P21**| Honest training | **DONE** | Time-split (70/15/15), Gaussian overlay purged |
| **P22**| Calibration | **DONE** | TimeSeriesSplit, Isotonic calibration, operating thresholds |
| **P23**| Learned fusion | **DONE** | Stacking meta-classifier, `fusion.json`, Z-score cap 60 |
| **P24**| Scenario suite | **DONE** | 21/21 scenarios match, `ACCURACY_REPORT.md` generated |
| **P25**| SHAP explainability | **DONE** | Cached TreeExplainer (<10ms), top-5 feature attributions |
| **P26**| Testing & CI | **DONE** | 201 pytest passing (was 156), `.github/workflows/ci.yml` |
| **P27**| Hosting setup | **DONE** | Waitress `serve.py` (8 threads), SQLite WAL, `start_mlbfd.bat` |
| **P28**| Mobile web | **DONE** | Viewport meta, responsive CSS (360px), >=44px touch targets |
| **P29**| Flutter mobile APK | **PARTIAL** | Apps rewritten for dual-OTP signup/login, server URL on first launch, per-channel resend; `flutter analyze` 0 errors; `flutter build apk --release` blocked: no JDK (JAVA_HOME) |
| **P30**| Optional extras | **TODO** | Advanced extras (Ablation, GraphSAGE) intentionally deferred |
| **P31**| OTP delivery mission (2026-10-31) | **DONE (code)** | Root causes proven (see 15); otp_doctor; per-channel status + resend; 201 pytest; smoke 14/14; FILE_REVIEW.md 153 files; Gmail app password = user action |

---

## 15. KNOWN RISKS, LIMITATIONS & ARCHITECTURAL TRADEOFFS

### 15.1 OTP failure root causes (proven 2026-10-31)
1. **Gmail rejects the app password** in `.env`: explicit AUTH LOGIN/PLAIN on 587 and 465 return
   `535 5.7.8 BadCredentials`; TLS issuer is Google (no antivirus interception). User action.
2. `smtplib.login()` retried a 2nd mechanism after the 535; Gmail closed the socket, so logs only
   showed `SMTPServerDisconnected` (fixed: single mechanism).
3. Missing credentials were reported as "sent" (fixed: EmailConfigError).
4. Telegram API is healthy; Telegram codes never arrived because signup aborted at the email step,
   and `issue_dual` ignored both send results (fixed: per-channel `delivery` in every OTP response).
5. Behind Cloudflare every request came from 127.0.0.1: the 5 OTPs/hour/IP limit (and Flask-Limiter)
   was shared by **all** users (fixed: tunnel-aware `security.client_ip`).
6. Two stale `serve.py` processes kept port 5000 (Windows allowed a 2nd bind), so code/.env edits
   never reached the answering server (stopped; port guard + poller heartbeat added).
7. `python backend/app.py` (debug reloader) started two Telegram pollers -> HTTP 409 (fixed).

### 15.2 Remaining risks
| Severity | Issue | Mitigation |
| :---: | :--- | :--- |
| **HIGH** | `MLBFD_SECRET_KEY` (Fernet key for all PII) is in git history and guessable | Rotate with `scripts/rotate_secrets.py --apply --fresh-db` (wipes demo data, backups kept) |
| **HIGH** | Low recall on real benchmark rows (6.83% at 1% FPR) | Public datasets lack UPI features; honest limitation, see ACCURACY_REPORT.md |
| **MEDIUM** | APK not built (no JDK) | Install JDK 17 (README_APK.md) |
| **MEDIUM** | Account delete exists in the API but has no web UI | Add a settings button calling `/api/account/delete` |
| **LOW** | `HASH_PEPPER` unused; legacy plaintext `phone_number` column still on User | Remove in a migration after rotation |
| **LOW** | Single sample per fraud scenario in the 21-scenario suite | Expand parametric variations |
| ~~HIGH~~ | ~~Median latency ~500 ms~~ | Fixed: detect p50 63.7 ms / p95 77.8 ms / p99 86.9 ms (ACCURACY_REPORT.md "Latency") |
| ~~LOW~~ | ~~Flutter 10.0.2.2 fallback URL~~ | Fixed: no fallback; URL asked on first launch |

---

## 16. BINDING USER POLICY DECISIONS

Recorded verbatim as foundational constraints for all succeeding agents:

1. **Compulsory Dual-Channel OTP:** OTP channels are Email (SMTP) and Telegram Bot only. Both are required simultaneously. SMS and Twilio are permanently banned.
2. **Adaptive Login Friction:** OTP verification occurs at registration and upon logging in from a new/unrecognized device. It is never triggered on routine app open from a trusted device.
3. **Step-Up Verification (`REQUIRES_2FA`):** High-risk transactions hold in `PENDING` state and require both Email and Telegram OTPs before funds transfer.
4. **Independent Dual PINs:** Separate 6-digit Login PIN and Payment PIN. PIN changes require current PIN + OTP; Forgot PIN requires OTP + security answer.
5. **Initial Account Balance:** Every newly activated user account is automatically granted a virtual balance of **Rs 1,00,000.00**.
6. **Canonical UPI ID Format:** All UPI identifiers follow `<10-digit-phone>@mlbfd`.
7. **Registered Active Users Only:** Transfers can only be sent to registered, active users by UPI ID or phone. Unregistered destinations fail with HTTP 404 before scoring.
8. **Consistent Branding:** Project name is strictly **MLBFD** across all web pages, apps, logs, and document headers.
9. **Accurate Geolocation:** Location requires accurate GPS or a user-selected draggable map pin. IP-based geolocation is prohibited.
10. **Zero-Cost Deployment:** System must run on local commodity hardware (Ryzen 5, CPU-only) utilizing free Cloudflare Tunnels and SQLite WAL.
11. **Dual Deliverables:** Project deliverables consist of a production web application and Flutter mobile APKs.
12. **Scientific Honesty Over Artificial Perfection:** The user requires unembellished, honest metrics. Never tune on the test split or manufacture artificial scores.

---

## 17. EXHIBITION POSTER STATUS

- **Poster Specification:** A3 Portrait academic project poster prepared for the **AARONAN 2026** Project Exhibition.
- **Header Elements:** Visvesvaraya Technological University (VTU) and BGS College of Engineering and Technology (BGSCET) institutional headers.
- **Core Results Card:** Highlights combined ROC-AUC `0.83`, real-data ROC-AUC `0.77`, UPI simulation recall `80.16%` at 1% FPR, 21/21 scenario pass rate, and `0.79 s` p95 latency.
- **Physical Asset Note:** `MLBFD_Poster_With_Results.png` is not currently present on disk. All exact metrics and layout specifications are compiled in `RESULTS_FOR_POSTER.txt` for immediate image generation.

---

## 18. STRATEGIC NEXT STEPS (PRIORITY ORDER)

1. **Fix email OTP**: new Gmail app password (no spaces) in `EMAIL_PASSWORD`, restart, run
   `python backend/otp_doctor.py --email-test` (must PASS; startup banner must not show
   "EMAIL OTP WILL FAIL").
2. **Prove Telegram on a phone**: stop the server, `python backend/otp_doctor.py --link-telegram`,
   open the link, press Start, Share contact; expect "MLBFD test".
3. **Rotate app keys** (leaked/guessable): `python scripts/rotate_secrets.py --apply --fresh-db`.
4. **Public demo**: `winget install --id Cloudflare.cloudflared`, run `start_mlbfd.bat` (prints the
   https://...trycloudflare.com URL). Set `ADMIN_API_TOKEN` to open `/admin?admin_token=...` remotely.
5. **APK**: install JDK 17, `flutter build apk --release` in `flutter_app/sender_app` and `receiver_app`.
6. **Viva**: emphasise honest metrics (1% FPR vs recall trade-off) and why dual email + Telegram OTP
   avoids SIM-swap risk of SMS.

---

## 19. INSTRUCTION BLOCK FOR FRESH CHAT SESSION

```
You are the lead AI engineer continuing the MLBFD (Multi-Layer Behavioral Fraud Detection for UPI) project in D:\Major Project\MLBFD.
Your context is strictly the files on disk and git history.
Before taking any action, read PROJECT_HANDOFF.md, CONTEXT.md, and PROGRESS.md.

CORE OPERATIONAL RULES:
1. Work in tiny, verifiable steps with save-as-you-go git commits.
2. Run pytest tests after every modification to prevent regressions (156 tests must stay passing).
3. Never log, print, or commit secrets from .env.
4. Maintain scientific integrity: report honest metrics, never train or tune on test splits.
5. Strictly adhere to binding user policies recorded in Section 16 of PROJECT_HANDOFF.md.
```
