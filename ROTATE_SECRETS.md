# ROTATE_SECRETS.md

Scan: `python scripts/secret_scan.py --history` (2026-10-31). Reports file and commit only.

## Leaked into git: treat as PUBLIC

| Secret | Where | Commits | Impact |
| --- | --- | --- | --- |
| `MLBFD_SECRET_KEY` (exact `.env` value) | `flutter_app/sender_app/lib/services/api_service.dart` (default of `MLBFD_CLIENT_SECRET`) | `feedf0c`, `d7f262d` | Fernet key of all encrypted PII columns, blind lookup hashes, OTP HMACs, freeze links, form-timing tokens. Anyone with the repo and a DB copy can decrypt phone/email/UPI. |
| `DB_PASS` (exact `.env` value) | `backend/config.py` default | `feedf0c` | Low: PostgreSQL is not used (SQLite). |

Removed from the working tree in this session. The Flutter app now signs requests only
with `--dart-define=MLBFD_CLIENT_SECRET=...`, a separate key from `MLBFD_SECRET_KEY`.
History was **not** rewritten. Rotation is the fix.

## Not found in any commit
- `TELEGRAM_BOT_TOKEN`, `EMAIL_PASSWORD`, `GOOGLE_SAFE_BROWSING_API_KEY`, `TURNSTILE_SECRET_KEY`.
- `.env.example` only ever had placeholders (no value equals a real `.env` value).

## Guessable (readable words; rotate even if not leaked)
`MLBFD_SECRET_KEY`, `JWT_SECRET_KEY`, `HASH_PEPPER` are readable phrases.

## How to rotate (manual, never automatic)

1. App keys (wipes app data, because the old key decrypts it):
   ```
   backend\.venv\Scripts\python.exe scripts\rotate_secrets.py                    (dry run)
   backend\.venv\Scripts\python.exe scripts\rotate_secrets.py --apply --fresh-db
   ```
   The current DB and `.env` are **moved/copied to `backups/`**, never deleted.
   Restart the server and register users again.
2. Telegram bot token (not leaked; only if you suspect exposure): BotFather > `/revoke` >
   choose the bot > paste the new token into `TELEGRAM_BOT_TOKEN`, restart.
3. Gmail app password: Google Account > Security > App passwords > delete the old one,
   create a new one, paste it (no spaces) into `EMAIL_PASSWORD`, restart.
4. Safe Browsing key: Google Cloud Console > APIs & Services > Credentials >
   regenerate key, restrict it to "Safe Browsing API", paste into
   `GOOGLE_SAFE_BROWSING_API_KEY`, restart.
5. Rebuild the APK with `--dart-define=MLBFD_CLIENT_SECRET=<new value>`.
