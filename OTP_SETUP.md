# MLBFD OTP Setup (Email + Telegram)

MLBFD requires **both** channels for every OTP: signup, new-device login, fraud
step-up (REQUIRES_2FA), PIN change, PIN reset and account delete. Codes are 6 digits,
valid 300 s, 3 attempts, 30 s resend cooldown per channel, stored only as HMAC hashes.

> **Rule: restart the server after ANY `.env` change.** A running server keeps the
> values it loaded at start-up. Stop `serve.py` / `app.py`, edit `.env`, start again.

## 1. `.env` names (repo root `D:\Major Project\MLBFD\.env`)

| Name | Required | Notes |
| --- | --- | --- |
| `EMAIL_HOST` | no | default `smtp.gmail.com` |
| `EMAIL_PORT` | no | `587` (STARTTLS) or `465` (SSL); the other is tried automatically |
| `EMAIL_SMTP_MODE` | no | `auto` (default), `starttls`, `ssl` |
| `EMAIL_USER` | yes | the mailbox (Gmail: also the login; doctor test mails go here) |
| `EMAIL_SMTP_LOGIN` | Brevo only | relay login if different from `EMAIL_USER` (Brevo: `xxxx@smtp-brevo.com`) |
| `EMAIL_PASSWORD` | yes | Gmail: 16-letter **app password**, no spaces. Brevo: **SMTP key** `xsmtpsib-...` (not the `xkeysib-` API key) |
| `EMAIL_FROM` | no | Gmail: must equal `EMAIL_USER`. Brevo: a sender verified in Brevo |
| `EMAIL_FROM_NAME` | no | default `MLBFD` |
| `EMAIL_DRY_RUN` | no | must be `false` for real delivery |
| `TELEGRAM_BOT_TOKEN` | yes | from BotFather, format `<digits>:<secret>` |
| `TELEGRAM_BOT_USERNAME` | yes | the bot's real username without `@` (checked by the doctor) |
| `TELEGRAM_POLLING_ENABLED` | no | must be `true` (the bot must see Start / contact) |
| `TELEGRAM_DRY_RUN` | no | must be `false` for real delivery |
| `ADMIN_API_TOKEN` | no | enables `GET /api/health/otp` remotely via header `X-Admin-Token` |

Legacy names `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` are still
read as a fallback. `.env` values override stale Windows environment variables of the
same name. `.env.example` is never read by the app.

### Gmail app password
1. Sign in to the Google account that is `EMAIL_USER`.
2. Google Account > Security > turn **2-Step Verification** on.
3. Security > **App passwords** > create one named "MLBFD".
4. Paste the 16 letters into `EMAIL_PASSWORD` **without spaces**. Restart the server.

### Brevo (free 300 emails/day) instead of Gmail
```
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_SMTP_LOGIN=<login from Brevo > SMTP & API > SMTP>
EMAIL_PASSWORD=<SMTP key, starts with xsmtpsib->
EMAIL_FROM=<sender verified in Brevo > Senders>
EMAIL_USER=<your inbox for the doctor test>
```
Restart the server, then run `--email-test`.

## 2. Doctor (never prints secrets)

Run from any folder with the project venv:

```
backend\.venv\Scripts\python.exe backend\otp_doctor.py                 # .env, names, flags, port 5000
backend\.venv\Scripts\python.exe backend\otp_doctor.py --email-test    # real email to EMAIL_USER
backend\.venv\Scripts\python.exe backend\otp_doctor.py --telegram-test # getMe, username, webhook, 409
backend\.venv\Scripts\python.exe backend\otp_doctor.py --link-telegram # phone test (see below)
backend\.venv\Scripts\python.exe backend\otp_doctor.py --safebrowsing-test
```

| Doctor says | Meaning / fix |
| --- | --- |
| `535 ... BadCredentials` | app password wrong or revoked: create a new one (above) |
| `534` / `5.7.9` | app password required: turn on 2-Step Verification |
| timeout on 587, PASS on 465 | port blocked by antivirus/firewall; set `EMAIL_PORT=465` |
| TLS error | antivirus mail scanning intercepts TLS; disable it or use 465 |
| `tg.getMe` 401 | token revoked: BotFather `/token`, update `.env` |
| `tg.username` FAIL | set `TELEGRAM_BOT_USERNAME` to the printed real name |
| `tg.poller` 409 | a server (or second copy) is already polling; stop it |

Every delivery attempt is appended to `logs/otp_delivery.log` (channel, purpose,
hashed user id, ok, exception class; never a code, address or chat id).

## 3. Testing with a real phone

1. Stop the MLBFD server (the doctor and the server cannot both poll Telegram).
2. Run `--link-telegram`. Open the printed `https://t.me/<bot>?start=doctor_...` link
   on the phone, press **Start**, then tap **Share contact**.
3. Expect PASS lines and a "MLBFD test" message in Telegram within 90 s.
4. Run `--email-test`, then check the inbox (and Spam) of `EMAIL_USER`.
5. Start the server (`python serve.py`). The banner must show no `OTP DELIVERY WARNINGS`.
6. Register at `/register`: the email code arrives first; on the Telegram step open the
   link, press Start, Share Contact; the page detects the link and sends the Telegram code.

## 4. Readiness endpoint

`GET /api/health/otp` returns channel readiness and the OTP policy (no secrets).
Allowed from the server machine directly, or remotely with header `X-Admin-Token`
equal to `ADMIN_API_TOKEN`.

## Email provider notes (learned 2026-11-05)
- **Gmail (current):** `EMAIL_HOST=smtp.gmail.com`, `EMAIL_USER` = `EMAIL_FROM` = the exact account that created the app password (`mlbfd.alerts@gmail.com`), `EMAIL_SMTP_LOGIN` empty. No IP restrictions, so it keeps working when your home IP changes.
- **Brevo:** works only while the laptop's public IP is on its allow-list. Home IPs change, and Brevo then answers `525 5.7.1 Unauthorized IP address`. Fix: Brevo > Security > Authorized IPs > turn off "Block unknown IP addresses" (or re-add the IP). Symptoms: `otp_doctor.py --email-test` fails with 525 and `logs/otp_delivery.log` shows `SMTPAuthenticationError`.
- Always run `otp_doctor.py --email-test` after changing `.env`, then restart the server.
