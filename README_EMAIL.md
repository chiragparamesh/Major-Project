# MLBFD Email Notification Service Configuration Guide

This guide provides step-by-step instructions for configuring the free SMTP email delivery channel for MLBFD multi-factor OTP verification.

---

## Option 1: Gmail App Password (Recommended - 100% Free)

Google accounts require an **App Password** rather than your regular account password to connect via SMTP.

### Step 1: Enable 2-Step Verification
1. Sign in to your Google Account at [https://myaccount.google.com](https://myaccount.google.com).
2. In the left navigation panel, click **Security**.
3. Under **How you sign in to Google**, ensure **2-Step Verification** is turned **ON**. (If not, follow Google's prompt to enable it).

### Step 2: Generate an App Password
1. In the search bar at the top of your Google Account page, search for **App passwords**.
   - Alternatively, navigate to: [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
2. Enter an app name, e.g., `MLBFD` or `MLBFD Fraud Detection`.
3. Click **Create**.
4. A modal will display a 16-character password (e.g., `abcd efgh ijkl mnop`).
5. **Copy this 16-character string** (spaces do not matter; you can remove them).

### Step 3: Configure `.env`
Open `MLBFD/.env` (and `MLBFD/backend/.env`) and set:

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=your_actual_email@gmail.com
EMAIL_PASSWORD=abcdefghijklmnop
EMAIL_FROM_NAME=MLBFD
EMAIL_FROM=your_actual_email@gmail.com
EMAIL_DRY_RUN=false
```

---

## Option 2: Brevo (Sendinblue) Free SMTP (300 Free Emails / Day)

If you prefer not to use a personal Gmail account, Brevo offers 300 free emails per day with zero credit card required:

1. Sign up for a free account at [https://www.brevo.com](https://www.brevo.com).
2. Navigate to **Transactional** > **Email** > **Settings** > **Configuration**.
3. Copy your SMTP server, port, login, and SMTP master key.
4. Configure in `MLBFD/.env`:

```env
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_USER=your_brevo_smtp_login
EMAIL_PASSWORD=your_brevo_smtp_key
EMAIL_FROM_NAME=MLBFD
EMAIL_FROM=your_verified_sender_email@domain.com
EMAIL_DRY_RUN=false
```

---

## Option 3: Dry-Run Mode (Testing & Offline Development)

For local development or running the automated test suite without contacting an external SMTP server, set:

```env
EMAIL_DRY_RUN=true
```

When `EMAIL_DRY_RUN=true`, the `EmailSender` records all outgoing messages in-memory (`email_sender.sent_emails`), logs dispatch events without revealing OTP codes in plaintext, and avoids network latency.

---

## Security & Privacy Guidelines
- **Never commit `.env`** to Git.
- **Never print or log OTP codes** in plain text or console logs.
- Codes are hashed using HMAC-SHA256 with the server key before being stored in the database.
- Transaction notification emails always mask payee UPI IDs (e.g., `j***@okaxis`) and display verified amounts.
