# VTU Report: Facts Extracted From the Project (not the report itself)

Project in the code: **MLBFD** (the brief calls it "Multi-Layer Behavioral Fraud Detection System Using Machine Learning"; the code and docs expand MLBFD as "Machine Learning-Based Financial Fraud Detection", CONTEXT.md line 2; confirm the final title).
Rules followed: facts only, source after each fact, `NOT PROVIDED` where the files do not say, code wins over docs.

**Global warnings (read first)**
- The template **"Major project REPORT.pdf" was provided later and has been read** (another team's project, "Sketch2Motion", BGS College of Engineering and Technology, AI&ML, 2025-26). It is used for **format only**; none of its content or names are copied. Its chapter/section numbering matches your prompt exactly (see "Template format notes" at the end).
- **No screenshots exist** in the project (no .png/.jpg outside Flutter build assets). All Fig 6.2/6.3/9.x files are NOT PROVIDED.
- **No research papers are attached**; `docs/PROJECT_RESEARCH_REPORT.md` has no numbered references. Chapter 3 and the bibliography are NOT PROVIDED.
- **All 135 git commits are by one author ("Chirag")**, 2026-10-15 to 2026-11-02 [`git log`]. Team members, roles and USNs are NOT PROVIDED.
- Doc/code conflicts found (code followed): see section "Conflicts" at the end.

---
## PRELIMINARY PAGES
**Title page** — the template's title page contains: VTU heading, "A Project Report on <title>", degree (Bachelor of Engineering in <branch>), "Project Phase II (<subject code>)", students with USNs, guide with designation, department, college name and address, academic year. For your project only the title (MLBFD) is known; the template's college (BGSCET), branch (AI&ML), subject code (BAI786) and year (2025-2026) are *its* details, not confirmed for you.
- Team names + USNs, guide + designation, department, college, subject code: NOT PROVIDED.
**Certificate:** the template certifies one student by name and USN and has three signatory blocks (guide, HOD, Principal) plus two "Name of Examiners / Signature with Date" lines. Your names: NOT PROVIDED. **Acknowledgments:** all names NOT PROVIDED.
**Abstract (facts only)** — the template abstract is 4 short paragraphs: (1) problem and objective, (2) method, (3) implementation tools, (4) results and future potential. Facts for each:
- Problem: real-time fraud detection for UPI-style payments with a virtual-money demo [CONTEXT.md:3-4, 45; PROJECT_HANDOFF.md §1].
- Method: 7 ML/DL models + 7 rule layers + stacking fusion + hard override rules [CONTEXT.md; backend/fraud_detection.py:16-51, 519-525; backend/models/fusion.json "selected_fusion": stacking].
- Results sentence (template paragraph 4) must use the measured numbers below only.
- Tools: Flask, SQLAlchemy/SQLite, XGBoost, scikit-learn, TensorFlow/Keras, SHAP, Waitress, Flutter [requirements.txt; installed versions in 5.5].
- Dataset: PaySim, IEEE-CIS, BAF + a UPI simulator; time-split train 56,000 / val 12,000 / test 12,000 [backend/models/mlbfd_mega_metrics.json `_metadata`; DATA_AUDIT.md §2].
- Best measured result (held-out test, 12,000 rows): **LSTM ROC-AUC 0.8287**; stacking recall at 1% FPR **0.1605** [mlbfd_mega_metrics.json; fusion.json `comparison.stacking`]. (Recall is low; do not claim high detection on the holdout.)
**List of Figures / Tables:** only figures that can exist from files: none have image files. Tables are listed per chapter below.

---
## CHAPTER 1: INTRODUCTION
**1.1 Introduction** [CONTEXT.md; PROJECT_HANDOFF.md §1]
- Scores each payment through 7 rule layers (weighted) and 7 ML/DL models, then returns APPROVED / APPROVED_WITH_WARNING / REQUIRES_2FA / BLOCKED [fraud_detection.py:578-589].
- High-risk payments are held until the user enters **two** one-time codes (email + Telegram) [otp_service.py; api.py `/api/otp/verify`].
- Users sign up with email + Telegram verification, separate 6-digit login and payment PINs; payments only to registered users [CONTEXT.md; security.py `validate_dual_pins`].
- Web user portal + admin portal (Flask) and two Flutter apps (Sender, Receiver) [dashboard/templates; flutter_app/*/lib/screens].
- Money is virtual (100,000 INR on activation) [config.py `VIRTUAL_BALANCE`; CONTEXT.md].
**1.2 Motivation / gaps** — the *reasons* are only partly in files:
- Research gap text exists: "existing literature treats fraud detection as an isolated tabular classification task on static data..." [docs/PROJECT_RESEARCH_REPORT.md:27]. Author's own motivation statement: NOT PROVIDED (question Q1.1).
**1.3 Problem statement (4-6 challenge points)** — the code supports these challenges: severe class imbalance (fraud 0.13%-3.5% in sources, DATA_AUDIT.md §2); public data lacks UPI features (PROJECT_HANDOFF.md §15: "10+ features masked"); OTP/SIM-swap risk (handoff §18 item 6); scam/mule/QR/phishing patterns (OVERRIDE_RULES; scenario categories ACCURACY_REPORT.md §4). The wording is yours to confirm.
**1.4 Objectives** — NOT PROVIDED as an official list. Implemented capabilities you can phrase as objectives: layered scoring, dual-channel OTP step-up, explainability (SHAP top-5), honest evaluation (time split, no leakage) [tests part21, part25].
**1.5 Outline:** interface (web + Flutter) -> Flask REST API (`backend/api.py`) -> detection engine (`fraud_detection.py`, `predictor.py`) -> 7 layers -> SQLite DB (`database.py`) -> admin dashboard (`app.py` `/admin`); deployment: Waitress on the laptop (8 threads) + Cloudflare quick tunnel [serve.py; start_mlbfd.bat].

---
## CHAPTER 2: PROJECT ORGANIZATION
**2.1 Process model:** NOT PROVIDED. Observed: work was done in numbered "Parts" 0-30, each committed on completion, with tests per part [PROGRESS.md; tests/test_partN_*.py]. Whether you call it Agile/Waterfall is your choice (Q2.1).
**2.2 Roles table (Table 2.1):** Member | Role | Responsibilities: NOT PROVIDED for every member, guide and reviewer (Q2.2).

---
## CHAPTER 3: REVIEW OF LITERATURE
**3.1** Literature-review figure (Fig 3.1): NOT PROVIDED. **3.2 Related works:** no papers attached; table NOT PROVIDED. Datasets cited by the project (usable as dataset references, not as papers): PaySim, IEEE-CIS (Vesta), Bank Account Fraud (BAF) [DATA_AUDIT.md; docs/PROJECT_RESEARCH_REPORT.md §3.1]. **3.3 Research gap:** see Q1.1; text at docs/PROJECT_RESEARCH_REPORT.md:27.

---
## CHAPTER 4: PROJECT MANAGEMENT PLAN
**4.1 Schedule.** No planned schedule exists. Actual work, commits per day [`git log`]: 10-15: 1, 10-16: 4, 10-20: 6, 10-23: 8, 10-25: 21, 10-28: 32, 10-29: 12, 10-30: 24, 10-31: 25, 11-02: 2.
| Phase (from PROGRESS.md Parts) | Activities | Dates (commits) |
|---|---|---|
| Setup, rename, config (Parts 0-1) | CONTEXT/PROGRESS, MLBFD rename | 10-15 to 10-16 |
| Core auth/OTP/signup (Parts 2-11) | user model, PINs, email/Telegram, signup, login, step-up | 10-16 to 10-25 (approx.) |
| Fraud logic + data/ML (Parts 12-26) | overrides, alerts, abuse, privacy, geo, data audit, loaders, simulator, training, calibration, fusion, SHAP, tests | 10-25 to 10-30 |
| Hosting + mobile (Parts 27-29) | Waitress, tunnel, responsive web, Flutter | 10-30 to 10-31 |
| OTP delivery + review + fixes | see FILE_REVIEW.md, PROGRESS.md | 10-31 to 11-02 |
Start/end *weeks* for a Gantt: derived only from commit dates above; planned dates NOT PROVIDED.
**4.2 Risks (Table 4.1):** no risk register exists. Risks *documented* in PROJECT_HANDOFF.md §15 with mitigation: low recall on real data (HIGH), APK not built (MEDIUM), leaked/guessable secret key (HIGH), Android SDK path with space (MEDIUM). Likelihood/Impact values are not stated except the severity word. Table must be confirmed by you (Q4.1).

---
## CHAPTER 5: SOFTWARE REQUIREMENT SPECIFICATIONS
**5.1 Product overview:** web application + REST API + mobile apps. Front end: Jinja2 HTML/JS/CSS (`dashboard/`), Flutter. Back end: Flask 3.0.0. DB: SQLite (WAL) with optional PostgreSQL fallback [db.py; serve.py].
**5.2 External interfaces / entities:** users (web, Flutter); admin (local or token); Telegram Bot API (`requests`, getUpdates polling) [telegram_bot.py]; SMTP (Brevo relay, Gmail supported) [email_sender.py]; Google Safe Browsing v4 [website_trust.py]; OpenPhish feed (needs key set, else keyword simulation) [website_trust.py]; WHOIS [website_trust.py]; Nominatim reverse geocode [geofence.py]; Cloudflare Turnstile (optional, honeypot fallback) [security.py]; Firebase key stored but unused [config.py].
**5.3 User interfaces (inputs/outputs):**
| Screen | File | Purpose |
|---|---|---|
| User register (3-step) | user_register.html | details, email code, Telegram link + code |
| User login (+ new-device OTP, forgot PIN) | user_login.html | login, dual OTP, PIN reset |
| User dashboard | user_dashboard.html | balance, send money (6-digit PIN pad), history, trusted payees, PIN change, 2FA modal |
| Admin overview / Transactions / Alerts / Users / Models / Drift | index, transactions, alerts, users, models, drift .html | monitoring, lock toggle, retrain, NPCI CSV export |
| Flutter Sender: registration, send money, OTP, history, trusted contacts, analytics, QR generator, biometric, server URL | flutter_app/sender_app/lib/screens | see files |
| Flutter Receiver: registration, balance, receive, history, server URL | flutter_app/receiver_app/lib/screens | see files |
Detailed control lists per screen: not extracted (Q5.1 if required).
**5.4 Hardware.** Minimum/recommended: NOT PROVIDED. Actual machine (measured 2026-11-02, PowerShell): AMD Ryzen 5 3500U, 4 cores / 8 threads, **5.9 GB RAM**, AMD Radeon Vega 8 (integrated; GPU disabled for TensorFlow via `CUDA_VISIBLE_DEVICES=-1`, predictor.py:2), D: drive 200 GB (151 GB free), Windows 11 Home 10.0.26300.
**5.5 Software (installed in backend/.venv; requirements.txt in brackets if different)**
| Item | Version |
|---|---|
| Python | 3.11.15 |
| Flask / Flask-SQLAlchemy / Flask-JWT-Extended / Flask-Limiter | 3.0.0 / 3.1.1 / 4.6.0 / 3.5.0 |
| XGBoost | 2.0.3 |
| scikit-learn | **1.9.1** (requirements.txt says 1.4.0; PROGRESS.md notes retraining under 1.9.1) |
| TensorFlow / Keras | 2.15.0 / 2.15.0 |
| imbalanced-learn | **0.14.2** (req: 0.12.0) |
| NumPy / pandas / pyarrow | 1.26.4 / **2.3.3** (req 2.2.0) / 16.1.0 (req >=15.0.0) |
| SHAP | **0.51.0** (req >=0.45.0) |
| NetworkX / bcrypt / cryptography / requests / python-whois | 3.2.1 / 4.1.2 / 42.0.0 / 2.31.0 / 0.9.4 |
| Waitress / pytest | 3.0.2 / 9.1.1 |
Flutter 3.41.6 / Dart 3.11.4 [README_APK.md]. DB: SQLite.
**5.6 Communication:** browser/Flutter -> HTTPS (Cloudflare tunnel) or HTTP LAN -> Flask REST (JSON, JWT bearer; optional HMAC `X-Signature`) -> in-process calls to predictor/layers -> SQLAlchemy -> SQLite; background threads for email send and Telegram polling [api.py; app.py; telegram_bot.py].
**5.7 Functional requirements (all verified by code + tests)**
- FR-01 Dual-OTP signup (email then Telegram link/code) — Implemented [tests/test_otp_e2e.py, scripts/smoke_test.py]
- FR-02 Separate login and payment 6-digit PINs, weak-PIN rejection — Implemented [security.py is_weak_pin; test_part3_dual_pin.py]
- FR-03 Login lockout 5 attempts/15 min; payment lockout 3/30 min — Implemented [user_manager.py:197, 256]
- FR-04 New-device login needs both codes; known device trusted 30 days — Implemented [test_part8]
- FR-05 Payments only to registered ACTIVE users (404 `USER_NOT_REGISTERED`) — Implemented [test_part11]
- FR-06 Fraud scoring: 7 layers + 7 models + stacking + override rules — Implemented [fraud_detection.py; fusion.json]
- FR-07 REQUIRES_2FA holds payment PENDING until both codes verify; 3 wrong -> cancel; 3 cancelled -> freeze — Implemented [test_part9]
- FR-08 "Was this you?" alert + single-use 24 h freeze link — Implemented [test_part13; smoke_test]
- FR-09 PIN change and forgot-PIN (dual OTP), 24 h reduced limits (10,000/txn, 25,000/day) — Implemented [config.py:74-75; test_part10]
- FR-10 Account delete (dual OTP) with ledger anonymisation — Implemented in API; **no web button** — Partial
- FR-11 Demo balance reset once per hour — Implemented [test_part15]
- FR-12 SHAP top-5 explanation per decision — Implemented [predictor.py; test_part25]
- FR-13 Admin portal: stats, transactions, alerts, users, lock/unlock, model metrics, drift, retrain, CSV export — Implemented
- FR-14 Website trust check (Safe Browsing, OpenPhish, WHOIS, SSL, look-alike) — Implemented (OpenPhish key = MOCK -> simulation only)
- FR-15 Geofence and impossible-travel (>900 km/h) — Implemented [geofence.py]
- FR-16 Per-channel OTP delivery status + resend (30 s cooldown) — Implemented
- FR-17 Flutter Sender/Receiver apps — **Partial**: source done, `flutter analyze` 0 errors, **APK not built** (no JDK) [logs/flutter_build_sender.log]
- FR-18 Optional Turnstile CAPTCHA — Partial (honeypot + timing used; keys empty)
- Item 30 "Optional extras (ablation, champion-challenger, GraphSAGE)" — **Planned** [PROGRESS.md]

---
## CHAPTER 6: DESIGN
**6.1 Architecture (Fig 6.1)** — order of data flow for one payment [api.py `/api/transfer`; fraud_detection.py]:
1. Client -> `/api/transfer` (JWT + payment PIN + amount) -> amount validated (positive, <= 1 crore, 2 decimals).
2. Payee lookup by blind hash; unregistered -> 404 before scoring.
3. `global_fraud_detector.detect()` builds 22 features (`feature_builder.py`), runs 7 models (`predictor.py`), then layers 1-7.
4. Weighted layer sum -> override rules -> final score -> verdict (thresholds below).
5. APPROVED: debit/credit in one SQL transaction. REQUIRES_2FA: PENDING + dual OTP. BLOCKED: freeze link + alerts.
6. Audit log + baseline/trusted-payee update; response includes SHAP reasons.
Mermaid exists in docs/PROJECT_RESEARCH_REPORT.md:64-112 (older; verify against this list).
**6.2 GUI:** screenshot file names NOT PROVIDED (none exist).
**6.3 Sequence (Fig 6.4) steps:** see 6.1 steps 1-6, actors User, Web/App, API, Fraud Engine (models + layers), DB, OTP channels (SMTP, Telegram).
**6.4 Components**
| Component | Purpose | Input | Output | Depends on |
|---|---|---|---|---|
| api.py | REST endpoints | HTTP JSON | JSON | all below |
| fraud_detection.py | 7 layers + fusion + overrides | txn dict | verdict, score, flags | predictor, feature_builder, social_graph, geofence, website_trust, DB |
| predictor.py | model inference + SHAP | 22 features | per-model probs, top-5 | models/*.pkl,*.keras |
| otp_service.py | issue/verify OTP (HMAC hashed) | user, purpose | code, delivery status | email_sender, telegram_bot |
| email_sender.py / telegram_bot.py | channels | message | delivery status | SMTP / Telegram API |
| user_manager.py | auth, lockouts, devices | credentials | session/user | security, DB |
| security.py | encryption, hashing, PIN rules, tokens | values | ciphertext/hash | config |
| website_trust.py | domain reputation | domain | score, verdict | Safe Browsing, WHOIS, DNS |
| geofence.py, social_graph.py, ubts.py | location, mule graph, baselines | coords / txns | scores | DB |

---
## CHAPTER 7: IMPLEMENTATION
**7.1 Tools:** Python 3.11.15, Flask 3.0.0, TensorFlow/Keras 2.15.0, XGBoost 2.0.3, scikit-learn 1.9.1, SHAP 0.51.0, pytest 9.1.1, Waitress 3.0.2, Flutter 3.41.6; Git (135 commits); IDE: NOT PROVIDED; visualization tools: NOT PROVIDED (charts.js uses Chart.js via CDN, base.html:14).
**7.2 Technologies and roles:** XGBoost/RandomForest/LogReg (tabular supervised), IsolationForest and Autoencoder (anomaly), DNN with focal loss, LSTM with attention (sequence), stacking meta-classifier + isotonic calibration, SHAP TreeExplainer, SMOTE vs class weights, Fernet AES encryption, bcrypt, HMAC-SHA256 OTP hashing, JWT.
**7.3 Workflow:** same as 6.1.
**7.4 Algorithms and parameters** [backend/model_trainer.py; train_all_models.py]
| Model (class) | Hyperparameters (file:line) |
|---|---|
| XGBoost `XGBClassifier` | n_estimators 150, max_depth 6, learning_rate 0.08, subsample 0.8, colsample_bytree 0.8, random_state 42, n_jobs 1 (model_trainer.py:142-149) |
| Random Forest `RandomForestClassifier` | n_estimators 100, max_depth 12, min_samples_split 5, random_state 42 (155-160) |
| Logistic Regression | max_iter 1000, solver lbfgs, class_weight balanced (165-168) |
| Isolation Forest | n_estimators 100, contamination 0.05 (175-177) |
| Neural Network (Keras) | Dense 128-ReLU, Dropout 0.3, Dense 64, Dropout 0.2, Dense 32, sigmoid; BinaryFocalLoss gamma 2.0 alpha 0.25 (81-92); epochs 15, batch 512, EarlyStopping val_auc patience 4 (train_all_models.py:378-387) |
| LSTM | LSTM 64 (return seq) -> Dropout 0.2 -> LSTM 32 -> attention -> Dense 16 -> sigmoid; 5 timesteps; epochs 12, batch 512 (model_trainer.py:97-105; train_all_models.py:405-418) |
| Autoencoder | 22-128-64-32-16-32-64-128-22, MSE reconstruction (117-130) |
- Features (22, in order): amount, hour, day_of_week, is_holiday, is_weekend, amount_vs_avg_ratio, amount_vs_std_zscore, txn_count_last_hour, txn_count_last_24h, new_payee_flag, new_payee_pct_last_7days, days_since_account_created, known_device_flag, device_change_count_30days, payee_incoming_txn_count, payee_account_age_days, is_scam_upi, distance_from_home_km, is_impossible_travel, payee_graph_centrality, is_mule_candidate, is_high_risk_mcc [CONTEXT.md]. Target: fraud label.
- Split: time-ordered 70% / 15% / 15% per source (train_all_models.py:109-110); 20,000 rows sampled per source (line 85); totals 56,000 / 12,000 / 12,000 [metrics `_metadata`]. Test = 9,000 real-data rows + 3,000 simulator rows [metrics `real_subset`/`simulator_subset`].
- Imbalance: SMOTE (random_state 42) vs class weights compared on validation PR-AUC; SMOTE selected (metrics `_metadata.rebalancing_used`; train_all_models.py:204-231). SMOTE never applied to val/test.
- Fusion: stacking meta-classifier on 13 features (7 model probabilities + 6 layer scores), isotonic calibration; static weighted fusion kept for comparison [fusion.json]. Stacking: PR-AUC 0.3562, recall@1%FPR 0.1605, Brier 0.0528; static: 0.1801, 0.1118, 0.0716.
- **Final score formula** [fraud_detection.py:519-525]: `0.38*behavioral + 0.04*velocity + 0.03*flow + 0.28*payee + 0.15*compromise + 0.10*amount + 0.02*website_trust`, then hard overrides.
- **Verdict thresholds** [fraud_detection.py:578-589]: 0-39 APPROVED; 40-59 APPROVED_WITH_WARNING; 60-79 REQUIRES_2FA; 80-100 BLOCKED. Velocity burst (>3 txns/10 min) forces step-up (570-575).
- **Override rules** [fraud_detection.py:16-51, 105-127]: scam blacklist -> BLOCKED min 90; QR payee mismatch -> BLOCKED min 85; impossible travel AND new device -> BLOCKED min 85; website flagged by Safe Browsing/OpenPhish -> BLOCKED min 85. (PROJECT_HANDOFF says 8 rules; only 4 were read here, Q7.1.)
- **Per-layer points** (as documented in PROJECT_HANDOFF.md §3.1 and spot-checked in code lines 303, 311, 347, 471): L1 base = ensemble_prob*100, +60 cap if z>3, +15 for 00:00-05:59, +10 first txn, +20 weekend amount>10,000; L2 >3 txns/10 min +80, >10/h +60, >30/24h +80; L3 mule flag, centrality>0.85 +40; L4 new payee +25, payee <7 days +25 (website_trust code differs, see Conflicts); L5 new device+unknown payee +60, impossible travel +50, geofence >500 km +40 / >100 km +20; L6 >10x avg +90, >5x +70, structuring +15; L7 see Conflicts. Line-by-line verification of every layer: not done (Q7.2).
- Website trust (code, website_trust.py): look-alike/typosquat +40, no valid SSL +25, domain <7 days +40 / <30 days +20, Safe Browsing hit +50, OpenPhish +50, domain does not exist +40; verdict FRAUD>=80, SUSPICIOUS>=60, CAUTION>=40.
- Pseudocode: derive from 6.1; not provided as a document.
**7.5 Modules** (file | key functions | what)
| Module | File | Key items |
|---|---|---|
| API | backend/api.py | register/login/OTP/PIN/transfer/freeze/resend/health routes |
| App + admin | backend/app.py | create_app, admin gate, admin APIs |
| Engine | backend/fraud_detection.py | FraudDetector.detect, evaluate_overrides |
| Models | backend/predictor.py, model_trainer.py, train_all_models.py, calibrate_and_tune.py, learned_fusion.py | inference, training, calibration, stacking |
| Data | backend/data_loader.py, upi_simulator.py, feature_builder.py | loaders, simulator, 22-vector |
| OTP/channels | otp_service.py, email_sender.py, telegram_bot.py, otp_doctor.py | issue/verify, SMTP, bot polling, diagnostics |
| Security | security.py, user_manager.py, rate_limiter.py, audit_logger.py | crypto, PINs, lockouts, limits |
| Signals | geofence.py, social_graph.py, website_trust.py, qr_parser.py, ubts.py | location, mule graph, web trust, QR, baselines |
| Hosting | serve.py, start_mlbfd.bat | Waitress, tunnel |
Total ~33,500 Python lines across root and backend (measured; includes scripts).

---
## CHAPTER 8: TESTING
**8.1 Types actually done:** unit and integration tests (pytest), API tests through the Flask test client, end-to-end smoke test, a 21-scenario scripted suite, latency benchmark, live external checks (SMTP, Telegram API, Safe Browsing, Firebase auth), static checks (`compileall`, `flutter analyze`).
**8.2 Tools/environment:** pytest 9.1.1, Flask test client, unittest.mock; scripts/smoke_test.py, scripts/static_check.py, latency_benchmark.py. Environment = machine in 5.4, Python 3.11.15, CPU only, throw-away SQLite DB (conftest.py).
**Test counts:** last full run **206 passed** (2026-10-31, tool output); 29 test files.
**8.3 Test cases (Table 8.1)** — all rows below were executed; outputs from scripts/smoke_test.py (14/14 PASS, 2026-10-31) unless noted
| ID | Scenario | Input | Expected | Actual | Status |
|---|---|---|---|---|---|
| TC-01 | Register user A with dual OTP | valid details, email code, Telegram link+code | ACTIVE account | ACTIVE | PASS |
| TC-02 | Register user B | same | ACTIVE | ACTIVE | PASS |
| TC-03 | Login on known device | correct PIN, trusted device | LOGGED_IN, no OTP | LOGGED_IN | PASS |
| TC-04 | Login on new device | correct PIN, new device | OTP_REQUIRED, both codes verify | tokens issued | PASS |
| TC-05 | Normal transfer | Rs 1,500 A->B, APPROVED verdict | A 98,500 / B 101,500 | same | PASS |
| TC-06 | Unregistered receiver | unknown UPI | 404 USER_NOT_REGISTERED | 404 | PASS |
| TC-07 | High-risk transfer | REQUIRES_2FA, both codes | COMPLETED | COMPLETED | PASS |
| TC-08 | PIN change | dual OTP | new PIN works | works | PASS |
| TC-09 | Forgot-PIN + reduced limit | reset, then Rs 15,000 | refused (limit 10,000/txn) | refused | PASS |
| TC-10 | Blocked transfer + freeze link | BLOCKED verdict | freeze link freezes; reuse rejected | as expected | PASS |
| TC-11 | Balance reset | JWT, twice | 200 then 429 | 200, 429 | PASS |
| TC-12 | Login lockout | 6 wrong PINs | locked at 5th | statuses 401x4, 403, 403 | PASS |
| TC-13 | Rate limit on /api/login | 12 requests | 429 appears | first 429 at request 11 | PASS |
| TC-14 | Account delete + ledger anonymised | dual OTP | no trace of user in ledger | none | PASS |
| TC-15 | Negative/NaN/inf/huge amount | 8 invalid values | 400 INVALID_AMOUNT | 400 each | PASS (pytest) |
| TC-16 | Admin API via tunnel headers | CF-Connecting-IP | 403 | 403 | PASS (pytest) |
| TC-17 | Live email send (Brevo) | otp_doctor --email-test | accepted | accepted 2026-11-02 | PASS |
| TC-18 | Live Safe Browsing | known malware test URL | flagged | MALWARE | PASS |
| TC-19 | Telegram on a real phone (Start + contact + message) | otp_doctor --link-telegram | message received | not run | **NOT EXECUTED** |
| TC-20 | Flutter APK build | flutter build apk --release | APK | failed: JAVA_HOME not set | **FAILED** |
| TC-21 | App flows on a real device / emulator | sign-up, payment | works | not run | **NOT EXECUTED** |

---
## CHAPTER 9: RESULTS & PERFORMANCE ANALYSIS
**9.1 Screenshots:** none available (Q9.1).
**9.2 Performance** — held-out test split, 12,000 rows, default 0.5 model threshold [backend/models/mlbfd_mega_metrics.json]. Confusion matrix = [[TN, FP], [FN, TP]].
| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC | Recall @1% FPR | Confusion matrix |
|---|---|---|---|---|---|---|---|---|
| XGBoost | 0.8735 | 0.2708 | 0.4035 | 0.3241 | 0.7946 | 0.3442 | 0.1707 | [[10118, 980], [538, 364]] |
| Random Forest | 0.8133 | 0.1846 | 0.4346 | 0.2592 | 0.7883 | 0.2954 | 0.1397 | [[9367, 1731], [510, 392]] |
| Logistic Regression | 0.6100 | 0.1359 | 0.7816 | 0.2315 | 0.7692 | 0.3093 | 0.1386 | [[6615, 4483], [197, 705]] |
| Isolation Forest | 0.8397 | 0.1057 | 0.1519 | 0.1247 | 0.5899 | 0.1040 | 0.0277 | [[9939, 1159], [765, 137]] |
| Neural Network | 0.9313 | 0.9643 | 0.0898 | 0.1643 | 0.8138 | 0.3603 | 0.1851 | [[11095, 3], [821, 81]] |
| LSTM | 0.9321 | 0.9888 | 0.0976 | 0.1776 | 0.8287 | 0.3769 | 0.1885 | [[11097, 1], [814, 88]] |
| Autoencoder | 0.9256 | 0.9091 | 0.0111 | 0.0219 | 0.5151 | 0.1769 | 0.1075 | [[11097, 1], [892, 10]] |
- 902 frauds in 12,000 test rows (from confusion matrices). Accuracy is misleading here: NN/LSTM reach ~93% accuracy while catching ~9-10% of fraud.
- Real-data subset vs simulator subset (recall @1% FPR, XGBoost): 0.0799 real vs 0.7778 simulator [metrics `real_subset`/`simulator_subset`]. The simulator is synthetic; report both.
- Stacking ensemble: PR-AUC 0.3562, recall@1%FPR 0.1605 [fusion.json]; ACCURACY_REPORT.md §1 lists holdout ROC-AUC 0.8342, PR-AUC 0.3840, recall@1%FPR 17.07%.
- Calibrated operating thresholds at <=1% FPR (test recall) e.g. XGBoost 0.1109, LSTM 0.1364 [operating_thresholds.json].
- **21-scenario suite: 21/21 matched, 100% recall** [ACCURACY_REPORT.md §1, §4]. These are 21 scripted payments, not a statistical result: report as a functional check only.
- Layer-wise results: no per-layer accuracy exists. Only per-category outcomes of the 21 scenarios (ACCURACY_REPORT.md §4).
- **Latency (detect(), 200 iterations, CPU)** [ACCURACY_REPORT.md "Latency"]: before p50 304.97 / p95 348.57 / p99 374.06 ms (3.19 txn/s); after p50 63.69 / p95 77.78 / p99 86.90 ms (14.40 txn/s). SHAP adds mean 4.85 ms. Older harness numbers (p50 497.91 ms, p95 790.93, p99 1257.15) are from a different run including DB writes.
- Charts that exist: none as files; admin portal draws charts live (charts.js). Figure files NOT PROVIDED.
- Datasets (DATA_AUDIT.md §2): PaySim 6,362,620 rows, 0.1291% fraud; IEEE-CIS train_transaction 590,540 rows, 3.4990% fraud; BAF Base and Variants I-V 1,000,000 rows each, ~1.103% fraud; synthetic_mobile_money 1,720,181 rows, 10.2035% fraud.

---
## CONCLUSION AND SCOPE FOR FUTURE WORK
- **Achieved (verified):** working end-to-end system with dual-channel OTP, 7-layer scoring + 7 models + stacking, admin portal, 206 passing tests, smoke 14/14, p50 63.7 ms.
- **Key results:** table 9.2; recall@1% FPR 0.16-0.19 for the best models on mixed test data; 100% on 21 scripted scenarios.
- **Limitations (documented):** low recall on real benchmark rows (0.0799 for XGBoost at 1% FPR, handoff §15); public data lacks UPI features; one scenario sample each; APK not built; OpenPhish key not set; leaked/guessable secret key (rotation pending, ROTATE_SECRETS.md); no production/real-money use.
- **Future (not done):** ablation study, champion-challenger, GraphSAGE [PROGRESS.md Part 30]; expand scenarios to 100+ per pattern [handoff §15]; web account-delete button; Firebase push notifications (key stored, no code); live-device testing; source-aware imputation for real-data features [handoff §15].

## BIBLIOGRAPHY
NOT PROVIDED. No papers attached (Q3.1). Dataset sources can be cited once you supply their official references.

## PUBLICATION DETAILS
Paper title, conference/journal, organiser, dates, mode, location, session, status: NOT PROVIDED. (docs/PROJECT_RESEARCH_REPORT.md is titled "for IEEE Publication" but contains no submission details.)

---
## CONFLICTS BETWEEN DOCS AND CODE (code followed)
- scikit-learn 1.4.0 / imbalanced-learn 0.12.0 / pandas 2.2.0 in requirements.txt vs installed 1.9.1 / 0.14.2 / 2.3.3.
- docs/PROJECT_RESEARCH_REPORT.md:168-172 says 16 GB RAM, 8 cores / 16 threads; measured machine is 5.9 GB RAM, 4 cores / 8 threads.
- docs/PROJECT_RESEARCH_REPORT.md:191 lists an IEEE-CIS sub-sample of 28,163 rows (older design); the current honest pipeline uses 20,000 rows per source, 56,000/12,000/12,000 split.
- PROJECT_HANDOFF.md §3.1 Layer 7 (+100 Safe Browsing, +30 age<30d, +40 SSL) differs from website_trust.py (+50, +20/+40, +25).
- PROJECT_HANDOFF.md says 8 override rules; 4 were verified in fraud_detection.py:16-51.
- Older ACCURACY_REPORT.md section 2 latency (p50 497.91 ms) vs measured detect() latency 63.69 ms (different harness).
- Scenario suite "100%" and holdout "17.07%" recall@1%FPR measure different things.

---
## MISSING INFORMATION (questions for you)
**Prelim:** Q0.1 team names + USNs; Q0.2 guide name/designation; Q0.3 department, college, academic year, subject code; Q0.4 HOD, Principal, Director, coordinator names.
**Ch 1:** Q1.1 your own motivation and research-gap statement; Q1.2 official objectives (3-5).
**Ch 2:** Q2.1 process model and phases; Q2.2 each member's role and contribution, guide, reviewer.
**Ch 3:** Q3.1 the research papers to cite (title/authors/year/venue/result) and the literature-review figure.
**Ch 4:** Q4.1 planned schedule (weeks) and your risk table with likelihood/impact.
**Ch 5:** Q5.1 minimum/recommended hardware; IDE used; whether per-screen control lists are needed.
**Ch 6/9:** Q6.1 / Q9.1 screenshots (input, legitimate, fraud, OTP, admin pages) with file names.
**Ch 7:** Q7.1 confirm the 8 override rules (4 verified); Q7.2 whether per-layer point rules need line-by-line verification; visualization/IDE tools.
**Ch 8:** Q8.1 which tests you want shown (all 206 pytest ones are real; a full ID table was not extracted); Q8.2 run TC-19 and TC-21 if they must be in the report.
**Publication:** Q10.1 all fields.
**Template:** answered (read). Q11.1 confirm whether your college/branch/subject code/academic year are the same as the template's (BGSCET, AI&ML, BAI786, 2025-26) or different.

## READINESS
| Chapter | Status |
|---|---|
| Preliminary pages | Missing (format known) |
| 1 Introduction | Partial |
| 2 Project organization | Missing |
| 3 Literature review | Missing |
| 4 Project management | Partial (actual dates only) |
| 5 SRS | Ready (except min/recommended hardware) |
| 6 Design | Partial (no screenshots) |
| 7 Implementation | Ready (override rules and per-layer lines partly verified) |
| 8 Testing | Ready (2 tests NOT EXECUTED) |
| 9 Results | Partial (no figures/screenshots; metrics Ready) |
| Conclusion | Ready |
| Bibliography | Missing |
| Publication details | Missing |

---
## TEMPLATE FORMAT NOTES (from "Major project REPORT.pdf", format only)
- Order: Title page, Certificate, Abstract (page i), Acknowledgments, List of Figures, List of Tables, Contents, Chapters 1-9, Conclusion (+ "Scope for Future Work" as a numbered list), Bibliography, then the attached publication/paper pages.
- Template list of figures: 3.1 literature-review workflow, 4.1 Gantt chart, 6.1 architecture, 6.2-6.3 user interface, 6.4 sequence diagram, 9.x result screenshots and charts. Tables: 2.1 roles, 4.1 risks, 8.1 test cases, 9.1 results explanation. (Your prompt's numbering matches.)
- 2.2 Roles: a short paragraph (e.g. "four student members and two faculty mentors") then Table 2.1 Member name | Role | Responsibilities.
- 3.2 Related Works is written as **one narrative paragraph per paper** ("Author et al. [n] presents ... limitation ... future work"), not a table; a table can be used as the source for those paragraphs. 3.3 Conclusion of Survey follows.
- 4.1 Schedule: intro text + "10-week plan" Gantt figure (Fig 4.1); 4.2 Risk table: Risk Description | Likelihood | Impact | Mitigation Strategy.
- 6.4 Component Design is narrative: "Component (Technology): description" per component, introduced by the number of major components.
- 8.3 Test table columns: Test Case ID | Test Scenario | Input | Expected output | Actual output | Status.
- 9.2 explains each chart with axes and a "what each bar means" table (Table 9.1). For MLBFD the chart candidates (must be created from the measured metrics; none exist as images): per-model ROC-AUC / PR-AUC / recall@1%FPR bar chart, confusion matrices, latency before/after bar chart.
- Bibliography: IEEE numbered, in order of citation in Chapter 3.
- Page footer style: "Dept of <branch> <year>" and a running project title.
