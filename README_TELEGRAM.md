# MLBFD - Telegram Bot Setup Guide

This guide details step-by-step how to create and configure a free Telegram bot with **@BotFather** for MLBFD multi-factor OTP verification and transaction security alerts.

---

## 1. Creating Your Telegram Bot with @BotFather

1. Open Telegram (mobile app, desktop, or web at [web.telegram.org](https://web.telegram.org)).
2. In the search bar, search for `@BotFather` (verified bot with a blue checkmark).
3. Start a conversation by clicking **Start** or sending:
   ```text
   /start
   ```
4. Create a new bot by sending:
   ```text
   /newbot
   ```
5. Choose a display name for your bot, for example:
   ```text
   MLBFD Security Bot
   ```
6. Choose a unique username ending in `bot` (e.g. `mlbfd_otp_bot` or `mlbfd_<yourname>_bot`).
7. BotFather will reply with congratulations and your **API Token**:
   ```text
   Use this token to access the HTTP API:
   1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```

---

## 2. Configuring MLBFD Environment Variables

Add the token and bot username to your `.env` file (or `backend/.env`):

```bash
# Telegram Bot Channel Configuration
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_BOT_USERNAME=mlbfd_otp_bot
TELEGRAM_POLLING_ENABLED=true
TELEGRAM_DRY_RUN=false
```

For automated testing or offline development without internet:
```bash
TELEGRAM_DRY_RUN=true
```

---

## 3. How the MLBFD Telegram Bot Works

1. **User Verification Flow**:
   - Telegram bots cannot message a user until the user interacts with the bot.
   - When a user signs up or requests linking, MLBFD calls `POST /api/telegram/link_token`, generating a single-use 10-minute token and returning:
     `https://t.me/<BOT_USERNAME>?start=<token>`.
   - The user clicks the link, which opens the bot and triggers `/start <token>`.
   - MLBFD links the user's encrypted Telegram `chat_id` and prompts them to share their contact via a secure keyboard button (`request_contact=true`).
   - The bot verifies that the contact was shared by the sender (`contact.user_id == message.from.id`) and matches the registered account phone number.
   - Once verified, `telegram_verified` is set to `True`.
   - If there is a mismatch or spoof attempt, the link is revoked and chat unlinked.

2. **Delivery & Unlinking**:
   - `send_telegram(user, text)` dispatches messages via Telegram `sendMessage`.
   - If a user blocks the bot, Telegram returns HTTP 403; MLBFD automatically sets `telegram_chat_id = None` and `telegram_verified = False` to prevent stale states.

3. **Status Check**:
   - Frontend and mobile clients check `GET /api/telegram/status` to determine whether the user has completed Telegram binding.

---

## 4. Testing Without a Real Bot Token

If you are running automated tests or do not have a bot token yet:
- Run tests with `pytest tests/test_part6_telegram_channel.py` (all tests use mocked HTTP requests).
- Or set `TELEGRAM_DRY_RUN=true` in your `.env`.
