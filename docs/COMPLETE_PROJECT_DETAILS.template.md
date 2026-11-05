# MLBFD: Complete Project Details

**Machine Learning-Based Financial Fraud Detection** for UPI-style payments
Document built 2026-11-05 from the project source, tests, generated tables and the session history. No secret value (passwords, tokens, keys) appears in this document; settings are listed by name only.

**Contents:** 1 Summary · 2 Binding policies · 3 Feature catalogue · 4 Architecture · 5 User journeys · 6 Fraud engine · 7 Data and ML · 8 Security · 9 OTP system · 10 Interfaces · 11 API reference · 12 Database · 13 Configuration · 14 Deployment and operations · 15 Scripts and tools · 16 Testing · 17 Performance · 18 History and fixes · 19 Limitations and open items · 20 File inventory · 21 Dependencies · 22 Glossary

---

# 1. Project Summary

- **What it is:** a complete demo payment platform in which every payment is risk-scored in real time by seven ML/DL models and seven rule layers. Risky payments are held until the user enters **two** codes (email and Telegram). Money is virtual (100,000 INR credited on activation).
- **Name:** MLBFD everywhere (code, UI, docs). UPI IDs have the form `<10-digit phone>@mlbfd`.
- **Components:** Flask REST API + SQLAlchemy/SQLite, a web user portal, a web admin portal, two Flutter apps (Sender, Receiver), Telegram bot, SMTP email, Waitress server, optional Cloudflare tunnel.
- **Size:** about 33,500 lines of Python (measured across root and backend), 62 API routes, 17 database tables, 153 tracked source files reviewed, 196 test functions (206 test cases with parametrisation).
- **Development window:** 2026-10-15 to 2026-11-05 (git history: 135+ commits by a single author).
- **Free-services-only policy:** no paid APIs. Brevo/Gmail SMTP, Telegram Bot API, Google Safe Browsing, Nominatim, OpenPhish feed, Cloudflare tunnel are all free tiers.
- **Honest-metrics policy:** the evaluation uses a time-ordered split with no leakage; low recall on real data is reported openly (section 7).

---

# 2. Binding Policy Decisions

1. OTP channels are **email and Telegram bot only. Both are required.** No SMS, no Twilio, no PyOTP.
2. OTP is required at: signup, login from a new device, fraud step-up (REQUIRES_2FA), PIN change, PIN reset, account delete.
3. **Separate login PIN and payment PIN**, both exactly 6 digits, and they must differ. Weak PINs (repeated or sequential digits, a blacklist) are rejected.
4. Payments go **only to registered, ACTIVE users**. An unknown payee gets HTTP 404 `USER_NOT_REGISTERED` before any scoring.
5. Project name **MLBFD** everywhere.
6. Metrics are reported honestly (no label leakage, no inflated numbers).
7. Free services only.
8. Secrets live only in `.env` (never committed, never logged, never printed). The app reads only `.env`, never `.env.example`.

---

# 3. Complete Feature Catalogue

Status key: **Implemented** (works and tested), **Partial**, **Planned**.

## 3.1 Accounts, signup and identity
| Feature | Details | Status |
|---|---|---|
| Three-step signup wizard (web) | details, then email code, then Telegram link and code; account becomes ACTIVE only after both codes | Implemented |
| Telegram linking | single-use 10-minute link token, `/start <token>`, "Share Registered Contact" button; contact must belong to the sender (`contact.user_id == from.id`) and its phone must equal the registered phone (E.164 compare) | Implemented |
| Account activation | status PENDING to ACTIVE, balance 100,000 INR, UPI ID `<phone>@mlbfd` generated | Implemented |
| PENDING cleanup | unverified signups purged after 30 minutes; their IP-log rows removed | Implemented |
| Encrypted personal data | phone, email, UPI ID and Telegram chat ID are Fernet (AES) encrypted; blind HMAC hashes allow lookup | Implemented |
| Security question | stored as bcrypt hash of the answer; used in forgot-PIN | Implemented |
| Privacy consent | consent flag and timestamp stored at signup | Implemented |
| Account delete | dual OTP + payment PIN; PII scrubbed, ledger rows anonymised (`deleted_user@mlbfd`) | Implemented in API; **no web button** (Partial) |
| Demo banner | "MLBFD demo - virtual money only" on all pages | Implemented |
| Balance reset | restores 100,000 INR, once per hour per user, JWT required | Implemented |

## 3.2 Authentication and sessions
| Feature | Details | Status |
|---|---|---|
| Login with login PIN | identifier can be user ID, UPI ID or phone; generic error messages (no user enumeration) | Implemented |
| Lockouts | login: 5 wrong PINs lock 15 minutes; payment PIN: 3 wrong lock 30 minutes; stored in the database | Implemented |
| Device binding | `X-Device-ID` header / `device_id`; a device is trusted for 30 days; unknown or expired device requires both OTP codes | Implemented |
| JWT | access token 1 hour, refresh token 30 days, token blocklist table, `tokens_revoked_at` revokes all older tokens | Implemented |
| Logout and refresh | `/api/logout`, `/api/refresh` | Implemented |
| PIN change | verify current PIN, then dual OTP, then confirm; revokes tokens | Implemented |
| Forgot PIN | generic start (no enumeration), dual OTP verify, security-question answer, 10-minute reset token, new PIN, 24-hour reduced limits, other devices cleared, JWTs revoked; max 3 requests per hour | Implemented |
| Reduced-limit mode | after PIN reset for 24 hours: Rs 10,000 per transaction, Rs 25,000 per day | Implemented |
| Daily limit | per-user `daily_limit` (default Rs 50,000) with spent-today tracking | Implemented |

## 3.3 Payments
| Feature | Details | Status |
|---|---|---|
| Transfer | amount validated: finite, positive, at most Rs 1 crore, 2 decimals; payment PIN checked before scoring | Implemented |
| Payee lookup | `/api/lookup_payee` resolves UPI, phone or user ID; self-transfer blocked | Implemented |
| Verdicts | APPROVED, APPROVED_WITH_WARNING, REQUIRES_2FA, BLOCKED | Implemented |
| Atomic money movement | conditional SQL UPDATE debit + credit in one commit (no double spend, no half transfer) | Implemented |
| Step-up hold | REQUIRES_2FA is saved as PENDING (10-minute hold), dual OTP, 3 wrong attempts cancel it, 3 cancelled payments freeze the account | Implemented |
| "Was this you?" alert | on BLOCKED or REQUIRES_2FA: email + Telegram alert with a signed single-use 24-hour freeze link | Implemented |
| Freeze and unfreeze | freeze via link; unfreeze only through forgot-PIN or an admin | Implemented |
| Trusted payees | add, list, remove; counts and totals tracked; payee becomes trusted after 3 payments | Implemented |
| Transaction history | sent and received; location and area name stored | Implemented |
| What-if preview | `/api/predict-secure` scores without saving | Implemented |
| Scam report and feedback | `/api/report-scam`, `/api/feedback` | Implemented |
| QR parsing | UPI QR parser with payee/amount mismatch detection | Implemented |
| Website check | `/api/website-check/<domain>`; see 6.7 | Implemented |

## 3.4 Fraud detection
| Feature | Status |
|---|---|
| 22 canonical features with a SHA-256 order guard | Implemented |
| 7 models: XGBoost, Random Forest, Logistic Regression, Isolation Forest, Deep Neural Network (focal loss), LSTM with self-attention, Deep Autoencoder | Implemented |
| 7 rule layers with static weights and a stacking fusion meta-classifier with isotonic calibration | Implemented |
| 4 verified hard override rules (scam blacklist, QR mismatch, impossible travel + new device, flagged website); the project notes list 8 | Implemented (4 verified) |
| SHAP top-5 feature explanations and a plain-language reason | Implemented |
| Behavioural baselines per user (running mean, std, usual hours, devices, payees, MCC history) | Implemented |
| Velocity bursts, flow/mule graph (NetworkX), geofence and impossible travel (900 km/h), amount deviation, structuring boundaries, odd-hour rules | Implemented |
| Website trust: Safe Browsing, OpenPhish, WHOIS age, SSL, look-alike brands, nonexistent domain | Implemented (OpenPhish key not set: keyword simulation) |
| Model drift page (PSI, amount deviation, block ratio, KS test) | Implemented |
| Model retraining from the admin page | Implemented |
| Ablation, champion-challenger, GraphSAGE | **Planned** (deferred) |

## 3.5 Abuse protection and privacy
Honeypot field, minimum 3-second form-fill timing token, disposable-email blocklist, 3 signups per IP per day, optional Cloudflare Turnstile (honeypot + timing fallback when keys are empty), per-route rate limits, OTP issue limits, audit log of every action.

## 3.6 Admin portal (web)
Overview (volume, transaction count, average risk, active fraud rate, charts), Transactions (filter by verdict, sort, details with layer scores and SHAP, NPCI CSV export), Alerts queue (pending 2FA, blocked, cancelled), Users (masked phone/email, balance, status, failed PIN tries, lock/unlock toggle), Model performance (all 7 models, including recall at 1% FPR), Data drift, Retrain button. Admin is open on the server laptop itself; through a tunnel or from another machine it needs `ADMIN_API_TOKEN`.

## 3.7 Mobile apps (Flutter)
Sender app: registration/login (dual-OTP signup, Telegram link polling, new-device login), send money (6-digit payment PIN, risk preview, biometric), OTP screen (email + Telegram codes, per-channel status and resend), history, trusted contacts, analytics, QR generator, server-URL screen. Receiver app: registration/login, balance, receive (QR), history, server-URL screen. **Status: source complete, `flutter analyze` has no errors; the APK has not been built (no JDK installed).**

## 3.8 OTP and notification delivery
Email (SMTP: STARTTLS 587 with automatic SSL 465 fallback, 10-second timeout, one retry) and Telegram (Bot API, long polling) with per-channel delivery status (`sent`, `failed`, `not_linked`, `pending`, `dry_run`), per-channel Resend (30-second cooldown), delivery log file, readiness endpoint, startup warnings.

## 3.9 Operations features
Waitress production server, SQLite WAL, Cloudflare quick tunnel launcher, LAN mode with printed share URL, port-in-use guard, single Telegram poller guard (PID lock with heartbeat), diagnostics (`otp_doctor`), secret scanner, key-rotation script, smoke test, boot check, static checker, profiler.

---

# 4. Architecture

## 4.1 Components
```
 Browser (user portal)       Browser (admin portal)        Flutter apps
        |                            |                          |
        +----------- HTTP(S) JSON / HTML  (JWT bearer) ---------+
                                     |
                    Flask app (backend/app.py, api.py)  <-- Waitress, 8 threads
        +--------------+-------------+----------------+-----------------+
        |              |             |                |                 |
  user_manager    otp_service   fraud_detection    website_trust     audit_logger
  (auth, PINs)    (issue/verify) (7 layers + 7     (Safe Browsing,   rate_limiter
        |              |         models + fusion)   OpenPhish, WHOIS)
        |       +------+-----+        |
        |   email_sender  telegram_bot (polling thread)
        |      (SMTP)       (Bot API)         predictor.py (models, SHAP)
        |                                     feature_builder, social_graph,
        +------------- SQLAlchemy ----------- geofence, ubts, qr_parser
                           |
                  SQLite (WAL)  backend/instance/mlbfd.sqlite3
```

## 4.2 Payment data flow (in order)
1. Client calls `/api/transfer` with JWT, payment PIN, amount, receiver, device ID, location.
2. Amount is validated; payment PIN checked (3 wrong attempts lock 30 minutes).
3. Receiver looked up by blind hash; unregistered gives 404; self-transfer refused.
4. Reduced-limit and daily-limit checks.
5. `detect()` builds the 22 features, runs the 7 models, then layers 1 to 7, fuses, applies overrides.
6. Verdict by score band. APPROVED: debit and credit in one transaction, baselines and trusted payee updated. REQUIRES_2FA: PENDING hold, both OTPs sent, alerts and freeze link. BLOCKED: freeze link and alerts.
7. Audit log entry; response includes verdict, score, layer scores, flags and SHAP reasons plus per-channel delivery status.

## 4.3 Deployment modes
- **Local:** `python serve.py` on `http://localhost:5000`.
- **Same network (free):** the server laptop shares `http://<its LAN IP>:5000`; admin stays on the server laptop (README_LAN.md).
- **Public (free):** Cloudflare quick tunnel printed by `start_mlbfd.bat`; admin needs `ADMIN_API_TOKEN` through the tunnel.

---

# 5. User Journeys (step by step)

## 5.1 Sign up
1. Open `/register`, enter name, user ID, phone, email, login PIN, payment PIN (different), security question and answer, accept consent. Hidden honeypot and a timing token are sent; Turnstile if configured.
2. `/api/register/start` checks abuse rules (honeypot, timing, disposable email, IP quota 3/day), validates PINs/phone/email, creates a PENDING user and sends the **email** code.
3. If the email cannot be delivered the pending account is rolled back and the page shows the real reason.
4. User enters the email code (`/api/register/verify_email`).
5. Telegram step shows the exact `t.me` link; the user presses Start and shares their contact. The page polls `/api/telegram/status` and sends the Telegram code automatically after linking succeeds.
6. User enters the Telegram code; both verified, the account turns ACTIVE with 100,000 INR and tokens are issued; the device is bound.

## 5.2 Log in
Known device (trusted within 30 days): PIN only. New or expired device: both codes (email and Telegram), then the device is bound. Five wrong PINs lock login for 15 minutes.

## 5.3 Send money
Enter payee UPI, amount and payment PIN. Normal payment completes immediately. A REQUIRES_2FA payment opens the two-code dialog (per-channel status and Resend). Correct codes complete it atomically. A BLOCKED payment is refused and the user gets the freeze link by email and Telegram.

## 5.4 Change PIN / forgot PIN
Change: current PIN, new PIN, both codes, confirm. Forgot: enter user ID, both codes, security answer, new PIN; JWTs are revoked, other devices cleared, 24-hour reduced limits apply.

## 5.5 Freeze link
The alert contains a link valid for 24 hours and usable once. Opening it freezes the account. Unfreeze needs forgot-PIN or an admin.

## 5.6 Delete account
Payment PIN plus both codes; personal data scrubbed and the ledger anonymised.

## 5.7 Admin
Open `/admin` on the server laptop, review alerts, lock or unlock a user (unlock clears every lockout; pending signups cannot be toggled), view model metrics, retrain, export the NPCI CSV.

---

# 6. Fraud Detection Engine

## 6.1 The 22 features
`amount`, `hour`, `day_of_week`, `is_holiday`, `is_weekend`, `amount_vs_avg_ratio`, `amount_vs_std_zscore`, `txn_count_last_hour`, `txn_count_last_24h`, `new_payee_flag`, `new_payee_pct_last_7days`, `days_since_account_created`, `known_device_flag`, `device_change_count_30days`, `payee_incoming_txn_count`, `payee_account_age_days`, `is_scam_upi`, `distance_from_home_km`, `is_impossible_travel`, `payee_graph_centrality`, `is_mule_candidate`, `is_high_risk_mcc`. The order is guarded by a SHA-256 hash.

## 6.2 Seven layers
| Layer | Weight | Points (per project notes; spot-checked in code) |
|---|---|---|
| 1 Behavioural | 38% | base = ensemble probability x 100; z-score above 3 adds 60 (capped); 00:00 to 05:59 adds 15; first transaction adds 10; weekend amount above Rs 10,000 adds 20 |
| 2 Velocity | 4% | more than 3 transactions in 10 min: 80; more than 10 in 1 hour: 60; more than 30 in 24 hours: 80 |
| 3 Flow / network | 3% | mule fan-in candidate: mule score; graph centrality above 0.85: 40 |
| 4 Payee risk | 28% | blacklisted payee: 100; new payee: 25; payee newer than 7 days: 40 (code) ; suffix check ('@mlbfd' now accepted) |
| 5 Device and geo | 15% | new device + unknown payee 60; new device + trusted payee 15; impossible travel above 900 km/h 50; geofence above 500 km 40, above 100 km 20 (skipped if accuracy above 5,000 m); biometric failed 25 |
| 6 Amount | 10% | above 10x average 90; above 5x 70; structuring boundary (9,999 / 99,999) 15 |
| 7 Website trust | 2% | see 6.7 |

## 6.3 Final score and verdict
`final = 0.38*behavioural + 0.04*velocity + 0.03*flow + 0.28*payee + 0.15*compromise + 0.10*amount + 0.02*website_trust`, then hard overrides. Bands: **0-39 APPROVED**, **40-59 APPROVED_WITH_WARNING**, **60-79 REQUIRES_2FA**, **80-100 BLOCKED**. More than 3 transactions in 10 minutes forces step-up.

## 6.4 Override rules (verified in code)
Scam-blacklisted payee: BLOCKED, minimum 90. QR payee mismatch: BLOCKED, minimum 85. Impossible travel and a new device: BLOCKED, minimum 85. Website flagged by Safe Browsing or OpenPhish: BLOCKED, minimum 85.

## 6.5 Models and hyperparameters
| Model | Hyperparameters |
|---|---|
| XGBoost | 150 trees, max depth 6, learning rate 0.08, subsample 0.8, colsample 0.8, random_state 42 |
| Random Forest | 100 trees, max depth 12, min samples split 5 |
| Logistic Regression | lbfgs, max_iter 1000, class_weight balanced |
| Isolation Forest | 100 trees, contamination 0.05 |
| Neural network | Dense 128-64-32 (ReLU, dropout 0.3 and 0.2), sigmoid; focal loss gamma 2.0, alpha 0.25; 15 epochs, batch 512, early stopping on validation AUC (patience 4) |
| LSTM | LSTM 64, dropout 0.2, LSTM 32, self-attention, Dense 16, sigmoid; 5 timesteps; 12 epochs, batch 512 |
| Autoencoder | 22-128-64-32-16-32-64-128-22, MSE reconstruction anomaly score |

## 6.6 Fusion, calibration, explainability
Stacking meta-classifier over 13 inputs (7 model probabilities and 6 layer scores) with isotonic calibration; chosen over static weighting (PR-AUC 0.3562 vs 0.1801; recall at 1% FPR 0.1605 vs 0.1118). A cached SHAP TreeExplainer on XGBoost returns the top-5 signed features (about 5 ms) plus a plain-language reason. Each model has a calibrated operating threshold chosen at 1% false-positive rate on validation.

## 6.7 Website trust
Input is normalised to a hostname; free text (for example a person's name) returns **INVALID**. Checks run in parallel under a 3.5-second budget: look-alike or brand-in-name (for example `awazon.com`, `amazon-login.com`) +40; non-existent domain +40; no valid SSL +25; domain younger than 7 days +40 or 30 days +20; Google Safe Browsing match +50; OpenPhish match +50. Verdicts: FRAUD from 80, SUSPICIOUS from 60, CAUTION from 40, else SAFE. Known brands (Amazon, Google, Flipkart and others) are TRUSTED. Results are cached 6 hours. API errors, quota or timeouts are neutral (a payment is never blocked by an outage). **A "SAFE" result means "no known threat", not a guarantee:** Safe Browsing lists only already-reported sites.

## 6.8 Other signals
Geofence: home location from signup (Leaflet map picker, Nominatim reverse geocoding at 1 request per second, cached, off the payment path). Mule graph: NetworkX directed graph of the last 30 days of approved and completed transactions, cached and rebuilt periodically, with mule fan-in signatures. Baselines (`ubts.py`): running mean and standard deviation (Welford on variance), usual hour, devices, payees, MCC counts.

---

# 7. Data and ML Pipeline

## 7.1 Datasets (DATA_AUDIT.md)
| Dataset | Rows | Fraud ratio |
|---|---|---|
| PaySim (`PS_...log.csv`, also `AIML Dataset.csv`) | 6,362,620 | 0.1291% |
| IEEE-CIS `train_transaction.csv` (+ identity 144,233 rows) | 590,540 | 3.4990% |
| Bank Account Fraud (Base, Variants I-V) | 1,000,000 each | about 1.103% |
| synthetic mobile money | 1,720,181 | 10.2035% |
| MLBFD UPI simulator (`upi_simulator.py`) | generated | about 3.5% target, overlapping distributions, 0.5% label noise |

## 7.2 Training protocol
Chunked parquet generation with strict past-only windows (no leakage), 20,000 rows sampled per source, **time-ordered 70/15/15 split** giving 56,000 train, 12,000 validation, 12,000 test (9,000 real-data rows and 3,000 simulator rows in test). Scaler fitted on training only. SMOTE compared with class weights on validation PR-AUC (SMOTE chosen, applied to training only). Calibration and thresholds fitted on validation only.

## 7.3 Held-out test results (12,000 rows, 902 frauds)
| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC | Recall @1% FPR | Confusion [[TN,FP],[FN,TP]] |
|---|---|---|---|---|---|---|---|---|
| XGBoost | 0.8735 | 0.2708 | 0.4035 | 0.3241 | 0.7946 | 0.3442 | 0.1707 | [[10118,980],[538,364]] |
| Random Forest | 0.8133 | 0.1846 | 0.4346 | 0.2592 | 0.7883 | 0.2954 | 0.1397 | [[9367,1731],[510,392]] |
| Logistic Regression | 0.6100 | 0.1359 | 0.7816 | 0.2315 | 0.7692 | 0.3093 | 0.1386 | [[6615,4483],[197,705]] |
| Isolation Forest | 0.8397 | 0.1057 | 0.1519 | 0.1247 | 0.5899 | 0.1040 | 0.0277 | [[9939,1159],[765,137]] |
| Neural Network | 0.9313 | 0.9643 | 0.0898 | 0.1643 | 0.8138 | 0.3603 | 0.1851 | [[11095,3],[821,81]] |
| LSTM | 0.9321 | 0.9888 | 0.0976 | 0.1776 | 0.8287 | 0.3769 | 0.1885 | [[11097,1],[814,88]] |
| Autoencoder | 0.9256 | 0.9091 | 0.0111 | 0.0219 | 0.5151 | 0.1769 | 0.1075 | [[11097,1],[892,10]] |

Real-data subset versus simulator subset (recall at 1% FPR, XGBoost): 0.0799 versus 0.7778. **Accuracy is misleading here** (the NN and LSTM show 93% accuracy while catching about 9-10% of fraud). The stacking ensemble reports ROC-AUC 0.8342 and PR-AUC 0.3840 on the holdout.

## 7.4 Scenario suite
21 scripted payments (8 legitimate and 13 fraud patterns: cooling-period breach, odd-hour high amount, vishing/ATO surge, extreme deviation, scam blacklist, QR overlay, account takeover, phishing, mule fan-in, velocity burst, smurfing, vishing, identity validation): 21/21 matched. This is a functional check, not a statistical result.

---

# 8. Security Design

| Area | Design |
|---|---|
| Data at rest | Fernet (AES) for phone, email, UPI ID, Telegram chat ID, transaction UPI fields; blind HMAC-SHA256 hashes for lookup; bcrypt (12 rounds) for PINs and security answers |
| OTP | 6 digits from `secrets`, stored as HMAC-SHA256, constant-time compare, single use, 300 s expiry, 3 attempts, 30 s resend cooldown, 5 issues per hour per user+purpose and per IP, never logged |
| Tokens | JWT access 1 h / refresh 30 days, blocklist, revocation by timestamp; freeze tokens and form-timing tokens signed with `itsdangerous` (24 h / 1 h) |
| Admin | `/admin` and `/admin/api` allowed only for direct loopback requests or with `ADMIN_API_TOKEN` (header or HttpOnly cookie); tunnel traffic is never treated as local |
| Client IP | `security.client_ip()` trusts `CF-Connecting-IP`/`X-Forwarded-For` only when the immediate peer is the local tunnel (used by rate limits, OTP limits, signup quota, audit) |
| Money | amount validation, conditional-UPDATE debit and credit in one commit |
| Web | all server text escaped before innerHTML (`esc()`); free text cleaned server side; device IDs and MCC validated |
| Abuse | honeypot, timing token, disposable-email block, IP signup quota, Turnstile optional |
| Secrets | in `.env` only; `.gitignore` covers `.env`, `*.sqlite3`, `models/`, `logs/`, `backups/`, `Datasets/`, `secrets/`; `scripts/secret_scan.py` scans tree and history |
| Request signing | optional HMAC `X-Signature` with a separate `MLBFD_CLIENT_SECRET` (the APK never contains the server key) |
| Telegram | bot cannot message before Start; blocked-bot (403) unlinks; 429 and network errors handled; one poller per machine |

---

# 9. OTP System in Detail

- **Policy:** 300 s expiry, 3 attempts (shared across a dual pair), 30 s resend cooldown per channel, 5 issues per hour per user and purpose, 5 per hour per IP.
- **Purposes:** SIGNUP, LOGIN_NEW_DEVICE, TRANSACTION, PIN_CHANGE, PIN_RESET, ACCOUNT_DELETE.
- **Dual issue:** two independent codes sharing a group ID; Telegram is sent while the email thread runs in parallel; the request waits at most 8 seconds for email and then reports `pending`.
- **Per-channel status:** every OTP response carries `delivery`, for example `{"email":"sent","telegram":"not_linked"}`; `/api/otp/resend` re-issues a single channel.
- **Email:** `smtp_settings()` cleans values and accepts old `SMTP_*` names as fallback; STARTTLS 587 then SSL 465; one authentication mechanism (so a real 535 is visible); no retry after an authentication failure; supports a separate `EMAIL_SMTP_LOGIN` (relays such as Brevo).
- **Telegram:** long-polling thread with crash backoff, PID lock with heartbeat, reloader guard, 409/429/403 handling.
- **Diagnostics:** `backend/otp_doctor.py` (env check, `--email-test`, `--telegram-test`, `--link-telegram`, `--safebrowsing-test`); `logs/otp_delivery.log` (channel, purpose, hashed user, result, exception class, never codes or addresses); `GET /api/health/otp` (admin only); startup banner and background SMTP login probe print warnings.
- **Current email provider:** Gmail with an app password (Brevo was used briefly but blocks changing IP addresses).

---

# 10. Interfaces

## 10.1 Web pages
| Page | File | Purpose |
|---|---|---|
| `/register`, `/user/register` | user_register.html | 3-step signup wizard |
| `/login`, `/user/login` | user_login.html | login, new-device dual OTP, forgot PIN |
| `/`, `/dashboard` | user_dashboard.html | balance, send money with 6-digit PIN pad, history, trusted payees, PIN change, location card, 2FA dialog |
| `/admin` | index.html | overview and charts |
| `/admin/transactions` | transactions.html | all transactions, filters, details, export |
| `/admin/alerts` | alerts.html | alert queue with SHAP reasons |
| `/admin/users` | users.html | user list and lock toggle |
| `/admin/models` | models.html | model metrics and retrain |
| `/admin/drift` | drift.html | drift analysis |
JavaScript: `user.js`, `dashboard.js`, `charts.js`, `otp_status.js` (per-channel status and Resend). CSS: `main.css`, `user.css` (responsive, 360 px tested, touch targets at least 44 px).

## 10.2 Flutter screens
Sender: registration_screen, server_url_screen, home_screen, send_money_screen, otp_screen, transaction_history_screen, trusted_contacts_screen, analytics_screen, qr_generator_screen, biometric_screen; widget `risk_gauge`, `otp_delivery_status`. Receiver: registration_screen, server_url_screen, home_screen, balance_screen, receive_screen, transaction_history_screen. Config: `api_config.dart` (no hard-coded URL; asked on first launch), `app_theme.dart`.

---

# 11. API Reference (generated from the code)

Auth column: "JWT required" means a valid bearer token; "JWT optional" means the route also works for pending signups or uses the body user ID where allowed.

{{INCLUDE:routes.md}}

---

# 12. Database Schema (generated from `backend/database.py`)

{{INCLUDE:schema.md}}

Notes: SQLite file `backend/instance/mlbfd.sqlite3` in WAL mode; optional PostgreSQL if `DATABASE_URL` points to it (falls back to SQLite). Money columns are `Numeric(12,2)`. `otp_codes` holds hashed codes only. The legacy `otp_records` table was removed and `migrate_db.py` drops it only if empty.

---

# 13. Configuration

## 13.1 Settings read by `backend/config.py` (names and defaults, no values)
{{INCLUDE:config.md}}

## 13.2 Variable names in `.env.example`
{{INCLUDE:env_names.md}}

Other names read by the code: `EMAIL_SMTP_LOGIN`, `EMAIL_SMTP_MODE`, `ADMIN_API_TOKEN`, `MLBFD_CLIENT_SECRET`, `FIREBASE_CREDENTIALS_FILE`, `HASH_PEPPER`. `.env` overrides stale Windows variables of the same name; `backend/.env` only fills missing keys. **Restart the server after any `.env` change.**

---

# 14. Deployment and Operations

## 14.1 Start and stop
`start_mlbfd.bat` (or `python serve.py`): refuses to start if port 5000 is taken, prints the banner (local URLs, LAN share URL, OTP warnings), starts Waitress (8 threads, trusts `X-Forwarded-Proto` from the local tunnel) and, if installed, a Cloudflare quick tunnel whose public URL is printed. Closing the window stops everything.

## 14.2 Free same-network setup (4 laptops)
1. Server laptop: allow port 5000 once (administrator PowerShell): `New-NetFirewallRule -DisplayName "MLBFD 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Any`.
2. Stop sleep: `powercfg /change standby-timeout-ac 0` and `powercfg /change standby-timeout-dc 0`; keep it plugged in.
3. Connect all laptops to the same hotspot/Wi-Fi; start the server; share the printed `http://<ip>:5000/user/register`.
4. Others sign up and log in; the server laptop opens `http://localhost:5000/admin`.
5. Each user needs their own email and Telegram. Limits: 3 signups per laptop per day.
6. Troubleshooting: firewall rule, Wi-Fi client isolation, different networks, changed IP, server not running. Browser location is unavailable over plain http on a LAN (a default or manual pin is used).

## 14.3 Public access
Install `cloudflared` (`winget install --id Cloudflare.cloudflared`); the launcher prints the `https://...trycloudflare.com` link. Set `ADMIN_API_TOKEN` to use the admin portal remotely via `/admin?admin_token=<token>` (sets an HttpOnly cookie).

## 14.4 Mobile apps
Sender and Receiver ask for the server URL on first launch. Build needs a JDK (`winget install --id Microsoft.OpenJDK.17`, set `JAVA_HOME`) and, because the Android SDK path contains a space, a junction: `mklink /J C:\AndroidSdk "<sdk path>"`, `setx ANDROID_HOME C:\AndroidSdk`, `flutter config --android-sdk C:\AndroidSdk`. Then `flutter build apk --release`. See README_APK.md.

## 14.5 Backups and secrets
`.env` edits are backed up in `backups/` (ignored by git). Rotate the guessable and git-leaked app keys with `python scripts/rotate_secrets.py --apply --fresh-db` (moves the database to `backups/`, never deletes); see ROTATE_SECRETS.md.

## 14.6 Troubleshooting quick table
| Symptom | Cause and fix |
|---|---|
| No email arrives | run `otp_doctor.py --email-test`; Gmail 535 = wrong address/app password; Brevo 525 = IP not authorised; restart server after `.env` change |
| Telegram code missing | user has not pressed Start and shared contact; polling must be on; only one server may poll (HTTP 409 otherwise) |
| Port 5000 busy | an older server is still running; `Stop-Process` its PID |
| Admin 403 | open it as `http://localhost:5000/admin` on the server laptop, or use the admin token |
| Website check says SAFE | no known threat; typo or new scam domains can still look clean |

---

# 15. Scripts and Tools

| Tool | Purpose |
|---|---|
| `backend/otp_doctor.py` | proves OTP delivery; never prints secrets |
| `backend/env_loader.py` | resolves and cleans `.env`, overrides stale OS variables |
| `backend/otp_delivery_log.py` | secret-free delivery log |
| `scripts/smoke_test.py` | 14-step end-to-end flow test (mock senders; `--live` option) |
| `scripts/boot_check.py` | boots `serve.py`, checks readiness, kills the whole process tree |
| `scripts/secret_scan.py` | finds secrets in tracked files and git history (file and commit only) |
| `scripts/rotate_secrets.py` | generates fresh app keys; refuses without `--fresh-db` |
| `scripts/static_check.py` | offline undefined-name / unused-import / swallowed-exception checker |
| `scripts/profile_detect.py`, `verify_keras_equivalence.py` | latency profiling and proof of unchanged model outputs |
| `scripts/gen_doc_fragments.py` | generates the tables in this document |
| `scripts/ledger.py` | updates FILE_REVIEW.md |
| `latency_benchmark.py`, `scenario_tests.py`, `train_all_models.py`, `calibrate_and_tune.py` | benchmark, scenario suite, training, calibration |
| `backend/reset_all_balances.py` | resets all balances (requires `--yes`) |

---

# 16. Testing

- **Automated:** 196 test functions in 30 test files (206 test cases with parametrisation); last full run **206 passed**. The suite uses a throw-away SQLite database and forces email and Telegram dry-run so it can never reach real services. The later website-trust change was verified with the scenario, layer and override subset (27 passed); the full suite was not re-run after that change.
- **Smoke test:** 14/14 passed (two registrations, known and new-device login, normal transfer, unregistered payee, 2FA transfer, PIN change, forgot-PIN with reduced limit, blocked transfer and single-use freeze link, balance reset, lockout, rate limit, account delete with ledger anonymisation).
- **Live checks:** SMTP send (passed), Telegram API (getMe, username, webhook, no competing poller: passed), Safe Browsing (known test URL flagged: passed), Firebase service-account token (obtained).
- **Not run:** Telegram on a real phone (needs your action), the Flutter app on a device, APK build (no JDK).
- **Static:** `compileall` clean; `flutter analyze` has no errors (sender 32 infos/warnings, receiver 9 infos).

## 16.1 Test inventory (generated)
{{INCLUDE:tests.md}}

---

# 17. Performance

Measured with `latency_benchmark.py` (200 iterations of the full `detect()`: 7 layers, 7 models, fusion, SHAP; CPU only on a Ryzen 5 3500U laptop).

| Stage | p50 | p95 | p99 | Throughput |
|---|---|---|---|---|
| Before | 304.97 ms | 348.57 ms | 374.06 ms | 3.19 txn/s |
| Keras direct call instead of `.predict()` | 104.72 ms | 122.07 ms | 137.06 ms | 8.97 txn/s |
| Plus `tf.function` and `n_jobs=1` (final) | **63.69 ms** | **77.78 ms** | **86.90 ms** | **14.40 txn/s** |

Model outputs are unchanged (largest difference 1.2e-6). SHAP costs 4.85 ms on average. Other request-path measures: email and Telegram sent in parallel with an 8-second cap, website checks in parallel under 3.5 s, geocoding off the payment path.

---

# 18. History and Fixes

## 18.1 Build timeline (commits per day)
2026-10-15: 1, 10-16: 4, 10-20: 6, 10-23: 8, 10-25: 21, 10-28: 32, 10-29: 12, 10-30: 24, 10-31: 25, then further work to 11-05. Development ran in numbered parts 0 to 30 (state files, rename, user model, PINs, OTP core, email, Telegram, signup, login, step-up, PIN management, registered payees, override rules, alerts, abuse protection, privacy, geolocation, data audit, loaders, feature builder, simulator, honest training, calibration, fusion, scenarios, SHAP, testing and CI, hosting, mobile web, Flutter).

## 18.2 Why OTP codes did not arrive (proven root causes)
1. The email provider rejected the credentials (Gmail `535 BadCredentials`); the address was also misspelled in `.env` for a period.
2. Python's login retry after a 535 made Gmail hang up, so logs only showed "connection unexpectedly closed" (fixed: one mechanism).
3. Missing credentials were reported as "sent" (fixed).
4. Signup stopped at the failed email step, and the code ignored each channel's send result (fixed: per-channel status).
5. Through the tunnel every user shared one IP, so 5 OTPs per hour were allowed for everyone together (fixed: tunnel-aware client IP).
6. Two stale server processes held port 5000 with old code and `.env` (stopped; port guard added).
7. The debug reloader started two Telegram pollers (HTTP 409) (fixed).
8. Later: Brevo blocked the laptop when its IP changed (525); email was moved back to Gmail.

## 18.3 Bugs found and fixed in the full file review (about 114 across 153 files)
Admin pages were open to everyone through the tunnel; negative transfer amounts reversed payments; double spend and split commits; all web payments failed (4-digit keypad vs 6-digit PIN); the app's 2FA screen sent one code as both channels; account delete crashed and never anonymised the ledger; undecryptable values were returned as if plaintext; QR parser crashed on non-numeric amounts; fraud Layer 4 mis-scored every payee (+40 and +20); running standard deviation mixed variance and std; mule graph race and missing completed edges; unauthenticated Telegram re-linking of active accounts; balance reset by user ID without login; legacy OTP-less endpoints (`/api/register`, `/api/user/change-pin`) retired; token from PIN reset instantly revoked; stored XSS in admin and user pages; timestamps shown in the wrong zone (now UTC with Z, displayed in Asia/Kolkata); the real secret key hard-coded in the Flutter app and a default DB password; duplicate root modules replaced by shims; dead and unsafe scripts removed or guarded.

## 18.4 Later fixes
Admin portal: local access works even with a token set; model metrics read from the training file; unlock clears all lockouts; retrain guard; lockout display "/ 5". Website check: input validation, nonexistent-domain and brand look-alike detection, honest SAFE note. Email: Brevo support and provider-aware hints, then Gmail restored. LAN hosting: share URL in the banner and README_LAN.md. Firebase service-account key stored in a git-ignored `secrets/` folder and registered as `FIREBASE_CREDENTIALS_FILE` (not used by any code yet).

---

# 19. Limitations and Open Items

| Severity | Item | Action |
|---|---|---|
| HIGH | `MLBFD_SECRET_KEY` (encrypts all personal data) is guessable and appeared in git history (commits `feedf0c`, `d7f262d`) | rotate with `scripts/rotate_secrets.py --apply --fresh-db` |
| HIGH | Recall is low on real benchmark rows (0.0799 at 1% FPR for XGBoost) because public data lacks UPI features | disclosed; improve with source-aware features |
| HIGH | Secrets shared in chat (Brevo key, Firebase key, Gmail app password) | regenerate and replace |
| MEDIUM | APK not built | install a JDK, then build |
| MEDIUM | Telegram not yet tested on a real phone | `otp_doctor.py --link-telegram` |
| MEDIUM | Account delete has no web button | add one |
| MEDIUM | OpenPhish key not set (keyword simulation) | optional |
| LOW | `HASH_PEPPER` is required but unused; legacy plaintext `phone_number` column remains | remove in a migration |
| LOW | One sample per fraud scenario | expand to many variations |
| LOW | Firebase key stored but no push-notification code | future work |
| LOW | Turnstile cannot run inside the Flutter app | keep keys empty for app signups |
| Planned | Ablation study, champion-challenger, GraphSAGE | deferred |

---

# 20. Source File Inventory (153 tracked files plus files added later; status and bugs from the review)

{{INCLUDE:files.md}}

---

# 21. Dependencies (`backend/requirements.txt`)

{{INCLUDE:requirements.md}}

Installed versions that differ from the file: scikit-learn 1.9.1, imbalanced-learn 0.14.2, pandas 2.3.3, shap 0.51.0, pyarrow 16.1.0, pytest 9.1.1, waitress 3.0.2. Python 3.11.15. Flutter 3.41.6 / Dart 3.11.4.

---

# 22. Glossary
**FPR** false-positive rate. **Recall at 1% FPR** share of fraud caught while wrongly flagging only 1% of genuine payments. **PR-AUC / ROC-AUC** area under the precision-recall / ROC curve. **SMOTE** synthetic minority oversampling. **SHAP** per-feature contribution explanation. **Stacking** a second model learns how to combine the first-level models. **Blind hash** a keyed hash that lets the database find an encrypted value without decrypting everything. **REQUIRES_2FA** payment held until both codes are verified. **Dry run** messages are buffered instead of sent. **Tunnel** Cloudflare quick tunnel giving a public HTTPS address to the laptop server. **WAL** SQLite write-ahead logging.
