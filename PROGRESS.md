# STATUS TABLE

| Part | Status | Evidence |
| :---: | :---: | :--- |
| **Part 0** | DONE | CONTEXT.md, PROGRESS.md, .gitignore exist, git repo active with commits |
| **Part 1** | DONE | Zero beyondotp matches outside paper_assets; UI headers and titles say MLBFD |
| **Part 2** | DONE | User model has dual PINs, encrypted phone/email/upi, blind hashes; migrate_db.py idempotent |
| **Part 3** | DONE | Dual PIN validation, wrong payment PIN blocked before fraud engine, lockout DB tests pass |
| **Part 4** | DONE | UPI ID format <phone>@mlbfd and 100000 virtual balance on activation |
| **Part 5** | DONE | email_sender.py, README_EMAIL.md exist, SMTP background retry & dry-run tests pass |
| **Part 6** | DONE | telegram_bot.py, README_TELEGRAM.md exist, requests polling, link token & contact match pass |
| **Part 7** | DONE | 3-step wizard, dual verification required to activate, 30-min PENDING purge |
| **Part 8** | DONE | Known device 30-day trust skips OTP; new device dual OTP required; refresh token works |
| **Part 9** | DONE | REQUIRES_2FA holds PENDING; dual OTP verify executes atomically; 3-strike cancel & freeze; Twilio/PyOTP purged |
| **Part 10** | DONE | Change PIN & Forgot PIN with dual OTPs, bcrypt security answer, 24-hr reduced limits, JWT revocation |
| **Part 11** | DONE | Registered users only via blind hash lookup; 404 before scoring; self-transfer blocked; GET /api/lookup_payee |
| **Part 12** | DONE | OVERRIDE_RULES exists in fraud_detection.py, all 8 rules implemented and verified, API returns weighted_score, final_score, overrides |
| **Part 13** | DONE | "Was this you?" dual-channel alerts, signed 24h freeze link works once then fails, unfreeze via PIN reset & admin |
| **Part 14** | DONE | Honeypot, 3s form timing check, disposable email block, and 3/day IP signup rate limits tested and passing |
| **Part 15** | DONE | Privacy consent, account deletion with dual OTP & ledger anonymization, demo banner, balance reset (1/hr) pass tests |
| **Part 16** | DONE | Leaflet map picker, rate-limited Nominatim reverse geocode, Rajajinagar pin tests, >5000m geofence penalty skip pass |
| **Part 17** | DONE | DATA_AUDIT.md generated via chunked audit covering 11 CSVs and Tier 3 reports, zero memory blowup, documented Gaussian overlay leakage |
| **Part 18** | DONE | data_loader.py chunked parquet generation (PaySim, IEEE, BAF), strict past-only causality, zero label leakage verified by tests |
| **Part 19** | DONE | feature_builder.py canonical 22-vector builder, SHA-256 hash verified, identity tests pass, grep confirms zero outside computation |
| **Part 20** | DONE | upi_simulator.py realistic generator, overlapping distributions, 0.5% noise, 3.5% fraud rate, all 22 single-feature AUCs < 0.81 (well below 0.90) |
| **Part 21** | DONE | train_all_models.py honest time-split (70/15/15), all 7 models trained, synthetic Gaussian overlays purged, tests pass |
| **Part 22** | DONE | operating_thresholds.json generated for all 7 models + ensemble with <=1% FPR on val, recall gap reported |
| **Part 23** | DONE | Stacking meta-classifier trained & calibrated, fusion.json created, layer 1 Z-score capped at 60, model agreement confidence added |
| **Part 24** | DONE | scenario_tests.py 21 scenarios pass (100% recall at 1% FPR, 0 mismatches), ACCURACY_REPORT.md generated with latency & test metrics |
| **Part 25** | DONE | Cached SHAP TreeExplainer (<10ms added latency), top-5 signed feature attributions returned in /api/transfer and /api/predict_secure, horizontal bar chart in alerts.html, plain-language reason in user_dashboard.html, 5/5 tests pass |
| **Part 26** | DONE | Full 7-layer boundary tests (10/10), security tests (4/4), latency_benchmark.py, .github/workflows/ci.yml, all 150 pytest tests passing |
| **Part 27** | DONE | Waitress serve.py (8 threads), SQLite WAL mode, start_mlbfd.bat launcher, README_HOSTING.md, HTTP 200 verified |
| **Part 28** | DONE | Viewport meta, responsive CSS (360px no overflow), touch targets >= 44px, table wrappers, 6/6 tests pass |
| **Part 29** | TODO | Flutter APK sender & receiver apps, server URL config, README_APK.md |
| **Part 30** | TODO | Optional extras (ablation, champion-challenger, GraphSAGE) |

# CURRENT
- Part: Part 29 (Flutter APK Sender & Receiver Apps)
- Steps:
  - [x] Step 1: Run flutter doctor and write diagnostics/setup steps into README_APK.md
  - [ ] Step 2: Update flutter_app apps: MLBFD branding, dynamic Server URL config, X-Device-ID header
  - [ ] Step 3: Implement dual-OTP, PIN screens, and modern signup wizard screens
  - [ ] Step 4: Build release APKs (flutter build apk --release) and verify DONE CHECK
- LAST ACTION: STARTED part 21 step 2: retrain 7 models under scikit-learn 1.9.1 and regenerate ACCURACY_REPORT.md with real vs simulator metrics
- NEXT STEP: Run train_all_models.py and scenario_tests.py

# BLOCKED ON USER
- Telegram Bot Token: `TELEGRAM_BOT_TOKEN` in `.env` (using mocks/dry-run in tests).
- Email SMTP Credentials: `EMAIL_USER`/`EMAIL_PASSWORD` in `.env` (using `EMAIL_DRY_RUN=True`).
- Cloudflare Tunnel: `cloudflared` executable install (Part 27).
- Flutter SDK: `flutter` command / Android SDK (Part 29).
- Cloudflare Turnstile: `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` (Part 14, honeypot fallback active).

# KNOWN ISSUES
- None. Full test suite passing (66/66 tests green).

# COMMANDS TO RUN
```bash
& "D:\Major Project\MLBFD\backend\.venv\Scripts\python.exe" -m pytest
```

# OTP DISPATCH TRACE (2026-10-31, secrets never printed)

- backend/user_manager.py:392-405 | `cleanup_expired_pending_accounts()` now deletes `SignupIpLog` rows for each purged PENDING user and removes pre-existing orphans; live log: `Removed 3 orphaned signup_ip_logs rows with no user record`.
- backend/api.py:214-219 | 3-per-IP/24h check was the first stop: 3 ghost rows caused `429 IP_SIGNUP_LIMIT_EXCEEDED` before any OTP code ran.
- backend/api.py:128-129 | Every request now logs `register_start: request received` then runs cleanup before parsing.
- backend/api.py:142-263 | All pre-dispatch rejects now log a reason: missing fields, consent, honeypot, Turnstile, timing, disposable email, IP quota, user-id, PIN, phone, email, collision.
- backend/api.py:325-330 | Live log: `abuse checks passed (ip quota 0/3)` -> user committed -> `issuing EMAIL OTP ... require_delivery=True`.
- backend/api.py:325 | Registration issues ONLY the EMAIL OTP; Telegram OTP is by design issued later by `/api/register/send_telegram_otp` after bot linking.
- backend/otp_service.py:352-365 | Dispatch logs sender class + dry_run, logs exceptions, and raises `OtpDispatchError` when `require_delivery=True` and delivery is false.
- backend/email_sender.py:217-227 | OTP email is sent synchronously (`background=False`); a daemon thread no longer hides SMTP errors.
- backend/email_sender.py:182 | Live failure: `server.login()` -> `smtplib.SMTPServerDisconnected: Connection unexpectedly closed` on both retries; `delivered=False`.
- backend/api.py:334-350 | On `OtpDispatchError` the PENDING user + IP log row are rolled back and HTTP 502 `OTP_DISPATCH_FAILED` is returned (was a false 201).
- dashboard/templates/user_register.html:483-509 | `readApiResponse()` parses JSON or raw text and every register step now shows `HTTP <status>: <real API message>`.
- backend/app.py:66-89 | Both senders register at startup and the Telegram polling daemon starts; live log confirms `Telegram bot polling daemon started.`
- Verification: `POST /api/register/start` -> 502 in 6.89s with rollback; IMAP probe with the same env values -> `[AUTHENTICATIONFAILED] Invalid credentials`. Code path is fixed; delivery is blocked by the Gmail app password in `.env` (user action).
- Tests: `pytest tests -q` -> 156 passed.


# OTP DELIVERY MISSION (2026-10-31)
## PHASE 1: PROVE WHAT THE RUNNING APP SEES
- [x] 1a otp_doctor.py env-loading checks -> all PASS (no BOM, no dups, no OS shadowing); backend/env_loader.py now loads root .env with override=True
- [x] 1b variable-name audit -> all required names present; code reads canonical EMAIL_*/TELEGRAM_* with SMTP_* fallback
- [x] 1c flags -> EMAIL_DRY_RUN=false, TELEGRAM_DRY_RUN=false, POLLING=true
- [x] 1d nothing listening on :5000
- [x] 2 OTP ROOT CAUSES recorded below

## OTP ROOT CAUSES (proven)
0b. STALE SERVERS: two older serve.py processes kept :5000 (Windows double-bind), so edits to .env/code never reached the answering server. Stopped; serve.py now refuses a taken port; start_mlbfd.bat checks too.
0. HOSTED (via Cloudflare tunnel): every request has remote_addr 127.0.0.1, and otp_service limits 5 OTP issues/hour per IP -> after 5 OTPs worldwide all further issues raised OtpRateLimitError (no code sent); Flask-Limiter likewise shared one bucket. Fixed: security.client_ip() trusts CF-Connecting-IP/XFF only from the local tunnel; used by limiter, OTP, signup, audit.
1. EMAIL: Gmail rejects the app password in .env. Evidence: explicit AUTH LOGIN and AUTH PLAIN over SSL:465 and STARTTLS:587 both return `535 5.7.8 Username and Password not accepted (BadCredentials)`. TLS issuer is Google Trust Services (no antivirus interception); EMAIL_USER is a gmail.com address; password is 16 lowercase letters (correct shape) -> revoked/mistyped app password, or created under a different Google account. USER ACTION required.
2. EMAIL (code bug, masked #1): smtplib.login() retried a second AUTH mechanism after the 535; Gmail closed the socket, so logs only ever showed `SMTPServerDisconnected`. Fixed: email_sender._smtp_login() uses one mechanism -> real 535 surfaces.
3. EMAIL (code bug): missing EMAIL_USER/EMAIL_PASSWORD returned True (fake "sent"). Fixed: raises EmailConfigError.
4. TELEGRAM: API is healthy (getMe 200, @mlbfd_otp_bot matches .env, no webhook, no 409). Telegram codes never arrived because signup aborts with 502 OTP_DISPATCH_FAILED at the email step (cause #1), before the Telegram link step is reached; also issue_dual() ignored both send results so no channel status reached the UI.

## Phase 2: EMAIL
- [x] doctor --email-test with 587->465 fallback and exception hints
- [x] email_sender: cleaned settings, STARTTLS/SSL auto fallback, 10 s timeout, 1 retry (no retry after 535), background thread with bounded wait, per-attempt logs/otp_delivery.log, status dict returned, alert HTML escaped, no addresses in logs

## Phase 3: TELEGRAM
- [x] doctor --telegram-test: getMe 200, username matches, no webhook, no 409
- [ ] doctor --link-telegram (NEEDS USER ACTION, phone)
- [x] telegram_bot audit: PID lock (one poller per machine), reloader parent never polls (app.py), crash backoff + rollback, 409/429/403/timeouts handled, contact.user_id==from.id with both required, E.164 match, no message text in logs
- [x] Bug: `python backend/app.py` (debug reloader) started TWO pollers -> 409 Conflict. Fixed.

## Phase 4: OTP FLOW
- [x] otp_service: _dispatch normalizes sender result, issue() returns IssuedCode(.delivery), issue_dual() returns .channel_status, resend_channel(), channel_readiness(); 300 s expiry for all purposes (TRANSACTION was 10 min)
- [x] removed otp_manager.py + OtpRecord model; migrate_db drops otp_records only when empty
- [x] API: `delivery` map on register/start, send_telegram_otp, login, transfer 2FA, /otp/send, PIN change, PIN forgot, account delete; POST /api/otp/resend (per channel, 30 s cooldown, JWT for TRANSACTION/PIN_CHANGE/ACCOUNT_DELETE); GET /api/health/otp (ADMIN_API_TOKEN or direct loopback); startup banner in serve.py and app.py
- [x] Bug: account delete did `verified, otp_err = verify_dual()` (returns bool) -> 500 in production; fixed
- [x] Bug: unauthenticated /api/telegram/link_token could re-link ANY active account's Telegram; now PENDING-only without JWT
- [x] web pages: dashboard/static/js/otp_status.js (status chips + per-channel Resend, 30 s cooldown, textContent only); register (email status, exact t.me link, polls /api/telegram/status, auto-sends Telegram code after link), login (new device + forgot PIN), dashboard (REQUIRES_2FA modal + PIN change)
- [ ] Flutter per-channel status (Phase 10)
- NOTE: account delete has an API but no web UI (Part 15 gap) - logged for Phase 6
- [x] tests: tests/test_otp_e2e.py (7) + tests/test_otp_delivery_infra.py (21)
- [x] OTP_SETUP.md
- pytest: 184 passed

## PHASE 5: SECRET HYGIENE
- [x] 5.1/5.2 scripts/secret_scan.py (tree + history, file/commit only). LEAK: exact MLBFD_SECRET_KEY in flutter api_service.dart (commits feedf0c, d7f262d); DB_PASS default in config.py (feedf0c). Telegram token / Gmail password / Safe Browsing key never committed.
- [x] Removed both from the tree; Flutter signing now uses separate --dart-define MLBFD_CLIENT_SECRET (server: MLBFD_CLIENT_SECRET, fallback SECRET_KEY); .env.example placeholders
- [x] 5.3 ROTATE_SECRETS.md written (history not rewritten; rotation is the fix)
- [x] 5.4 .gitignore OK; untracked backend/bin/uv*.exe; removed _tmp_env_meta.py
- [x] 5.5 all three app secrets are readable phrases -> GUESSABLE; scripts/rotate_secrets.py (dry run default, --apply requires --fresh-db, moves DB to backups/, never deletes). NOT rotated.
- NOTE: HASH_PEPPER is required by serve.py but never used by security.py (lookup hashes use SECRET_KEY) -> Phase 6

## PHASE 6: EVERY-FILE REVIEW
- [ ] 6.1 generate FILE_REVIEW.md ledger
- [ ] 6.2 review in prescribed order, commit every 3-5 files
- [ ] 6.3 compileall + pyflakes/ruff if installed + pytest after each fix group
- [x] 6.1 FILE_REVIEW.md (154 files)
- batch 1: admin gate (CRITICAL), decrypt fallback, QR crash, duplicate modules -> shims
- batch 2: atomic conditional-UPDATE transfers (double spend + split commits), reset_balance needs JWT, legacy /api/register retired (410), telegram status JWT for ACTIVE
- batch 3: negative/NaN/inf amount accepted by /transfer (reversed transfer) -> _parse_amount; tunnel-aware client_ip for limiter/OTP/signup/audit
- batch 4: stored XSS (admin + user pages) escaped + server-side free-text cleaning; UTC 'Z' timestamps displayed Asia/Kolkata; docs travel speed 800->900 km/h and bot @mlbfd_bot->@mlbfd_otp_bot

## PHASE 7: SAFE BROWSING / EXTERNAL APIS
- [x] website_trust: key via params (was in URL -> could leak in exception logs), HTTP 400/403/429/timeouts neutral + logged by class, 6 h cache (was 24 h), checks parallel under 3.5 s budget (WHOIS had no timeout), OpenPhish feed cached 6 h with UA, SSL network errors neutral
- [x] geofence: Nominatim 1 req/s + UA + bounded cache; transfer path uses reverse_geocode_nonblocking (no OSM wait); failure fallback was a fabricated "Bengaluru, Karnataka" -> "Unknown Area"
- [x] otp_doctor --safebrowsing-test: PASS (testsafebrowsing malware URL -> MALWARE)
- [x] /api/health/otp reports safe_browsing key status + last call state, openphish state
- batch 5-8: fraud Layer4 payee/suffix bugs; encrypted-ledger anonymization; web keypad 4->6 digits (all web payments failed); OTP-less /api/user/change-pin retired; ubts std bug; social graph race/COMPLETED; ML pipeline leak-free; insecure dev script removed; destructive reset guarded; launcher prints public URL; waitress X-Forwarded-Proto
- REMAINING Phase 6: flutter lib/ (Phase 10), tests/ + docs rows
- LAST ACTION: DONE Phase 6 backend+web; hosting fixes
## PHASE 8: SMOKE TESTS
- [x] scripts/smoke_test.py: 14/14 PASS (register x2, known/new-device login, normal transfer, unregistered 404, 2FA->COMPLETED, block+freeze link single-use, PIN change, forgot-PIN + reduced limit, balance reset 1/h, lockout, rate limit, account delete + ledger anonymized)
- [x] Bug found by smoke: token returned by PIN reset was instantly revoked (iat seconds <= revoked_at microseconds) -> fixed + test
- [x] Found 2 STALE serve.py instances (09:54, 11:26) still on :5000 with old code/.env; Windows allowed a second bind so new servers were shadowed (health 404). Stopped them (project processes). serve.py now refuses to start if the port is taken (SO_EXCLUSIVEADDRUSE); poller lock has a 90 s heartbeat (PID reuse)
- [x] scripts/boot_check.py: serve.py ready in ~22 s, alive 20 s, banner OK, one Telegram poller, background SMTP probe prints "EMAIL OTP WILL FAIL: SMTP login rejected (535)"
- pytest: 202 passed
- LAST ACTION: DONE Phase 8
## PHASE 9: LATENCY
- [x] baseline p50 304.97 / p95 348.57 / p99 374.06 ms, 3.19 txn/s
- [x] profile: Keras .predict x3 (~103 ms each) -> model(x) + tf.function; RF/IF n_jobs=1; equivalence proven (max diff 1.2e-6)
- [x] final p50 63.69 / p95 77.78 / p99 86.90 ms, 14.40 txn/s -> ACCURACY_REPORT.md "Latency"
- [x] OTP email/Telegram dispatched concurrently, SMTP wait capped 8 s (pending)
- LAST ACTION: DONE Phase 9; DONE Phase 10 (APK blocked on JDK)
## PHASE 11: FINAL REPORT
- [x] PROJECT_HANDOFF.md sections 11, 14, 15, 18 rewritten from verified state
- [x] Final: compileall OK, pytest 202 passed, smoke 14/14, nothing left on :5000
- LAST ACTION: DONE Phase 11 (mission complete except NEEDS USER ACTION items)
- NEXT STEP: user actions below, then re-run `python backend/otp_doctor.py --email-test` and `--link-telegram`
## PHASE 10: FLUTTER + HOSTING
- [x] flutter analyze: sender 32 / receiver 9 issues, 0 errors (infos + 3 pre-existing unused-field warnings)
- [x] removed 10.0.2.2 fallback; ApiConfig.init() was never called -> init + ServerUrlScreen on first launch (both apps)
- [x] rewrote signup (3-step dual OTP + Telegram link polling) and new-device login; OtpScreen sent ONE code as both channels (2FA impossible) -> two codes + per-channel status/resend; 6-digit PINs; Twilio text removed
- [x] README_APK.md: mklink /J C:\AndroidSdk junction (old advice pointed SDK at an empty folder), OTP flow, Turnstile note
- [x] flutter build apk --release FAILED: "JAVA_HOME is not set and no 'java' command could be found in your PATH." (no JDK installed) -> NEEDS USER ACTION
- [x] hosting: launcher prints tunnel URL, X-Forwarded-Proto, tunnel-aware client IP, Turnstile->honeypot fallback (verified in security.verify_turnstile_token)
- NEXT STEP: Phase 10 flutter analyze
- NEXT STEP: Phase 6 api.py remaining chunk review (predict_secure, freeze, pin flows, timezones), then otp_service/email/telegram ledger rows, user_manager

# NEEDS USER ACTION
- [ ] Gmail app password: Google Account (the EMAIL_USER account) > Security > 2-Step Verification ON > App passwords > create "MLBFD" > paste the 16 letters WITHOUT spaces into EMAIL_PASSWORD in .env > run `python backend/otp_doctor.py --email-test` > check inbox/Spam.
- [ ] Rotate the leaked/guessable app keys when ready to wipe demo data: `backend\.venv\Scripts\python.exe scripts
otate_secrets.py --apply --fresh-db` (see ROTATE_SECRETS.md).
- [ ] Install cloudflared for public hosting: `winget install --id Cloudflare.cloudflared`, then run start_mlbfd.bat (prints the https://...trycloudflare.com URL).
- [ ] Install JDK 17 for the APK: `winget install --id Microsoft.OpenJDK.17`, `setx JAVA_HOME "C:\Program Files\Microsoft\jdk-17..."` (new terminal), then `cd flutter_app\sender_app && flutter build apk --release`.
- [ ] Telegram phone test: stop the server, run `python backend/otp_doctor.py --link-telegram`, open the printed t.me link on your phone, press START, tap "Share contact"; expect a "MLBFD test" message.
