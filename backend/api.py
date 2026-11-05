from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token, jwt_required, 
    get_jwt_identity, get_jwt
)
from datetime import datetime, timedelta
import logging
import re
import hashlib
import time
import secrets

from config import Config
from db import db
from database import (
    User, Transaction, UserBehaviorBaseline, TrustedPayee, ScamUpi, ScamReport, Feedback,
    TokenBlocklist, PendingPinChange, PasswordResetToken, OtpCode
)
from security import encrypt_val, decrypt_val, mask_upi, verify_pin, hash_pin, validate_pin
import otp_service
from fraud_detection import global_fraud_detector
from ubts import update_user_baseline
from audit_logger import log_audit_action

from rate_limiter import limiter

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__)

# HMAC Signature Header Verification Helper
def verify_headers(req):
    signature = req.headers.get("X-Signature")
    timestamp = req.headers.get("X-Timestamp")
    
    if not signature or not timestamp:
        return False
        
    from security import verify_request_signature
    # Verify signature on raw request body data
    return verify_request_signature(req.get_data(), signature, timestamp)

# ----------------------------------------------------
# AUTH ENDPOINTS
# ----------------------------------------------------
def _activate_user_and_issue_tokens(user, device_id=None):
    from user_manager import extract_10_digit_phone, bind_device
    from security import encrypt_val, compute_lookup_hash
    from flask_jwt_extended import create_access_token, create_refresh_token

    user.status = "ACTIVE"
    user.balance = 100000.00
    phone_dec = user.get_decrypted_phone()
    ten_digit = extract_10_digit_phone(phone_dec)
    std_upi = f"{ten_digit}@mlbfd"
    user.upi_id = encrypt_val(std_upi)
    user.upi_hash = compute_lookup_hash(std_upi)

    if device_id:
        bind_device(user, device_id)

    db.session.commit()

    access_token = create_access_token(identity=user.user_id)
    refresh_token = create_refresh_token(identity=user.user_id)

    return {
        "success": True,
        "message": "Account fully activated! Virtual balance credited.",
        "status": "ACTIVE",
        "user_id": user.user_id,
        "balance": 100000.00,
        "upi_id": std_upi,
        "access_token": access_token,
        "refresh_token": refresh_token
    }

def _delivery(result):
    """Per-channel status for the UI, e.g. {"email": "sent", "telegram": "not_linked"}."""
    status = getattr(result, "channel_status", None)
    if status is None:
        delivery = getattr(result, "delivery", None) or {}
        status = {k: v.get("status", "failed") for k, v in delivery.items()}
    return status or {}


def _delivery_detail(result):
    """Secret-free failure explanations per channel."""
    delivery = getattr(result, "delivery", None) or {}
    return {k: v.get("detail", "") for k, v in delivery.items() if v.get("status") not in ("sent", "dry_run", "pending")}


def _otp_message(delivery, purpose_text="Verification codes"):
    failed = [c for c, st in delivery.items() if st not in ("sent", "dry_run", "pending")]
    if not delivery or not failed:
        return f"{purpose_text} sent to your registered email and Telegram."
    return (f"{purpose_text}: " + ", ".join(f"{c} {delivery[c].replace('_', ' ')}" for c in sorted(delivery))
            + ". Use Resend once the channel is fixed.")


MAX_TXN_AMOUNT = 10_000_000.00  # ₹1 crore hard ceiling for the virtual ledger


def _parse_amount(raw):
    """Return a positive, finite amount rounded to paise, or None. Rejects negatives/NaN/inf/text."""
    import math
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val) or val <= 0 or val > MAX_TXN_AMOUNT:
        return None
    if round(val, 2) != round(val, 6):
        return None  # more than 2 decimal places
    return round(val, 2)


def _clean_text(value, max_len: int = 100) -> str:
    """Free text stored and later shown in admin/user pages: drop markup and control chars."""
    text = re.sub(r"[<>\"'`\x00-\x1f]", "", str(value or ""))
    return text.strip()[:max_len]


def _clean_mcc(value) -> str:
    v = str(value or "").strip()
    return v if re.fullmatch(r"\d{4}", v) else "0000"


def _clean_device_id(value):
    v = str(value or "").strip()
    return v[:100] if re.fullmatch(r"[A-Za-z0-9._:\-]{1,100}", v) else None


def _req_ip() -> str:
    from security import client_ip
    return client_ip(request)


def _move_funds(sender_id, receiver_user, amount) -> bool:
    """
    Debit sender and credit an ACTIVE registered receiver inside the CURRENT session
    with conditional SQL UPDATEs (no read-modify-write), so two concurrent transfers
    cannot both spend the same balance. Returns False when the balance is insufficient.
    The caller commits once, so debit and credit land together or not at all.
    """
    from decimal import Decimal
    from sqlalchemy import update
    amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    res = db.session.execute(
        update(User)
        .where(User.user_id == sender_id, User.balance >= amt)
        .values(balance=User.balance - amt)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        return False
    if receiver_user is not None and receiver_user.status == 'ACTIVE' and receiver_user.user_id != sender_id:
        db.session.execute(
            update(User)
            .where(User.user_id == receiver_user.user_id)
            .values(balance=User.balance + amt)
            .execution_options(synchronize_session=False)
        )
    return True


def _admin_allowed(req) -> bool:
    from security import admin_request_allowed
    return admin_request_allowed(req)


def _has_verified_telegram_otp(user):
    from database import OtpCode
    return OtpCode.query.filter_by(
        user_id=user.user_id,
        purpose="SIGNUP",
        channel="TELEGRAM"
    ).filter(OtpCode.used_at.isnot(None)).first() is not None


@api_bp.route('/register/timing_token', methods=['GET'])
def get_registration_timing_token():
    """Returns signed form timing token and Turnstile site key for registration form."""
    from security import generate_form_timing_token
    token = generate_form_timing_token()
    return jsonify({
        "success": True,
        "timing_token": token,
        "turnstile_site_key": getattr(Config, "TURNSTILE_SITE_KEY", "")
    }), 200


@api_bp.route('/reverse_geocode', methods=['GET'])
def reverse_geocode_api():
    """Returns human-readable area name from lat and lon via cached Nominatim."""
    from geofence import reverse_geocode
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    if not lat or not lon:
        return jsonify({"success": False, "message": "lat and lon query params required."}), 400
    try:
        area_name = reverse_geocode(float(lat), float(lon))
        return jsonify({
            "success": True,
            "lat": float(lat),
            "lon": float(lon),
            "area_name": area_name
        }), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500



@api_bp.route('/register/start', methods=['POST'])
@limiter.limit("10 per minute")
def register_start():
    import re
    from user_manager import cleanup_expired_pending_accounts, normalize_phone, extract_10_digit_phone
    from security import validate_dual_pins, hash_pin, encrypt_val, compute_lookup_hash
    import otp_service
    from telegram_bot import telegram_bot

    # 1. Purge PENDING accounts older than 30 minutes
    logger.info("register_start: request received")
    cleanup_expired_pending_accounts(max_age_minutes=30)

    data = request.get_json(silent=True) or {}
    full_name = _clean_text(data.get('full_name'), 150)
    user_id = str(data.get('user_id') or '').strip()
    phone = str(data.get('phone') or data.get('phone_number') or '').strip()
    email = str(data.get('email') or '').strip().lower()
    login_pin = str(data.get('login_pin') or '').strip()
    payment_pin = str(data.get('payment_pin') or '').strip()
    security_question = str(data.get('security_question') or '').strip()
    security_answer = str(data.get('security_answer') or '').strip()
    consent = data.get('consent') or data.get('consent_checkbox')

    if not (full_name and user_id and phone and email and login_pin and payment_pin and security_question and security_answer):
        logger.info("register_start: rejected — missing required fields")
        return jsonify({
            "success": False,
            "error": "MISSING_FIELDS",
            "message": "All fields including security question and answer are required."
        }), 400

    if not consent:
        logger.info("register_start: rejected — consent not given")
        return jsonify({
            "success": False,
            "error": "CONSENT_REQUIRED",
            "message": "You must accept the terms and privacy consent to register."
        }), 400

    # Bot & Abuse Protection Checks (Part 14)
    from security import check_honeypot, verify_turnstile_token, verify_form_fill_timing, is_disposable_email
    from database import SignupIpLog
    from config import Config

    # a. Honeypot Check (catches automated form-fill bots)
    if not check_honeypot(data):
        logger.info("register_start: honeypot triggered — bot detected")
        return jsonify({
            "success": False,
            "error": "BOT_DETECTED",
            "message": "Automated submission detected. Registration blocked."
        }), 400

    # b. Cloudflare Turnstile Check (with timing fallback if Turnstile unset)
    from security import client_ip as _client_ip
    client_ip = _client_ip(request)
    turnstile_secret = getattr(Config, "TURNSTILE_SECRET_KEY", "")
    has_turnstile = bool(turnstile_secret and turnstile_secret not in ("MOCK", "TEST"))

    if has_turnstile:
        turnstile_token = data.get("cf-turnstile-response") or data.get("turnstile_token")
        turnstile_ok, turnstile_err = verify_turnstile_token(turnstile_token, remote_ip=client_ip)
        if not turnstile_ok:
            logger.info(f"register_start: Turnstile check failed — {turnstile_err}")
            return jsonify({
                "success": False,
                "error": "BOT_DETECTED",
                "message": turnstile_err
            }), 400
    else:
        # Fallback to form fill timing verification (minimum 3 seconds)
        timing_token = data.get("form_timing_token")
        started_at = data.get("form_started_at")
        from flask import current_app
        if timing_token or started_at is not None or not current_app.config.get("TESTING"):
            timing_ok, timing_err = verify_form_fill_timing(token=timing_token, client_started_at=started_at)
            if not timing_ok:
                logger.info(f"register_start: timing check failed — {timing_err}")
                return jsonify({
                    "success": False,
                    "error": "BOT_DETECTED",
                    "message": timing_err
                }), 400

    # c. Disposable Email Domain Blocklist Check
    if is_disposable_email(email):
        logger.info("register_start: rejected — disposable email domain")
        return jsonify({
            "success": False,
            "error": "DISPOSABLE_EMAIL_BLOCKED",
            "message": "Disposable or temporary email addresses are not permitted. Please use a permanent email address."
        }), 400

    # d. IP Rate Limit: Maximum 3 new accounts per IP per 24 hours
    twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
    recent_signups = SignupIpLog.query.filter(
        SignupIpLog.ip_address == client_ip,
        SignupIpLog.created_at >= twenty_four_hours_ago
    ).count()

    if recent_signups >= 3:
        logger.info(
            f"register_start: rejected — IP signup quota {recent_signups}/3 used for ip={client_ip}"
        )
        return jsonify({
            "success": False,
            "error": "IP_SIGNUP_LIMIT_EXCEEDED",
            "message": "Maximum of 3 accounts per IP address within 24 hours exceeded."
        }), 429
    logger.info(f"register_start: abuse checks passed (ip quota {recent_signups}/3)")


    # User ID format validation
    if '@' in user_id:
        if user_id.count('@') != 1 or not user_id.split('@')[0] or not user_id.split('@')[1]:
            logger.info("register_start: rejected — invalid user_id format")
            return jsonify({"success": False, "error": "INVALID_USER_ID", "message": "Invalid user ID format."}), 400
    else:
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', user_id):
            logger.info("register_start: rejected — user_id contains invalid characters")
            return jsonify({"success": False, "error": "INVALID_USER_ID", "message": "User ID must be alphanumeric."}), 400

    # Dual PIN validation (6 digits each, must differ, reject weak)
    valid_pins, pin_err = validate_dual_pins(login_pin, payment_pin)
    if not valid_pins:
        logger.info(f"register_start: rejected — PIN validation: {pin_err}")
        return jsonify({"success": False, "error": "INVALID_PIN", "message": pin_err}), 400

    # Phone normalization
    norm_phone = normalize_phone(phone)
    if not (norm_phone.startswith('+91') and len(norm_phone) == 13 and norm_phone[3:].isdigit()):
        logger.info("register_start: rejected — invalid phone number")
        return jsonify({"success": False, "error": "INVALID_PHONE", "message": "Please enter a valid 10-digit Indian mobile number."}), 400

    # Email format validation
    if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
        logger.info("register_start: rejected — invalid email format")
        return jsonify({"success": False, "error": "INVALID_EMAIL", "message": "Please enter a valid email address."}), 400

    # Duplicate check across user_id, phone, and email
    p_hash = compute_lookup_hash(norm_phone)
    e_hash = compute_lookup_hash(email)
    ten_digit = extract_10_digit_phone(norm_phone)
    std_upi = f"{ten_digit}@mlbfd"
    u_hash = compute_lookup_hash(std_upi)

    existing = User.query.filter(
        (User.user_id == user_id) |
        (User.phone_hash == p_hash) |
        (User.email_hash == e_hash) |
        (User.upi_hash == u_hash)
    ).first()

    if existing:
        logger.info(f"register_start: rejected — registration collision for user_id={user_id}")
        return jsonify({
            "success": False,
            "error": "REGISTRATION_COLLISION",
            "message": "An account with these registration details already exists or registration is in progress."
        }), 400

    # Create PENDING account with zero balance
    try:
        login_hash = hash_pin(login_pin, rounds=12)
        payment_hash = hash_pin(payment_pin, rounds=12)
        sec_ans_hash = hash_pin(security_answer.lower(), rounds=12)

        # Location & Reverse Geocode (Part 16)
        lat = data.get('lat') if data.get('lat') is not None else data.get('latitude')
        lon = data.get('lon') if data.get('lon') is not None else data.get('longitude')
        accuracy_m = data.get('accuracy_m') if data.get('accuracy_m') is not None else data.get('accuracy')
        loc_source = data.get('source') or data.get('location_source') or 'gps'
        home_area = None
        if lat is not None and lon is not None:
            try:
                from geofence import reverse_geocode
                home_area = reverse_geocode(float(lat), float(lon))
            except Exception:
                logger.exception("register_start: reverse geocode failed; continuing without area name")

        new_user = User(
            user_id=user_id,
            full_name=full_name,
            phone=encrypt_val(norm_phone),
            phone_hash=p_hash,
            email=encrypt_val(email),
            email_hash=e_hash,
            upi_id=None,
            upi_hash=None,
            status="PENDING",
            email_verified=False,
            telegram_verified=False,
            telegram_chat_id=None,
            known_devices=[],
            security_question=security_question,
            security_answer_hash=sec_ans_hash,
            consent_at=datetime.utcnow(),
            balance=0.00,
            login_pin_hash=login_hash,
            payment_pin_hash=payment_hash,
            pin_hash=login_hash,
            phone_number=norm_phone,
            home_latitude=float(lat) if lat is not None else None,
            home_longitude=float(lon) if lon is not None else None,
            home_accuracy_m=float(accuracy_m) if accuracy_m is not None else None,
            home_location_source=str(loc_source) if loc_source else None,
            home_area_name=home_area
        )
        db.session.add(new_user)
        db.session.add(SignupIpLog(ip_address=client_ip, user_id=new_user.user_id))
        db.session.commit()
        logger.info(f"register_start: user record committed for user_id={user_id}")

    except Exception as e:
        db.session.rollback()
        logger.exception(f"register_start: exception during user creation for user_id={user_id}")
        return jsonify({"success": False, "message": "Database registration error."}), 500

    # Send email OTP — outside DB try/except so OTP errors are not misreported as DB errors
    from flask import current_app
    require_delivery = not current_app.config.get("TESTING")
    logger.info(
        f"register_start: issuing EMAIL OTP for user_id={user_id} require_delivery={require_delivery}"
    )
    email_delivery = {"email": "sent"}
    try:
        issued = otp_service.issue(
            new_user, purpose="SIGNUP", channel="EMAIL", require_delivery=require_delivery
        )
        email_delivery = _delivery(issued) or email_delivery
        logger.info(f"register_start: EMAIL OTP issued for user_id={user_id} status={email_delivery}")
    except otp_service.OtpRateLimitError as e:
        logger.warning(f"register_start: OTP rate limit for user_id={user_id}: {e}")
        return jsonify({"success": False, "error": "OTP_RATE_LIMITED", "message": str(e)}), 429
    except otp_service.OtpDispatchError as dispatch_err:
        logger.warning(f"register_start: OTP delivery failed for user_id={user_id}; rolling back pending account")
        detail = (dispatch_err.delivery.get("email") or {}).get("detail") or "email delivery failed"
        try:
            SignupIpLog.query.filter_by(user_id=new_user.user_id).delete()
            db.session.delete(new_user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("register_start: failed to roll back pending account after OTP failure")
        return jsonify({
            "success": False,
            "error": "OTP_DISPATCH_FAILED",
            "delivery": {"email": "failed", "telegram": "not_linked"},
            "delivery_detail": {"email": detail},
            "message": f"Verification email could not be sent ({detail}). Nothing was saved; please try again later."
        }), 502
    except Exception:
        logger.exception(f"register_start: OTP dispatch failed for user_id={user_id}")
        return jsonify({"success": False, "error": "OTP_DISPATCH_FAILED", "message": "Verification code could not be sent. Please try again."}), 500

    # Generate Telegram link token
    try:
        token, link_url = telegram_bot.create_link_token(user_id=new_user.user_id, expires_in_minutes=10)
    except Exception:
        logger.exception(f"register_start: failed to create Telegram link token for user_id={user_id}")
        link_url = ""

    log_audit_action(user_id, "REGISTER_START_SUCCESS", 201)
    return jsonify({
        "success": True,
        "message": "Registration started. Verification code sent to email. Please link your Telegram bot.",
        "user_id": new_user.user_id,
        "telegram_link": link_url,
        "telegram_bot_username": telegram_bot.username,
        # The Telegram code is sent only after the bot link + contact share succeeds.
        "delivery": {"email": email_delivery.get("email", "sent"), "telegram": "not_linked"}
    }), 201


@api_bp.route('/register/verify_email', methods=['POST'])
@limiter.limit("15 per minute")
def register_verify_email():
    import otp_service
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id') or '').strip()
    code = str(data.get('code') or '').strip()

    if not user_id or not code:
        return jsonify({"success": False, "message": "user_id and code are required."}), 400

    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.status != "PENDING":
        return jsonify({"success": False, "message": "Pending registration not found."}), 404

    verified = otp_service.verify(user, purpose="SIGNUP", channel="EMAIL", code=code)
    if not verified:
        return jsonify({"success": False, "message": "Invalid or expired verification code."}), 400

    user.email_verified = True
    db.session.commit()

    # If Telegram contact AND Telegram OTP are already verified, activate!
    if user.telegram_verified and _has_verified_telegram_otp(user):
        device_id = request.headers.get("X-Device-ID") or data.get("device_id")
        resp_data = _activate_user_and_issue_tokens(user, device_id=device_id)
        return jsonify(resp_data), 200

    return jsonify({
        "success": True,
        "message": "Email verified successfully.",
        "email_verified": True,
        "telegram_verified": bool(user.telegram_verified),
        "status": user.status
    }), 200


@api_bp.route('/register/send_telegram_otp', methods=['POST'])
@limiter.limit("10 per minute")
def register_send_telegram_otp():
    import otp_service
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id') or '').strip()

    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.status != "PENDING":
        return jsonify({"success": False, "message": "Pending registration not found."}), 404

    if not user.telegram_verified or not user.get_decrypted_telegram_chat_id():
        return jsonify({
            "success": False,
            "message": "Please start the Telegram bot and share your contact first."
        }), 400

    try:
        issued = otp_service.issue(user, purpose="SIGNUP", channel="TELEGRAM")
        delivery = _delivery(issued) or {"telegram": "sent"}
        ok = delivery.get("telegram") in ("sent", "dry_run", "pending")
        return jsonify({
            "success": ok,
            "delivery": delivery,
            "message": "Verification code dispatched to your Telegram chat." if ok
                       else f"Telegram delivery {delivery.get('telegram')}. Press Start in the bot and retry."
        }), 200 if ok else 502
    except otp_service.OtpRateLimitError as e:
        return jsonify({"success": False, "message": str(e)}), 429
    except Exception:
        logger.exception("Error sending Telegram OTP")
        return jsonify({"success": False, "message": "Could not send Telegram OTP."}), 500


@api_bp.route('/register/verify_telegram', methods=['POST'])
@limiter.limit("15 per minute")
def register_verify_telegram():
    import otp_service
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id') or '').strip()
    code = str(data.get('code') or '').strip()

    if not user_id or not code:
        return jsonify({"success": False, "message": "user_id and code are required."}), 400

    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.status != "PENDING":
        return jsonify({"success": False, "message": "Pending registration not found."}), 404

    verified = otp_service.verify(user, purpose="SIGNUP", channel="TELEGRAM", code=code)
    if not verified:
        return jsonify({"success": False, "message": "Invalid or expired verification code."}), 400

    # Telegram OTP verified! Check if email is also verified
    if user.email_verified:
        device_id = request.headers.get("X-Device-ID") or data.get("device_id")
        resp_data = _activate_user_and_issue_tokens(user, device_id=device_id)
        return jsonify(resp_data), 200
    else:
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Telegram verified successfully. Please also verify your email code.",
            "telegram_verified": True,
            "email_verified": False,
            "status": "PENDING"
        }), 200


@api_bp.route('/register', methods=['POST'])
def register():
    """
    Retired: the legacy one-step signup created accounts without OTP verification,
    honeypot/Turnstile/timing checks or the 3-per-IP limit. Use /api/register/start.
    """
    return jsonify({
        "success": False,
        "error": "ENDPOINT_RETIRED",
        "message": "Use /api/register/start (dual email + Telegram verification)."
    }), 410


@api_bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    pin = data.get('login_pin') or data.get('pin')
    device_id = _clean_device_id(data.get('device_id') or request.headers.get('X-Device-ID'))

    from user_manager import authenticate_login, is_device_trusted, bind_device
    from database import User
    import otp_service

    # Authenticate credentials using login PIN only (5 attempts lockout in DB)
    success, msg, user = authenticate_login(user_id, pin)
    if not success or not user:
        status_code = 403 if "locked" in msg.lower() else 401
        log_audit_action(user_id or "unknown", "LOGIN_FAIL", status_code)
        return jsonify({"success": False, "message": msg}), status_code

    # Frozen or pending accounts cannot log in
    if user.status != "ACTIVE":
        log_audit_action(user.user_id, "LOGIN_INACTIVE_BLOCK", 403)
        return jsonify({
            "success": False,
            "error": "ACCOUNT_INACTIVE",
            "message": "Account is not active or has been frozen."
        }), 403

    # Check device binding and 30-day trust
    if device_id and is_device_trusted(user, device_id, max_age_days=30):
        # Known trusted device under 30 days: direct login
        bind_device(user, device_id)
        db.session.commit()

        access_token = create_access_token(identity=user.user_id, expires_delta=timedelta(hours=1))
        refresh_token = create_refresh_token(identity=user.user_id, expires_delta=timedelta(days=30))
        log_audit_action(user.user_id, "LOGIN_SUCCESS_TRUSTED_DEVICE", 200)

        return jsonify({
            "success": True,
            "status": "LOGGED_IN",
            "message": "Login successful.",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_id": user.user_id,
            "upi_id": user.get_decrypted_upi_id()
        }), 200
    else:
        # Unknown device or expired trust (>30 days): Issue Dual OTPs
        try:
            res = otp_service.issue_dual(user, purpose="LOGIN_NEW_DEVICE", ip_address=_req_ip())
            delivery = _delivery(res)
            log_audit_action(user.user_id, "LOGIN_OTP_REQUIRED", 200)
            return jsonify({
                "success": True,
                "status": "OTP_REQUIRED",
                "message": "Unrecognized or expired device. " + _otp_message(delivery),
                "delivery": delivery,
                "delivery_detail": _delivery_detail(res),
                "user_id": user.user_id
            }), 200
        except otp_service.OtpRateLimitError as e:
            return jsonify({"success": False, "message": str(e)}), 429
        except Exception:
            logger.exception(f"Error issuing dual login OTPs for {user.user_id}")
            return jsonify({"success": False, "message": "Failed to send verification codes. Please try again."}), 500


@api_bp.route('/login/verify', methods=['POST'])
@limiter.limit("15 per minute")
def login_verify():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id') or '').strip()
    email_code = str(data.get('email_code') or '').strip()
    telegram_code = str(data.get('telegram_code') or '').strip()
    device_id = _clean_device_id(data.get('device_id') or request.headers.get('X-Device-ID'))

    if not user_id or not email_code or not telegram_code:
        return jsonify({
            "success": False,
            "message": "user_id, email_code, and telegram_code are required."
        }), 400

    from database import User
    from user_manager import bind_device
    import otp_service

    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    # Frozen or pending accounts cannot log in
    if user.status != "ACTIVE":
        return jsonify({
            "success": False,
            "error": "ACCOUNT_INACTIVE",
            "message": "Account is not active or has been frozen."
        }), 403

    # Verify dual OTP codes
    verified = otp_service.verify_dual(
        user=user,
        purpose="LOGIN_NEW_DEVICE",
        email_code=email_code,
        telegram_code=telegram_code
    )

    if not verified:
        log_audit_action(user.user_id, "LOGIN_VERIFY_FAIL", 400)
        return jsonify({
            "success": False,
            "message": "Invalid or expired verification codes."
        }), 400

    # Add/update device in known_devices
    if device_id:
        bind_device(user, device_id)
    db.session.commit()

    access_token = create_access_token(identity=user.user_id, expires_delta=timedelta(hours=1))
    refresh_token = create_refresh_token(identity=user.user_id, expires_delta=timedelta(days=30))
    log_audit_action(user.user_id, "LOGIN_VERIFY_SUCCESS", 200)

    return jsonify({
        "success": True,
        "status": "LOGGED_IN",
        "message": "Device verified and bound. Login successful.",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user_id": user.user_id,
        "upi_id": user.get_decrypted_upi_id()
    }), 200


@api_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    uid = get_jwt_identity()
    jti = get_jwt()["jti"]
    from database import TokenBlocklist
    try:
        db.session.add(TokenBlocklist(jti=jti))
        db.session.commit()
        log_audit_action(uid, "LOGOUT", 200)
        return jsonify({"success": True, "message": "Successfully logged out."}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Logout error for user {uid}: {e}")
        return jsonify({"success": False, "message": "Logout failed due to a server error."}), 500


@api_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    uid = get_jwt_identity()
    user = User.query.filter_by(user_id=uid).first()
    if not user or user.status != "ACTIVE":
        return jsonify({"success": False, "message": "Account inactive or invalid."}), 403
    new_token = create_access_token(identity=uid, expires_delta=timedelta(hours=1))
    return jsonify({"success": True, "access_token": new_token}), 200


# ----------------------------------------------------
# ACCOUNT PRIVACY & DEMO ENDPOINTS (PART 15)
# ----------------------------------------------------

@api_bp.route('/account/reset_balance', methods=['POST'])
@jwt_required(optional=True)
def reset_balance():
    """
    Demo feature: Restores account balance to 100,000 virtual rupees.
    Allowed at most once per hour per user. Requires the user's own JWT
    (a body user_id alone let anyone reset any account).
    """
    user_id = get_jwt_identity()
    if not user_id:
        return jsonify({"success": False, "error": "UNAUTHORIZED", "message": "Login required."}), 401

    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({"success": False, "error": "USER_NOT_FOUND", "message": "User not found."}), 404

    if user.status != "ACTIVE":
        return jsonify({"success": False, "error": "ACCOUNT_NOT_ACTIVE", "message": "Only active accounts can reset balance."}), 403

    now = datetime.utcnow()
    if user.last_balance_reset_at:
        elapsed = now - user.last_balance_reset_at
        if elapsed < timedelta(hours=1):
            remaining_seconds = int((timedelta(hours=1) - elapsed).total_seconds())
            remaining_minutes = max(1, remaining_seconds // 60)
            return jsonify({
                "success": False,
                "error": "RATE_LIMITED",
                "message": f"Balance can only be reset once per hour. Please wait {remaining_minutes} minute(s)."
            }), 429

    user.balance = 100000.00
    user.last_balance_reset_at = now
    db.session.commit()
    log_audit_action(user.user_id, "BALANCE_RESET", 200)

    return jsonify({
        "success": True,
        "message": "Account balance restored to ₹100,000.00 virtual rupees.",
        "balance": 100000.00
    }), 200


@api_bp.route('/account/delete', methods=['POST'])
@jwt_required(optional=True)
def account_delete():
    """
    Privacy & Account Deletion:
    Requires payment PIN and dual OTPs (Email + Telegram).
    If OTPs are not provided, verifies payment PIN and dispatches dual OTPs.
    Once verified:
    1. Removes all personally identifiable data from user record.
    2. Sets status to DELETED and revokes all active JWTs.
    3. Anonymizes ledger transaction rows.
    """
    uid = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    user_id = uid or data.get('user_id')
    if not user_id:
        return jsonify({"success": False, "error": "UNAUTHORIZED", "message": "Authentication or user_id required."}), 401

    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({"success": False, "error": "USER_NOT_FOUND", "message": "User not found."}), 404

    if user.status not in ("ACTIVE", "FROZEN"):
        return jsonify({"success": False, "error": "INVALID_STATUS", "message": "Account is already deleted or pending."}), 400

    payment_pin = str(data.get('payment_pin') or '').strip()
    if not payment_pin:
        return jsonify({"success": False, "error": "PIN_REQUIRED", "message": "Payment PIN is required."}), 400

    # 1. Verify Payment PIN
    from user_manager import verify_user_payment_pin
    is_valid_pin, err_msg = verify_user_payment_pin(user, payment_pin)
    if not is_valid_pin:
        return jsonify({"success": False, "error": "INVALID_PIN", "message": err_msg or "Incorrect payment PIN."}), 401

    email_code = str(data.get('email_code') or '').strip()
    telegram_code = str(data.get('telegram_code') or '').strip()

    # 2. If dual OTP codes are not provided, issue them
    if not email_code or not telegram_code:
        try:
            res = otp_service.issue_dual(user, purpose="ACCOUNT_DELETE", ip_address=_req_ip())
        except otp_service.OtpRateLimitError as e:
            return jsonify({"success": False, "message": str(e)}), 429
        delivery = _delivery(res)
        return jsonify({
            "success": True,
            "status": "OTP_REQUIRED",
            "delivery": delivery,
            "message": _otp_message(delivery, "Dual verification codes")
        }), 200

    # 3. Verify Dual OTP (verify_dual returns bool; older mocks return (bool, message))
    verify_res = otp_service.verify_dual(
        user, purpose="ACCOUNT_DELETE",
        email_code=email_code, telegram_code=telegram_code
    )
    verified, otp_err = verify_res if isinstance(verify_res, tuple) else (bool(verify_res), None)
    if not verified:
        return jsonify({"success": False, "error": "OTP_INVALID", "message": otp_err or "Invalid verification codes."}), 400

    # 4. Anonymize user ledger rows
    user_upi = user.get_decrypted_upi_id()
    if user_upi:
        # sender_upi/receiver_upi are Fernet-encrypted (non-deterministic), so a SQL
        # equality on the plaintext never matched and deleted users stayed in the ledger.
        for t in Transaction.query.filter(Transaction.user_id == user.user_id).all():
            t.sender_upi = "deleted_user@mlbfd"
        for t in Transaction.query.filter(Transaction.user_id != user.user_id).yield_per(500):
            if t.receiver_upi == user_upi or decrypt_val(t.receiver_upi) == user_upi:
                t.receiver_upi = "deleted_user@mlbfd"
            if t.sender_upi == user_upi:
                t.sender_upi = "deleted_user@mlbfd"

    Transaction.query.filter(Transaction.user_id == user.user_id).update({
        Transaction.device_id: None,
        Transaction.latitude: None,
        Transaction.longitude: None,
        Transaction.qr_code: None
    }, synchronize_session=False)

    # 5. Scrub Personal Data & Revoke Access
    user.full_name = "Deleted User"
    user.phone = None
    user.phone_hash = None
    user.phone_number = None
    user.email = None
    user.email_hash = None
    user.upi_id = None
    user.upi_hash = None
    user.telegram_chat_id = None
    user.telegram_verified = False
    user.security_question = None
    user.security_answer_hash = None
    user.known_devices = []
    user.status = "DELETED"
    user.balance = 0.00
    user.login_pin_hash = None
    user.payment_pin_hash = None
    user.pin_hash = None
    user.tokens_revoked_at = datetime.utcnow()

    # Clear trusted payees and behavior baselines
    TrustedPayee.query.filter_by(user_id=user.user_id).delete()
    UserBehaviorBaseline.query.filter_by(user_id=user.user_id).delete()

    db.session.commit()
    log_audit_action(user.user_id, "ACCOUNT_DELETE_SUCCESS", 200)

    return jsonify({
        "success": True,
        "message": "Account personal data successfully deleted and ledger records anonymized."
    }), 200


# ----------------------------------------------------
# PIN MANAGEMENT ENDPOINTS (CHANGE & FORGOT PIN)
# ----------------------------------------------------

@api_bp.route('/pin/change', methods=['POST'])
@jwt_required(optional=True)
def pin_change():
    """
    Step 1 of PIN change:
    - Verifies current PIN (login or payment)
    - Validates new PIN (6 digits, reject weak, must differ from other PIN and current PIN)
    - Sends dual OTPs to registered email and Telegram
    """
    uid = get_jwt_identity()
    data = request.get_json() or {}
    user_id = uid or data.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "Authentication or user_id required."}), 401
        
    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.status != "ACTIVE":
        return jsonify({"success": False, "message": "Active user account required."}), 404
        
    pin_type = str(data.get('pin_type') or '').strip().lower()
    if pin_type not in ('login', 'payment'):
        return jsonify({"success": False, "message": "pin_type must be 'login' or 'payment'."}), 400
        
    current_pin = str(data.get('current_pin') or '').strip()
    new_pin = str(data.get('new_pin') or '').strip()
    
    if not current_pin or not new_pin:
        return jsonify({"success": False, "message": "current_pin and new_pin are required."}), 400
        
    # Check if account is locked for that PIN type
    if pin_type == "login" and user.is_login_locked():
        return jsonify({"success": False, "message": "Login is temporarily locked due to too many failed attempts."}), 403
    if pin_type == "payment" and user.is_payment_locked():
        return jsonify({"success": False, "message": "Payment PIN is temporarily locked due to too many failed attempts."}), 403

    # Validate new PIN format and weakness
    is_valid_pin, err_msg = validate_pin(new_pin)
    if not is_valid_pin:
        return jsonify({"success": False, "message": f"New {pin_type} PIN is invalid: {err_msg}"}), 400

    # New PIN must differ from current PIN
    if current_pin == new_pin:
        return jsonify({"success": False, "message": "New PIN must be different from current PIN."}), 400

    # New PIN must differ from other PIN
    if pin_type == "login":
        if user.payment_pin_hash and verify_pin(new_pin, user.payment_pin_hash):
            return jsonify({"success": False, "message": "Login PIN and Payment PIN must differ."}), 400
    else:
        if user.login_pin_hash and verify_pin(new_pin, user.login_pin_hash):
            return jsonify({"success": False, "message": "Payment PIN and Login PIN must differ."}), 400

    # Verify current PIN against stored hash
    current_hash = user.login_pin_hash if pin_type == "login" else user.payment_pin_hash
    if not current_hash or not verify_pin(current_pin, current_hash):
        if pin_type == "login":
            user.login_failed_attempts = (user.login_failed_attempts or 0) + 1
            if user.login_failed_attempts >= 5:
                user.login_locked_until = datetime.utcnow() + timedelta(minutes=15)
        else:
            user.payment_failed_attempts = (user.payment_failed_attempts or 0) + 1
            if user.payment_failed_attempts >= 3:
                user.payment_locked_until = datetime.utcnow() + timedelta(minutes=30)
        db.session.commit()
        return jsonify({"success": False, "message": "Invalid current PIN."}), 400

    # Reset failed attempts on success
    if pin_type == "login":
        user.login_failed_attempts = 0
    else:
        user.payment_failed_attempts = 0

    # Invalidate existing pending changes for this user & pin_type
    PendingPinChange.query.filter_by(user_id=user.user_id, pin_type=pin_type).delete()

    # Save pending PIN change (10-minute expiry)
    new_pin_hash = hash_pin(new_pin, rounds=12)
    pending = PendingPinChange(
        user_id=user.user_id,
        pin_type=pin_type,
        new_pin_hash=new_pin_hash,
        expires_at=datetime.utcnow() + timedelta(minutes=10)
    )
    db.session.add(pending)
    db.session.commit()

    # Dispatch dual OTPs (Email + Telegram)
    try:
        res = otp_service.issue_dual(user=user, purpose="PIN_CHANGE", ip_address=_req_ip())
    except otp_service.OtpRateLimitError as e:
        return jsonify({"success": False, "message": str(e)}), 429
    except Exception:
        logger.exception("Error issuing dual OTP for PIN change")
        return jsonify({"success": False, "message": "Failed to send verification codes. Please try again."}), 500

    delivery = _delivery(res)
    log_audit_action(user.user_id, f"PIN_CHANGE_INITIATED_{pin_type.upper()}", 200)
    return jsonify({
        "success": True,
        "status": "OTP_SENT",
        "message": f"Current {pin_type} PIN verified. " + _otp_message(delivery),
        "delivery": delivery,
        "pin_type": pin_type
    }), 200


@api_bp.route('/pin/change/confirm', methods=['POST'])
@jwt_required(optional=True)
def pin_change_confirm():
    """
    Step 2 of PIN change:
    - Verifies dual OTP codes (both email_code and telegram_code required)
    - Updates the PIN in database
    """
    uid = get_jwt_identity()
    data = request.get_json() or {}
    user_id = uid or data.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "Authentication or user_id required."}), 401

    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.status != "ACTIVE":
        return jsonify({"success": False, "message": "Active user account required."}), 404

    email_code = str(data.get('email_code') or '').strip()
    telegram_code = str(data.get('telegram_code') or '').strip()
    if not email_code or not telegram_code:
        return jsonify({"success": False, "message": "Both email_code and telegram_code are required."}), 400

    # Retrieve active pending PIN change
    pending = PendingPinChange.query.filter_by(user_id=user.user_id).order_by(PendingPinChange.created_at.desc()).first()
    if not pending or datetime.utcnow() > pending.expires_at:
        return jsonify({"success": False, "message": "No active PIN change request found or request expired. Please start over."}), 400

    # Verify dual OTP
    is_valid = otp_service.verify_dual(
        user=user,
        purpose="PIN_CHANGE",
        email_code=email_code,
        telegram_code=telegram_code
    )
    if not is_valid:
        return jsonify({"success": False, "message": "Invalid or expired OTP codes. Both codes are required."}), 400

    # Commit PIN update
    pin_type = pending.pin_type
    if pin_type == "login":
        user.login_pin_hash = pending.new_pin_hash
        user.login_failed_attempts = 0
        user.login_locked_until = None
    else:
        user.payment_pin_hash = pending.new_pin_hash
        user.payment_failed_attempts = 0
        user.payment_locked_until = None

    db.session.delete(pending)
    db.session.commit()

    log_audit_action(user.user_id, f"PIN_CHANGE_CONFIRMED_{pin_type.upper()}", 200)
    return jsonify({
        "success": True,
        "message": f"{pin_type.capitalize()} PIN updated successfully."
    }), 200


@api_bp.route('/pin/forgot/start', methods=['POST'])
@limiter.limit("3 per hour")
def pin_forgot_start():
    """
    Step 1 of forgot PIN:
    - Generic response whether or not user exists
    - Limit reset starts to 3 per hour
    - Dispatches dual OTPs to email and Telegram if account exists
    """
    data = request.get_json() or {}
    identifier = str(data.get('user_id') or data.get('identifier') or '').strip()
    generic_msg = "If an account matches the provided identifier, verification codes have been sent to registered channels."

    if not identifier:
        return jsonify({"success": True, "message": generic_msg}), 200

    # Resolve user
    user = User.query.filter_by(user_id=identifier).first()
    if not user:
        from user_manager import find_user_by_upi_or_phone
        user = find_user_by_upi_or_phone(identifier)

    if not user or user.status != "ACTIVE":
        return jsonify({"success": True, "message": generic_msg}), 200

    # Check 3 per hour limit per user in DB
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent_starts = OtpCode.query.filter(
        OtpCode.user_id == user.user_id,
        OtpCode.purpose == "PIN_RESET",
        OtpCode.created_at >= one_hour_ago
    ).count()
    if recent_starts >= 6:  # 3 pairs of EMAIL + TELEGRAM = 6 records
        return jsonify({"success": False, "message": "Rate limit exceeded. Maximum 3 reset requests per hour."}), 429

    delivery = {}
    try:
        res = otp_service.issue_dual(user=user, purpose="PIN_RESET", ip_address=_req_ip())
        delivery = _delivery(res)
        log_audit_action(user.user_id, "PIN_FORGOT_INITIATED", 200)
    except otp_service.OtpRateLimitError as e:
        return jsonify({"success": False, "message": str(e)}), 429
    except Exception:
        logger.exception("Error issuing dual OTP for forgot PIN")

    return jsonify({
        "success": True,
        "message": generic_msg,
        "delivery": delivery,
        "user_id": user.user_id  # Provided for seamless UI continuation
    }), 200


@api_bp.route('/pin/forgot/verify', methods=['POST'])
def pin_forgot_verify():
    """
    Step 2 of forgot PIN:
    - Verifies dual OTP codes
    - Returns a 10-minute reset token
    """
    data = request.get_json() or {}
    user_id = str(data.get('user_id') or '').strip()
    email_code = str(data.get('email_code') or '').strip()
    telegram_code = str(data.get('telegram_code') or '').strip()

    if not (user_id and email_code and telegram_code):
        return jsonify({"success": False, "message": "user_id, email_code, and telegram_code are required."}), 400

    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.status != "ACTIVE":
        return jsonify({"success": False, "message": "Invalid user or verification codes."}), 400

    is_valid = otp_service.verify_dual(
        user=user,
        purpose="PIN_RESET",
        email_code=email_code,
        telegram_code=telegram_code
    )
    if not is_valid:
        return jsonify({"success": False, "message": "Invalid or expired OTP codes. Both codes are required."}), 400

    # Generate single-use 10-minute reset token
    reset_token = secrets.token_urlsafe(32)
    reset_record = PasswordResetToken(
        token=reset_token,
        user_id=user.user_id,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
        used=False
    )
    db.session.add(reset_record)
    db.session.commit()

    log_audit_action(user.user_id, "PIN_FORGOT_VERIFIED", 200)
    return jsonify({
        "success": True,
        "message": "Verification successful. You may now reset your PIN.",
        "reset_token": reset_token,
        "security_question": user.security_question or "Security verification question"
    }), 200


@api_bp.route('/pin/forgot/reset', methods=['POST'])
def pin_forgot_reset():
    """
    Step 3 of forgot PIN:
    - Validates 10-minute reset_token
    - Checks security_answer (lowercased, trimmed, bcrypt)
    - Validates new_pin (6 digits, non-weak, differing from other PIN)
    - Blacklists all active JWTs (tokens_revoked_at = now)
    - Clears known devices except current device
    - Enables 24-hour reduced-limit mode (max Rs 10,000 / txn, Rs 25,000 / day)
    - Notifies both email and Telegram channels
    """
    data = request.get_json() or {}
    reset_token = str(data.get('reset_token') or '').strip()
    security_answer = str(data.get('security_answer') or '').strip()
    new_pin = str(data.get('new_pin') or '').strip()
    pin_type = str(data.get('pin_type') or 'login').strip().lower()

    if not (reset_token and security_answer and new_pin):
        return jsonify({"success": False, "message": "reset_token, security_answer, and new_pin are required."}), 400

    if pin_type not in ('login', 'payment'):
        pin_type = 'login'

    # Check reset token
    reset_record = PasswordResetToken.query.filter_by(token=reset_token, used=False).first()
    if not reset_record or datetime.utcnow() > reset_record.expires_at:
        return jsonify({"success": False, "message": "Invalid or expired reset token. Please request a new one."}), 400

    user = User.query.filter_by(user_id=reset_record.user_id).first()
    if not user or user.status not in ["ACTIVE", "FROZEN"]:
        return jsonify({"success": False, "message": "Account invalid or inactive."}), 400

    # Verify security answer (lowercased, trimmed, bcrypt)
    if not user.security_answer_hash or not verify_pin(security_answer.lower(), user.security_answer_hash):
        log_audit_action(user.user_id, "PIN_RESET_FAILED_SECURITY_ANSWER", 400)
        return jsonify({"success": False, "message": "Incorrect security answer."}), 400

    # Validate new PIN format and weak checks
    is_valid_pin, err_msg = validate_pin(new_pin)
    if not is_valid_pin:
        return jsonify({"success": False, "message": f"New PIN is invalid: {err_msg}"}), 400

    # New PIN must differ from the other PIN
    if pin_type == "login":
        if user.payment_pin_hash and verify_pin(new_pin, user.payment_pin_hash):
            return jsonify({"success": False, "message": "Login PIN must differ from payment PIN."}), 400
        user.login_pin_hash = hash_pin(new_pin, rounds=12)
        user.login_failed_attempts = 0
        user.login_locked_until = None
    else:
        if user.login_pin_hash and verify_pin(new_pin, user.login_pin_hash):
            return jsonify({"success": False, "message": "Payment PIN must differ from login PIN."}), 400
        user.payment_pin_hash = hash_pin(new_pin, rounds=12)
        user.payment_failed_attempts = 0
        user.payment_locked_until = None

    now = datetime.utcnow()

    # 1. Blacklist all active JWTs
    user.tokens_revoked_at = now
    blocklist_entry = TokenBlocklist(
        jti=f"all-{user.user_id}-{int(time.time())}",
        user_id=user.user_id,
        created_at=now
    )
    db.session.add(blocklist_entry)

    # 2. Clear known devices except the current one
    current_device_id = request.headers.get("X-Device-ID") or data.get("device_id")
    if current_device_id:
        user.known_devices = [{"device_id": current_device_id, "last_verified_at": now.isoformat()}]
    else:
        user.known_devices = []

    # Also update UserBehaviorBaseline known_devices
    baseline = UserBehaviorBaseline.query.filter_by(user_id=user.user_id).first()
    if baseline:
        baseline.known_devices = [current_device_id] if current_device_id else []

    # 3. Enable 24-hour reduced-limit mode
    user.reduced_limit_until = now + timedelta(hours=24)
    user.daily_spent_date = now.strftime("%Y-%m-%d")
    user.daily_spent_amount = 0.00

    # If account was frozen, unfreeze upon verified PIN reset
    if user.status == "FROZEN":
        user.status = "ACTIVE"
        user.is_locked = False
        user.login_failed_attempts = 0
        user.login_locked_until = None
        user.payment_failed_attempts = 0
        user.payment_locked_until = None

    # Mark reset token as used
    reset_record.used = True
    db.session.commit()

    # 4. Notify both email and Telegram channels
    notify_msg = (
        f"Security Alert: Your MLBFD {pin_type.capitalize()} PIN was successfully reset. "
        "All previous sessions have been logged out. A 24-hour reduced transaction limit "
        f"(max ₹{Config.REDUCED_TXN_LIMIT:,.0f}/txn, ₹{Config.REDUCED_DAILY_LIMIT:,.0f}/day) "
        "has been activated on your account. If you did not initiate this, freeze your account immediately."
    )
    try:
        otp_service.get_channel_sender('EMAIL').send(user, 'EMAIL', notify_msg)
    except Exception as e:
        logger.warning(f"Could not send PIN reset email alert: {e}")
    try:
        otp_service.get_channel_sender('TELEGRAM').send(user, 'TELEGRAM', notify_msg)
    except Exception as e:
        logger.warning(f"Could not send PIN reset Telegram alert: {e}")

    log_audit_action(user.user_id, "PIN_RESET_COMPLETED", 200)

    # Issue fresh tokens for the current device
    access_token = create_access_token(identity=user.user_id, expires_delta=timedelta(hours=1))
    refresh_token = create_refresh_token(identity=user.user_id, expires_delta=timedelta(days=30))

    return jsonify({
        "success": True,
        "message": f"{pin_type.capitalize()} PIN reset successfully. Reduced limit mode active for 24 hours.",
        "access_token": access_token,
        "refresh_token": refresh_token
    }), 200


# ----------------------------------------------------
# TRANSACTION ENDPOINTS
# ----------------------------------------------------
@api_bp.route('/predict-secure', methods=['POST'])
@api_bp.route('/predict_secure', methods=['POST'])
@jwt_required()
def predict_secure():
    """Calculates real-time risk scores for what-if previews. Does NOT save transaction."""
    uid = get_jwt_identity()
    data = request.get_json()
    
    # Enforce request signature verification to prevent replay attacks
    if request.headers.get("X-Signature") or request.headers.get("X-Timestamp"):
        if not verify_headers(request):
            logger.warning(f"Signature check failed on predict-secure for user {uid}")
            return jsonify({"success": False, "message": "Invalid request signature. Potential replay attack."}), 400
        
    try:
        # Construct txn payload
        txn_payload = {
            'user_id': uid,
            'sender_upi': data.get('sender_upi'),
            'receiver_upi': data.get('receiver_upi'),
            'amount': float(data.get('amount', 0)),
            'device_id': _clean_device_id(data.get('device_id')),
            'latitude': float(data.get('latitude', 0.0)),
            'longitude': float(data.get('longitude', 0.0)),
            'biometric_failed': data.get('biometric_failed', False),
            'qr_code': data.get('qr_code', ''),
            'mcc_code': _clean_mcc(data.get('mcc_code'))
        }
        
        verdict = global_fraud_detector.detect(txn_payload)
        log_audit_action(uid, "PREDICT_SECURE", 200, risk_score=verdict['risk_score'])
        return jsonify(verdict), 200
    except Exception as e:
        logger.error(f"Predict secure error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@api_bp.route('/lookup_payee', methods=['GET'])
@jwt_required()
@limiter.limit("10 per minute")
def lookup_payee():
    """
    Looks up a payee by UPI id, 10-digit phone, or +91 phone.
    Returns masked name and masked UPI id for confirmation card.
    Only ACTIVE users can be looked up.
    """
    uid = get_jwt_identity()
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"error": "USER_NOT_REGISTERED", "message": "Payee identifier required."}), 400

    from user_manager import find_user_by_upi_or_phone
    payee_user = find_user_by_upi_or_phone(q)
    if not payee_user or payee_user.status != 'ACTIVE':
        return jsonify({
            "error": "USER_NOT_REGISTERED",
            "message": "This user is not registered on MLBFD"
        }), 404

    if payee_user.user_id == uid:
        return jsonify({
            "error": "SELF_TRANSFER_BLOCKED",
            "message": "Self-transfer is not permitted."
        }), 400

    raw_name = payee_user.full_name or "MLBFD User"
    payee_upi = payee_user.get_decrypted_upi_id() or f"{payee_user.user_id}@mlbfd"

    # Mask name: e.g. "Chirag Patil" -> "C****g P***l"
    name_parts = raw_name.split()
    masked_name_parts = []
    for part in name_parts:
        if len(part) <= 2:
            masked_name_parts.append(part[0] + "*")
        else:
            masked_name_parts.append(part[0] + "*" * (len(part) - 2) + part[-1])
    masked_name = " ".join(masked_name_parts)

    masked_upi_str = mask_upi(payee_upi)

    return jsonify({
        "success": True,
        "registered": True,
        "masked_name": masked_name,
        "masked_upi": masked_upi_str,
        "receiver_upi": payee_upi,
        "receiver": payee_upi
    }), 200


@api_bp.route('/transfer', methods=['POST'])
@jwt_required()
def transfer():
    """Executes money transfer. Runs detection, saves log, updates balance if safe."""
    uid = get_jwt_identity()
    data = request.get_json() or {}
    
    # Enforce request signature verification to prevent replay attacks
    if request.headers.get("X-Signature") or request.headers.get("X-Timestamp"):
        if not verify_headers(request):
            logger.warning(f"Signature check failed on transfer for user {uid}")
            return jsonify({"success": False, "message": "Invalid request signature. Potential replay attack."}), 400
    
    user = User.query.filter_by(user_id=uid).first()
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
        
    # Check if payment transactions are locked (3 wrong payment PINs lock payments for 30 minutes)
    if user.is_payment_locked():
        return jsonify({"success": False, "message": "Payment transactions temporarily locked. Please try again later."}), 403

    # 1. Enforce Payment PIN Verification BEFORE any scoring
    payment_pin = data.get('payment_pin') or data.get('pin')
    if not payment_pin:
        return jsonify({"success": False, "message": "Payment authorization failed."}), 400
        
    from user_manager import verify_user_payment_pin
    pin_ok, pin_msg = verify_user_payment_pin(user, payment_pin)
    if not pin_ok:
        status_code = 403 if "locked" in pin_msg.lower() else 401
        return jsonify({"success": False, "message": pin_msg}), status_code
        
    amount = _parse_amount(data.get('amount'))
    if amount is None:
        # A negative amount used to reverse the transfer (sender credited, receiver debited).
        return jsonify({"success": False, "error": "INVALID_AMOUNT",
                        "message": f"Amount must be a positive number up to {MAX_TXN_AMOUNT:,.0f} with at most 2 decimals."}), 400
    if float(user.balance) < amount:
        return jsonify({"success": False, "message": "Insufficient virtual balance."}), 400

    # 2. Enforce 24-Hour Reduced Limit & Daily Limit checks
    is_reduced = user.is_reduced_limit_active()
    reduced_txn_limit = Config.REDUCED_TXN_LIMIT
    reduced_daily_limit = Config.REDUCED_DAILY_LIMIT

    if is_reduced and amount > reduced_txn_limit:
        return jsonify({
            "success": False,
            "message": f"Transaction limit exceeded. Your account is in 24-hour reduced-limit mode (max ₹{reduced_txn_limit:,.2f} per transaction)."
        }), 400

    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    todays_txns = Transaction.query.filter(
        Transaction.user_id == uid,
        Transaction.created_at >= start_of_day,
        Transaction.status.in_(["APPROVED", "APPROVED_WITH_WARNING", "COMPLETED"])
    ).all()
    todays_total = sum(float(t.amount) for t in todays_txns)
    effective_daily_limit = reduced_daily_limit if is_reduced else float(user.daily_limit or 50000.00)

    if todays_total + amount > effective_daily_limit:
        mode_text = " (24-hour reduced-limit mode active)" if is_reduced else ""
        return jsonify({
            "success": False,
            "message": f"Daily limit exceeded{mode_text}! You have sent ₹{todays_total:,.2f} today. Your daily limit is ₹{effective_daily_limit:,.2f}."
        }), 400
        
    # Enforce receiver resolution & registration check BEFORE scoring
    receiver_raw = str(data.get('receiver') or data.get('receiver_upi') or '').strip()
    if not receiver_raw:
        return jsonify({
            "error": "USER_NOT_REGISTERED",
            "message": "This user is not registered on MLBFD"
        }), 404

    from user_manager import find_user_by_upi_or_phone
    receiver_user = find_user_by_upi_or_phone(receiver_raw)
    if not receiver_user or receiver_user.status != 'ACTIVE':
        return jsonify({
            "error": "USER_NOT_REGISTERED",
            "message": "This user is not registered on MLBFD"
        }), 404

    # Block self-transfer
    if receiver_user.user_id == uid:
        return jsonify({
            "error": "SELF_TRANSFER_BLOCKED",
            "message": "Self-transfer is not permitted."
        }), 400

    receiver_upi = receiver_user.get_decrypted_upi_id() or f"{receiver_user.user_id}@mlbfd"
    sender_upi = data.get('sender_upi') or user.get_decrypted_upi_id() or f"{user.user_id}@mlbfd"
    
    # Generate unique transaction ID
    txn_id = f"TXN-{int(time.time() * 1000)}"
    
    # Location and reverse geocoding (Part 16)
    txn_lat = float(data.get('latitude', data.get('lat', 0.0)))
    txn_lon = float(data.get('longitude', data.get('lon', 0.0)))
    txn_accuracy_m = float(data.get('accuracy_m') or data.get('accuracy')) if (data.get('accuracy_m') or data.get('accuracy')) is not None else None
    txn_source = data.get('source') or data.get('location_source') or 'gps'
    txn_area = None
    if txn_lat != 0.0 or txn_lon != 0.0:
        try:
            from geofence import reverse_geocode_nonblocking
            txn_area = reverse_geocode_nonblocking(txn_lat, txn_lon)
        except Exception as e:
            # Area name is cosmetic; never fail a payment on it, but do not hide the error.
            logger.warning(f"transfer: reverse geocode failed ({type(e).__name__})")

    # Construct detection payload
    txn_payload = {
        'user_id': uid,
        'sender_upi': sender_upi,
        'receiver_upi': receiver_upi,
        'amount': amount,
        'device_id': _clean_device_id(data.get('device_id')),
        'latitude': txn_lat,
        'longitude': txn_lon,
        'accuracy_m': txn_accuracy_m,
        'location_source': txn_source,
        'biometric_failed': data.get('biometric_failed', False),
        'qr_code': data.get('qr_code', ''),
        'mcc_code': _clean_mcc(data.get('mcc_code'))
    }
    
    # Run 7-layer fraud detection
    verdict = global_fraud_detector.detect(txn_payload)
    status = verdict['status']
    risk_score = verdict['risk_score']
    is_fraud = status == 'BLOCKED'
    
    # Determine DB status and expiry
    is_stepup = (status == 'REQUIRES_2FA')
    db_status = 'PENDING' if is_stepup else status
    expires_at = (otp_service.get_clock().now() + timedelta(minutes=10)) if is_stepup else None

    # Save transaction (UPIs are encrypted before write)
    try:
        new_txn = Transaction(
            txn_id=txn_id,
            user_id=uid,
            sender_upi=encrypt_val(sender_upi),
            receiver_upi=encrypt_val(receiver_upi),
            amount=amount,
            status=db_status,
            risk_score=risk_score,
            is_fraud=is_fraud,
            device_id=_clean_device_id(data.get('device_id')),
            latitude=txn_lat,
            longitude=txn_lon,
            accuracy_m=txn_accuracy_m,
            location_source=txn_source,
            area_name=txn_area,
            hour=datetime.utcnow().hour,
            day_of_week=datetime.utcnow().weekday(),
            qr_code=data.get('qr_code', ''),
            merchant_name=_clean_text(data.get('merchant_name', ''), 100),
            mcc_code=_clean_mcc(data.get('mcc_code')),
            layer_scores={
                **verdict['layers'],
                'top_5_features': verdict.get('top_5_features', []),
                'shap_explanations': verdict.get('shap_explanations', []),
                'plain_language_reason': verdict.get('plain_language_reason', '')
            },
            flags=verdict['flags'],
            ensemble_confidence=verdict['ensemble_confidence'],
            expires_at=expires_at,
            failed_attempts=0
        )
        db.session.add(new_txn)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to log transaction: {e}")
        return jsonify({"success": False, "message": "Transaction logging failed."}), 500
        
    # Deduct balance only if APPROVED or APPROVED_WITH_WARNING
    if status in ['APPROVED', 'APPROVED_WITH_WARNING']:
        try:
            # Debit + credit atomically (one commit, conditional UPDATE guards the balance).
            from user_manager import find_user_by_upi_or_phone
            receiver_user = find_user_by_upi_or_phone(receiver_upi)
            if not _move_funds(uid, receiver_user, amount):
                db.session.rollback()
                new_txn.status = 'CANCELLED'
                db.session.commit()
                return jsonify({"success": False, "status": "CANCELLED", "txn_id": txn_id,
                                "message": "Insufficient virtual balance."}), 400
            db.session.commit()
            db.session.refresh(user)

            # Update user behavior baseline rolling aggregates
            update_user_baseline(
                uid, amount, new_txn.hour, 
                new_txn.device_id, receiver_upi, new_txn.mcc_code
            )
            
            # Update trusted payee counts
            tp = TrustedPayee.query.filter_by(user_id=uid, payee_upi=receiver_upi).first()
            if tp:
                tp.txn_count += 1
                tp.total_amount = float(tp.total_amount) + amount
            else:
                tp = TrustedPayee(user_id=uid, payee_upi=receiver_upi, txn_count=1, total_amount=amount)
                db.session.add(tp)
            db.session.commit()
            
        except Exception:
            db.session.rollback()
            logger.exception("Failed to update balances / baselines after approval")

    # Audit log
    log_audit_action(uid, f"TRANSFER_{db_status}", 200, risk_score=risk_score)
    
    # Return response binding OTP trigger
    response = dict(verdict)
    response['txn_id'] = txn_id
    response['status'] = status
    response['txn_status'] = db_status
    
    # If 2FA required, trigger dual OTP send across Email and Telegram
    if is_stepup:
        try:
            res = otp_service.issue_dual(
                user=user,
                purpose="TRANSACTION",
                txn_id=txn_id,
                ip_address=_req_ip(),
                amount=amount,
                receiver=receiver_upi
            )
            response['delivery'] = _delivery(res)
            response['message'] = "Transaction held pending two-factor authorization. " + _otp_message(
                response['delivery'], "OTP security codes")
        except Exception:
            logger.exception("Failed to trigger dual OTP")
            response['delivery'] = {"email": "failed", "telegram": "failed"}
            response['message'] = "Transaction held pending two-factor authorization. Use Resend to get the codes."

    # Part 13: "Was this you?" alerts and signed freeze link on BLOCKED or REQUIRES_2FA
    if status in ['BLOCKED', 'REQUIRES_2FA']:
        try:
            from security import generate_freeze_token
            from database import AccountFreezeToken
            freeze_token = generate_freeze_token(uid)
            freeze_record = AccountFreezeToken(
                token=freeze_token,
                user_id=uid,
                expires_at=datetime.utcnow() + timedelta(hours=24),
                used=False
            )
            db.session.add(freeze_record)
            db.session.commit()

            base_url = request.host_url.rstrip('/')
            freeze_url = f"{base_url}/api/freeze?token={freeze_token}"
            response['freeze_url'] = freeze_url
            response['freeze_token'] = freeze_token

            masked_receiver = mask_upi(receiver_upi)
            txn_time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            lat = float(data.get('latitude', 0.0))
            lon = float(data.get('longitude', 0.0))
            approx_loc = f"Lat {lat:.4f}, Lon {lon:.4f}" if (lat != 0.0 or lon != 0.0) else "Location unavailable"
            reason_summary = "; ".join(verdict.get('top_reasons') or verdict.get('flags') or [f"Risk score: {risk_score}"])

            # 1. Send Email security alert
            user_email = user.get_decrypted_email()
            if user_email:
                from email_sender import default_email_sender
                default_email_sender.send_security_alert(
                    to_email=user_email,
                    amount=amount,
                    receiver=masked_receiver,
                    timestamp=txn_time_str,
                    location=approx_loc,
                    reason_summary=reason_summary,
                    freeze_link=freeze_url
                )

            # 2. Send Telegram security alert
            import telegram_bot
            telegram_msg = (
                f"🚨 <b>MLBFD Security Alert: Was this you?</b>\n\n"
                f"A suspicious transaction was flagged on your account ({status}):\n"
                f"• <b>Amount:</b> ₹{amount:,.2f}\n"
                f"• <b>Receiver:</b> {masked_receiver}\n"
                f"• <b>Time:</b> {txn_time_str}\n"
                f"• <b>Location:</b> {approx_loc}\n"
                f"• <b>Reasons:</b> {reason_summary}\n\n"
                f"If this was <b>NOT</b> you, immediately freeze your account using this secure link (valid for 24h):\n"
                f"{freeze_url}"
            )
            telegram_bot.send_telegram(user, telegram_msg)
        except Exception:
            logger.exception("Failed to dispatch 'Was this you?' alerts")

    return jsonify(response), 200


@api_bp.route('/freeze', methods=['GET'])
def freeze_account_via_link():
    """
    Validates single-use signed 24-hour freeze link and freezes user account.
    Unfreeze is only permitted via forgot-PIN flow or admin Users page.
    """
    token = request.args.get('token', '').strip()
    if not token:
        return jsonify({"success": False, "error": "MISSING_TOKEN", "message": "Freeze token is required."}), 400

    from security import verify_and_decode_freeze_token
    is_valid, user_id, err_msg = verify_and_decode_freeze_token(token)
    if not is_valid:
        return jsonify({"success": False, "error": "INVALID_TOKEN", "message": err_msg}), 400

    from database import AccountFreezeToken, TokenBlocklist
    freeze_record = AccountFreezeToken.query.filter_by(token=token).first()
    if not freeze_record:
        return jsonify({"success": False, "error": "INVALID_TOKEN", "message": "Freeze token not recognized."}), 400

    if freeze_record.used:
        return jsonify({"success": False, "error": "TOKEN_ALREADY_USED", "message": "This freeze link has already been used."}), 400

    if freeze_record.expires_at < datetime.utcnow():
        return jsonify({"success": False, "error": "TOKEN_EXPIRED", "message": "This freeze link has expired (valid for 24 hours)."}), 400

    user = User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({"success": False, "error": "USER_NOT_FOUND", "message": "User not found."}), 404

    # Mark token as used
    freeze_record.used = True

    # Freeze user account
    user.status = "FROZEN"
    user.is_locked = True
    now = datetime.utcnow()
    user.tokens_revoked_at = now

    # Revoke active JWTs
    blocklist_entry = TokenBlocklist(
        jti=f"freeze-{user.user_id}-{int(time.time())}",
        user_id=user.user_id,
        created_at=now
    )
    db.session.add(blocklist_entry)

    db.session.commit()
    log_audit_action(user_id, "FREEZE_VIA_LINK", 200)

    return jsonify({
        "success": True,
        "status": "FROZEN",
        "message": "Your MLBFD account has been frozen successfully. Unfreeze is only permitted via Forgot PIN verification or by contacting an administrator."
    }), 200


@api_bp.route('/balance/<uid>', methods=['GET'])
@jwt_required()
def get_balance(uid):
    identity = get_jwt_identity()
    if identity != uid:
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
        
    user = User.query.filter_by(user_id=uid).first()
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
        
    return jsonify({"success": True, "balance": float(user.balance)}), 200

@api_bp.route('/transactions/<uid>', methods=['GET'])
@jwt_required()
def get_transactions(uid):
    identity = get_jwt_identity()
    if identity != uid:
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
        
    # Fetch transactions where the user is the initiator (user_id field) — O(n) SQL filter.
    # Also fetch a batch of recent transactions to check if user appears as receiver (Fernet-encrypted, non-deterministic).
    sent_txns = Transaction.query.filter_by(user_id=uid).order_by(Transaction.created_at.desc()).all()
    # For received: check recent 500 (Fernet is non-deterministic, can't filter by encrypted value in SQL)
    recent_txns = Transaction.query.filter(
        Transaction.user_id != uid
    ).order_by(Transaction.created_at.desc()).limit(500).all()
    
    seen_ids = set()
    output = []
    
    for txn in sent_txns:
        if txn.id in seen_ids:
            continue
        seen_ids.add(txn.id)
        sender_dec = decrypt_val(txn.sender_upi)
        receiver_dec = decrypt_val(txn.receiver_upi)
        output.append({
            'txn_id': txn.txn_id,
            'sender_upi': sender_dec,
            'receiver_upi': receiver_dec,
            'amount': float(txn.amount),
            'status': txn.status,
            'risk_score': float(txn.risk_score),
            'is_fraud': txn.is_fraud,
            'created_at': txn.created_at.isoformat() + 'Z'
        })
    
    for txn in recent_txns:
        if txn.id in seen_ids:
            continue
        receiver_dec = decrypt_val(txn.receiver_upi)
        if receiver_dec == uid:
            seen_ids.add(txn.id)
            sender_dec = decrypt_val(txn.sender_upi)
            output.append({
                'txn_id': txn.txn_id,
                'sender_upi': sender_dec,
                'receiver_upi': receiver_dec,
                'amount': float(txn.amount),
                'status': txn.status,
                'risk_score': float(txn.risk_score),
                'is_fraud': txn.is_fraud,
                'created_at': txn.created_at.isoformat() + 'Z'
            })
    
    # Sort by date descending
    output.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify({"success": True, "transactions": output}), 200

# ----------------------------------------------------
# OTP / 2FA ENDPOINTS
# ----------------------------------------------------
@api_bp.route('/otp/send', methods=['POST'])
@jwt_required()
@limiter.limit("5 per minute")
def trigger_otp():
    uid = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    txn_id = data.get('txn_id')
    
    user = User.query.filter_by(user_id=uid).first()
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
        
    if not txn_id:
        return jsonify({"success": False, "message": "Transaction ID (txn_id) is required."}), 400

    txn = Transaction.query.filter_by(txn_id=txn_id, user_id=uid).first()
    if not txn:
        return jsonify({"success": False, "message": "Transaction not found."}), 404

    if txn.status != 'PENDING':
        return jsonify({"success": False, "message": f"Transaction is not pending verification (status: {txn.status})."}), 400

    # Check 10-minute expiry
    now = otp_service.get_clock().now()
    is_expired = (now > txn.expires_at) if txn.expires_at else (now - txn.created_at > timedelta(minutes=10))
    if is_expired:
        txn.status = 'CANCELLED'
        db.session.commit()
        return jsonify({"success": False, "status": "CANCELLED", "message": "Transaction expired. Transaction has been cancelled."}), 400

    try:
        receiver_dec = decrypt_val(txn.receiver_upi)
        res = otp_service.issue_dual(
            user=user,
            purpose="TRANSACTION",
            txn_id=txn_id,
            ip_address=_req_ip(),
            amount=float(txn.amount),
            receiver=receiver_dec
        )
        delivery = _delivery(res)
        return jsonify({"success": True, "delivery": delivery,
                        "message": _otp_message(delivery, "Security codes")}), 200
    except otp_service.OtpCooldownError as e:
        return jsonify({"success": False, "message": str(e)}), 429
    except otp_service.OtpRateLimitError as e:
        return jsonify({"success": False, "message": str(e)}), 429
    except Exception as e:
        logger.error(f"Failed to dispatch dual OTP: {e}")
        return jsonify({"success": False, "message": "Failed to dispatch security codes."}), 500

@api_bp.route('/otp/verify', methods=['POST'])
@jwt_required()
@limiter.limit("10 per minute")
def verify_otp_endpoint():
    uid = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    txn_id = data.get('txn_id')
    email_code = data.get('email_code')
    telegram_code = data.get('telegram_code')

    # Backward compatibility: if 'otp' is provided as a single field
    if not email_code and not telegram_code and data.get('otp'):
        email_code = data.get('otp')
        telegram_code = data.get('otp')
    
    # Enforce signature verification
    if request.headers.get("X-Signature") or request.headers.get("X-Timestamp"):
        if not verify_headers(request):
            logger.warning(f"Signature check failed on OTP verification for user {uid}")
            return jsonify({"success": False, "message": "Invalid request signature. Potential replay attack."}), 400
        
    user = User.query.filter_by(user_id=uid).first()
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    if user.status == "FROZEN":
        return jsonify({"success": False, "message": "Account is frozen. Transactions cannot be verified."}), 403

    if not txn_id:
        return jsonify({"success": False, "message": "Transaction ID (txn_id) is required."}), 400
        
    txn = Transaction.query.filter_by(txn_id=txn_id).first()
    if not txn:
        return jsonify({"success": False, "message": "Transaction not found."}), 404

    if txn.user_id != user.user_id:
        return jsonify({"success": False, "message": "Unauthorized transaction verification."}), 403

    if txn.status in ['COMPLETED', 'APPROVED', 'APPROVED_WITH_WARNING']:
        return jsonify({"success": False, "message": "Transaction has already been completed."}), 400

    if txn.status == 'CANCELLED':
        return jsonify({"success": False, "message": "Transaction has been cancelled."}), 400

    now = otp_service.get_clock().now()

    # 10-minute transaction expiry check
    is_expired = (now > txn.expires_at) if txn.expires_at else (now - txn.created_at > timedelta(minutes=10))
    if is_expired:
        txn.status = 'CANCELLED'
        db.session.commit()
        return jsonify({
            "success": False,
            "status": "CANCELLED",
            "message": "Transaction expired (10-minute limit exceeded). Transaction cancelled."
        }), 400

    if not email_code or not telegram_code:
        return jsonify({"success": False, "message": "Both email_code and telegram_code are required."}), 400

    # Verify both codes via verify_dual
    is_valid = otp_service.verify_dual(
        user=user,
        purpose="TRANSACTION",
        email_code=email_code,
        telegram_code=telegram_code,
        txn_id=txn_id
    )

    if is_valid:
        # Authenticated! Execute transfer in ONE atomic DB transaction
        try:
            amount = float(txn.amount)
            receiver_dec = decrypt_val(txn.receiver_upi)
            from user_manager import find_user_by_upi_or_phone
            receiver_user = find_user_by_upi_or_phone(receiver_dec)
            # Re-check + debit + credit in one conditional UPDATE pair (no double spend).
            if not _move_funds(uid, receiver_user, amount):
                db.session.rollback()
                return jsonify({"success": False, "message": "Insufficient virtual balance."}), 400
            txn.status = 'COMPLETED'
            txn.failed_attempts = txn.failed_attempts or 0

            # Log updates to baselines and payees
            hour_val = txn.hour if txn.hour is not None else datetime.utcnow().hour
            mcc_val = txn.mcc_code or '0000'
            try:
                update_user_baseline(
                    uid, txn.amount, hour_val, 
                    txn.device_id, receiver_dec, mcc_val
                )
            except Exception as e:
                logger.warning(f"Baseline update warning: {e}")
            
            # Trusted Payee increment or creation
            tp = TrustedPayee.query.filter_by(user_id=uid, payee_upi=receiver_dec).first()
            if tp:
                tp.txn_count += 1
                tp.total_amount = float(tp.total_amount) + amount
            else:
                tp = TrustedPayee(user_id=uid, payee_upi=receiver_dec, txn_count=1, total_amount=amount)
                db.session.add(tp)

            db.session.commit()
            db.session.refresh(user)

            log_audit_action(uid, "OTP_VERIFY_SUCCESS", 200, risk_score=float(txn.risk_score or 0))
            return jsonify({
                "success": True,
                "status": "COMPLETED",
                "message": "Transfer completed successfully!",
                "txn_id": txn_id,
                "amount": amount,
                "balance": float(user.balance)
            }), 200

        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to complete txn atomically after OTP verify: {e}")
            return jsonify({"success": False, "message": "Failed to update database after verification."}), 500

    else:
        # Increment failed attempts on the transaction
        txn.failed_attempts = (txn.failed_attempts or 0) + 1
        db.session.commit()

        log_audit_action(uid, "OTP_VERIFY_FAIL", 401, risk_score=float(txn.risk_score or 0))

        # Three failures cancel the transaction
        if txn.failed_attempts >= 3:
            txn.status = 'CANCELLED'
            db.session.commit()

            # Three cancelled transactions within an hour freeze the account and push an alert
            one_hour_ago = now - timedelta(hours=1)
            cancelled_count = Transaction.query.filter(
                Transaction.user_id == user.user_id,
                Transaction.status == 'CANCELLED',
                Transaction.created_at >= one_hour_ago
            ).count()

            if cancelled_count >= 3:
                user.status = 'FROZEN'
                # Push alert to admin queue
                txn.flags = (txn.flags or []) + ["ACCOUNT_FROZEN: Account frozen due to 3 cancelled transactions within 1 hour"]
                db.session.commit()
                log_audit_action(uid, "ACCOUNT_FROZEN_3_CANCELLED_TXNS", 403)
                return jsonify({
                    "success": False,
                    "status": "CANCELLED",
                    "account_frozen": True,
                    "message": "Maximum verification attempts exceeded (3). Transaction cancelled and account frozen due to repeated failures."
                }), 403

            return jsonify({
                "success": False,
                "status": "CANCELLED",
                "attempts_remaining": 0,
                "message": "Maximum verification attempts exceeded (3). Transaction has been cancelled."
            }), 400

        attempts_remaining = 3 - txn.failed_attempts
        return jsonify({
            "success": False,
            "status": "PENDING",
            "attempts_remaining": attempts_remaining,
            "message": f"Invalid or expired verification codes. {attempts_remaining} attempt(s) remaining."
        }), 401

# ----------------------------------------------------
# TRUST & SAFETY ENDPOINTS
# ----------------------------------------------------
@api_bp.route('/website-check/<domain>', methods=['GET'])
@jwt_required()
def website_check(domain):
    from website_trust import WebsiteTrustScore
    wts_checker = WebsiteTrustScore()
    score, verdict, reasons = wts_checker.check(domain)
    resp = {
        "success": True,
        "domain": domain,
        "trust_score": score,
        "verdict": verdict,
        "reasons": reasons
    }
    if verdict == "SAFE":
        resp["note"] = ("No known threats found. This is not a guarantee: Google Safe Browsing only lists "
                        "sites already reported as dangerous, so a brand-new scam site can still look clean.")
    return jsonify(resp), 200

@api_bp.route('/trusted-payees/add', methods=['POST'])
@jwt_required()
def add_trusted_payee():
    uid = get_jwt_identity()
    data = request.get_json()
    payee_upi = data.get('payee_upi')
    nickname = _clean_text(data.get('nickname', ''), 60)
    
    if not payee_upi:
        return jsonify({"success": False, "message": "Payee UPI address required."}), 400
        
    try:
        tp = TrustedPayee(user_id=uid, payee_upi=payee_upi, nickname=nickname, txn_count=3) # Seed as trusted instantly
        db.session.add(tp)
        db.session.commit()
        return jsonify({"success": True, "message": "Trusted payee added successfully."}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Payee already in trusted list or DB error."}), 400

@api_bp.route('/trusted-payees/<uid>', methods=['GET'])
@jwt_required()
def get_trusted_payees(uid):
    identity = get_jwt_identity()
    if identity != uid:
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
        
    tps = TrustedPayee.query.filter_by(user_id=uid).all()
    output = []
    for tp in tps:
        output.append({
            'id': tp.id,
            'payee_upi': tp.payee_upi,
            'nickname': tp.nickname,
            'txn_count': tp.txn_count,
            'total_amount': float(tp.total_amount)
        })
    return jsonify({"success": True, "trusted_payees": output}), 200

@api_bp.route('/trusted-payees/<int:tp_id>', methods=['DELETE'])
@jwt_required()
def remove_trusted_payee(tp_id):
    uid = get_jwt_identity()
    tp = TrustedPayee.query.filter_by(id=tp_id, user_id=uid).first()
    if not tp:
        return jsonify({"success": False, "message": "Payee not found in trusted list."}), 404
        
    try:
        db.session.delete(tp)
        db.session.commit()
        return jsonify({"success": True, "message": "Payee removed from trusted list."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@api_bp.route('/report-scam', methods=['POST'])
@jwt_required()
def report_scam():
    uid = get_jwt_identity()
    data = request.get_json()
    scam_upi = data.get('scam_upi')
    desc = data.get('description', '')
    
    if not scam_upi:
        return jsonify({"success": False, "message": "Scam UPI ID is required."}), 400
        
    try:
        # Create crowdsourced report log
        report = ScamReport(reporter_id=uid, scam_upi=scam_upi, description=desc)
        db.session.add(report)
        
        # Increment report counts on target
        target = ScamUpi.query.filter_by(upi_id=scam_upi).first()
        if target:
            target.reported_count += 1
        else:
            target = ScamUpi(upi_id=scam_upi, reported_count=1, verified=False)
            db.session.add(target)
            
        db.session.commit()
        return jsonify({"success": True, "message": "Scam report filed successfully. Admin will review."}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@api_bp.route('/feedback', methods=['POST'])
@jwt_required()
def submit_feedback():
    uid = get_jwt_identity()
    data = request.get_json()
    txn_id = data.get('txn_id')
    is_fraud = bool(data.get('is_fraud'))
    predicted_fraud = bool(data.get('predicted_fraud'))
    text = data.get('feedback_text', '')
    
    try:
        f = Feedback(
            txn_id=txn_id,
            user_id=uid,
            is_fraud=is_fraud,
            predicted_fraud=predicted_fraud,
            feedback_text=text
        )
        db.session.add(f)
        db.session.commit()
        return jsonify({"success": True, "message": "Feedback submitted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# ----------------------------------------------------
# SECURE USER & SETTINGS ENDPOINTS
# ----------------------------------------------------
@api_bp.route('/user/balance-secured', methods=['POST'])
@jwt_required()
def get_balance_secured():
    uid = get_jwt_identity()
    data = request.get_json() or {}
    pin = data.get('pin')
    
    if not pin:
        return jsonify({"success": False, "message": "UPI PIN is required."}), 400
        
    from user_manager import authenticate_user
    pin_ok, pin_msg = authenticate_user(uid, pin)
    if not pin_ok:
        return jsonify({"success": False, "message": "Invalid UPI PIN: " + pin_msg}), 401
        
    user = User.query.filter_by(user_id=uid).first()
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
        
    return jsonify({"success": True, "balance": float(user.balance)}), 200

@api_bp.route('/user/settings', methods=['GET', 'POST'])
@jwt_required()
def user_settings():
    uid = get_jwt_identity()
    user = User.query.filter_by(user_id=uid).first()
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
        
    if request.method == 'POST':
        data = request.get_json() or {}
        daily_limit = data.get('daily_limit')
        
        if daily_limit is not None:
            try:
                limit_val = float(daily_limit)
                if limit_val <= 0:
                    return jsonify({"success": False, "message": "Limit must be a positive number."}), 400
                user.daily_limit = limit_val
                db.session.commit()
                log_audit_action(uid, "UPDATE_DAILY_LIMIT", 200)
            except ValueError:
                return jsonify({"success": False, "message": "Invalid limit value."}), 400
            except Exception as e:
                db.session.rollback()
                return jsonify({"success": False, "message": str(e)}), 500
                
        return jsonify({
            "success": True,
            "message": "Settings updated successfully.",
            "daily_limit": float(user.daily_limit),
            "phone_number": user.phone_number,
            "home_latitude": float(user.home_latitude or 0),
            "home_longitude": float(user.home_longitude or 0)
        }), 200
    else:
        return jsonify({
            "success": True,
            "daily_limit": float(user.daily_limit or 50000.00),
            "phone_number": user.phone_number,
            "home_latitude": float(user.home_latitude or 0),
            "home_longitude": float(user.home_longitude or 0)
        }), 200

@api_bp.route('/user/change-pin', methods=['POST'])
def change_user_pin():
    """Retired: changed a PIN without dual OTP and enforced 4 digits. Use /api/pin/change."""
    return jsonify({"success": False, "error": "ENDPOINT_RETIRED",
                    "message": "Use /api/pin/change (6-digit PIN + email and Telegram codes)."}), 410


@api_bp.route('/telegram/link_token', methods=['POST'])
@jwt_required(optional=True)
def telegram_link_token():
    """
    Creates a single-use 10-minute token and returns https://t.me/<BOT_USERNAME>?start=<token>.
    Supports JWT authenticated user or pending-signup session via body/query { "user_id": "..." }.
    """
    current_uid = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    user_id = current_uid or data.get('user_id') or request.args.get('user_id')

    if not user_id:
        return jsonify({
            "success": False,
            "error": "AUTHENTICATION_REQUIRED",
            "message": "User identification (JWT or user_id) is required to generate a Telegram link."
        }), 400

    user = User.query.filter_by(user_id=str(user_id).strip()).first()
    if not user:
        return jsonify({
            "success": False,
            "error": "USER_NOT_FOUND",
            "message": "User account not found."
        }), 404
    # Without a JWT anyone could re-link an ACTIVE account's Telegram chat; allow it only mid-signup.
    if not current_uid and user.status != "PENDING":
        return jsonify({
            "success": False,
            "error": "AUTHENTICATION_REQUIRED",
            "message": "Log in to link Telegram to an active account."
        }), 401

    from telegram_bot import telegram_bot
    token, link_url = telegram_bot.create_link_token(user_id=user.user_id, expires_in_minutes=10)

    return jsonify({
        "success": True,
        "token": token,
        "link_url": link_url,
        "bot_username": telegram_bot.username,
        "expires_in_seconds": 600
    }), 200


@api_bp.route('/telegram/status', methods=['GET'])
@jwt_required(optional=True)
def telegram_status():
    """
    Checks Telegram link and verification status.
    Supports JWT authenticated user or query ?user_id=...
    """
    current_uid = get_jwt_identity()
    user_id = current_uid or request.args.get('user_id')

    if not user_id:
        return jsonify({
            "success": False,
            "error": "AUTHENTICATION_REQUIRED",
            "message": "User identification (JWT or user_id) is required."
        }), 400

    user = User.query.filter_by(user_id=str(user_id).strip()).first()
    if not user:
        return jsonify({
            "success": False,
            "error": "USER_NOT_FOUND",
            "message": "User account not found."
        }), 404
    if not current_uid and user.status != "PENDING":
        # Only a signup in progress may poll without a JWT (no link-state leak for active accounts).
        return jsonify({"success": False, "error": "AUTHENTICATION_REQUIRED", "message": "Login required."}), 401

    has_chat_id = bool(user.get_decrypted_telegram_chat_id())
    is_verified = bool(user.telegram_verified)

    return jsonify({
        "success": True,
        "user_id": user.user_id,
        "telegram_linked": has_chat_id,
        "telegram_verified": is_verified
    }), 200


# Purposes whose resend is allowed before a JWT exists (the user proves identity with the codes).
_PRE_AUTH_PURPOSES = {"SIGNUP", "LOGIN_NEW_DEVICE", "PIN_RESET"}


@api_bp.route('/otp/resend', methods=['POST'])
@jwt_required(optional=True)
@limiter.limit("6 per minute")
def resend_otp_channel():
    """
    Per-channel Resend (30 s cooldown per channel).
    Body: {user_id?, purpose, channel: "email"|"telegram", txn_id?}
    """
    data = request.get_json(silent=True) or {}
    purpose = str(data.get("purpose") or "").strip().upper()
    channel = str(data.get("channel") or "").strip().upper()
    txn_id = data.get("txn_id") or None
    if purpose not in otp_service.VALID_PURPOSES or channel not in otp_service.VALID_CHANNELS:
        return jsonify({"success": False, "message": "Valid purpose and channel are required."}), 400

    jwt_uid = get_jwt_identity()
    uid = jwt_uid or str(data.get("user_id") or "").strip()
    if not jwt_uid and purpose not in _PRE_AUTH_PURPOSES:
        return jsonify({"success": False, "error": "AUTHENTICATION_REQUIRED", "message": "Login required."}), 401
    user = User.query.filter_by(user_id=uid).first() if uid else None
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
    if purpose == "SIGNUP" and user.status != "PENDING":
        return jsonify({"success": False, "message": "Pending registration not found."}), 404
    if purpose == "SIGNUP" and channel == "TELEGRAM" and not user.telegram_verified:
        return jsonify({"success": False, "delivery": {"telegram": "not_linked"},
                        "message": "Link the Telegram bot (Start + Share Contact) first."}), 400

    amount = receiver = None
    if purpose == "TRANSACTION":
        txn = Transaction.query.filter_by(txn_id=txn_id, user_id=user.user_id).first() if txn_id else None
        if not txn or txn.status != 'PENDING':
            return jsonify({"success": False, "message": "No pending transaction to verify."}), 404
        amount, receiver = float(txn.amount), decrypt_val(txn.receiver_upi)

    try:
        if purpose == "SIGNUP":
            # Signup issues the two channels independently (Telegram only after linking).
            res = otp_service.issue(user, purpose="SIGNUP", channel=channel, ip_address=_req_ip())
            status = _delivery(res).get(channel.lower(), "sent")
        else:
            out = otp_service.resend_channel(user, purpose, channel, txn_id=txn_id, ip_address=_req_ip(),
                                             amount=amount, receiver=receiver)
            status = out.get("status", "failed")
    except otp_service.OtpRateLimitError as e:
        return jsonify({"success": False, "error": "COOLDOWN", "message": str(e)}), 429
    except otp_service.OtpError as e:
        return jsonify({"success": False, "message": str(e)}), 400

    ok = status in ("sent", "dry_run", "pending")
    return jsonify({"success": ok, "delivery": {channel.lower(): status}, "cooldown_seconds": otp_service.COOLDOWN_SECONDS,
                    "message": f"{channel.title()} code {'sent' if ok else status.replace('_', ' ')}."}), 200 if ok else 502


@api_bp.route('/health/otp', methods=['GET'])
def otp_health():
    """Admin-only, secret-free readiness of the EMAIL and TELEGRAM OTP channels."""
    if not _admin_allowed(request):
        return jsonify({"success": False, "message": "Admin only."}), 403
    readiness = otp_service.channel_readiness()
    from env_loader import env_str, is_placeholder
    sb_key = env_str("GOOGLE_SAFE_BROWSING_API_KEY")
    return jsonify({
        "success": True,
        "otp_ready": readiness["email"]["ready"] and readiness["telegram"]["ready"],
        "channels": readiness,
        "safe_browsing": {"key": "empty/MOCK (keyword simulation in use)" if is_placeholder(sb_key) else "set",
                          "last_call": __import__("website_trust").EXTERNAL_STATUS.get("safe_browsing")},
        "openphish": __import__("website_trust").EXTERNAL_STATUS.get("openphish"),
        "policy": {"expiry_seconds": otp_service.EXPIRY_SECONDS, "max_attempts": otp_service.MAX_ATTEMPTS,
                   "cooldown_seconds": otp_service.COOLDOWN_SECONDS, "hourly_limit": otp_service.HOURLY_LIMIT},
    }), 200
