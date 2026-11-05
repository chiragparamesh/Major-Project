import base64
import hashlib
import hmac
import time
import secrets
import bcrypt
import logging
import requests
from typing import Optional, Tuple
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from cryptography.fernet import Fernet
from config import Config

logger = logging.getLogger(__name__)

# Derive a valid 32-byte Fernet key from our environment secret key
def _derive_fernet_key(secret: str) -> str:
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)

_key = _derive_fernet_key(Config.SECRET_KEY)
cipher = Fernet(_key)

def encrypt_val(val: str) -> str:
    """Encrypts a string value using AES-256 (Fernet)"""
    if not val:
        return val
    return cipher.encrypt(val.encode()).decode()

def decrypt_val(cipher_text: str) -> str:
    """Decrypts a value using AES-256 (Fernet)"""
    if not cipher_text:
        return cipher_text
    try:
        return cipher.decrypt(cipher_text.encode()).decode()
    except Exception as e:
        # Fernet tokens start with "gAAAAA". An undecryptable token (key rotated / wrong key)
        # must not be returned as if it were an email/phone; legacy plaintext passes through.
        if str(cipher_text).startswith("gAAAAA"):
            logger.error(f"Failed to decrypt value ({type(e).__name__}): key mismatch or corrupt token")
            return ""
        return cipher_text

def compute_lookup_hash(val: str) -> str:
    """
    Computes a deterministic HMAC-SHA256 hash using the server secret key.
    Used for blind indexing and querying Fernet-encrypted fields (phone, email, upi_id).
    """
    if not val:
        return ""
    key = Config.SECRET_KEY.encode('utf-8')
    return hmac.new(key, val.strip().lower().encode('utf-8'), hashlib.sha256).hexdigest()


def mask_upi(upi_id: str) -> str:
    """Masks a UPI ID for logs/display (e.g. john@okaxis -> j***@okaxis)"""
    if not upi_id or "@" not in upi_id:
        return upi_id
    user, domain = upi_id.split("@", 1)
    if len(user) <= 2:
        masked_user = user[0] + "*" * len(user[1:])
    else:
        masked_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{masked_user}@{domain}"

def is_weak_pin(pin: str) -> bool:
    """
    Checks if a 6-digit PIN is weak:
    - Must be a 6-digit numeric string
    - Rejects 000000, 123456, and common weak PINs
    - Rejects repeated digits (e.g. 111111, 222222, ...)
    - Rejects sequential ascending digits (e.g. 012345, 123456, 234567, 345678, 456789, 567890)
    - Rejects sequential descending digits (e.g. 987654, 876543, 765432, 654321, 543210, 098765)
    """
    if not pin or not isinstance(pin, str):
        return True
    pin = pin.strip()
    if len(pin) != 6 or not pin.isdigit():
        return True
        
    # Check repeated digits: all 6 digits identical (e.g. 000000, 111111, etc.)
    if len(set(pin)) == 1:
        return True
        
    digits = [int(c) for c in pin]
    
    # Sequential ascending: each digit is previous + 1
    if all(digits[i+1] - digits[i] == 1 for i in range(5)):
        return True
        
    # Sequential descending: each digit is previous - 1
    if all(digits[i] - digits[i+1] == 1 for i in range(5)):
        return True
        
    # Modular/wrapping sequential ascending (e.g., 567890, 890123)
    if all((digits[i+1] - digits[i]) % 10 == 1 for i in range(5)):
        return True
        
    # Modular/wrapping sequential descending (e.g., 098765, 321098)
    if all((digits[i] - digits[i+1]) % 10 == 1 for i in range(5)):
        return True
        
    # Explicit weak PIN blacklist
    blacklist = {
        "000000", "123456", "654321", "012345", "543210",
        "112233", "121212", "123123", "111222", "999999"
    }
    if pin in blacklist:
        return True
        
    return False

def validate_pin(pin: str, pin_name: str = "PIN") -> tuple:
    """Validates that a PIN is exactly 6 numeric digits and not weak"""
    if not pin or not isinstance(pin, str):
        return False, f"{pin_name} must be a 6-digit numeric string."
    pin = pin.strip()
    if len(pin) != 6 or not pin.isdigit():
        return False, f"{pin_name} must be exactly 6 numeric digits."
    if is_weak_pin(pin):
        return False, f"{pin_name} is too weak (repeated or sequential digits are not allowed)."
    return True, ""

def validate_dual_pins(login_pin: str, payment_pin: str) -> tuple:
    """
    Validates dual 6-digit PINs:
    1. Both must be 6 digits and not weak.
    2. Login PIN and Payment PIN must strictly differ.
    """
    valid_login, msg1 = validate_pin(login_pin, "Login PIN")
    if not valid_login:
        return False, msg1
    valid_payment, msg2 = validate_pin(payment_pin, "Payment PIN")
    if not valid_payment:
        return False, msg2
    if str(login_pin).strip() == str(payment_pin).strip():
        return False, "Login PIN and Payment PIN must differ."
    return True, ""

def hash_pin(pin: str, rounds: int = 12) -> str:
    """Hashes a PIN using bcrypt with specified cost factor (default 12 rounds)"""
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(str(pin).strip().encode('utf-8'), salt).decode('utf-8')

def verify_pin(pin: str, hashed_pin: str) -> bool:
    """Verifies a PIN against a bcrypt hash in constant time"""
    if not pin or not hashed_pin:
        return False
    try:
        return bcrypt.checkpw(str(pin).strip().encode('utf-8'), hashed_pin.encode('utf-8'))
    except Exception:
        return False

def verify_request_signature(request_data: bytes, signature: str, timestamp_str: str) -> bool:
    """
    Verifies that the HMAC request signature matches the payload.
    Signature is HMAC-SHA256(MLBFD_SECRET_KEY, request_data + timestamp).
    Timestamp check ensures request is within a 60-second window.
    """
    if not signature or not timestamp_str:
        return False
        
    try:
        req_time = int(timestamp_str)
        curr_time = int(time.time())
        # Check 60-second window to prevent replay attacks
        if abs(curr_time - req_time) > 60:
            logger.warning(f"Signature time window exceeded: diff {abs(curr_time - req_time)}s")
            return False
            
        # Compute expected HMAC signature
        message = request_data + timestamp_str.encode()
        # Dedicated client-signing key (it ships inside the APK, so it must NOT be the
        # Flask/OTP SECRET_KEY). Falls back to SECRET_KEY only when unset.
        from env_loader import env_str
        signing_key = env_str("MLBFD_CLIENT_SECRET") or Config.SECRET_KEY
        expected = hmac.new(
            signing_key.encode(),
            message,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Error during signature verification: {e}")
        return False


FREEZE_TOKEN_SALT = "mlbfd-account-freeze-token-salt"
FREEZE_TOKEN_MAX_AGE = 86400  # 24 hours


def generate_freeze_token(user_id: str) -> str:
    """
    Generates a cryptographically signed 24-hour single-use freeze token.
    Encodes user_id, a random nonce, and creation timestamp.
    """
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY, salt=FREEZE_TOKEN_SALT)
    nonce = secrets.token_hex(16)
    return serializer.dumps({"user_id": user_id, "nonce": nonce})


def verify_and_decode_freeze_token(token: str) -> tuple[bool, str, str]:
    """
    Validates cryptographic signature and 24-hour expiration of a freeze token.
    Returns: (is_valid: bool, user_id: str, error_message: str)
    """
    if not token:
        return False, "", "Freeze token is required."
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY, salt=FREEZE_TOKEN_SALT)
    try:
        data = serializer.loads(token, max_age=FREEZE_TOKEN_MAX_AGE)
        user_id = data.get("user_id", "")
        if not user_id:
            return False, "", "Malformed freeze token payload."
        return True, user_id, ""
    except SignatureExpired:
        return False, "", "Freeze token has expired (valid for 24 hours)."
    except BadSignature:
        return False, "", "Invalid freeze token signature."
    except Exception as e:
        logger.error(f"Error decoding freeze token: {e}")
        return False, "", "Invalid freeze token."


# ==============================================================================
# BOT & ABUSE PROTECTION (PART 14)
# ==============================================================================

DISPOSABLE_EMAIL_DOMAINS = {
    '10minutemail.com', 'tempmail.com', 'guerrillamail.com', 'mailinator.com',
    'yopmail.com', 'trashmail.com', 'getairmail.com', 'dispostable.com',
    'sharklasers.com', 'generator.email', 'fakeinbox.com', 'throwawaymail.com',
    'temp-mail.org', 'tempail.com', 'burnermail.io', 'mohmal.com'
}


def is_disposable_email(email: str) -> bool:
    """Checks if an email domain belongs to known disposable email providers."""
    if not email or "@" not in email:
        return False
    domain = email.strip().lower().split("@", 1)[1]
    return domain in DISPOSABLE_EMAIL_DOMAINS


def verify_turnstile_token(token: str, remote_ip: Optional[str] = None) -> Tuple[bool, str]:
    """
    Verifies Cloudflare Turnstile token via siteverify API.
    If secret key is not set or set to MOCK/TEST, returns True (or mock behavior).
    Returns: (success: bool, error_message: str)
    """
    secret = getattr(Config, "TURNSTILE_SECRET_KEY", "")
    if not secret or secret in ("MOCK", "TEST"):
        # When keys are unset or MOCK in development, turnstile is considered unset
        return True, ""

    if not token:
        return False, "Cloudflare Turnstile verification token missing."

    url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    payload = {
        "secret": secret,
        "response": token
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        resp = requests.post(url, data=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return True, ""
            return False, f"Turnstile verification failed: {', '.join(data.get('error-codes', ['invalid']))}"
        return False, f"Turnstile service error (HTTP {resp.status_code})"
    except Exception as e:
        logger.error(f"Turnstile request error: {e}")
        return False, "Failed to verify Turnstile challenge."


def check_honeypot(form_data: dict, honeypot_field: str = "website") -> bool:
    """
    Checks if a hidden honeypot field has been filled by a bot.
    Returns True if clean (field empty or missing), False if bot detected (field filled).
    """
    if not form_data:
        return True
    val = form_data.get(honeypot_field) or form_data.get("fax_number") or form_data.get("hp_field")
    if val and str(val).strip():
        logger.warning(f"Bot detected via honeypot field '{honeypot_field}'")
        return False
    return True


FORM_TIMING_SALT = "mlbfd-form-timing-salt"
MIN_FORM_FILL_SECONDS = 3.0


def generate_form_timing_token(timestamp: Optional[float] = None) -> str:
    """Generates a signed timestamp token to verify minimum form-fill duration."""
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY, salt=FORM_TIMING_SALT)
    t = timestamp if timestamp is not None else time.time()
    return serializer.dumps({"t": t})


def verify_form_fill_timing(token: Optional[str] = None, client_started_at: Optional[float] = None) -> Tuple[bool, str]:
    """
    Verifies that form filling took at least 3 seconds.
    Can verify using signed timing token or client start timestamp.
    """
    current_time = time.time()

    # 1. Check signed timing token if provided
    if token:
        serializer = URLSafeTimedSerializer(Config.SECRET_KEY, salt=FORM_TIMING_SALT)
        try:
            data = serializer.loads(token, max_age=3600)  # valid for up to 1 hour
            start_time = float(data.get("t", 0.0))
            elapsed = current_time - start_time
            if elapsed < MIN_FORM_FILL_SECONDS:
                return False, f"Form submitted too quickly ({elapsed:.2f}s). Minimum {MIN_FORM_FILL_SECONDS}s required to prevent bots."
            return True, ""
        except Exception:
            logger.exception("verify_form_fill_timing: token deserialization failed — token invalid or SECRET_KEY mismatch")
            return False, "Invalid or expired form timing token."

    # 2. Check client start timestamp if provided
    if client_started_at is not None and client_started_at > 0:
        elapsed = current_time - client_started_at
        if elapsed < MIN_FORM_FILL_SECONDS:
            return False, f"Form submitted too quickly ({elapsed:.2f}s). Minimum {MIN_FORM_FILL_SECONDS}s required to prevent bots."
        return True, ""

    # If neither provided in fallback mode, reject automated script
    return False, "Form timing verification required."


def mask_phone(phone: Optional[str]) -> str:
    """
    Masks a phone number preserving only the last 2 digits.
    e.g. +919876543210 -> +91******10, 9876543210 -> ********10
    """
    if not phone:
        return ""
    phone = str(phone).strip()
    if len(phone) <= 2:
        return phone
    if phone.startswith("+91") and len(phone) > 5:
        return f"+91{'*' * (len(phone) - 5)}{phone[-2:]}"
    return f"{'*' * (len(phone) - 2)}{phone[-2:]}"


def mask_email(email: Optional[str]) -> str:
    """
    Masks an email address into partial form (e.g. r***h@domain.com or r***@domain.com).
    """
    if not email or "@" not in email:
        return ""
    parts = email.strip().split("@", 1)
    local, domain = parts[0], parts[1]
    if len(local) <= 1:
        masked_local = f"{local}***"
    elif len(local) == 2:
        masked_local = f"{local[0]}***"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"





# ==============================================================================
# ADMIN ACCESS GATE
# ==============================================================================
ADMIN_COOKIE = "mlbfd_admin"


def admin_request_allowed(req) -> bool:
    """
    Admin portal / admin API access.
    - Direct loopback request (browser on the server machine, no proxy headers): always allowed.
      The Cloudflare tunnel connects from 127.0.0.1 too, but it adds CF-Connecting-IP /
      X-Forwarded-For, so tunnel traffic is never mistaken for local.
    - Anything else (tunnel, LAN, other machine): needs ADMIN_API_TOKEN via the X-Admin-Token
      header or the HttpOnly admin cookie. With no token configured it is refused.
    """
    from env_loader import env_str
    proxied = req.headers.get("X-Forwarded-For") or req.headers.get("CF-Connecting-IP")
    if (not proxied) and req.remote_addr in ("127.0.0.1", "::1"):
        return True
    token = env_str("ADMIN_API_TOKEN")
    if not token:
        return False
    presented = req.headers.get("X-Admin-Token") or req.cookies.get(ADMIN_COOKIE) or ""
    return hmac.compare_digest(presented, token)


# ==============================================================================
# CLIENT IP (Cloudflare tunnel aware)
# ==============================================================================
_LOOPBACK = ("127.0.0.1", "::1")


def client_ip(req=None) -> str:
    """
    Real client IP for rate limits, the signup-per-IP rule and audit logs.
    cloudflared connects from 127.0.0.1, so remote_addr alone would put every user
    in one bucket. Proxy headers are trusted ONLY when the immediate peer is local
    (the tunnel); a direct client cannot spoof its IP with X-Forwarded-For.
    """
    if req is None:
        from flask import request as req
    peer = req.remote_addr or "127.0.0.1"
    if peer in _LOOPBACK:
        cf = (req.headers.get("CF-Connecting-IP") or "").strip()
        if cf:
            return cf
        xff = (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if xff:
            return xff
    return peer
