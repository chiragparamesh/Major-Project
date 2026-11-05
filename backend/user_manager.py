import re
import logging
from datetime import datetime, timedelta
from db import db
from database import User
from security import (
    hash_pin, verify_pin, compute_lookup_hash, encrypt_val, decrypt_val,
    validate_pin, validate_dual_pins, is_weak_pin
)
from config import Config

logger = logging.getLogger(__name__)

def register_user(
    user_id: str,
    login_pin: str = None,
    payment_pin: str = None,
    phone_number: str = None,
    home_lat: float = 0.0,
    home_lon: float = 0.0,
    pin: str = None,
    full_name: str = None,
    email: str = None,
    upi_id: str = None
) -> tuple:
    """
    Registers a new user with dual bcrypt (rounds 12) 6-digit PINs:
    - login_pin_hash and payment_pin_hash must differ and reject weak PINs.
    - Also supports legacy 'pin' parameter for backwards compatibility.
    """
    if not user_id:
        return False, "User ID is required."
        
    user_id = user_id.strip()
    
    # Validate user_id format (supports both UPI handles like name@bank and alphanumeric usernames)
    if '@' in user_id:
        if user_id.count('@') != 1:
            return False, "User ID must be a valid UPI handle (e.g. name@bank)."
        parts = user_id.split('@')
        if not parts[0] or not parts[1]:
            return False, "User ID must be a valid UPI handle (e.g. name@bank)."
    else:
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', user_id):
            return False, "User ID must contain only alphanumeric characters, underscores, or be a valid UPI handle."
        
    # Determine login_pin and payment_pin
    eff_login_pin = login_pin or pin
    eff_payment_pin = payment_pin

    if not eff_login_pin:
        return False, "Login PIN is required."

    # If both PINs provided, perform dual PIN validation
    if eff_login_pin and eff_payment_pin:
        valid, err_msg = validate_dual_pins(eff_login_pin, eff_payment_pin)
        if not valid:
            return False, err_msg
        login_hash = hash_pin(eff_login_pin, rounds=12)
        payment_hash = hash_pin(eff_payment_pin, rounds=12)
    else:
        # Legacy single PIN registration fallback
        if len(str(eff_login_pin)) == 6:
            valid, err_msg = validate_pin(eff_login_pin, "Login PIN")
            if not valid:
                return False, err_msg
        elif len(str(eff_login_pin)) != 4 or not str(eff_login_pin).isdigit():
            return False, "PIN must be exactly 6 numeric digits (or 4 for legacy)."
        login_hash = hash_pin(eff_login_pin, rounds=12)
        payment_hash = None
        
    # Validate phone number (starts with '+', followed by digits, minimum 8 characters)
    if not phone_number:
        return False, "Phone number is required."
    phone_number = phone_number.strip()
    if not phone_number.startswith('+') or not phone_number[1:].isdigit() or len(phone_number) < 8:
        return False, "Phone number must be in E.164 format (starting with '+' followed by digits, minimum 8 characters)."
    
    # Check if user already exists
    existing = User.query.filter_by(user_id=user_id).first()
    if existing:
        return False, f"User '{user_id}' is already registered."
        
    try:
        norm_phone = normalize_phone(phone_number)
        std_upi = upi_id or (f"{extract_10_digit_phone(norm_phone)}@mlbfd" if norm_phone else user_id)
        email_val = email or f"{user_id.split('@')[0]}@mlbfd.local"
        
        new_user = User(
            user_id=user_id,
            full_name=full_name or user_id.split('@')[0].title(),
            pin_hash=login_hash,
            login_pin_hash=login_hash,
            payment_pin_hash=payment_hash,
            balance=Config.VIRTUAL_BALANCE,
            phone=encrypt_val(norm_phone),
            phone_hash=compute_lookup_hash(norm_phone),
            email=encrypt_val(email_val),
            email_hash=compute_lookup_hash(email_val),
            upi_id=encrypt_val(std_upi),
            upi_hash=compute_lookup_hash(std_upi),
            phone_number=norm_phone,
            home_latitude=home_lat,
            home_longitude=home_lon,
            is_locked=False,
            failed_attempts=0,
            login_failed_attempts=0,
            payment_failed_attempts=0
        )
        db.session.add(new_user)
        db.session.commit()
        logger.info(f"Registered user {user_id} with dual PINs and balance {Config.VIRTUAL_BALANCE}")
        return True, "User registered successfully."
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to register user: {e}")
        return False, "Database registration error."

def check_account_lock(user: User, now: datetime = None) -> tuple:
    """
    Checks if the user account login is locked and if the lock duration has expired.
    Returns: (is_locked: bool, error_message: str)
    """
    now = now or datetime.utcnow()
    lock_time = user.login_locked_until or user.locked_until
    if not lock_time:
        return False, ""
        
    if now > lock_time:
        # Lock has expired! Reset temporary lock
        try:
            user.is_locked = False
            user.locked_until = None
            user.login_locked_until = None
            user.login_failed_attempts = 0
            user.failed_attempts = 0
            db.session.commit()
            logger.info(f"Account for user {user.user_id} automatically unlocked after timeout.")
            return False, ""
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to unlock account: {e}")
            return False, ""
            
    # Lock still active — generic message
    return True, "Account temporarily locked. Please try again later."

def authenticate_login(identifier: str, login_pin: str, now: datetime = None) -> tuple:
    """
    Authenticates user login using login PIN only.
    - Uses generic error message, no hint whether user_id or PIN was wrong.
    - 5 wrong login PINs lock login for 15 minutes.
    - Lockout stored in the DB (login_locked_until, login_failed_attempts).
    Returns: (success: bool, message: str, user: Optional[User])
    """
    now = now or datetime.utcnow()
    if not identifier or not login_pin:
        return False, "Invalid credentials.", None
        
    user = find_user_by_upi_or_phone(identifier)
    if not user:
        # Generic error message: no hint that user does not exist
        return False, "Invalid credentials.", None
        
    # Check if login is locked
    if user.login_locked_until:
        if now < user.login_locked_until:
            return False, "Account temporarily locked. Please try again later.", None
        else:
            # Lockout expired, reset attempts
            user.login_locked_until = None
            user.login_failed_attempts = 0
            user.is_locked = False
            user.locked_until = None
            db.session.commit()
            
    # Verify login PIN only (use login_pin_hash, fallback to pin_hash if not set)
    pin_target_hash = user.login_pin_hash or user.pin_hash
    if pin_target_hash and verify_pin(str(login_pin).strip(), pin_target_hash):
        try:
            user.login_failed_attempts = 0
            user.login_locked_until = None
            user.failed_attempts = 0
            user.is_locked = False
            user.locked_until = None
            db.session.commit()
            return True, "Login successful.", user
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to reset login attempts: {e}")
            return True, "Login successful.", user
    else:
        try:
            user.login_failed_attempts = (user.login_failed_attempts or 0) + 1
            user.failed_attempts = user.login_failed_attempts
            
            if user.login_failed_attempts >= 5:
                user.login_locked_until = now + timedelta(minutes=15)
                user.locked_until = user.login_locked_until
                user.is_locked = True
                db.session.commit()
                logger.warning(f"🔒 Account {user.user_id} login locked for 15 minutes (5 failed attempts)")
                return False, "Account temporarily locked. Please try again later.", None
            else:
                db.session.commit()
                return False, "Invalid credentials.", None
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to record failed login: {e}")
            return False, "Invalid credentials.", None

def verify_user_payment_pin(user: User, payment_pin: str, now: datetime = None) -> tuple:
    """
    Verifies payment PIN for transaction authorization.
    - Verified BEFORE any scoring or fraud engine invocation.
    - 3 wrong payment PINs lock payments for 30 minutes.
    - Lockout stored in the DB (payment_locked_until, payment_failed_attempts).
    - Generic error message, no hint about internal fields.
    Returns: (success: bool, message: str)
    """
    now = now or datetime.utcnow()
    if not user:
        return False, "Payment authorization failed."
        
    # Check if payment is locked
    if user.payment_locked_until:
        if now < user.payment_locked_until:
            return False, "Payment transactions temporarily locked. Please try again later."
        else:
            # Lockout expired, reset attempts
            user.payment_locked_until = None
            user.payment_failed_attempts = 0
            db.session.commit()
            
    if not payment_pin:
        return False, "Payment authorization failed."
        
    # Verify payment PIN against payment_pin_hash
    target_hash = user.payment_pin_hash
    if not target_hash:
        return False, "Payment authorization failed."
        
    if verify_pin(str(payment_pin).strip(), target_hash):
        try:
            user.payment_failed_attempts = 0
            user.payment_locked_until = None
            db.session.commit()
            return True, "Payment authorized."
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to reset payment pin attempts: {e}")
            return True, "Payment authorized."
    else:
        try:
            user.payment_failed_attempts = (user.payment_failed_attempts or 0) + 1
            if user.payment_failed_attempts >= 3:
                user.payment_locked_until = now + timedelta(minutes=30)
                db.session.commit()
                logger.warning(f"🔒 Account {user.user_id} payments locked for 30 minutes (3 failed attempts)")
                return False, "Payment transactions temporarily locked. Please try again later."
            else:
                db.session.commit()
                return False, "Payment authorization failed."
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to record failed payment pin: {e}")
            return False, "Payment authorization failed."

def authenticate_user(user_id: str, pin: str) -> tuple:
    """
    Backwards-compatible wrapper that authenticates using login PIN.
    Returns: (is_authenticated: bool, error_message/jwt_user_id)
    """
    success, msg, user = authenticate_login(user_id, pin)
    if success and user:
        return True, user.user_id
    return False, msg

def update_user_balance(user_id: str, new_balance: float) -> bool:
    """Updates a user's virtual balance"""
    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return False
    try:
        user.balance = new_balance
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update balance for user {user_id}: {e}")
        return False

def normalize_phone(phone_input: str) -> str:
    """Normalizes phone number to +91XXXXXXXXXX (10-digit Indian phone with +91 country code)"""
    if not phone_input:
        return ""
    cleaned = re.sub(r'[\s\-\(\)\.]', '', str(phone_input).strip())
    if cleaned.startswith('+91') and len(cleaned) == 13 and cleaned[3:].isdigit():
        return cleaned
    if cleaned.startswith('91') and len(cleaned) == 12 and cleaned.isdigit():
        return f"+{cleaned}"
    if cleaned.startswith('0') and len(cleaned) == 11 and cleaned.isdigit():
        return f"+91{cleaned[1:]}"
    if len(cleaned) == 10 and cleaned.isdigit():
        return f"+91{cleaned}"
    return cleaned

def extract_10_digit_phone(phone_input: str) -> str:
    """Extracts the 10-digit phone number if valid"""
    norm = normalize_phone(phone_input)
    if norm.startswith('+91') and len(norm) == 13:
        return norm[3:]
    return norm

def find_user_by_upi_or_phone(identifier: str):
    """
    Finds a user by:
    1. UPI ID (e.g., '9876543210@mlbfd' or other valid UPI handle)
    2. 10-digit phone number (e.g., '9876543210')
    3. +91 E.164 phone number (e.g., '+919876543210')
    Uses HMAC-SHA256 blind indexing (upi_hash and phone_hash) because plain values are Fernet-encrypted.
    Falls back to user_id match or legacy phone_number match.
    """
    if not identifier:
        return None
    raw = str(identifier).strip()

    # 1. If identifier contains '@', treat as UPI ID
    if '@' in raw:
        upi_clean = raw.lower()
        u_hash = compute_lookup_hash(upi_clean)
        user = User.query.filter_by(upi_hash=u_hash).first()
        if user:
            return user
        # Direct user_id match fallback
        user = User.query.filter_by(user_id=raw).first()
        if user:
            return user
        user = User.query.filter_by(user_id=upi_clean).first()
        if user:
            return user

    # 2. Check as phone number
    norm_phone = normalize_phone(raw)
    if norm_phone.startswith('+91') and len(norm_phone) == 13 and norm_phone[3:].isdigit():
        # Match by phone_hash
        p_hash = compute_lookup_hash(norm_phone)
        user = User.query.filter_by(phone_hash=p_hash).first()
        if user:
            return user

        # Match by standard MLBFD UPI ID (<10-digit>@mlbfd)
        ten_digit = norm_phone[3:]
        std_upi = f"{ten_digit}@mlbfd"
        u_hash = compute_lookup_hash(std_upi)
        user = User.query.filter_by(upi_hash=u_hash).first()
        if user:
            return user

        # Match by legacy phone_number column
        user = User.query.filter_by(phone_number=norm_phone).first()
        if user:
            return user

    # 3. Fallback: match by direct user_id, phone_hash, or upi_hash
    user = User.query.filter_by(user_id=raw).first()
    if user:
        return user

    raw_hash = compute_lookup_hash(raw)
    user = User.query.filter_by(upi_hash=raw_hash).first()
    if user:
        return user
    user = User.query.filter_by(phone_hash=raw_hash).first()
    if user:
        return user

    return None


def cleanup_expired_pending_accounts(max_age_minutes: int = 30) -> int:
    """
    Deletes PENDING accounts older than 30 minutes and their associated link tokens and OTP codes.
    Also removes the matching signup_ip_logs rows: those rows are the 24h IP signup quota,
    and leaving them behind permanently burned the quota for every abandoned registration.
    """
    from database import TelegramLinkToken, OtpCode, SignupIpLog
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    expired = User.query.filter(
        User.status == "PENDING",
        User.created_at < cutoff
    ).all()
    count = 0
    for u in expired:
        try:
            TelegramLinkToken.query.filter_by(user_id=u.user_id).delete()
            OtpCode.query.filter_by(user_id=u.user_id).delete()
            SignupIpLog.query.filter_by(user_id=u.user_id).delete()
            db.session.delete(u)
            count += 1
        except Exception as e:
            logger.error(f"Error deleting expired user {u.user_id}: {e}")
    # Self-heal orphan quota rows left by purges performed before this fix.
    try:
        orphaned = SignupIpLog.query.filter(
            SignupIpLog.user_id.notin_(db.session.query(User.user_id))
        ).delete(synchronize_session=False)
        if orphaned:
            logger.info(f"Removed {orphaned} orphaned signup_ip_logs rows with no user record")
    except Exception as e:
        logger.warning(f"Could not remove orphaned signup_ip_logs rows: {e}")
    if count > 0:
        try:
            db.session.commit()
            logger.info(f"Cleaned up {count} expired PENDING accounts older than {max_age_minutes}m")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to commit cleanup of expired accounts: {e}")
        return count
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return count


def bind_device(user: User, device_id: str) -> list:
    """Binds device_id to user.known_devices JSON list"""
    if not device_id:
        return user.known_devices or []
    import json
    devices = user.known_devices or []
    if isinstance(devices, str):
        try:
            devices = json.loads(devices)
        except Exception:
            devices = []
    if not isinstance(devices, list):
        devices = []

    now_iso = datetime.utcnow().isoformat()
    found = False
    for item in devices:
        if isinstance(item, dict) and item.get("device_id") == device_id:
            item["last_verified"] = now_iso
            found = True
            break
        elif item == device_id:
            found = True
            break

    if not found:
        devices.append({
            "device_id": device_id,
            "added_at": now_iso,
            "last_verified": now_iso
        })

    user.known_devices = devices
    return devices


def is_device_trusted(user: User, device_id: str, max_age_days: int = 30) -> bool:
    """
    Checks if device_id is in user.known_devices and was verified within max_age_days (30 days).
    """
    if not device_id or not user.known_devices:
        return False
    import json
    devices = user.known_devices
    if isinstance(devices, str):
        try:
            devices = json.loads(devices)
        except Exception:
            return False
    if not isinstance(devices, list):
        return False

    now = datetime.utcnow()
    cutoff = now - timedelta(days=max_age_days)

    for item in devices:
        if isinstance(item, dict):
            if item.get("device_id") == device_id:
                last_verified_str = item.get("last_verified") or item.get("added_at")
                if not last_verified_str:
                    return False
                try:
                    cleaned_str = str(last_verified_str).replace("Z", "").split("+")[0]
                    last_verified = datetime.fromisoformat(cleaned_str)
                    if last_verified >= cutoff:
                        return True
                except (ValueError, TypeError):
                    logger.warning("is_device_trusted: unparsable last_verified timestamp; treating device as untrusted")
        elif item == device_id:
            # legacy string format: trusted
            return True
    return False



