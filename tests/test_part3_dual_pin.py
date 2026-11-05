import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from db import db
from database import User, Transaction
from security import (
    hash_pin, verify_pin, validate_pin, validate_dual_pins,
    is_weak_pin, encrypt_val, compute_lookup_hash
)
from user_manager import (
    register_user, authenticate_login, verify_user_payment_pin,
    find_user_by_upi_or_phone
)
from fraud_detection import global_fraud_detector

@pytest.fixture(scope="module")
def app_and_client():
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        client = app.test_client()
        yield app, client

def test_pin_hashing_rounds_12():
    pin = "739104"
    h = hash_pin(pin, rounds=12)
    # Bcrypt format: $2b$12$... indicates rounds=12
    assert h.startswith("$2b$12$"), f"Expected bcrypt rounds 12 prefix '$2b$12$', got: {h[:7]}"
    assert verify_pin(pin, h) is True
    assert verify_pin("739105", h) is False

def test_weak_pin_rejection():
    # 1. 000000 & 123456
    assert is_weak_pin("000000") is True
    assert is_weak_pin("123456") is True

    # 2. Repeated digits
    assert is_weak_pin("111111") is True
    assert is_weak_pin("222222") is True
    assert is_weak_pin("999999") is True

    # 3. Sequential ascending
    assert is_weak_pin("012345") is True
    assert is_weak_pin("234567") is True
    assert is_weak_pin("345678") is True
    assert is_weak_pin("456789") is True
    assert is_weak_pin("567890") is True

    # 4. Sequential descending
    assert is_weak_pin("987654") is True
    assert is_weak_pin("876543") is True
    assert is_weak_pin("765432") is True
    assert is_weak_pin("654321") is True
    assert is_weak_pin("543210") is True
    assert is_weak_pin("098765") is True

    # 5. Invalid lengths
    assert is_weak_pin("12345") is True
    assert is_weak_pin("1234567") is True
    assert is_weak_pin("abcdef") is True

    # 6. Strong valid PINs
    assert is_weak_pin("839201") is False
    assert is_weak_pin("491827") is False
    assert is_weak_pin("618294") is False

def test_dual_pins_must_differ():
    # Identical PINs must be rejected
    valid, msg = validate_dual_pins("839201", "839201")
    assert valid is False
    assert "must differ" in msg.lower()

    # Weak login PIN rejected
    valid, msg = validate_dual_pins("123456", "839201")
    assert valid is False
    assert "weak" in msg.lower()

    # Weak payment PIN rejected
    valid, msg = validate_dual_pins("839201", "000000")
    assert valid is False
    assert "weak" in msg.lower()

    # Valid different PINs accepted
    valid, msg = validate_dual_pins("839201", "491827")
    assert valid is True
    assert msg == ""

def test_login_pin_authentication_and_5_attempt_lockout(app_and_client):
    app, client = app_and_client
    uid = "dualpin_test_login_user"
    User.query.filter_by(user_id=uid).delete()
    db.session.commit()

    login_pin = "839201"
    payment_pin = "491827"
    success, msg = register_user(
        user_id=uid,
        login_pin=login_pin,
        payment_pin=payment_pin,
        phone_number="+919870001122"
    )
    assert success is True

    user = User.query.filter_by(user_id=uid).first()
    assert user is not None
    assert user.login_pin_hash.startswith("$2b$12$")
    assert user.payment_pin_hash.startswith("$2b$12$")

    # Attempt login with payment PIN -> must FAIL (login uses login PIN only)
    ok, err_msg, _ = authenticate_login(uid, payment_pin)
    assert ok is False
    assert err_msg == "Invalid credentials."

    # Non-existent user -> generic error message, no hint user doesn't exist
    ok_ghost, err_ghost, _ = authenticate_login("nonexistent_user_id@mlbfd", login_pin)
    assert ok_ghost is False
    assert err_ghost == "Invalid credentials."

    # After attempting login with payment_pin, attempts counter is 1
    u = User.query.filter_by(user_id=uid).first()
    assert u.login_failed_attempts == 1

    # Attempts 2, 3, and 4 (consecutive wrong login PINs) -> generic message, not yet locked
    for attempt_num in range(2, 5):
        ok, err_msg, _ = authenticate_login(uid, "102938")
        assert ok is False
        assert err_msg == "Invalid credentials."
        u = User.query.filter_by(user_id=uid).first()
        assert u.login_failed_attempts == attempt_num
        assert u.is_login_locked() is False

    # 5th wrong attempt -> triggers 15-minute lockout stored in DB
    now = datetime.utcnow()
    ok, err_msg, _ = authenticate_login(uid, "102938", now=now)
    assert ok is False
    assert "temporarily locked" in err_msg.lower()

    u = User.query.filter_by(user_id=uid).first()
    assert u.login_failed_attempts == 5
    assert u.login_locked_until is not None
    assert u.login_locked_until > now
    assert (u.login_locked_until - now).total_seconds() >= 14 * 60  # ~15 min
    assert u.is_login_locked(now=now) is True

    # While locked, even correct login PIN is rejected with generic lockout message
    ok, err_msg, _ = authenticate_login(uid, login_pin, now=now)
    assert ok is False
    assert "temporarily locked" in err_msg.lower()

    # Simulate 16 minutes later (lockout expired)
    later = now + timedelta(minutes=16)
    ok, succ_msg, logged_user = authenticate_login(uid, login_pin, now=later)
    assert ok is True
    assert logged_user.user_id == uid
    u = User.query.filter_by(user_id=uid).first()
    assert u.login_failed_attempts == 0
    assert u.login_locked_until is None

    # Cleanup
    db.session.delete(u)
    db.session.commit()

def test_payment_pin_verification_and_3_attempt_lockout(app_and_client):
    app, client = app_and_client
    uid = "dualpin_test_pay_user"
    User.query.filter_by(user_id=uid).delete()
    db.session.commit()

    login_pin = "839201"
    payment_pin = "491827"
    register_user(
        user_id=uid,
        login_pin=login_pin,
        payment_pin=payment_pin,
        phone_number="+919870002233"
    )
    user = User.query.filter_by(user_id=uid).first()

    # Verify with login PIN -> fails (payment requires payment PIN)
    ok, msg = verify_user_payment_pin(user, login_pin)
    assert ok is False
    assert msg == "Payment authorization failed."

    # 1st and 2nd wrong attempts
    user = User.query.filter_by(user_id=uid).first()
    assert user.payment_failed_attempts == 1

    ok, msg = verify_user_payment_pin(user, "999888")
    assert ok is False
    assert msg == "Payment authorization failed."
    user = User.query.filter_by(user_id=uid).first()
    assert user.payment_failed_attempts == 2
    assert user.is_payment_locked() is False

    # 3rd wrong attempt -> locks payments for 30 minutes in DB
    now = datetime.utcnow()
    ok, msg = verify_user_payment_pin(user, "999888", now=now)
    assert ok is False
    assert "temporarily locked" in msg.lower()

    user = User.query.filter_by(user_id=uid).first()
    assert user.payment_failed_attempts == 3
    assert user.payment_locked_until is not None
    assert (user.payment_locked_until - now).total_seconds() >= 29 * 60  # ~30 min
    assert user.is_payment_locked(now=now) is True

    # Crucial: Payment lockout does NOT lock login!
    login_ok, _, _ = authenticate_login(uid, login_pin, now=now)
    assert login_ok is True, "Payment lockout must not lock login!"

    # While locked, even correct payment PIN is rejected
    ok, msg = verify_user_payment_pin(user, payment_pin, now=now)
    assert ok is False
    assert "temporarily locked" in msg.lower()

    # After 31 minutes: lock expired, correct payment PIN succeeds and resets attempts
    later = now + timedelta(minutes=31)
    ok, msg = verify_user_payment_pin(user, payment_pin, now=later)
    assert ok is True
    user = User.query.filter_by(user_id=uid).first()
    assert user.payment_failed_attempts == 0
    assert user.payment_locked_until is None

    # Cleanup
    db.session.delete(user)
    db.session.commit()

def test_api_transfer_requires_payment_pin_and_never_reaches_fraud_engine(app_and_client):
    app, client = app_and_client
    uid = "dualpin_api_transfer_user"
    User.query.filter_by(user_id=uid).delete()
    db.session.commit()

    login_pin = "619284"
    payment_pin = "738192"
    register_user(
        user_id=uid,
        login_pin=login_pin,
        payment_pin=payment_pin,
        phone_number="+919870003344"
    )
    user = User.query.filter_by(user_id=uid).first()
    user.activate_account(initial_balance=100000.00)
    from user_manager import bind_device
    bind_device(user, "device-transfer-test")
    db.session.commit()

    # 1. Login to get JWT with known trusted device
    login_resp = client.post("/api/login", json={
        "user_id": uid,
        "login_pin": login_pin,
        "device_id": "device-transfer-test"
    })
    assert login_resp.status_code == 200
    token = login_resp.get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}


    # 2. Transfer request WITHOUT payment_pin -> must reject BEFORE fraud engine
    with patch.object(global_fraud_detector, 'detect', wraps=global_fraud_detector.detect) as mock_detect:
        resp = client.post("/api/transfer", headers=headers, json={
            "sender_upi": user.get_decrypted_upi_id(),
            "receiver_upi": "merchant@okaxis",
            "amount": 500.00
            # missing payment_pin
        })
        assert resp.status_code == 400
        assert mock_detect.call_count == 0, "Fraud engine must NOT be called when payment_pin is missing!"

    # 3. Transfer request with WRONG payment_pin -> must reject BEFORE fraud engine
    with patch.object(global_fraud_detector, 'detect', wraps=global_fraud_detector.detect) as mock_detect:
        resp = client.post("/api/transfer", headers=headers, json={
            "sender_upi": user.get_decrypted_upi_id(),
            "receiver_upi": "merchant@okaxis",
            "amount": 500.00,
            "payment_pin": "000111"  # wrong payment PIN
        })
        assert resp.status_code == 401
        assert "Payment authorization failed." in resp.get_json()["message"]
        assert mock_detect.call_count == 0, "Fraud engine must NEVER be reached on wrong payment PIN!"

    # 4. Trigger 3 wrong payment PINs through /api/transfer -> locks payments
    client.post("/api/transfer", headers=headers, json={"payment_pin": "111222"})
    resp_lock = client.post("/api/transfer", headers=headers, json={"payment_pin": "111222"})
    assert resp_lock.status_code == 403
    assert "temporarily locked" in resp_lock.get_json()["message"]

    # 5. Attempt while locked with CORRECT payment_pin -> still blocked BEFORE fraud engine
    with patch.object(global_fraud_detector, 'detect', wraps=global_fraud_detector.detect) as mock_detect:
        resp_blocked = client.post("/api/transfer", headers=headers, json={
            "sender_upi": user.get_decrypted_upi_id(),
            "receiver_upi": "merchant@okaxis",
            "amount": 500.00,
            "payment_pin": payment_pin
        })
        assert resp_blocked.status_code == 403
        assert mock_detect.call_count == 0, "Fraud engine must NEVER be reached when payment is locked!"

    # Cleanup
    User.query.filter_by(user_id=uid).delete()
    db.session.commit()
