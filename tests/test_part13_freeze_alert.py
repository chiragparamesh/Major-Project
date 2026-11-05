import pytest
import os
import sys
import time
from datetime import datetime, timedelta
from unittest.mock import patch

# Add backend directory to sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, Transaction, AccountFreezeToken, PasswordResetToken
from security import (
    encrypt_val, compute_lookup_hash, hash_pin,
    generate_freeze_token, verify_and_decode_freeze_token
)
from flask_jwt_extended import create_access_token
from email_sender import default_email_sender
import telegram_bot


@pytest.fixture
def app():
    os.environ["MLBFD_SECRET_KEY"] = "test-secret-key-at-least-32-chars-long-mlbfd"
    os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-at-least-32-chars-mlbfd"
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:TEST_BOT_TOKEN_ABCDEF"
    os.environ["TELEGRAM_BOT_USERNAME"] = "mlbfd_test_bot"
    os.environ["TELEGRAM_POLLING_ENABLED"] = "false"
    os.environ["TELEGRAM_DRY_RUN"] = "true"
    os.environ["EMAIL_DRY_RUN"] = "true"

    test_app = create_app()
    test_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def test_users(app):
    with app.app_context():
        sender = User(
            user_id="user_sender_13",
            full_name="Sender Thirteen",
            phone=encrypt_val("+919876543210"),
            phone_hash=compute_lookup_hash("+919876543210"),
            email=encrypt_val("sender13@example.com"),
            email_hash=compute_lookup_hash("sender13@example.com"),
            upi_id=encrypt_val("9876543210@mlbfd"),
            upi_hash=compute_lookup_hash("9876543210@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            telegram_chat_id=encrypt_val("99887766"),
            login_pin_hash=hash_pin("847291"),
            payment_pin_hash=hash_pin("395816"),
            security_answer_hash=hash_pin("bangalore"),
            balance=100000.00,
            known_devices=[{"device_id": "device_13", "last_verified_at": datetime.utcnow().isoformat()}]
        )
        receiver = User(
            user_id="user_receiver_13",
            full_name="Receiver Thirteen",
            phone=encrypt_val("+919876543211"),
            phone_hash=compute_lookup_hash("+919876543211"),
            email=encrypt_val("receiver13@example.com"),
            email_hash=compute_lookup_hash("receiver13@example.com"),
            upi_id=encrypt_val("9876543211@mlbfd"),
            upi_hash=compute_lookup_hash("9876543211@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            login_pin_hash=hash_pin("192837"),
            payment_pin_hash=hash_pin("582914"),
            balance=50000.00
        )
        db.session.add(sender)
        db.session.add(receiver)
        db.session.commit()
    return "user_sender_13", "user_receiver_13"


def _auth_headers(app, uid):
    with app.app_context():
        token = create_access_token(identity=uid)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }


# ==============================================================================
# TOKEN UNIT TESTS
# ==============================================================================

def test_generate_and_verify_freeze_token(app):
    """Test signed freeze token creation and validation."""
    with app.app_context():
        token = generate_freeze_token("user_123")
        is_valid, uid, err = verify_and_decode_freeze_token(token)
        assert is_valid is True
        assert uid == "user_123"
        assert err == ""

        # Test tampered token fails
        is_valid_bad, _, err_bad = verify_and_decode_freeze_token(token + "tampered")
        assert is_valid_bad is False
        assert "Invalid" in err_bad


# ==============================================================================
# FREEZE ENDPOINT TESTS (PROVES IT WORKS ONCE, THEN FAILS)
# ==============================================================================

def test_freeze_link_works_once_then_fails(client, app, test_users):
    """
    DONE CHECK TEST:
    Proves /api/freeze?token=... sets account to FROZEN on first call,
    and returns 400 error on any subsequent call.
    """
    sender_id, _ = test_users

    with app.app_context():
        # Generate token and save DB record
        token = generate_freeze_token(sender_id)
        record = AccountFreezeToken(
            token=token,
            user_id=sender_id,
            expires_at=datetime.utcnow() + timedelta(hours=24),
            used=False
        )
        db.session.add(record)
        db.session.commit()

        # Verify initial status is ACTIVE
        user = User.query.filter_by(user_id=sender_id).first()
        assert user.status == "ACTIVE"

    # 1. First click on freeze link -> Success (200) and account frozen
    res1 = client.get(f'/api/freeze?token={token}')
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert data1["success"] is True
    assert data1["status"] == "FROZEN"
    assert "frozen successfully" in data1["message"].lower()

    # Verify database state after first click
    with app.app_context():
        user = User.query.filter_by(user_id=sender_id).first()
        assert user.status == "FROZEN"
        assert user.is_locked is True

        rec = AccountFreezeToken.query.filter_by(token=token).first()
        assert rec.used is True

    # 2. Second click on same freeze link -> Fails (400 TOKEN_ALREADY_USED)
    res2 = client.get(f'/api/freeze?token={token}')
    assert res2.status_code == 400
    data2 = res2.get_json()
    assert data2["success"] is False
    assert data2["error"] == "TOKEN_ALREADY_USED"
    assert "already been used" in data2["message"].lower()


def test_freeze_link_fails_when_expired(client, app, test_users):
    """Test that an expired freeze link (>24 hours) is rejected."""
    sender_id, _ = test_users

    with app.app_context():
        token = generate_freeze_token(sender_id)
        # Store with past expiry
        record = AccountFreezeToken(
            token=token,
            user_id=sender_id,
            expires_at=datetime.utcnow() - timedelta(hours=1),
            used=False
        )
        db.session.add(record)
        db.session.commit()

    res = client.get(f'/api/freeze?token={token}')
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert data["error"] in ["TOKEN_EXPIRED", "INVALID_TOKEN"]


def test_freeze_link_fails_without_token(client):
    """Test missing token returns 400 MISSING_TOKEN."""
    res = client.get('/api/freeze')
    assert res.status_code == 400
    assert res.get_json()["error"] == "MISSING_TOKEN"


# ==============================================================================
# "WAS THIS YOU?" ALERT DISPATCH ON FRAUD VERDICT
# ==============================================================================

def test_transfer_blocked_triggers_freeze_alerts_on_email_and_telegram(client, app, test_users):
    """
    On BLOCKED verdict in /api/transfer:
    - Generates signed freeze link
    - Dispatches security alert to email (with details & freeze link)
    - Dispatches security alert to Telegram (with details & freeze link)
    """
    sender_id, receiver_id = test_users
    headers = _auth_headers(app, sender_id)

    # Clear sent message buffers
    default_email_sender.sent_emails.clear()
    telegram_bot.default_telegram_bot.sent_messages.clear()

    mock_blocked_verdict = {
        'status': 'BLOCKED',
        'risk_score': 92.0,
        'weighted_score': 90.0,
        'final_score': 92.0,
        'override_applied': True,
        'override_reasons': ['Payee in scam blacklist (hard override: BLOCKED)'],
        'top_reasons': ['Payee in scam blacklist'],
        'flags': ['SCAM_BLACKLIST_MATCH'],
        'layers': {'behavioral': 20.0, 'payee': 100.0},
        'ensemble_confidence': 0.95
    }

    with patch('api.global_fraud_detector.detect', return_value=mock_blocked_verdict):
        res = client.post('/api/transfer', headers=headers, json={
            "receiver": "9876543211@mlbfd",
            "amount": 2500.0,
            "payment_pin": "395816",
            "latitude": 12.9716,
            "longitude": 77.5946
        })

    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "BLOCKED"
    assert "freeze_url" in data
    freeze_url = data["freeze_url"]

    # 1. Verify freeze token was saved in DB
    with app.app_context():
        token_str = data["freeze_token"]
        rec = AccountFreezeToken.query.filter_by(token=token_str).first()
        assert rec is not None
        assert rec.user_id == sender_id
        assert rec.used is False

    # 2. Verify Email alert was sent
    assert len(default_email_sender.sent_emails) >= 1
    last_email = default_email_sender.sent_emails[-1]
    assert "Security Alert" in last_email["subject"]
    assert "2,500.00" in last_email["plain_text"]
    assert freeze_url in last_email["plain_text"] or "/api/freeze?token=" in last_email["plain_text"]

    # 3. Verify Telegram alert was sent
    assert len(telegram_bot.default_telegram_bot.sent_messages) >= 1
    last_tg = telegram_bot.default_telegram_bot.sent_messages[-1]
    assert "Security Alert: Was this you?" in last_tg["text"]
    assert "2,500.00" in last_tg["text"]
    assert freeze_url in last_tg["text"] or "/api/freeze?token=" in last_tg["text"]


def test_transfer_approved_does_not_dispatch_freeze_alerts(client, app, test_users):
    """Normal approved transaction does NOT create freeze token or send freeze alerts."""
    sender_id, _ = test_users
    headers = _auth_headers(app, sender_id)

    default_email_sender.sent_emails.clear()
    telegram_bot.default_telegram_bot.sent_messages.clear()

    mock_approved_verdict = {
        'status': 'APPROVED',
        'risk_score': 15.0,
        'weighted_score': 15.0,
        'final_score': 15.0,
        'override_applied': False,
        'override_reasons': [],
        'top_reasons': ['No anomalies detected.'],
        'flags': [],
        'layers': {'behavioral': 10.0},
        'ensemble_confidence': 0.1
    }

    with patch('api.global_fraud_detector.detect', return_value=mock_approved_verdict):
        res = client.post('/api/transfer', headers=headers, json={
            "receiver": "9876543211@mlbfd",
            "amount": 200.0,
            "payment_pin": "395816"
        })

    assert res.status_code == 200
    assert res.get_json()["status"] == "APPROVED"

    # Ensure no freeze alerts were sent
    freeze_emails = [e for e in default_email_sender.sent_emails if "Security Alert" in e.get("subject", "")]
    assert len(freeze_emails) == 0


# ==============================================================================
# UNFREEZE PATH TESTS: FORGOT PIN & ADMIN USERS PAGE
# ==============================================================================

def test_unfreeze_via_forgot_pin_reset(client, app, test_users):
    """Test unfreeze is permitted via forgot-PIN verification flow."""
    sender_id, _ = test_users

    with app.app_context():
        # Put user in FROZEN state
        user = User.query.filter_by(user_id=sender_id).first()
        user.status = "FROZEN"
        user.is_locked = True
        db.session.commit()

        # Create valid reset token
        reset_token = "valid-reset-token-for-unfreeze"
        prt = PasswordResetToken(
            token=reset_token,
            user_id=sender_id,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            used=False
        )
        db.session.add(prt)
        db.session.commit()

    # Call /api/pin/forgot/reset with correct answer and new PIN
    res = client.post('/api/pin/forgot/reset', json={
        "reset_token": reset_token,
        "security_answer": "Bangalore",
        "new_pin": "918273",
        "pin_type": "login"
    })
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Verify user is now ACTIVE and unlocked
    with app.app_context():
        user = User.query.filter_by(user_id=sender_id).first()
        assert user.status == "ACTIVE"
        assert user.is_locked is False


def test_unfreeze_via_admin_users_page(client, app, test_users):
    """Test unfreeze is permitted via Admin Users toggle-lock endpoint."""
    sender_id, _ = test_users

    with app.app_context():
        user = User.query.filter_by(user_id=sender_id).first()
        user.status = "FROZEN"
        user.is_locked = True
        db.session.commit()

    # Admin unlocks user account
    res = client.post(f'/admin/api/users/{sender_id}/toggle-lock', json={"lock": False})
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Verify user is now ACTIVE and unlocked
    with app.app_context():
        user = User.query.filter_by(user_id=sender_id).first()
        assert user.status == "ACTIVE"
        assert user.is_locked is False
