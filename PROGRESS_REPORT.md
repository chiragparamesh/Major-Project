# MLBFD Comprehensive Audit & Progress Report

**Generated:** 2026-10-30T11:44:00+05:30  
**Repository:** `D:\Major Project\MLBFD`  
**Git HEAD:** `1e851b6 WIP start P29S2: Update flutter apps with dynamic Server URL, X-Device-ID, and branding`  
**Test Suite Health:** 156 passed, 0 failed, 0 errors, 89 warnings (225.62s)

---

## 1. Overall Progress

- **Passed Checks:** 103 / 107 checks (**96.3%**)
- **Parts Fully Done:** 28 of 30 parts (P0–P20, P22–P28)
- **Parts In Progress / Partial:** 
  - **Part 21**: 80% (4/5 checks) — residual synthetic Gaussian overlay in `data_processor.py`
  - **Part 29**: 25% (1/4 checks) — Flutter apps renaming done; Server URL UI dialog, dual OTP screens, and release APK builds pending

---

## 2. Part-by-Part Audit Scorecard

| Part | Name | Percent | Status | Evidence (max 12 words) |
| :---: | :--- | :---: | :---: | :--- |
| **P0** | State files | 100% | DONE | CONTEXT.md, PROGRESS.md, .gitignore exist, active git commits verified |
| **P1** | Rename | 100% | DONE | Zero BeyondOTP in code, portal titles and mobile labels say MLBFD |
| **P2** | User model | 100% | DONE | 10 blind-hash fields present, migrate_db.py idempotent, lookup tests pass |
| **P3** | PINs | 100% | DONE | Dual PIN hashes, weak PIN rejection, early transfer block, lockouts pass |
| **P4** | OTP core | 100% | DONE | OtpCode model, HMAC hashing, issue/verify dual, rate limits verified |
| **P5** | Email | 100% | DONE | email_sender.py, EMAIL_DRY_RUN mode, README_EMAIL.md exist and tested |
| **P6** | Telegram | 100% | DONE | telegram_bot.py, link_token endpoint, contact phone match, README_TELEGRAM.md exist |
| **P7** | Signup | 100% | DONE | 4-endpoint wizard, dual verification required, 100000 balance, 30m cleanup |
| **P8** | Login | 100% | DONE | X-Device-ID tracking, OTP_REQUIRED branch, login verify, 30-day refresh |
| **P9** | Fraud step-up | 100% | DONE | PENDING step-up state, dual verification required, 3-cancel freeze, no Twilio/PyOTP backend |
| **P10** | PIN change/forgot | 100% | DONE | Dual OTP confirmation, bcrypt security answer, 24h reduced limits, JWT blacklist |
| **P11** | Registered transfers | 100% | DONE | 404 before scoring, blind hash lookup, payee endpoint, self-transfer blocked |
| **P12** | Override rules | 100% | DONE | OVERRIDE_RULES table, blacklisted payee blocked, response breakdown fields present |
| **P13** | Alerts | 100% | DONE | Dual-channel notifications, signed 24h freeze link works once and expires |
| **P14** | Abuse protection | 100% | DONE | Honeypot fallback, 3-signup/IP limit, unique hashes, disposable domain block |
| **P15** | Privacy & demo | 100% | DONE | consent_at logged, account delete anonymization, masked admin PII, demo banner |
| **P16** | Location | 100% | DONE | HTML5 geolocation, Leaflet picker, accuracy_m stored, >5000m geofence penalty skip |
| **P17** | Data audit | 100% | DONE | data_audit.py chunked inspection, DATA_AUDIT.md covering 11 datasets |
| **P18** | Real loaders | 100% | DONE | data_loader.py chunked parquet generation (PaySim, IEEE, BAF), zero leakage |
| **P19** | Feature builder | 100% | DONE | build_feature_vector canonical 22 vector, SHA-256 hash verified, identity tests pass |
| **P20** | Simulator | 100% | DONE | Realistic distributions, 0.5% label noise, 3.5% fraud rate, AUCs < 0.81 |
| **P21** | Training | 80% | PARTIAL | Time-split, 7 models & metrics JSON exist; Gaussian overlay in data_processor.py |
| **P22** | Tuning/thresholds | 100% | DONE | TimeSeriesSplit RandomizedSearchCV, Platt/Isotonic calibration, operating_thresholds.json |
| **P23** | Fusion | 100% | DONE | Stacking meta-classifier, fusion.json, layer 1 z-score capped at 60 |
| **P24** | Scenarios/report | 100% | DONE | 21/21 scenarios match, 100% recall at 1% FPR, ACCURACY_REPORT.md generated |
| **P25** | SHAP | 100% | DONE | Cached TreeExplainer, top-5 signed feature attributions in API and UI |
| **P26** | Tests & CI | 100% | DONE | 156 pytest passing, latency_benchmark.py, GitHub Actions CI workflow |
| **P27** | Hosting | 100% | DONE | Waitress serve.py (8 threads), SQLite WAL mode, start_mlbfd.bat, README_HOSTING.md |
| **P28** | Mobile web | 100% | DONE | Viewport meta, responsive CSS (360px no overflow), touch targets >= 44px |
| **P29** | Flutter APK | 25% | PARTIAL | Apps renamed MLBFD; Server URL UI, dual OTP screens, APK builds pending |
| **P30** | Extras | 0% | TODO | Optional extras skipped unless explicitly requested |

---

## 3. Phase Subtotals

- **Features (P1–P16):** 61 / 61 checks (**100.0%**)
- **Accuracy (P17–P24):** 24 / 25 checks (**96.0%**)
- **Quality (P25–P26):** 6 / 6 checks (**100.0%**)
- **Deploy (P27–P29):** 8 / 11 checks (**72.7%**)

---

## 4. Work Resumption Point

1. **First incomplete part:** **Part 21 (Training Pipeline)**
   - *Missing check:* Remove legacy synthetic Gaussian overlay (`loc=4.5`, `loc=6.0`) in `backend/data_processor.py` (lines 147 and 152).
2. **First active development part:** **Part 29 Step 2 (Flutter APK)**
   - *Next actions:* Finish Server URL configuration UI dialog in Flutter apps, wire dual-OTP verification screen, build release APKs (`flutter build apk --release`).

---

## 5. BLOCKED ON USER Items

- **Telegram Bot Token:** NO (EMPTY in `.env`, using mocks in tests)
- **Email SMTP Credentials:** NO (EMPTY in `.env`, `EMAIL_DRY_RUN=True` active)
- **Cloudflared Installed:** NO (Not found on PATH)
- **Flutter Installed:** YES (`C:\src\flutter\flutter\bin\flutter.bat`)
- **Turnstile Keys:** NO (EMPTY in `.env`, honeypot fallback active)

---

## 6. Top 5 Risks

1. **Uncommitted Changes in Flutter App:** 5 modified files in `flutter_app/sender_app` and `receiver_app` currently pending completion and testing.
2. **Legacy Synthetic Gaussian Overlay:** Residual `loc=4.5` in `backend/data_processor.py` lines 147/152 could cause accidental synthetic leakage if called outside `feature_builder.py`.
3. **Android SDK Path Whitespace:** Android SDK installed at `C:\Users\Chirag p\AppData\Local\Android\Sdk`. Gradle/NDK builds may fail on the space in `Chirag p`.
4. **Production Credential Dependences:** External channels (Telegram Bot, Gmail SMTP, Turnstile, Cloudflare Tunnel) are currently operating in local mock/dry-run mode until user accounts are configured.
5. **Scikit-Learn Version Warnings:** Models trained under scikit-learn 1.4.0 generate InconsistentVersionWarning under current virtualenv scikit-learn 1.9.1.

---

## 7. Next Recommended Action

Clean lines 147/152 of `data_processor.py` to close Part 21, then resume Part 29 Step 2 to finish Flutter server configuration dialog and dual-OTP screens.
