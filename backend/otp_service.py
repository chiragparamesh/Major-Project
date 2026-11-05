import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, Union, Tuple, Any, Dict

from config import Config
from db import db
from database import User, OtpCode
from security import mask_upi

logger = logging.getLogger(__name__)

# Valid constants
VALID_PURPOSES = {
    'SIGNUP',
    'LOGIN_NEW_DEVICE',
    'TRANSACTION',
    'PIN_CHANGE',
    'PIN_RESET',
    'ACCOUNT_DELETE'
}

VALID_CHANNELS = {
    'EMAIL',
    'TELEGRAM'
}

# One policy for every purpose: 300 s expiry, 3 attempts, 30 s resend cooldown.
EXPIRY_SECONDS = 300
EXPIRY_MINUTES = EXPIRY_SECONDS // 60
COOLDOWN_SECONDS = 30
EMAIL_WAIT_SECONDS = 8  # longest an OTP request waits for SMTP before answering "pending"
HOURLY_LIMIT = 5
MAX_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Clock Abstraction (Enables testing with a fake clock)
# ---------------------------------------------------------------------------
class Clock:
    """Standard system clock based on UTC time."""
    def now(self) -> datetime:
        return datetime.utcnow()

class FakeClock(Clock):
    """Controllable test clock for testing expiry, cooldowns, and rate limits."""
    def __init__(self, initial_time: Optional[datetime] = None):
        self._current = initial_time or datetime(2026, 1, 1, 12, 0, 0)

    def now(self) -> datetime:
        return self._current

    def advance(self, seconds: float = 0, minutes: float = 0, hours: float = 0):
        self._current += timedelta(seconds=seconds, minutes=minutes, hours=hours)

    def set_time(self, new_time: datetime):
        self._current = new_time

_active_clock: Clock = Clock()

def get_clock() -> Clock:
    return _active_clock

def set_clock(clock: Clock):
    global _active_clock
    _active_clock = clock

def reset_clock():
    global _active_clock
    _active_clock = Clock()

# ---------------------------------------------------------------------------
# Sender Interface & Mock Sender
# ---------------------------------------------------------------------------
class BaseOtpSender:
    """Sender interface for dispatching OTP messages across channels."""
    def send(self, user: Any, channel: str, message: str, **kwargs) -> bool:
        raise NotImplementedError

class MockOtpSender(BaseOtpSender):
    """
    Mock sender for unit and integration testing.
    Records sent messages in-memory.
    Never prints or logs OTP codes to terminal or system loggers.
    """
    def __init__(self):
        self.messages = []

    def send(self, user: Any, channel: str, message: str, **kwargs) -> bool:
        user_id = user.user_id if hasattr(user, 'user_id') else str(user)
        self.messages.append({
            "user_id": user_id,
            "channel": channel,
            "message": message,
            "amount": kwargs.get('amount'),
            "receiver": kwargs.get('receiver'),
            "sent_at": get_clock().now()
        })
        return True

    def clear(self):
        self.messages.clear()

    @property
    def count(self) -> int:
        return len(self.messages)

_active_sender: BaseOtpSender = MockOtpSender()
_channel_senders: Dict[str, BaseOtpSender] = {}

def get_sender() -> BaseOtpSender:
    return _active_sender

def set_sender(sender: BaseOtpSender):
    global _active_sender
    _active_sender = sender
    _channel_senders.clear()

def register_channel_sender(channel: str, sender: BaseOtpSender):
    """Registers a channel-specific sender (e.g. EMAIL or TELEGRAM)"""
    global _channel_senders
    _channel_senders[str(channel).strip().upper()] = sender

def get_channel_sender(channel: str) -> BaseOtpSender:
    """Gets the channel-specific sender or falls back to the default sender"""
    ch = str(channel).strip().upper()
    return _channel_senders.get(ch, _active_sender)

def clear_channel_senders():
    """Clears channel-specific senders, reverting to default sender"""
    global _channel_senders
    _channel_senders.clear()

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class OtpError(Exception):
    """Base exception for OTP service errors."""
    pass

class OtpRateLimitError(OtpError):
    """Raised when request rate limit is exceeded."""
    pass

class OtpCooldownError(OtpRateLimitError):
    """Raised when requests occur within the 30-second cooldown period."""
    pass

class OtpDispatchError(OtpError):
    """Raised when a channel sender fails to deliver an OTP message."""
    def __init__(self, message: str, delivery: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.delivery = delivery or {}


# Per-channel delivery states reported to the API/UI.
DELIVERED_STATES = ("sent", "dry_run", "pending")


def _normalize_send_result(ret: Any) -> Dict[str, str]:
    """Senders may return bool (legacy/mock) or {"status", "detail", "error_class"}."""
    if isinstance(ret, dict):
        out = {"status": str(ret.get("status") or "failed"), "detail": str(ret.get("detail") or ""),
               "error_class": str(ret.get("error_class") or "")}
        if callable(ret.get("_join")):
            out["_join"] = ret["_join"]
        return out
    return {"status": "sent" if ret else "failed", "detail": "", "error_class": ""}


def _dispatch(user: Any, channel: str, message: str, **kwargs) -> Dict[str, str]:
    """Send through the registered sender; never swallow: exceptions become status=failed + log."""
    sender = get_channel_sender(channel)
    user_id = _extract_user_id(user)
    logger.info(f"OTP dispatch starting user={user_id} channel={channel} sender={type(sender).__name__}")
    try:
        res = _normalize_send_result(sender.send(user, channel, message, **kwargs))
    except Exception as e:
        logger.exception(f"OTP dispatch raised for user={user_id} channel={channel}")
        res = {"status": "failed", "detail": "sender error", "error_class": type(e).__name__}
    logger.info(f"OTP dispatch finished user={user_id} channel={channel} status={res['status']}")
    return res


class IssuedCode(str):
    """The 6-digit code (a str) plus the channel delivery result in `.delivery`."""
    delivery: Dict[str, str] = {}

# ---------------------------------------------------------------------------
# Dual OTP Result Helper
# ---------------------------------------------------------------------------
class DualOtpResult(tuple):
    """
    Two-channel OTP result that behaves as a 2-tuple (email, telegram),
    supports attribute access (.email_code, .telegram_code),
    and dict-like indexing (result['EMAIL'], result['TELEGRAM']).
    """
    def __new__(cls, email_code: str, telegram_code: str, delivery: Optional[Dict[str, Dict[str, str]]] = None):
        obj = super().__new__(cls, (email_code, telegram_code))
        obj.delivery = delivery or {}
        return obj

    @property
    def channel_status(self) -> Dict[str, str]:
        """{"email": "sent", "telegram": "not_linked"} for the API."""
        return {k: v.get("status", "failed") for k, v in self.delivery.items()}

    @property
    def email_code(self) -> str:
        return self[0]

    @property
    def telegram_code(self) -> str:
        return self[1]

    def __getitem__(self, item):
        if isinstance(item, str):
            clean = item.strip().upper()
            if clean == 'EMAIL':
                return self[0]
            if clean == 'TELEGRAM':
                return self[1]
        return super().__getitem__(item)

    def get(self, key: str, default=None):
        clean = str(key).strip().upper()
        if clean == 'EMAIL':
            return self[0]
        if clean == 'TELEGRAM':
            return self[1]
        return default

# ---------------------------------------------------------------------------
# Core Utilities
# ---------------------------------------------------------------------------
def _extract_user_id(user: Any) -> str:
    if hasattr(user, 'user_id'):
        return str(user.user_id).strip()
    return str(user).strip()

def hash_code_hmac(code: str, secret_key: Optional[str] = None) -> str:
    """
    Computes HMAC-SHA256 of code using server secret key.
    Ensures secure, irreversible storage without reversible plaintext.
    """
    key = (secret_key or Config.SECRET_KEY).encode('utf-8')
    return hmac.new(key, str(code).strip().encode('utf-8'), hashlib.sha256).hexdigest()

def generate_otp_code() -> str:
    """
    Generates a secure 6-digit numeric OTP code using secrets.randbelow.
    Guarantees uniform cryptographically secure randomness.
    """
    return f"{secrets.randbelow(1000000):06d}"

# ---------------------------------------------------------------------------
# Rate Limiting & Cooldown Checks
# ---------------------------------------------------------------------------
def _check_rate_limits(user_id: str, purpose: str, channel: Optional[str] = None, ip_address: Optional[str] = None, now: Optional[datetime] = None):
    now = now or get_clock().now()

    # 1. 30-Second Resend Cooldown per user+purpose+channel (prevents rapid resends on same channel)
    cooldown_cutoff = now - timedelta(seconds=COOLDOWN_SECONDS)
    cooldown_query = OtpCode.query.filter(
        OtpCode.user_id == user_id,
        OtpCode.purpose == purpose,
        OtpCode.created_at >= cooldown_cutoff
    )
    if channel:
        cooldown_query = cooldown_query.filter(OtpCode.channel == channel)
    recent_issue = cooldown_query.first()
    if recent_issue:
        raise OtpCooldownError("Resend cooldown active. Please wait 30 seconds before requesting another code.")


    # 2. Limit of 5 issues per hour per user+purpose
    hour_cutoff = now - timedelta(hours=1)
    # Count distinct issuance events (grouping dual-issues by dual_group_id if present)
    user_records = OtpCode.query.filter(
        OtpCode.user_id == user_id,
        OtpCode.purpose == purpose,
        OtpCode.created_at >= hour_cutoff
    ).all()
    
    unique_events = set()
    for r in user_records:
        unique_events.add(r.dual_group_id if r.dual_group_id else f"single_{r.id}")
    if len(unique_events) >= HOURLY_LIMIT:
        raise OtpRateLimitError(f"Hourly rate limit exceeded: Maximum {HOURLY_LIMIT} OTP requests per hour per purpose.")

    # 3. Limit of 5 issues per hour per IP
    if ip_address:
        ip_records = OtpCode.query.filter(
            OtpCode.ip_address == ip_address,
            OtpCode.created_at >= hour_cutoff
        ).all()
        unique_ip_events = set()
        for r in ip_records:
            unique_ip_events.add(r.dual_group_id if r.dual_group_id else f"single_{r.id}")
        if len(unique_ip_events) >= HOURLY_LIMIT:
            raise OtpRateLimitError(f"Hourly rate limit exceeded: Maximum {HOURLY_LIMIT} OTP requests per hour for this IP.")

def _invalidate_older_unused_codes(user_id: str, purpose: str, channel: Optional[str] = None, txn_id: Optional[str] = None, now: Optional[datetime] = None):
    now = now or get_clock().now()
    query = OtpCode.query.filter(
        OtpCode.user_id == user_id,
        OtpCode.purpose == purpose,
        OtpCode.used_at.is_(None),
        OtpCode.expires_at > now
    )
    if channel:
        query = query.filter(OtpCode.channel == channel)
    if txn_id:
        query = query.filter(OtpCode.txn_id == txn_id)
        
    older_codes = query.all()
    for code_rec in older_codes:
        # Expire and invalidate older unused code
        code_rec.expires_at = now - timedelta(seconds=1)
    if older_codes:
        db.session.commit()

# ---------------------------------------------------------------------------
# Public Service API
# ---------------------------------------------------------------------------
def issue(
    user: Any,
    purpose: str,
    channel: str,
    txn_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    amount: Optional[float] = None,
    receiver: Optional[str] = None,
    require_delivery: bool = False
) -> str:
    """
    Generates a 6-digit code with secrets.randbelow and invalidates older unused codes.
    Enforces 30-second cooldown and 5 per hour limits (per user+purpose and per IP).
    Dispatches message via registered sender interface.
    Never logs codes.
    When require_delivery=True, raises OtpDispatchError if the sender reports failure
    (used by registration so the UI cannot claim an OTP was sent when it was not).
    Returns: 6-digit OTP code string.
    """
    purpose = str(purpose).strip().upper()
    channel = str(channel).strip().upper()

    if purpose not in VALID_PURPOSES:
        raise ValueError(f"Invalid purpose '{purpose}'. Must be one of {sorted(list(VALID_PURPOSES))}")
    if channel not in VALID_CHANNELS:
        raise ValueError(f"Invalid channel '{channel}'. Must be one of {sorted(list(VALID_CHANNELS))}")

    user_id = _extract_user_id(user)
    now = get_clock().now()

    # Rate limiting & cooldown validation
    _check_rate_limits(user_id, purpose, channel=channel, ip_address=ip_address, now=now)

    # Invalidate older unused codes for this user, purpose, channel, and txn_id
    _invalidate_older_unused_codes(user_id, purpose, channel=channel, txn_id=txn_id, now=now)

    # Generate 6-digit secure code & compute HMAC
    code = generate_otp_code()
    code_hash = hash_code_hmac(code)
    expiry_mins = EXPIRY_MINUTES
    expires_at = now + timedelta(seconds=EXPIRY_SECONDS)

    record = OtpCode(
        user_id=user_id,
        purpose=purpose,
        channel=channel,
        code_hash=code_hash,
        txn_id=txn_id,
        expires_at=expires_at,
        attempts=0,
        max_attempts=MAX_ATTEMPTS,
        used_at=None,
        created_at=now,
        ip_address=ip_address,
        dual_group_id=None
    )
    db.session.add(record)
    db.session.commit()

    # Never log code: log only audit event without secret
    logger.info(f"OTP issued for user {user_id} on channel {channel} for purpose {purpose}")

    # Dispatch via sender interface
    message = f"Your MLBFD code is {code}. Valid for {expiry_mins} minutes. Purpose: {purpose}. Never share this code."
    if purpose == "TRANSACTION" and (amount is not None or receiver is not None):
        amt_formatted = f"Rs. {float(amount):,.2f}" if amount is not None else "N/A"
        rcv_masked = mask_upi(str(receiver)) if receiver else "N/A"
        message += f"\nTransaction Details:\n- Amount: {amt_formatted}\n- Payee: {rcv_masked}\n"

    res = _dispatch(user, channel, message, amount=amount, receiver=receiver)
    res.pop("_join", None)
    if require_delivery and res["status"] not in DELIVERED_STATES:
        # Undelivered code must not stay valid (and must not count toward the cooldown).
        db.session.delete(record)
        db.session.commit()
        raise OtpDispatchError(f"{channel} delivery failed for user {user_id}: {res['detail']}",
                               delivery={channel.lower(): res})

    issued = IssuedCode(code)
    issued.delivery = {channel.lower(): res}
    return issued

def verify(
    user: Any,
    purpose: str,
    channel: str,
    code: str,
    txn_id: Optional[str] = None
) -> bool:
    """
    Verifies an OTP code using constant-time HMAC comparison.
    Enforces:
    - Expiry within 5 minutes (or 10 minutes for transactions)
    - Maximum 3 attempts before code lockout
    - Marks used_at upon successful verification (prevents replay/reuse)
    Never logs codes.
    Returns: bool
    """
    if not code:
        return False

    purpose = str(purpose).strip().upper()
    channel = str(channel).strip().upper()
    user_id = _extract_user_id(user)
    now = get_clock().now()

    query = OtpCode.query.filter(
        OtpCode.user_id == user_id,
        OtpCode.purpose == purpose,
        OtpCode.channel == channel
    )
    if txn_id:
        query = query.filter(OtpCode.txn_id == txn_id)
        
    record = query.order_by(OtpCode.created_at.desc()).first()
    if not record:
        logger.warning(f"No active OTP record found for user {user_id} channel {channel}")
        return False

    # Check if already consumed / reused
    if record.used_at is not None:
        logger.warning(f"Attempt to reuse consumed OTP for user {user_id} channel {channel}")
        return False

    # Check expiry
    if now > record.expires_at:
        logger.warning(f"OTP expired for user {user_id} channel {channel}")
        return False

    # Check if maximum attempts reached
    if record.attempts >= record.max_attempts:
        logger.warning(f"OTP maximum attempts exceeded for user {user_id} channel {channel}")
        return False

    # Constant-time HMAC comparison
    expected_hash = record.code_hash
    candidate_hash = hash_code_hmac(code)
    is_valid = hmac.compare_digest(expected_hash, candidate_hash)

    if is_valid:
        record.used_at = now
        db.session.commit()
        logger.info(f"OTP verified successfully for user {user_id} channel {channel}")
        return True
    else:
        record.attempts += 1
        db.session.commit()
        logger.warning(f"OTP verification failed (attempt {record.attempts}/{record.max_attempts}) for user {user_id}")
        return False

def issue_dual(
    user: Any,
    purpose: str,
    txn_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    amount: Optional[float] = None,
    receiver: Optional[str] = None
) -> DualOtpResult:
    """
    Creates independent 6-digit codes for both channels (EMAIL and TELEGRAM).
    Shares a dual_group_id so verify_dual shares an attempt counter.
    Enforces 30-second cooldown and 5 per hour limits.
    Never logs codes.
    Returns: DualOtpResult(email_code, telegram_code)
    """
    purpose = str(purpose).strip().upper()
    if purpose not in VALID_PURPOSES:
        raise ValueError(f"Invalid purpose '{purpose}'. Must be one of {sorted(list(VALID_PURPOSES))}")

    user_id = _extract_user_id(user)
    now = get_clock().now()

    # Rate limiting & cooldown validation
    _check_rate_limits(user_id, purpose, ip_address=ip_address, now=now)

    # Invalidate older unused codes for both channels
    _invalidate_older_unused_codes(user_id, purpose, txn_id=txn_id, now=now)

    # Generate independent codes for each channel
    email_code = generate_otp_code()
    telegram_code = generate_otp_code()
    # Guarantee they differ
    while email_code == telegram_code:
        telegram_code = generate_otp_code()

    group_id = str(uuid.uuid4())
    expiry_mins = EXPIRY_MINUTES
    expires_at = now + timedelta(seconds=EXPIRY_SECONDS)

    email_record = OtpCode(
        user_id=user_id,
        purpose=purpose,
        channel='EMAIL',
        code_hash=hash_code_hmac(email_code),
        txn_id=txn_id,
        expires_at=expires_at,
        attempts=0,
        max_attempts=MAX_ATTEMPTS,
        used_at=None,
        created_at=now,
        ip_address=ip_address,
        dual_group_id=group_id
    )

    telegram_record = OtpCode(
        user_id=user_id,
        purpose=purpose,
        channel='TELEGRAM',
        code_hash=hash_code_hmac(telegram_code),
        txn_id=txn_id,
        expires_at=expires_at,
        attempts=0,
        max_attempts=MAX_ATTEMPTS,
        used_at=None,
        created_at=now,
        ip_address=ip_address,
        dual_group_id=group_id
    )

    db.session.add(email_record)
    db.session.add(telegram_record)
    db.session.commit()

    logger.info(f"Dual OTPs issued for user {user_id} across EMAIL and TELEGRAM for purpose {purpose}")

    # Build formatted messages
    amt_formatted = f"Rs. {float(amount):,.2f}" if amount is not None else "N/A"
    rcv_masked = mask_upi(str(receiver)) if receiver else "N/A"

    email_msg = f"Your MLBFD code is {email_code}. Valid for {expiry_mins} minutes. Purpose: {purpose}. Never share this code."
    if purpose == "TRANSACTION" and (amount is not None or receiver is not None):
        email_msg += f"\nTransaction Details:\n- Amount: {amt_formatted}\n- Payee: {rcv_masked}\n"

    telegram_msg = f"Your MLBFD code is <b>{telegram_code}</b>. Valid for {expiry_mins} minutes. Purpose: <b>{purpose}</b>. Never share this code."
    if purpose == "TRANSACTION" and (amount is not None or receiver is not None):
        telegram_msg += f"\n\n<b>Transaction Details:</b>\n• Amount: <b>{amt_formatted}</b>\n• Payee: <b>{rcv_masked}</b>"

    # Overlap the channels: SMTP starts in its own thread (wait=0), Telegram is sent meanwhile,
    # then we wait at most EMAIL_WAIT_SECONDS in total. A slow SMTP reports "pending"; its final
    # outcome is still written to logs/otp_delivery.log.
    import time as _time
    t0 = _time.monotonic()
    email_res = _dispatch(user, 'EMAIL', email_msg, amount=amount, receiver=receiver, wait=0)
    telegram_res = _dispatch(user, 'TELEGRAM', telegram_msg, amount=amount, receiver=receiver)
    join = email_res.pop("_join", None)
    if join:
        email_res = _normalize_send_result(join(EMAIL_WAIT_SECONDS - (_time.monotonic() - t0)))
        email_res.pop("_join", None)
    delivery = {"telegram": telegram_res, "email": email_res}
    return DualOtpResult(email_code, telegram_code, delivery)


def resend_channel(
    user: Any,
    purpose: str,
    channel: str,
    txn_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    amount: Optional[float] = None,
    receiver: Optional[str] = None,
) -> Dict[str, str]:
    """
    Re-issue ONE channel's code inside the latest dual group (per-channel Resend button).
    Keeps the group's shared attempt counter and expiry policy; enforces the 30 s cooldown
    for that channel. Returns the channel delivery status.
    """
    purpose = str(purpose).strip().upper()
    channel = str(channel).strip().upper()
    if channel not in VALID_CHANNELS:
        raise ValueError(f"Invalid channel '{channel}'")
    user_id = _extract_user_id(user)
    now = get_clock().now()
    q = OtpCode.query.filter(OtpCode.user_id == user_id, OtpCode.purpose == purpose,
                             OtpCode.channel == channel, OtpCode.dual_group_id.isnot(None))
    if txn_id:
        q = q.filter(OtpCode.txn_id == txn_id)
    rec = q.order_by(OtpCode.created_at.desc()).first()
    if not rec or rec.used_at is not None:
        raise OtpError("No active verification to resend. Start again.")
    if rec.attempts >= rec.max_attempts:
        raise OtpError("Maximum attempts reached. Start again.")
    if (now - rec.created_at).total_seconds() < COOLDOWN_SECONDS:
        raise OtpCooldownError("Resend cooldown active. Please wait 30 seconds before requesting another code.")
    code = generate_otp_code()
    rec.code_hash = hash_code_hmac(code)
    rec.created_at = now
    rec.expires_at = now + timedelta(seconds=EXPIRY_SECONDS)
    db.session.commit()
    if channel == "TELEGRAM":
        msg = (f"Your MLBFD code is <b>{code}</b>. Valid for {EXPIRY_MINUTES} minutes. "
               f"Purpose: <b>{purpose}</b>. Never share this code.")
    else:
        msg = f"Your MLBFD code is {code}. Valid for {EXPIRY_MINUTES} minutes. Purpose: {purpose}. Never share this code."
    return _dispatch(user, channel, msg, amount=amount, receiver=receiver)


def channel_readiness() -> Dict[str, Dict[str, Any]]:
    """Secret-free readiness of both channels for the startup banner and /api/health/otp."""
    from env_loader import env_str, env_bool, is_placeholder
    import re as _re
    email_user = env_str("EMAIL_SMTP_LOGIN") or env_str("EMAIL_USER", "SMTP_USER")
    email_pw = env_str("EMAIL_PASSWORD", "SMTP_PASS")
    token = env_str("TELEGRAM_BOT_TOKEN")
    email = {
        "sender_registered": "EMAIL" in _channel_senders,
        "dry_run": env_bool("EMAIL_DRY_RUN"),
        "user": "set" if not is_placeholder(email_user) else "empty/MOCK",
        "password": "set" if not is_placeholder(email_pw) else "empty/MOCK",
    }
    email["ready"] = bool(email["sender_registered"] and not email["dry_run"]
                          and email["user"] == "set" and email["password"] == "set")
    tg = {
        "sender_registered": "TELEGRAM" in _channel_senders,
        "dry_run": env_bool("TELEGRAM_DRY_RUN"),
        "polling_enabled": env_bool("TELEGRAM_POLLING_ENABLED", True),
        "token": ("looks-valid" if _re.match(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$", token or "")
                  else ("empty/MOCK" if is_placeholder(token) else "invalid-format")),
        "bot_username": env_str("TELEGRAM_BOT_USERNAME", default="mlbfd_otp_bot").lstrip("@"),
    }
    tg["ready"] = bool(tg["sender_registered"] and not tg["dry_run"] and tg["polling_enabled"]
                       and tg["token"] == "looks-valid")
    return {"email": email, "telegram": tg}


def verify_dual(
    user: Any,
    purpose: str,
    email_code: str,
    telegram_code: str,
    txn_id: Optional[str] = None
) -> bool:
    """
    Verifies dual OTP codes for both channels (EMAIL and TELEGRAM).
    - Succeeds ONLY if both codes are correct.
    - Shares one attempt counter across both channels.
    - Consumes both codes on success (sets used_at = now).
    Never logs codes.
    Returns: bool
    """
    if not email_code or not telegram_code:
        return False

    purpose = str(purpose).strip().upper()
    user_id = _extract_user_id(user)
    now = get_clock().now()

    # Query for the latest dual group record for this user and purpose
    query = OtpCode.query.filter(
        OtpCode.user_id == user_id,
        OtpCode.purpose == purpose,
        OtpCode.dual_group_id.isnot(None)
    )
    if txn_id:
        query = query.filter(OtpCode.txn_id == txn_id)
        
    latest_rec = query.order_by(OtpCode.created_at.desc()).first()
    if not latest_rec:
        logger.warning(f"No active dual OTP group found for user {user_id} purpose {purpose}")
        return False

    group_id = latest_rec.dual_group_id
    group_records = OtpCode.query.filter_by(dual_group_id=group_id).all()
    
    email_rec = next((r for r in group_records if r.channel == 'EMAIL'), None)
    telegram_rec = next((r for r in group_records if r.channel == 'TELEGRAM'), None)

    if not email_rec or not telegram_rec:
        logger.warning(f"Incomplete dual OTP pair found for group {group_id}")
        return False

    # Check reuse
    if email_rec.used_at is not None or telegram_rec.used_at is not None:
        logger.warning(f"Attempt to reuse consumed dual OTP for user {user_id}")
        return False

    # Check expiry (5 minutes)
    if now > email_rec.expires_at or now > telegram_rec.expires_at:
        logger.warning(f"Dual OTP expired for user {user_id}")
        return False

    # Check shared attempts counter
    shared_attempts = max(email_rec.attempts, telegram_rec.attempts)
    if shared_attempts >= email_rec.max_attempts:
        logger.warning(f"Dual OTP maximum attempts exceeded for user {user_id}")
        return False

    # Constant-time comparison for BOTH codes
    email_ok = hmac.compare_digest(email_rec.code_hash, hash_code_hmac(email_code))
    telegram_ok = hmac.compare_digest(telegram_rec.code_hash, hash_code_hmac(telegram_code))

    if email_ok and telegram_ok:
        # Both are correct! Consume both records
        email_rec.used_at = now
        telegram_rec.used_at = now
        db.session.commit()
        logger.info(f"Dual OTP verification succeeded for user {user_id}")
        return True
    else:
        # Failed! Shared attempt counter increments by 1 on both records
        new_attempts = shared_attempts + 1
        email_rec.attempts = new_attempts
        telegram_rec.attempts = new_attempts
        db.session.commit()
        logger.warning(f"Dual OTP verification failed (shared attempt {new_attempts}/{email_rec.max_attempts}) for user {user_id}")
        return False


def startup_banner_lines() -> list:
    """Loud warnings when OTP delivery cannot work (printed by serve.py / app.py)."""
    r = channel_readiness()
    lines = []
    if r["email"]["dry_run"]:
        lines.append("EMAIL_DRY_RUN=true: OTP emails are NOT sent")
    if r["email"]["user"] != "set" or r["email"]["password"] != "set":
        lines.append("EMAIL_USER/EMAIL_PASSWORD empty or MOCK: OTP emails cannot be sent")
    if r["telegram"]["dry_run"]:
        lines.append("TELEGRAM_DRY_RUN=true: Telegram OTPs are NOT sent")
    if r["telegram"]["token"] != "looks-valid":
        lines.append(f"TELEGRAM_BOT_TOKEN {r['telegram']['token']}: Telegram OTPs cannot be sent")
    if not r["telegram"]["polling_enabled"]:
        lines.append("TELEGRAM_POLLING_ENABLED=false: bot never sees Start/contact, linking cannot finish")
    for ch in ("email", "telegram"):
        if not r[ch]["sender_registered"]:
            lines.append(f"{ch.upper()} sender not registered: codes go to the in-memory mock")
    return lines


def _register_default_senders():
    """Both real senders are registered at import so no code path silently uses the mock."""
    try:
        from email_sender import register_as_email_sender
        register_as_email_sender()
    except Exception:
        logger.exception("otp_service: could not register EMAIL sender")
    try:
        from telegram_bot import register_as_telegram_sender
        register_as_telegram_sender()
    except Exception:
        logger.exception("otp_service: could not register TELEGRAM sender")


_register_default_senders()
