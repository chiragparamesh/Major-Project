# FILE_REVIEW.md: every tracked source file

Generated from `git ls-files` (excluding datasets, models, parquet, images, build, venv,
platform scaffolding). Status: TODO / REVIEWED / FIXED. Total files: see table (originally 154 tracked; new files from this session appended at the end).

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
