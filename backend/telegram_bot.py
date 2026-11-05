import os
import re
import secrets
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
import requests

from config import Config
from db import db
from database import User, TelegramLinkToken
from security import encrypt_val, decrypt_val, mask_upi
from user_manager import normalize_phone
from env_loader import env_str, clean_value, REPO_ROOT
import otp_delivery_log

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
POLLER_PID_FILE = os.path.join(REPO_ROOT, "logs", "telegram_poller.pid")
POLLER_STALE_SECONDS = 90  # lock older than this (no heartbeat) is taken over
_start_lock = threading.Lock()


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID exists (Windows-safe: never calls os.kill)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_poller_lock() -> bool:
    """One poller per machine: a second process polling getUpdates gets HTTP 409 Conflict."""
    try:
        os.makedirs(os.path.dirname(POLLER_PID_FILE), exist_ok=True)
        if os.path.exists(POLLER_PID_FILE):
            try:
                other = int(open(POLLER_PID_FILE).read().strip() or 0)
            except ValueError:
                other = 0
            # Windows reuses PIDs: also require a fresh heartbeat (the poller touches the file every loop).
            fresh = (time.time() - os.path.getmtime(POLLER_PID_FILE)) < POLLER_STALE_SECONDS
            if other and other != os.getpid() and _pid_alive(other) and fresh:
                logger.warning(f"Telegram polling NOT started: PID {other} already polls getUpdates.")
                return False
        with open(POLLER_PID_FILE, "w") as fh:
            fh.write(str(os.getpid()))
        return True
    except OSError as e:
        logger.error(f"Telegram poller lock unavailable ({type(e).__name__}); starting anyway")
        return True


def _release_poller_lock():
    try:
        if os.path.exists(POLLER_PID_FILE) and open(POLLER_PID_FILE).read().strip() == str(os.getpid()):
            os.remove(POLLER_PID_FILE)
    except OSError:
        pass

class TelegramBot:
    """
    MLBFD Telegram Bot Channel using only the requests library.
    Handles link tokens, long-polling getUpdates daemon, contact verification,
    and OTP dispatching.
    """
    def __init__(self, config=None, dry_run: Optional[bool] = None):
        self.config = config or Config
        self._dry_run = dry_run
        self.sent_messages: List[Dict[str, Any]] = []
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def token(self) -> str:
        return env_str("TELEGRAM_BOT_TOKEN") or clean_value(str(getattr(self.config, "TELEGRAM_BOT_TOKEN", "") or ""))

    @property
    def username(self) -> str:
        name = env_str("TELEGRAM_BOT_USERNAME") or getattr(self.config, "TELEGRAM_BOT_USERNAME", "") or "mlbfd_otp_bot"
        return clean_value(str(name)).lstrip("@")

    @property
    def is_dry_run(self) -> bool:

        if self._dry_run is not None:
            return self._dry_run
        env_val = os.getenv("TELEGRAM_DRY_RUN")
        if env_val is not None:
            return clean_value(env_val).lower() in ("true", "1", "yes")
        dry_run = getattr(self.config, "TELEGRAM_DRY_RUN", False)
        if isinstance(dry_run, bool):
            return dry_run
        return str(dry_run).strip().lower() in ("true", "1", "yes")

    @is_dry_run.setter
    def is_dry_run(self, val: bool):
        self._dry_run = val

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def create_link_token(self, user_id: str, expires_in_minutes: int = 10) -> Tuple[str, str]:
        """
        Generates a single-use 10-minute link token and returns:
        (token, https://t.me/<BOT_USERNAME>?start=<token>)
        """
        token = secrets.token_urlsafe(24)
        expires_at = datetime.utcnow() + timedelta(minutes=expires_in_minutes)

        link_token = TelegramLinkToken(
            token=token,
            user_id=user_id,
            expires_at=expires_at,
            used=False
        )
        db.session.add(link_token)
        db.session.commit()

        link_url = f"https://t.me/{self.username}?start={token}"
        return token, link_url

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, int, str]:
        """
        Sends message via Telegram sendMessage API using requests.
        Returns: (success: bool, status_code: int, response_text: str)
        """
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        if self.is_dry_run or not self.token or self.token == "MOCK":
            # Never log the text: it carries OTP codes.
            logger.info("[Telegram DRY RUN] message buffered")
            self.sent_messages.append(payload)
            return True, 200, "OK (dry run)"

        url = f"{self.base_url}/sendMessage"
        for attempt in range(2):
            try:
                resp = requests.post(url, json=payload, timeout=10)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Telegram sendMessage attempt {attempt + 1}/2 failed: {type(e).__name__}")
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                return False, 0, type(e).__name__
            if resp.status_code == 200:
                return True, 200, "OK"
            desc = ""
            retry_after = 0
            try:
                body = resp.json()
                desc = str(body.get("description", ""))[:120]
                retry_after = int((body.get("parameters") or {}).get("retry_after", 0))
            except ValueError:
                pass
            if resp.status_code == 429 and attempt == 0 and retry_after <= 10:
                logger.warning(f"Telegram 429 rate limited; retrying after {retry_after}s")
                time.sleep(max(1, retry_after))
                continue
            logger.warning(f"Telegram sendMessage returned {resp.status_code}: {desc}")
            return False, resp.status_code, desc
        return False, 0, "retry exhausted"

    def send_telegram(self, user_or_id, text: str) -> Tuple[bool, str]:
        res = self.send_telegram_status(user_or_id, text)
        return res["status"] in ("sent", "dry_run"), res["detail"]

    def send_telegram_status(self, user_or_id, text: str, purpose: str = "") -> Dict[str, str]:
        """
        Sends Telegram message to a user.
        On HTTP 403 (user blocked bot), marks user unlinked.
        Returns (success: bool, message: str)
        """
        user = user_or_id
        if isinstance(user_or_id, str):
            user = User.query.filter_by(user_id=user_or_id).first()

        if not user:
            return {"status": "failed", "detail": "User not found", "error_class": "NoUser"}
        uid = user.user_id

        chat_id_plain = user.get_decrypted_telegram_chat_id()
        if not chat_id_plain:
            # A bot cannot message anyone who has not pressed Start.
            logger.warning(f"telegram_bot: send skipped - user {uid} has not linked Telegram")
            otp_delivery_log.record("TELEGRAM", purpose, uid, False, "not linked", error_class="NotLinked")
            return {"status": "not_linked", "detail": "User has not linked Telegram", "error_class": ""}

        success, status_code, resp_text = self.send_message(chat_id_plain, text)
        if success:
            dry = self.is_dry_run or not self.token or self.token == "MOCK"
            otp_delivery_log.record("TELEGRAM", purpose, uid, True, "dry_run" if dry else "sent")
            return {"status": "dry_run" if dry else "sent", "detail": "Message sent", "error_class": ""}

        otp_delivery_log.record("TELEGRAM", purpose, uid, False, f"HTTP {status_code}",
                                error_class=f"HTTP{status_code}" if status_code else resp_text)
        if status_code == 403:
            logger.warning(f"User {user.user_id} blocked bot (HTTP 403). Unlinking user.")
            user.telegram_chat_id = None
            user.telegram_verified = False
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error unlinking user {user.user_id}: {e}")
            return {"status": "not_linked", "detail": "User unlinked: bot blocked by user (HTTP 403)",
                    "error_class": "HTTP403"}

        return {"status": "failed", "detail": f"Telegram delivery failed ({status_code}): {resp_text}",
                "error_class": f"HTTP{status_code}"}

    def format_otp_text(
        self,
        code: str,
        purpose: str,
        amount: Optional[float] = None,
        receiver: Optional[str] = None
    ) -> str:
        """
        Formats OTP notification for Telegram:
        'Your MLBFD code is 123456. Valid for 5 minutes. Purpose: <purpose>. Never share this code.'
        Transaction emails/messages show amount and masked receiver.
        """
        purpose_str = str(purpose or "VERIFICATION").strip().upper()
        msg = f"Your MLBFD code is <b>{code}</b>. Valid for 5 minutes. Purpose: <b>{purpose_str}</b>. Never share this code."
        if purpose_str == "TRANSACTION" and (amount is not None or receiver is not None):
            amt_formatted = f"Rs. {float(amount):,.2f}" if amount is not None else "N/A"
            rcv_masked = mask_upi(str(receiver)) if receiver else "N/A"
            msg += f"\n\n<b>Transaction Details:</b>\n• Amount: <b>{amt_formatted}</b>\n• Payee: <b>{rcv_masked}</b>"
        return msg

    def handle_update(self, update: Dict[str, Any], app=None) -> Dict[str, Any]:
        """
        Handles an individual update from getUpdates.
        Processes:
        1. /start <token> -> Link chat_id, prompt for contact
        2. contact -> Verify sender identity, check against registered phone, verify or unlink
        """
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return {"status": "no_message"}

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        from_user = msg.get("from", {})
        from_id = from_user.get("id")

        if not chat_id:
            return {"status": "no_chat_id"}

        text = msg.get("text", "").strip() if msg.get("text") else ""

        # Case 1: /start with token
        if text.startswith("/start"):
            parts = text.split(None, 1)
            if len(parts) > 1:
                token_val = parts[1].strip()
                now = datetime.utcnow()
                link_rec = TelegramLinkToken.query.filter_by(token=token_val, used=False).first()
                if not link_rec or link_rec.expires_at < now:
                    self.send_message(
                        chat_id,
                        "⚠️ <b>Link Expired or Invalid</b>\n\n"
                        "This link token is invalid or has expired (valid for 10 minutes).\n"
                        "Please request a new link in your MLBFD app or dashboard."
                    )
                    return {"status": "invalid_or_expired_token"}

                link_rec.used = True
                user = User.query.filter_by(user_id=link_rec.user_id).first()
                if not user:
                    self.send_message(chat_id, "❌ <b>Account Not Found</b>\n\nUser account not found.")
                    db.session.commit()
                    return {"status": "user_not_found"}

                # Store encrypted chat_id
                user.telegram_chat_id = encrypt_val(str(chat_id))
                user.telegram_verified = False
                db.session.commit()

                # Prompt user for contact
                keyboard = {
                    "keyboard": [
                        [{"text": "📱 Share Registered Contact", "request_contact": True}]
                    ],
                    "resize_keyboard": True,
                    "one_time_keyboard": True
                }
                self.send_message(
                    chat_id,
                    "🔒 <b>MLBFD Account Verification</b>\n\n"
                    f"Hello {user.full_name or user.user_id}!\n"
                    "To complete Telegram verification for your account, please tap the button below to share your registered contact number.",
                    reply_markup=keyboard
                )
                return {"status": "start_token_linked", "user_id": user.user_id}
            else:
                self.send_message(
                    chat_id,
                    "👋 <b>Welcome to MLBFD Security Bot</b>\n\n"
                    "To link your account, please generate a link from the MLBFD registration or settings page."
                )
                return {"status": "start_no_token"}

        # Case 2: Contact message
        contact = msg.get("contact")
        if contact:
            # Rule: require contact.user_id == message.from.id
            contact_user_id = contact.get("user_id")
            remove_kb = {"remove_keyboard": True}

            if contact_user_id is None or from_id is None or contact_user_id != from_id:
                self.send_message(
                    chat_id,
                    "❌ <b>Security Verification Failed</b>\n\n"
                    "The shared contact does not match your Telegram sender ID. "
                    "You may only share your own contact.",
                    reply_markup=remove_kb
                )
                return {"status": "contact_spoof_rejected"}

            # Telegram sends "919876543210" or "+919876543210"; compare normalized E.164.
            shared_phone = normalize_phone(contact.get("phone_number", ""))

            # Find user linked to this chat_id
            users_with_tg = User.query.filter(User.telegram_chat_id.isnot(None)).all()
            matched_user = None
            for u in users_with_tg:
                if u.get_decrypted_telegram_chat_id() == str(chat_id):
                    matched_user = u
                    break

            if not matched_user:
                self.send_message(
                    chat_id,
                    "⚠️ <b>No Account Linked</b>\n\n"
                    "Please link your MLBFD account using the registration link first.",
                    reply_markup=remove_kb
                )
                return {"status": "no_linked_user"}

            reg_phone = normalize_phone(matched_user.get_decrypted_phone())
            if shared_phone.startswith("+") and reg_phone.startswith("+") and shared_phone == reg_phone:
                matched_user.telegram_verified = True
                db.session.commit()
                self.send_message(
                    chat_id,
                    "✅ <b>Telegram Verification Successful!</b>\n\n"
                    "Your MLBFD account is now fully verified. You will receive two-factor OTPs and real-time security alerts here.",
                    reply_markup=remove_kb
                )
                return {"status": "verified", "user_id": matched_user.user_id}
            else:
                # Mismatch: reject and unlink
                matched_user.telegram_chat_id = None
                matched_user.telegram_verified = False
                db.session.commit()
                self.send_message(
                    chat_id,
                    "❌ <b>Verification Mismatch</b>\n\n"
                    "The phone number shared from Telegram does not match the phone number registered with your MLBFD account.\n"
                    "Your Telegram chat has been unlinked.",
                    reply_markup=remove_kb
                )
                return {"status": "phone_mismatch_unlinked", "user_id": matched_user.user_id}

        return {"status": "unhandled_message"}

    def poll_updates_once(self, offset: int = 0, timeout: int = 20, app=None) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Polls getUpdates once using requests and processes received updates.
        Returns (new_offset, processed_results)
        """
        if self.is_dry_run or not self.token or self.token == "MOCK":
            return offset, []

        url = f"{self.base_url}/getUpdates"
        params = {"offset": offset, "timeout": timeout}
        try:
            resp = requests.get(url, params=params, timeout=timeout + 5)
            if resp.status_code in (401, 404):
                logger.warning(
                    f"Telegram bot token invalid or not found (HTTP {resp.status_code}: {resp.text}). "
                    "Disabling polling daemon to avoid log flooding."
                )
                self.stop_polling()
                return offset, []
            elif resp.status_code == 409:
                # Another process is polling (or a webhook is set). Back off instead of spinning.
                logger.warning("getUpdates HTTP 409 Conflict: another poller/webhook is active; backing off 30s")
                self._stop_event.wait(30)
                return offset, []
            elif resp.status_code == 429:
                try:
                    wait = int((resp.json().get("parameters") or {}).get("retry_after", 5))
                except ValueError:
                    wait = 5
                self._stop_event.wait(min(wait, 60))
                return offset, []
            elif resp.status_code != 200:
                logger.warning(f"getUpdates returned {resp.status_code}")
                return offset, []

            data = resp.json()
            if not data.get("ok"):
                return offset, []

            updates = data.get("result", [])
            results = []
            new_offset = offset
            for u in updates:
                uid = u.get("update_id")
                if uid is not None and uid >= new_offset:
                    new_offset = uid + 1
                res = self.handle_update(u, app=app)
                results.append(res)
            return new_offset, results
        except requests.exceptions.Timeout:
            return offset, []
        except requests.exceptions.RequestException as e:
            logger.warning(f"Telegram getUpdates network error: {type(e).__name__}")
            self._stop_event.wait(5)
            return offset, []

    def start_polling(self, app=None):
        """
        Starts the getUpdates long-polling daemon thread.
        Guarded against starting twice.
        """
        with _start_lock:
            self._start_polling_locked(app)

    def _start_polling_locked(self, app=None):
        if self._polling_thread and self._polling_thread.is_alive():
            logger.info("Telegram polling thread already running.")
            return

        if self.is_dry_run or not self.token or self.token == "MOCK":
            logger.info("Telegram polling skipped (dry-run or no token configured).")
            return

        polling_enabled = getattr(self.config, "TELEGRAM_POLLING_ENABLED", True)
        if str(polling_enabled).strip().lower() in ("false", "0", "no"):
            logger.info("Telegram polling disabled via configuration.")
            return

        # Validate standard BotFather format (<digits>:<secret>)
        if not TOKEN_RE.match(str(self.token).strip()):
            logger.warning(
                "TELEGRAM_BOT_TOKEN is not in valid Telegram BotFather format (<bot_id>:<secret>). "
                "Telegram polling daemon disabled. Dual OTP continues in dry-run/mock mode."
            )
            return

        if not _acquire_poller_lock():
            return

        self._stop_event.clear()

        def _poller():
            logger.info(f"Telegram bot polling daemon started (pid {os.getpid()}).")
            offset = 0
            failures = 0
            while not self._stop_event.is_set():
                try:
                    if app:
                        with app.app_context():
                            offset, _ = self.poll_updates_once(offset=offset, timeout=25, app=app)
                    else:
                        offset, _ = self.poll_updates_once(offset=offset, timeout=25)
                    failures = 0
                    try:
                        os.utime(POLLER_PID_FILE, None)  # heartbeat for the cross-process lock
                    except OSError:
                        pass
                except Exception:
                    # Keep the daemon alive: log with traceback, roll back, back off exponentially.
                    failures += 1
                    logger.exception(f"Telegram poller crashed (failure {failures}); restarting with backoff")
                    try:
                        db.session.rollback()
                    except Exception:
                        logger.exception("Telegram poller: session rollback failed")
                    self._stop_event.wait(min(60, 2 ** min(failures, 6)))
                self._stop_event.wait(0.5)
            _release_poller_lock()
            logger.info("Telegram bot polling daemon stopped.")

        self._polling_thread = threading.Thread(target=_poller, daemon=True, name="TelegramBotPoller")
        self._polling_thread.start()

    def stop_polling(self):
        """Stops the polling daemon thread."""
        self._stop_event.set()
        if (
            self._polling_thread
            and self._polling_thread.is_alive()
            and threading.current_thread() != self._polling_thread
        ):
            self._polling_thread.join(timeout=2)


# Global singleton
telegram_bot = TelegramBot()
default_telegram_bot = telegram_bot

def get_telegram_bot() -> TelegramBot:
    return telegram_bot

def send_telegram(user, text: str) -> Tuple[bool, str]:
    """Helper to dispatch Telegram message using global bot instance."""
    return telegram_bot.send_telegram(user, text)

class TelegramOtpSender:
    """
    Adapter registering TelegramBot as the TELEGRAM channel sender in otp_service.
    """
    def __init__(self, bot: Optional[TelegramBot] = None):
        self.bot = bot or telegram_bot

    def send(self, user: Any, channel: str, message: str, **kwargs) -> Dict[str, str]:
        if str(channel).strip().upper() != "TELEGRAM":
            return {"status": "failed", "detail": "wrong channel", "error_class": "ChannelMismatch"}
        m = re.search(r"Purpose:\s*(?:<b>)?([A-Za-z0-9_]+)", message)
        return self.bot.send_telegram_status(user, message, purpose=m.group(1) if m else "")

default_telegram_otp_sender = TelegramOtpSender(telegram_bot)

def register_as_telegram_sender():
    """Registers default_telegram_otp_sender in otp_service for the TELEGRAM channel."""
    from otp_service import register_channel_sender
    register_channel_sender("TELEGRAM", default_telegram_otp_sender)
    logger.info("✅ TelegramOtpSender successfully registered with otp_service for TELEGRAM channel.")
