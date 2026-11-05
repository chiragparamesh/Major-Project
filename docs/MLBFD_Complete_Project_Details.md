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

| Route | Methods | Auth | Rate limit | Handler | Purpose (docstring) |
|---|---|---|---|---|---|
| `/api/account/delete` | POST | JWT optional | default | `account_delete` | Privacy & Account Deletion: |
| `/api/account/reset_balance` | POST | JWT optional | default | `reset_balance` | Demo feature: Restores account balance to 100,000 virtual rupees. |
| `/api/balance/<uid>` | GET | JWT required | default | `get_balance` |  |
| `/api/feedback` | POST | JWT required | default | `submit_feedback` |  |
| `/api/freeze` | GET | - | default | `freeze_account_via_link` | Validates single-use signed 24-hour freeze link and freezes user account. |
| `/api/health/otp` | GET | - | default | `otp_health` | Admin-only, secret-free readiness of the EMAIL and TELEGRAM OTP channels. |
| `/api/login` | POST | - | 10 per minute | `login` |  |
| `/api/login/verify` | POST | - | 15 per minute | `login_verify` |  |
| `/api/logout` | POST | JWT required | default | `logout` |  |
| `/api/lookup_payee` | GET | JWT required | 10 per minute | `lookup_payee` | Looks up a payee by UPI id, 10-digit phone, or +91 phone. |
| `/api/otp/resend` | POST | JWT optional | 6 per minute | `resend_otp_channel` | Per-channel Resend (30 s cooldown per channel). |
| `/api/otp/send` | POST | JWT required | 5 per minute | `trigger_otp` |  |
| `/api/otp/verify` | POST | JWT required | 10 per minute | `verify_otp_endpoint` |  |
| `/api/pin/change` | POST | JWT optional | default | `pin_change` | Step 1 of PIN change: |
| `/api/pin/change/confirm` | POST | JWT optional | default | `pin_change_confirm` | Step 2 of PIN change: |
| `/api/pin/forgot/reset` | POST | - | default | `pin_forgot_reset` | Step 3 of forgot PIN: |
| `/api/pin/forgot/start` | POST | - | 3 per hour | `pin_forgot_start` | Step 1 of forgot PIN: |
| `/api/pin/forgot/verify` | POST | - | default | `pin_forgot_verify` | Step 2 of forgot PIN: |
| `/api/predict-secure` | POST | JWT required | default | `predict_secure` | Calculates real-time risk scores for what-if previews. Does NOT save transaction. |
| `/api/predict_secure` | POST | JWT required | default | `predict_secure` | Calculates real-time risk scores for what-if previews. Does NOT save transaction. |
| `/api/refresh` | POST | JWT required | default | `refresh` |  |
| `/api/register` | POST | - | default | `register` | Retired: the legacy one-step signup created accounts without OTP verification, |
| `/api/register/send_telegram_otp` | POST | - | 10 per minute | `register_send_telegram_otp` |  |
| `/api/register/start` | POST | - | 10 per minute | `register_start` |  |
| `/api/register/timing_token` | GET | - | default | `get_registration_timing_token` | Returns signed form timing token and Turnstile site key for registration form. |
| `/api/register/verify_email` | POST | - | 15 per minute | `register_verify_email` |  |
| `/api/register/verify_telegram` | POST | - | 15 per minute | `register_verify_telegram` |  |
| `/api/report-scam` | POST | JWT required | default | `report_scam` |  |
| `/api/reverse_geocode` | GET | - | default | `reverse_geocode_api` | Returns human-readable area name from lat and lon via cached Nominatim. |
| `/api/telegram/link_token` | POST | JWT optional | default | `telegram_link_token` | Creates a single-use 10-minute token and returns https://t.me/<BOT_USERNAME>?start=<token>. |
| `/api/telegram/status` | GET | JWT optional | default | `telegram_status` | Checks Telegram link and verification status. |
| `/api/transactions/<uid>` | GET | JWT required | default | `get_transactions` |  |
| `/api/transfer` | POST | JWT required | default | `transfer` | Executes money transfer. Runs detection, saves log, updates balance if safe. |
| `/api/trusted-payees/<int:tp_id>` | DELETE | JWT required | default | `remove_trusted_payee` |  |
| `/api/trusted-payees/<uid>` | GET | JWT required | default | `get_trusted_payees` |  |
| `/api/trusted-payees/add` | POST | JWT required | default | `add_trusted_payee` |  |
| `/api/user/balance-secured` | POST | JWT required | default | `get_balance_secured` |  |
| `/api/user/change-pin` | POST | - | default | `change_user_pin` | Retired: changed a PIN without dual OTP and enforced 4 digits. Use /api/pin/change. |
| `/api/user/settings` | GET,POST | JWT required | default | `user_settings` |  |
| `/api/website-check/<domain>` | GET | JWT required | default | `website_check` |  |
| `/` | GET | - | default | `user_dashboard_view` |  |
| `/admin` | GET | - | default | `index` |  |
| `/admin/alerts` | GET | - | default | `alerts_view` |  |
| `/admin/api/alerts` | GET | - | default | `get_dashboard_alerts` |  |
| `/admin/api/compliance/npci-export` | GET | - | default | `export_npci_csv` |  |
| `/admin/api/drift/metrics` | GET | - | default | `get_data_drift_metrics` |  |
| `/admin/api/models/metrics` | GET | - | default | `get_model_metrics` |  |
| `/admin/api/models/retrain` | POST | - | default | `trigger_model_retrain` |  |
| `/admin/api/stats` | GET | - | default | `get_dashboard_stats` |  |
| `/admin/api/transactions` | GET | - | default | `get_all_transactions` |  |
| `/admin/api/users` | GET | - | default | `get_all_users` |  |
| `/admin/api/users/<user_id>/toggle-lock` | POST | - | default | `toggle_user_lock` |  |
| `/admin/drift` | GET | - | default | `drift_view` |  |
| `/admin/models` | GET | - | default | `models_view` |  |
| `/admin/overview` | GET | - | default | `index` |  |
| `/admin/transactions` | GET | - | default | `transactions_view` |  |
| `/admin/users` | GET | - | default | `users_view` |  |
| `/dashboard` | GET | - | default | `user_dashboard_view` |  |
| `/login` | GET | - | default | `user_login_view` |  |
| `/register` | GET | - | default | `user_register_view` |  |
| `/user/login` | GET | - | default | `user_login_view` |  |
| `/user/register` | GET | - | default | `user_register_view` |  |


---

# 12. Database Schema (generated from `backend/database.py`)


### Table `users` (model `User`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `user_id` | String(50) | unique, NOT NULL, index |
| `full_name` | String(150) |  |
| `phone` | Text |  |
| `email` | Text |  |
| `upi_id` | String(255) | unique |
| `telegram_chat_id` | Text |  |
| `phone_hash` | String(64) | index |
| `email_hash` | String(64) | index |
| `upi_hash` | String(64) | unique, index |
| `status` | String(20) | default 'PENDING', NOT NULL, index |
| `email_verified` | Boolean | default False |
| `telegram_verified` | Boolean | default False |
| `known_devices` | JSON_TYPE | default lambda: [] |
| `security_question` | String(255) |  |
| `security_answer_hash` | String(255) |  |
| `consent_at` | DateTime |  |
| `balance` | Numeric(12, 2) | default 0.0 |
| `login_pin_hash` | String(255) |  |
| `payment_pin_hash` | String(255) |  |
| `pin_hash` | String(255) |  |
| `login_failed_attempts` | Integer | default 0 |
| `login_locked_until` | DateTime |  |
| `payment_failed_attempts` | Integer | default 0 |
| `payment_locked_until` | DateTime |  |
| `tokens_revoked_at` | DateTime |  |
| `reduced_limit_until` | DateTime |  |
| `daily_spent_date` | String(10) |  |
| `daily_spent_amount` | Numeric(12, 2) | default 0.0 |
| `phone_number` | String(20) |  |
| `device_token` | Text |  |
| `home_latitude` | Numeric(10, 8) |  |
| `home_longitude` | Numeric(11, 8) |  |
| `home_accuracy_m` | Float |  |
| `home_location_source` | String(20) |  |
| `home_area_name` | String(200) |  |
| `is_locked` | Boolean | default False |
| `failed_attempts` | Integer | default 0 |
| `locked_until` | DateTime |  |
| `daily_limit` | Numeric(12, 2) | default 50000.0 |
| `last_balance_reset_at` | DateTime |  |
| `created_at` | DateTime | default datetime.utcnow |

### Table `transactions` (model `Transaction`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `txn_id` | String(100) | unique, NOT NULL, index |
| `user_id` | String(50) | FK users.user_id, NOT NULL, index |
| `sender_upi` | String(255) | NOT NULL |
| `receiver_upi` | String(255) | NOT NULL, index |
| `amount` | Numeric(12, 2) | NOT NULL |
| `status` | String(30) | NOT NULL |
| `risk_score` | Numeric(5, 2) |  |
| `is_fraud` | Boolean | default False |
| `device_id` | String(100) |  |
| `latitude` | Numeric(10, 8) |  |
| `longitude` | Numeric(11, 8) |  |
| `accuracy_m` | Float |  |
| `location_source` | String(20) |  |
| `area_name` | String(200) |  |
| `hour` | Integer |  |
| `day_of_week` | Integer |  |
| `is_holiday` | Boolean | default False |
| `qr_code` | Text |  |
| `merchant_name` | String(255) |  |
| `mcc_code` | String(10) |  |
| `layer_scores` | JSON_TYPE |  |
| `flags` | JSON_TYPE |  |
| `ensemble_confidence` | Numeric(5, 4) |  |
| `created_at` | DateTime | default datetime.utcnow, index |
| `expires_at` | DateTime |  |
| `failed_attempts` | Integer | default 0 |

### Table `user_behavior_baseline` (model `UserBehaviorBaseline`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `user_id` | String(50) | FK users.user_id, unique, NOT NULL, index |
| `avg_amount` | Numeric(12, 2) | default 0.0 |
| `std_amount` | Numeric(12, 2) | default 0.0 |
| `avg_hour` | Numeric(5, 2) | default 0.0 |
| `txn_count` | Integer | default 0 |
| `known_devices` | JSON_TYPE | default lambda: [] |
| `known_payees` | JSON_TYPE | default lambda: [] |
| `mcc_history` | JSON_TYPE | default lambda: {} |
| `last_updated` | DateTime | default datetime.utcnow |

### Table `trusted_payees` (model `TrustedPayee`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `user_id` | String(50) | FK users.user_id, NOT NULL, index |
| `payee_upi` | String(100) | NOT NULL |
| `nickname` | String(100) |  |
| `txn_count` | Integer | default 0 |
| `total_amount` | Numeric(12, 2) | default 0.0 |
| `added_date` | DateTime | default datetime.utcnow |

### Table `website_reputation` (model `WebsiteReputation`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `domain` | String(255) | unique, NOT NULL, index |
| `is_scam` | Boolean | default False |
| `trust_score` | Numeric(5, 2) | default 0.0 |
| `ssl_valid` | Boolean | default False |
| `domain_age_days` | Integer | default -1 |
| `google_safe` | Boolean | default True |
| `openphish_flagged` | Boolean | default False |
| `last_checked` | DateTime | default datetime.utcnow |

### Table `scam_upis` (model `ScamUpi`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `upi_id` | String(100) | unique, NOT NULL, index |
| `reported_count` | Integer | default 1 |
| `reported_by_count` | Integer | default 1 |
| `verified` | Boolean | default False |
| `added_at` | DateTime | default datetime.utcnow |

### Table `scam_reports` (model `ScamReport`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `reporter_id` | String(50) | FK users.user_id |
| `scam_upi` | String(100) | NOT NULL |
| `description` | Text |  |
| `reported_at` | DateTime | default datetime.utcnow |
| `verified` | Integer | default 0 |

### Table `otp_codes` (model `OtpCode`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `user_id` | String(50) | NOT NULL, index |
| `purpose` | String(50) | NOT NULL, index |
| `channel` | String(20) | NOT NULL |
| `code_hash` | String(64) | NOT NULL |
| `txn_id` | String(100) | index |
| `expires_at` | DateTime | NOT NULL |
| `attempts` | Integer | default 0, NOT NULL |
| `max_attempts` | Integer | default 3, NOT NULL |
| `used_at` | DateTime |  |
| `created_at` | DateTime | default datetime.utcnow, NOT NULL |
| `ip_address` | String(45) | index |
| `dual_group_id` | String(64) | index |

### Table `feedback` (model `Feedback`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `txn_id` | String(100) | FK transactions.txn_id, NOT NULL |
| `user_id` | String(50) | FK users.user_id, NOT NULL |
| `is_fraud` | Boolean | NOT NULL |
| `predicted_fraud` | Boolean |  |
| `feedback_text` | Text |  |
| `created_at` | DateTime | default datetime.utcnow |

### Table `audit_log` (model `AuditLog`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `user_id` | String(50) | index |
| `action` | String(100) | NOT NULL |
| `ip_address` | String(45) |  |
| `request_hash` | String(64) |  |
| `response_code` | Integer |  |
| `risk_score` | Numeric(5, 2) |  |
| `created_at` | DateTime | default datetime.utcnow |

### Table `model_metrics` (model `ModelMetrics`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `model_name` | String(100) | NOT NULL |
| `auc_score` | Numeric(6, 4) |  |
| `recall` | Numeric(6, 4) |  |
| `precision` | Numeric(6, 4) |  |
| `f1_score` | Numeric(6, 4) |  |
| `accuracy` | Numeric(6, 4) |  |
| `trained_at` | DateTime | default datetime.utcnow |

### Table `token_blocklist` (model `TokenBlocklist`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `jti` | String(36) | NOT NULL, index |
| `user_id` | String(50) | index |
| `created_at` | DateTime | default datetime.utcnow |

### Table `telegram_link_tokens` (model `TelegramLinkToken`)

| Column | Type | Constraints / default |
|---|---|---|
| `token` | String(64) | primary_key |
| `user_id` | String(50) | NOT NULL, index |
| `expires_at` | DateTime | NOT NULL |
| `used` | Boolean | default False, NOT NULL |
| `created_at` | DateTime | default datetime.utcnow, NOT NULL |

### Table `pending_pin_changes` (model `PendingPinChange`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `user_id` | String(50) | NOT NULL, index |
| `pin_type` | String(20) | NOT NULL |
| `new_pin_hash` | String(255) | NOT NULL |
| `expires_at` | DateTime | NOT NULL |
| `created_at` | DateTime | default datetime.utcnow, NOT NULL |

### Table `password_reset_tokens` (model `PasswordResetToken`)

| Column | Type | Constraints / default |
|---|---|---|
| `token` | String(64) | primary_key |
| `user_id` | String(50) | NOT NULL, index |
| `expires_at` | DateTime | NOT NULL |
| `used` | Boolean | default False, NOT NULL |
| `created_at` | DateTime | default datetime.utcnow, NOT NULL |

### Table `account_freeze_tokens` (model `AccountFreezeToken`)

| Column | Type | Constraints / default |
|---|---|---|
| `token` | String(255) | primary_key |
| `user_id` | String(50) | NOT NULL, index |
| `expires_at` | DateTime | NOT NULL |
| `used` | Boolean | default False, NOT NULL |
| `created_at` | DateTime | default datetime.utcnow, NOT NULL |

### Table `signup_ip_logs` (model `SignupIpLog`)

| Column | Type | Constraints / default |
|---|---|---|
| `id` | Integer | primary_key |
| `ip_address` | String(50) | NOT NULL, index |
| `user_id` | String(50) | NOT NULL, index |
| `created_at` | DateTime | default datetime.utcnow, index |


Notes: SQLite file `backend/instance/mlbfd.sqlite3` in WAL mode; optional PostgreSQL if `DATABASE_URL` points to it (falls back to SQLite). Money columns are `Numeric(12,2)`. `otp_codes` holds hashed codes only. The legacy `otp_records` table was removed and `migrate_db.py` drops it only if empty.

---

# 13. Configuration

## 13.1 Settings read by `backend/config.py` (names and defaults, no values)
| Setting | How it is read / default |
|---|---|
| `SECRET_KEY` | `os.getenv('MLBFD_SECRET_KEY')` |
| `JWT_SECRET_KEY` | `os.getenv('JWT_SECRET_KEY')` |
| `JWT_ACCESS_TOKEN_EXPIRES` | `timedelta(hours=1)` |
| `JWT_REFRESH_TOKEN_EXPIRES` | `timedelta(days=30)` |
| `DB_HOST` | `os.getenv('DB_HOST', 'localhost')` |
| `DB_PORT` | `os.getenv('DB_PORT', '5432')` |
| `DB_NAME` | `os.getenv('DB_NAME', 'mlbfd_db')` |
| `DB_USER` | `os.getenv('DB_USER', 'mlbfd_user')` |
| `DB_PASS` | `os.getenv('DB_PASS', '')` |
| `DATABASE_URL` | `os.getenv('DATABASE_URL', f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}')` |
| `SQLITE_DATABASE_URL` | `'sqlite:///mlbfd.sqlite3'` |
| `GOOGLE_SAFE_BROWSING_API_KEY` | `env_str('GOOGLE_SAFE_BROWSING_API_KEY', default='MOCK')` |
| `FIREBASE_SERVER_KEY` | `os.getenv('FIREBASE_SERVER_KEY', 'MOCK')` |
| `FIREBASE_CREDENTIALS_FILE` | `env_str('FIREBASE_CREDENTIALS_FILE')` |
| `OPENPHISH_API_KEY` | `os.getenv('OPENPHISH_API_KEY', 'MOCK')` |
| `EMAIL_HOST` | `env_str('EMAIL_HOST', 'SMTP_HOST', default='smtp.gmail.com')` |
| `EMAIL_PORT` | `int(env_str('EMAIL_PORT', 'SMTP_PORT', default='587'))` |
| `EMAIL_SMTP_MODE` | `env_str('EMAIL_SMTP_MODE', default='auto')` |
| `EMAIL_USER` | `env_str('EMAIL_USER', 'SMTP_USER')` |
| `EMAIL_SMTP_LOGIN` | `env_str('EMAIL_SMTP_LOGIN')` |
| `EMAIL_PASSWORD` | `env_str('EMAIL_PASSWORD', 'SMTP_PASS')` |
| `EMAIL_FROM_NAME` | `env_str('EMAIL_FROM_NAME', default='MLBFD')` |
| `EMAIL_FROM` | `env_str('EMAIL_FROM', 'SMTP_FROM', 'EMAIL_USER', default='no-reply@mlbfd.local')` |
| `EMAIL_DRY_RUN` | `env_bool('EMAIL_DRY_RUN', False)` |
| `TELEGRAM_BOT_TOKEN` | `env_str('TELEGRAM_BOT_TOKEN')` |
| `TELEGRAM_BOT_USERNAME` | `env_str('TELEGRAM_BOT_USERNAME', default='mlbfd_otp_bot').lstrip('@')` |
| `TELEGRAM_POLLING_ENABLED` | `env_bool('TELEGRAM_POLLING_ENABLED', True)` |
| `TELEGRAM_DRY_RUN` | `env_bool('TELEGRAM_DRY_RUN', False)` |
| `TURNSTILE_SITE_KEY` | `os.getenv('TURNSTILE_SITE_KEY', '')` |
| `TURNSTILE_SECRET_KEY` | `os.getenv('TURNSTILE_SECRET_KEY', '')` |
| `VIRTUAL_BALANCE` | `float(os.getenv('VIRTUAL_BALANCE', 100000.0))` |
| `RATE_LIMIT_PER_MIN` | `int(os.getenv('RATE_LIMIT_PER_MIN', 30))` |
| `OTP_EXPIRY_SECONDS` | `int(os.getenv('OTP_EXPIRY_SECONDS', 300))` |
| `SESSION_TIMEOUT_MINUTES` | `int(os.getenv('SESSION_TIMEOUT_MINUTES', 15))` |
| `TRUSTED_PAYEE_MIN_TXNS` | `int(os.getenv('TRUSTED_PAYEE_MIN_TXNS', 3))` |
| `SCAM_LIST_REFRESH_HOURS` | `int(os.getenv('SCAM_LIST_REFRESH_HOURS', 6))` |
| `REDUCED_TXN_LIMIT` | `float(os.getenv('REDUCED_TXN_LIMIT', 10000.0))` |
| `REDUCED_DAILY_LIMIT` | `float(os.getenv('REDUCED_DAILY_LIMIT', 25000.0))` |
| `SQLALCHEMY_TRACK_MODIFICATIONS` | `False` |


## 13.2 Variable names in `.env.example`
- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASS`
- `DATABASE_URL`
- `MLBFD_SECRET_KEY`
- `JWT_SECRET_KEY`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_SMTP_LOGIN`
- `EMAIL_USER`
- `EMAIL_PASSWORD`
- `EMAIL_FROM_NAME`
- `EMAIL_FROM`
- `EMAIL_DRY_RUN`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_FROM`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_BOT_USERNAME`
- `TELEGRAM_POLLING_ENABLED`
- `TELEGRAM_DRY_RUN`
- `GOOGLE_SAFE_BROWSING_API_KEY`
- `FIREBASE_SERVER_KEY`
- `FIREBASE_CREDENTIALS_FILE`
- `OPENPHISH_API_KEY`
- `FLASK_ENV`
- `FLASK_PORT`
- `VIRTUAL_BALANCE`
- `MAX_PAYLOAD_KB`
- `RATE_LIMIT_PER_MIN`
- `OTP_EXPIRY_SECONDS`
- `SESSION_TIMEOUT_MINUTES`
- `TRUSTED_PAYEE_MIN_TXNS`
- `SCAM_LIST_REFRESH_HOURS`
- `REDUCED_TXN_LIMIT`
- `REDUCED_DAILY_LIMIT`
- `EMAIL_SMTP_MODE`
- `MLBFD_CLIENT_SECRET`
- `ADMIN_API_TOKEN`
- `HASH_PEPPER`


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

- **Automated:** 196 test functions in 29 test files (206 test cases with parametrisation); last full run **206 passed**. The suite uses a throw-away SQLite database and forces email and Telegram dry-run so it can never reach real services. The later website-trust change was verified with the scenario, layer and override subset (27 passed); the full suite was not re-run after that change.
- **Smoke test:** 14/14 passed (two registrations, known and new-device login, normal transfer, unregistered payee, 2FA transfer, PIN change, forgot-PIN with reduced limit, blocked transfer and single-use freeze link, balance reset, lockout, rate limit, account delete with ledger anonymisation).
- **Live checks:** SMTP send (passed), Telegram API (getMe, username, webhook, no competing poller: passed), Safe Browsing (known test URL flagged: passed), Firebase service-account token (obtained).
- **Not run:** Telegram on a real phone (needs your action), the Flutter app on a device, APK build (no JDK).
- **Static:** `compileall` clean; `flutter analyze` has no errors (sender 32 infos/warnings, receiver 9 infos).

## 16.1 Test inventory (generated)

**test_otp_delivery_infra.py** (23 test functions)

- `test_clean_value`
- `test_parse_env_file_bom_crlf_spaces`
- `test_load_env_overrides_stale_os_value`
- `test_load_env_keeps_test_pins`
- `test_env_str_alias_fallback`
- `test_smtp_routes_auto_fallback_order`
- `test_port_587_timeout_falls_back_to_465`
- `test_bad_app_password_surfaces_535_and_stops`
- `test_missing_credentials_is_failure_not_fake_success`
- `test_delivery_log_has_no_code_or_address`
- `test_polling_starts_exactly_once`
- `test_second_process_does_not_poll`
- `test_reloader_parent_never_polls`
- `test_unlinked_telegram_reports_not_linked`
- `test_sender_exception_is_status_failed_not_swallowed`
- `test_both_senders_registered_at_import`
- `test_admin_api_blocked_through_tunnel`
- `test_admin_token_header_and_cookie_login`
- `test_client_ip_trusts_proxy_headers_only_from_tunnel`
- `test_ubts_running_std_matches_population_std`
- `test_dual_dispatch_overlaps_slow_email_and_caps_wait`
- `test_brevo_login_separate_from_inbox`
- `test_brevo_from_not_rewritten_to_login`

**test_otp_e2e.py** (15 test functions)

- `test_signup_dual_channel_end_to_end`
- `test_signup_email_failure_reports_reason_and_rolls_back`
- `test_new_device_login_dual_otp`
- `test_requires_2fa_transfer_dual_otp`
- `test_pin_reset_dual_otp_and_per_channel_resend`
- `test_resend_requires_jwt_for_transaction`
- `test_health_otp_is_admin_only`
- `test_concurrent_debits_cannot_double_spend`
- `test_debit_and_credit_commit_together`
- `test_transfer_rejects_invalid_amounts`
- `test_account_delete_anonymizes_encrypted_ledger`
- `test_registered_mlbfd_payee_not_flagged_as_bad_suffix`
- `test_token_returned_by_pin_reset_is_not_instantly_revoked`
- `test_admin_models_metrics_come_from_training_file`
- `test_admin_unlock_clears_all_lockouts_and_refuses_pending`

**test_part10_pin_management.py** (7 test functions)

- `test_pin_change_success_login_pin`
- `test_pin_change_rejections`
- `test_forgot_pin_flow_success`
- `test_forgot_pin_rejections`
- `test_forgot_pin_rate_limiting_3_per_hour`
- `test_reduced_limit_enforced_in_transfer`
- `test_jwt_blacklisting_after_reset`

**test_part11_registered_users_only.py** (5 test functions)

- `test_unregistered_receiver_returns_404_no_ledger_row`
- `test_frozen_receiver_returns_404_no_ledger_row`
- `test_self_transfer_blocked`
- `test_transfer_to_active_registered_user_by_all_identifier_formats`
- `test_lookup_payee_endpoint`

**test_part12_override_rules.py** (17 test functions)

- `test_users`
- `test_override_rules_table_structure`
- `test_rule_1_scam_blacklist`
- `test_rule_2_qr_payee_mismatch`
- `test_rule_3_impossible_travel_and_new_device`
- `test_rule_3_impossible_travel_only_not_triggered`
- `test_rule_4_website_flagged`
- `test_rule_5_mule_topology`
- `test_rule_6_new_device_new_payee_high_amount`
- `test_rule_7_extreme_amount_new_payee`
- `test_rule_8_cooling_off_cap_new_payee_under_24h`
- `test_normal_transaction_unaffected`
- `test_engine_detect_scam_blacklist_overrides_to_blocked`
- `test_engine_detect_qr_mismatch_overrides_to_blocked`
- `test_engine_detect_cooling_cap_under_24h_overrides_to_70`
- `test_api_predict_secure_returns_override_fields`
- `test_api_transfer_returns_override_fields`

**test_part13_freeze_alert.py** (9 test functions)

- `test_users`
- `test_generate_and_verify_freeze_token`
- `test_freeze_link_works_once_then_fails`
- `test_freeze_link_fails_when_expired`
- `test_freeze_link_fails_without_token`
- `test_transfer_blocked_triggers_freeze_alerts_on_email_and_telegram`
- `test_transfer_approved_does_not_dispatch_freeze_alerts`
- `test_unfreeze_via_forgot_pin_reset`
- `test_unfreeze_via_admin_users_page`

**test_part14_bot_abuse_protection.py** (6 test functions)

- `test_honeypot_rejection`
- `test_fast_form_fill_rejection`
- `test_disposable_email_rejection`
- `test_ip_signup_rate_limiting`
- `test_turnstile_verification_real_key_mocked`
- `test_timing_token_endpoint`

**test_part15_privacy_demo.py** (6 test functions)

- `test_mask_phone_and_email_helpers`
- `test_consent_at_recorded_on_registration`
- `test_reset_balance_endpoint`
- `test_account_delete_flow_and_anonymization`
- `test_admin_portal_users_api_masks_phone_and_email`
- `test_demo_banner_in_templates`

**test_part16_accurate_location.py** (7 test functions)

- `test_reverse_geocode_rajajinagar_landmark`
- `test_reverse_geocode_caching`
- `test_reverse_geocode_api_endpoint`
- `test_signup_stores_rajajinagar_pin_and_area`
- `test_geofence_penalty_skip_when_accuracy_over_5000m`
- `test_transfer_stores_location_source_and_accuracy`
- `test_map_picker_exists_in_portal_template`

**test_part18_data_loader.py** (5 test functions)

- `test_paysim_temporal_zero_leakage`
- `test_future_events_do_not_affect_past_features`
- `test_ieee_temporal_processor_causality`
- `test_parquet_files_exist_and_conform_schema`
- `test_no_synthetic_gaussian_leakage_in_clean_parquets`

**test_part19_feature_builder.py** (4 test functions)

- `test_canonical_22_features_structure`
- `test_feature_order_hash_generation_and_verification`
- `test_live_and_training_feature_identity`
- `test_feature_builder_calculations`

**test_part1_baseline.py** (3 test functions)

- `test_env_example_exists_and_contains_standard_keys`
- `test_backend_config_importable`
- `test_no_legacy_brand_in_ui_templates`

**test_part20_upi_simulator.py** (3 test functions)

- `test_upi_simulator_generates_natural_fraud_rate_and_noise`
- `test_single_feature_auc_below_0_90_for_all_22_features`
- `test_simulator_parquet_generation`

**test_part21_honest_training.py** (3 test functions)

- `test_all_seven_model_artifacts_and_metrics_exist`
- `test_metrics_json_conforms_to_spec`
- `test_feature_order_hash_verified_in_models`

**test_part22_tuning_calibration.py** (3 test functions)

- `test_operating_thresholds_json_exists_and_valid`
- `test_calibrate_probabilities_brier_comparison`
- `test_determine_threshold_at_1pct_fpr`

**test_part23_learned_fusion.py** (3 test functions)

- `test_fusion_json_exists_and_valid`
- `test_get_fusion_prediction_returns_selected_mode_and_confidence`
- `test_layer1_zscore_bonus_capped_at_60`

**test_part24_scenario_suite.py** (1 test functions)

- `test_accuracy_report_exists_and_contains_sections`

**test_part25_shap_explainability.py** (5 test functions)

- `test_shap_explainer_cached_and_returns_top5`
- `test_shap_added_latency_strictly_under_10ms`
- `test_plain_language_reason_generation`
- `test_api_predict_secure_and_transfer_return_top5`
- `test_ui_templates_display_shap_and_plain_language`

**test_part26_layers_boundary.py** (10 test functions)

- `test_decision_matrix_threshold_boundaries`
- `test_layer_weights_sum_to_one`
- `test_layer_1_behavioral_score_and_zscore_cap`
- `test_layer_2_velocity_bounds`
- `test_layer_3_flow_topology`
- `test_layer_4_payee_trust_weights`
- `test_layer_5_device_and_compromise_bounds`
- `test_layer_6_amount_limit_bounds`
- `test_layer_7_website_reputation_bounds`
- `test_feature_builder_canonical_22_features`

**test_part26_security_coverage.py** (4 test functions)

- `test_replay_attack_rejected_with_old_timestamp`
- `test_revoked_jwt_blocked_by_tokens_revoked_at`
- `test_revoked_jwt_blocked_by_token_blocklist`
- `test_rate_limits_enforced_on_restricted_endpoints`

**test_part28_mobile_responsiveness.py** (6 test functions)

- `test_viewport_meta_tag_in_all_templates`
- `test_all_tables_wrapped_in_table_wrapper`
- `test_responsive_css_media_queries_exist`
- `test_touch_target_minimum_dimensions`
- `test_table_overflow_x_rule`
- `test_endpoints_render_with_viewport_and_no_overflow`

**test_part2_user_model.py** (5 test functions)

- `test_user_model_columns`
- `test_new_user_balance_is_zero_until_activation`
- `test_find_user_by_upi_or_phone_variations`
- `test_phone_normalization`
- `test_migration_script_execution`

**test_part3_dual_pin.py** (6 test functions)

- `test_pin_hashing_rounds_12`
- `test_weak_pin_rejection`
- `test_dual_pins_must_differ`
- `test_login_pin_authentication_and_5_attempt_lockout`
- `test_payment_pin_verification_and_3_attempt_lockout`
- `test_api_transfer_requires_payment_pin_and_never_reaches_fraud_engine`

**test_part3_otp_service.py** (8 test functions)

- `test_otp_codes_table_schema`
- `test_otp_expiry_with_fake_clock`
- `test_otp_attempts_lockout`
- `test_otp_cooldown_and_hourly_limits`
- `test_otp_invalidation_of_older_unused_codes`
- `test_otp_reuse_prevention`
- `test_dual_channel_issue_and_verification`
- `test_dual_channel_shared_attempts_lockout`

**test_part5_email_channel.py** (7 test functions)

- `test_email_formatting_plain_and_html`
- `test_transaction_email_shows_amount_and_masked_receiver`
- `test_email_dry_run_flag`
- `test_email_background_thread_dispatch`
- `test_email_retry_on_failure_and_clean_error`
- `test_otp_service_integration_via_email_sender`
- `test_dual_issue_sends_email_via_email_sender`

**test_part6_telegram_channel.py** (7 test functions)

- `test_telegram_link_token_generation`
- `test_api_telegram_link_token_endpoint`
- `test_start_command_with_valid_and_expired_token`
- `test_contact_verification_success_and_mismatch`
- `test_send_telegram_success_and_403_unlink`
- `test_api_telegram_status_endpoint`
- `test_telegram_otp_service_integration`

**test_part7_signup_flow.py** (5 test functions)

- `test_register_start_validation_and_creation`
- `test_register_start_collision_generic_message`
- `test_expired_pending_account_cleanup`
- `test_nothing_activates_with_only_one_verification`
- `test_full_activation_flow_with_dual_verification`

**test_part8_login_device_binding.py** (5 test functions)

- `test_unknown_device_requires_dual_otp`
- `test_login_verify_binds_device_and_issues_tokens`
- `test_device_trust_expires_after_30_days`
- `test_frozen_and_pending_accounts_cannot_login`
- `test_refresh_token_endpoint`

**test_part9_fraud_stepup.py** (8 test functions)

- `test_transfer_requires_2fa_holds_pending`
- `test_otp_verify_success_atomic_transfer`
- `test_otp_verify_rechecks_balance`
- `test_three_failed_attempts_cancels_transaction`
- `test_three_cancelled_transactions_freezes_account`
- `test_expired_transaction_cannot_be_verified`
- `test_twilio_and_pyotp_removed`
- `test_admin_alerts_and_stats_include_pending_and_cancelled`


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

| path | lines | status | bugs found | notes |
| --- | --- | --- | --- | --- |
| backend/config.py | 79 | FIXED | 3 | env_loader (override, cleaned values); canonical EMAIL_*/TELEGRAM_* with SMTP_* fallback; DB_PASS literal default removed (leaked); TELEGRAM_DRY_RUN added |
| backend/security.py | 366 | FIXED | 3 | decrypt_val returned ciphertext as plaintext on key mismatch; client-signing key split from SECRET_KEY (was embedded in APK); admin_request_allowed gate. NOTE HASH_PEPPER unused (lookup hash uses SECRET_KEY) |
| backend/database.py | 296 | FIXED | 1 | removed legacy OtpRecord model/relationship; money columns Numeric OK; datetimes naive UTC |
| backend/db.py | 165 | REVIEWED | 0 | SQLite fallback OK; silent ALTER TABLE rollbacks are intentional idempotent migrations |
| backend/migrate_db.py | 289 | FIXED | 1 | drops unused otp_records only when empty |
| migrate_db.py | 260 | FIXED | 1 | stale full duplicate (missing 7 columns) replaced by shim to backend/migrate_db.py |
| backend/app.py | 472 | FIXED | 3 | CRITICAL: /admin pages + /admin/api/* were unauthenticated (decrypted UPI ids, toggle-lock, retrain, CSV export public via tunnel) -> before_request admin gate; reloader parent started a 2nd Telegram poller (409); start_bot param + OTP banner |
| backend/api.py | 2422 | FIXED | 14 | admin/OTP helpers; delivery maps; resend + health endpoints; account-delete bool unpack 500; ledger anonymization never matched encrypted rows; atomic transfers; negative amount exploit; reset_balance auth; legacy /register retired; telegram link/status hijack; tunnel IP; XSS input cleaning; UTC Z; nonblocking geocode |
| backend/otp_service.py | 758 | FIXED | 6 | issue_dual ignored send results; per-channel status; 300 s expiry for TRANSACTION (was 600 s); resend_channel; readiness; overlapped dispatch; senders registered at import |
| backend/email_sender.py | 545 | FIXED | 7 | smtplib.login masked 535 as SMTPServerDisconnected; fake success on missing creds; no 465 fallback; values uncleaned; addresses in logs; alert HTML unescaped; background wait cap |
| backend/telegram_bot.py | 556 | FIXED | 6 | reloader double poller (409); no PID lock / heartbeat; crash without backoff; 409/429 unhandled; contact.user_id None==None passed; message text (codes) logged in dry-run |
| backend/user_manager.py | 501 | FIXED | 1 | lockouts 5/15min login, 3/30min payment consistent with docs; device trust parse narrowed; legacy register_user only reachable from tests now |
| backend/rate_limiter.py | 8 | FIXED | 1 | keyed on remote_addr: behind cloudflared ALL users shared one bucket (100/h global) -> tunnel-aware client_ip key |
| backend/audit_logger.py | 29 | FIXED | 2 | audit IP was always 127.0.0.1 behind tunnel; bool(request) outside context; swallowed rollback now logged |
| backend/fraud_detection.py | 628 | FIXED | 3 | Layer4: payee lookup by user_id=phone digits never matched; ciphertext equality never matched (+40 on every payee); @mlbfd missing from valid suffixes (+20 on every allowed payment). SHAP on sync path -> Phase 9 |
| feature_builder.py | 25 | REVIEWED | 0 | shim |
| backend/feature_builder.py | 180 | REVIEWED | 0 | canonical 22-vector + SHA guard (tests part19) |
| backend/predictor.py | 319 | FIXED | 2 | Keras .predict per request (~310 ms) -> tf.function direct call; RF/IF n_jobs=1 (equivalence verified) |
| learned_fusion.py | 21 | REVIEWED | 0 | shim |
| backend/learned_fusion.py | 483 | REVIEWED | 0 | OOF stacking folds; meta fit on OOF |
| backend/social_graph.py | 97 | FIXED | 3 | COMPLETED (OTP-verified) txns excluded from mule graph; graph.clear() race with 8 threads; whole-graph degree_centrality per request |
| backend/geofence.py | 194 | FIXED | 3 | fabricated Bengaluru fallback; Nominatim blocking payment path; unbounded cache; thresholds 900 km/h, 100/500 km match tests |
| backend/website_trust.py | 264 | FIXED | 5 | API key in URL (log leak); WHOIS unbounded; serial checks; 24h cache vs 6h policy; OpenPhish feed per call; SSL network error penalized |
| backend/qr_parser.py | 105 | FIXED | 1 | float(am) outside try -> 500 on non-numeric QR amount |
| backend/ubts.py | 79 | FIXED | 2 | running std applied variance update to std (units mixed, std inflated -> tiny z-scores) -> Welford on variance; None txn_count |
| upi_simulator.py | 17 | REVIEWED | 0 | shim |
| backend/upi_simulator.py | 442 | REVIEWED | 0 | overlapping distributions; AUC guard tests part20 |
| data_loader.py | 25 | REVIEWED | 0 | shim |
| backend/data_loader.py | 456 | REVIEWED | 0 | chunked parquet, past-only windows (tests part18) |
| train_all_models.py | 21 | REVIEWED | 0 | shim |
| backend/train_all_models.py | 492 | REVIEWED | 0 | scaler fit on train only; SMOTE train-only; time split 70/15/15 |
| calibrate_and_tune.py | 15 | REVIEWED | 0 | shim |
| backend/calibrate_and_tune.py | 362 | REVIEWED | 0 | isotonic/Platt fit on validation only |
| scenario_tests.py | 1007 | FIXED | 1 | 1007-line exact duplicate replaced by shim |
| backend/scenario_tests.py | 1007 | REVIEWED | 0 | single implementation; root file is shim |
| latency_benchmark.py | 237 | REVIEWED | 0 | config/asset |
| serve.py | 130 | FIXED | 3 | env_loader override; OTP readiness banner; waitress trusts X-Forwarded-Proto from local tunnel (freeze links were http://) |
| start_mlbfd.bat | 40 | FIXED | 2 | prints the trycloudflare public URL from logs/cloudflared.log; refuses to start when :5000 already busy (stale .env values) |
| backend/data_processor.py | 237 | REVIEWED | 0 | DEAD: superseded by feature_builder.py; not imported by app |
| backend/env_loader.py | 133 | REVIEWED | 0 | written this session | | |
| backend/generate_complete_mlbfd_pdf.py | 1015 | REVIEWED | 0 | config/asset |
| backend/lstm_sequence.py | 99 | REVIEWED | 0 | USED by predictor (LSTM sequence builder); earlier DEAD note was wrong |
| backend/model_trainer.py | 180 | REVIEWED | 0 | model factories used by calibrate/fusion |
| backend/otp_delivery_log.py | 45 | REVIEWED | 0 | written this session | | |
| backend/otp_doctor.py | 547 | REVIEWED | 0 | written this session | | |
| backend/reset_all_balances.py | 35 | FIXED | 2 | ran destructively on import with hard-coded absolute path -> --yes guard, relative path |
| backend/test_detector.py | 186 | REVIEWED | 0 | dev script (not collected by pytest); deletes only chirag_test rows |
| dashboard/static/css/main.css | 950 | REVIEWED | 0 | config/asset |
| dashboard/static/css/user.css | 1912 | REVIEWED | 0 | config/asset |
| dashboard/static/js/charts.js | 70 | REVIEWED | 0 | config/asset |
| dashboard/static/js/dashboard.js | 107 | FIXED | 2 | esc() helper; dates shown in Asia/Kolkata (API UTC was parsed as local) |
| dashboard/static/js/otp_status.js | 118 | REVIEWED | 0 | written this session | | |
| dashboard/static/js/user.js | 1661 | FIXED | 5 | flags/reasons/payee XSS -> esc(); Asia/Kolkata dates; per-channel OTP UI; UPI keypad took 4 digits vs 6-digit payment PIN (every web payment failed); dead changeUserPin removed |
| dashboard/templates/alerts.html | 260 | FIXED | 1 | stored XSS in admin alerts (upi ids, flags, reasons) -> esc() |
| dashboard/templates/base.html | 193 | REVIEWED | 0 | config/asset |
| dashboard/templates/drift.html | 237 | REVIEWED | 0 | config/asset |
| dashboard/templates/index.html | 416 | FIXED | 1 | recent txn feed innerHTML -> esc() |
| dashboard/templates/models.html | 144 | REVIEWED | 0 | config/asset |
| dashboard/templates/transactions.html | 275 | FIXED | 1 | stored XSS: merchant_name/device_id/mcc/user_id/flags via innerHTML -> esc() |
| dashboard/templates/user_dashboard.html | 948 | FIXED | 2 | keypad label/dots 4 -> 6; OTP delivery containers; NOTE no account-delete UI (API only) |
| dashboard/templates/user_login.html | 566 | FIXED | 1 | per-channel OTP status/resend for new device + forgot PIN |
| dashboard/templates/user_register.html | 723 | FIXED | 2 | esc() for API text; Telegram step: exact link, status polling, auto-send after link, per-channel resend |
| dashboard/templates/users.html | 125 | FIXED | 1 | user_id/email/phone into innerHTML -> esc() |
| flutter_app/receiver_app/lib/config/api_config.dart | 55 | FIXED | 1 | same as sender (no fallback URL) |
| flutter_app/receiver_app/lib/config/app_theme.dart | 78 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/lib/main.dart | 21 | FIXED | 1 | init + server screen |
| flutter_app/receiver_app/lib/screens/balance_screen.dart | 189 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/lib/screens/home_screen.dart | 249 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/lib/screens/receive_screen.dart | 118 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/lib/screens/registration_screen.dart | 251 | FIXED | 2 | shared dual-OTP signup/login (no GPS dep), 6-digit PINs |
| flutter_app/receiver_app/lib/screens/transaction_history_screen.dart | 253 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/lib/services/api_service.dart | 135 | FIXED | 2 | legacy register/login replaced |
| flutter_app/sender_app/lib/config/api_config.dart | 68 | FIXED | 2 | hard-coded 10.0.2.2 fallback removed; new signup/resend/status URLs |
| flutter_app/sender_app/lib/config/app_theme.dart | 79 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/lib/main.dart | 21 | FIXED | 1 | ApiConfig.init() was never called (saved URL ignored) -> init + first-launch server screen |
| flutter_app/sender_app/lib/screens/analytics_screen.dart | 223 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/lib/screens/biometric_screen.dart | 115 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/lib/screens/home_screen.dart | 469 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/lib/screens/otp_screen.dart | 115 | FIXED | 1 | single code sent as both email+telegram -> two fields + per-channel status/resend |
| flutter_app/sender_app/lib/screens/qr_generator_screen.dart | 116 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/lib/screens/registration_screen.dart | 276 | FIXED | 3 | rewritten: 3-step dual signup + Telegram link polling, new-device dual OTP login, 6-digit PINs, Twilio text removed |
| flutter_app/sender_app/lib/screens/send_money_screen.dart | 489 | FIXED | 2 | 4-digit PIN vs 6-digit payment PIN; Twilio label; passes delivery to OtpScreen |
| flutter_app/sender_app/lib/screens/transaction_history_screen.dart | 278 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/lib/screens/trusted_contacts_screen.dart | 179 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/lib/services/api_service.dart | 375 | FIXED | 4 | embedded MLBFD_SECRET_KEY default; legacy register payload (always 400); login crashed on OTP_REQUIRED (null tokens); verifyOtp sent one code as both |
| flutter_app/sender_app/lib/widgets/risk_gauge.dart | 178 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| .env.example | 62 | REVIEWED | 0 | config/asset |
| .github/workflows/ci.yml | 54 | REVIEWED | 0 | config/asset |
| ACCURACY_REPORT.md | 130 | REVIEWED | 0 | doc |
| BUGFIX_STATE.md | 68 | REVIEWED | 0 | doc |
| CONTEXT.md | 45 | REVIEWED | 0 | doc |
| DATA_AUDIT.md | 461 | REVIEWED | 0 | doc |
| OTP_SETUP.md | 78 | REVIEWED | 0 | doc |
| PROGRESS.md | 136 | REVIEWED | 0 | doc |
| PROGRESS_REPORT.md | 98 | REVIEWED | 0 | doc |
| PROJECT_HANDOFF.md | 840 | REVIEWED | 0 | doc |
| README_APK.md | 85 | REVIEWED | 0 | doc |
| README_EMAIL.md | 76 | REVIEWED | 0 | doc |
| README_HOSTING.md | 95 | REVIEWED | 0 | doc |
| README_TELEGRAM.md | 76 | REVIEWED | 0 | doc |
| RESULTS_FOR_POSTER.txt | 14 | REVIEWED | 0 | doc |
| ROTATE_SECRETS.md | 39 | REVIEWED | 0 | doc |
| backend/.env.example | 58 | REVIEWED | 0 | config/asset |
| backend/requirements.txt | 31 | REVIEWED | 0 | doc |
| data_audit.py | 351 | REVIEWED | 0 | config/asset |
| database/schema.sql | 258 | REVIEWED | 0 | config/asset |
| docs/PROJECT_RESEARCH_REPORT.md | 575 | REVIEWED | 0 | doc |
| docs/generate_paper_assets.py | 399 | REVIEWED | 0 | config/asset |
| flutter_app/receiver_app/README.md | 17 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/analysis_options.yaml | 28 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/pubspec.yaml | 98 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/test/widget_test.dart | 30 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/web/index.html | 46 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/receiver_app/web/manifest.json | 35 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/README.md | 17 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/analysis_options.yaml | 28 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/pubspec.yaml | 105 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/test/widget_test.dart | 30 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/web/index.html | 46 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| flutter_app/sender_app/web/manifest.json | 35 | REVIEWED | 0 | flutter analyze: no errors (infos only: async BuildContext, withOpacity deprecations) |
| pytest.ini | 3 | REVIEWED | 0 | config/asset |
| scripts/rotate_secrets.py | 81 | REVIEWED | 0 | written this session | | |
| scripts/secret_scan.py | 117 | REVIEWED | 0 | written this session | | |
| conftest.py | 52 | FIXED | 1 | MLBFD_TESTING pin + forced dry-run (suite could reach real SMTP) |
| tests/test_otp_delivery_infra.py | 185 | REVIEWED | 0 | written this session | | |
| tests/test_otp_e2e.py | 228 | REVIEWED | 0 | written this session | | |
| tests/test_part10_pin_management.py | 393 | REVIEWED | 0 | passing; 201 total |
| tests/test_part11_registered_users_only.py | 277 | REVIEWED | 0 | passing; 201 total |
| tests/test_part12_override_rules.py | 388 | REVIEWED | 0 | passing; 201 total |
| tests/test_part13_freeze_alert.py | 376 | REVIEWED | 0 | passing; 201 total |
| tests/test_part14_bot_abuse_protection.py | 147 | REVIEWED | 0 | passing; 201 total |
| tests/test_part15_privacy_demo.py | 242 | FIXED | 1 | updated for security fixes (JWT required) |
| tests/test_part16_accurate_location.py | 199 | REVIEWED | 0 | passing; 201 total |
| tests/test_part18_data_loader.py | 164 | REVIEWED | 0 | passing; 201 total |
| tests/test_part19_feature_builder.py | 157 | REVIEWED | 0 | passing; 201 total |
| tests/test_part1_baseline.py | 38 | REVIEWED | 0 | passing; 201 total |
| tests/test_part20_upi_simulator.py | 82 | REVIEWED | 0 | passing; 201 total |
| tests/test_part21_honest_training.py | 79 | REVIEWED | 0 | passing; 201 total |
| tests/test_part22_tuning_calibration.py | 90 | REVIEWED | 0 | passing; 201 total |
| tests/test_part23_learned_fusion.py | 133 | REVIEWED | 0 | passing; 201 total |
| tests/test_part24_scenario_suite.py | 28 | REVIEWED | 0 | passing; 201 total |
| tests/test_part25_shap_explainability.py | 252 | REVIEWED | 0 | passing; 201 total |
| tests/test_part26_layers_boundary.py | 176 | REVIEWED | 0 | passing; 201 total |
| tests/test_part26_security_coverage.py | 258 | REVIEWED | 0 | passing; 201 total |
| tests/test_part28_mobile_responsiveness.py | 131 | REVIEWED | 0 | passing; 201 total |
| tests/test_part2_user_model.py | 151 | REVIEWED | 0 | passing; 201 total |
| tests/test_part3_dual_pin.py | 309 | REVIEWED | 0 | passing; 201 total |
| tests/test_part3_otp_service.py | 257 | REVIEWED | 0 | passing; 201 total |
| tests/test_part5_email_channel.py | 150 | REVIEWED | 0 | passing; 201 total |
| tests/test_part6_telegram_channel.py | 310 | FIXED | 1 | updated for security fixes (JWT required) |
| tests/test_part7_signup_flow.py | 291 | REVIEWED | 0 | passing; 201 total |
| tests/test_part8_login_device_binding.py | 222 | REVIEWED | 0 | passing; 201 total |
| tests/test_part9_fraud_stepup.py | 435 | REVIEWED | 0 | passing; 201 total |
| flutter_app/sender_app/lib/screens/server_url_screen.dart | 77 | REVIEWED | 0 | written this session |
| flutter_app/sender_app/lib/widgets/otp_delivery_status.dart | 163 | REVIEWED | 0 | written this session |
| flutter_app/receiver_app/lib/screens/server_url_screen.dart | 77 | REVIEWED | 0 | written this session |
| flutter_app/receiver_app/lib/widgets/otp_delivery_status.dart | 163 | REVIEWED | 0 | written this session |
| scripts/smoke_test.py | 269 | REVIEWED | 0 | written this session |
| scripts/boot_check.py | 59 | REVIEWED | 0 | written this session |
| scripts/static_check.py | 139 | REVIEWED | 0 | written this session |
| scripts/profile_detect.py | 36 | REVIEWED | 0 | written this session |
| scripts/verify_keras_equivalence.py | 31 | REVIEWED | 0 | written this session |
| scripts/ledger.py | 24 | REVIEWED | 0 | written this session |


---

# 21. Dependencies (`backend/requirements.txt`)

```
flask==3.0.0
flask-sqlalchemy==3.1.1
flask-jwt-extended==4.6.0
flask-limiter==3.5.0
flask-cors==4.0.0
psycopg2-binary==2.9.9
python-dotenv==1.0.0
gunicorn==21.2.0
xgboost==2.0.3
scikit-learn==1.4.0
tensorflow==2.15.0
keras==2.15.0
imbalanced-learn==0.12.0
numpy==1.26.4
pandas==2.2.0
scipy==1.12.0
joblib==1.3.2
cryptography==42.0.0
bcrypt==4.1.2
requests==2.31.0
python-whois==0.9.4
Pillow==10.2.0
networkx==3.2.1
qrcode==7.4.2
opencv-python==4.9.0.80
python-dateutil==2.8.2
pytz==2024.1
pytest>=8.0.0
shap>=0.45.0
pyarrow>=15.0.0
waitress>=3.0.0
```


Installed versions that differ from the file: scikit-learn 1.9.1, imbalanced-learn 0.14.2, pandas 2.3.3, shap 0.51.0, pyarrow 16.1.0, pytest 9.1.1, waitress 3.0.2. Python 3.11.15. Flutter 3.41.6 / Dart 3.11.4.

---

# 22. Glossary
**FPR** false-positive rate. **Recall at 1% FPR** share of fraud caught while wrongly flagging only 1% of genuine payments. **PR-AUC / ROC-AUC** area under the precision-recall / ROC curve. **SMOTE** synthetic minority oversampling. **SHAP** per-feature contribution explanation. **Stacking** a second model learns how to combine the first-level models. **Blind hash** a keyed hash that lets the database find an encrypted value without decrypting everything. **REQUIRES_2FA** payment held until both codes are verified. **Dry run** messages are buffered instead of sent. **Tunnel** Cloudflare quick tunnel giving a public HTTPS address to the laptop server. **WAL** SQLite write-ahead logging.
