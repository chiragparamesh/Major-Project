import pytest
import os
import sys
import json
import time
from datetime import datetime, timedelta

# Add backend directory to sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, OtpCode, TokenBlocklist, PendingPinChange, PasswordResetToken, Transaction
from security import encrypt_val, compute_lookup_hash, hash_pin, verify_pin
from otp_service import hash_code_hmac
from config import Config


@pytest.fixture
def app():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["MLBFD_SECRET_KEY"] = "test-secret-key-at-least-32-chars-long-mlbfd"
    os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-at-least-32-chars-mlbfd"
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:TEST_BOT_TOKEN_ABCDEF"
    os.environ["TELEGRAM_BOT_USERNAME"] = "mlbfd_test_bot"
    os.environ["TELEGRAM_POLLING_ENABLED"] = "false"
    os.environ["TELEGRAM_DRY_RUN"] = "true"
    os.environ["EMAIL_DRY_RUN"] = "true"
    os.environ["REDUCED_TXN_LIMIT"] = "10000.0"
    os.environ["REDUCED_DAILY_LIMIT"] = "25000.0"

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
def user_id(app):
    uid = "pin_user_01"
    with app.app_context():
        u = User(
            user_id=uid,
            full_name="PIN Test User",
            phone=encrypt_val("+919876543210"),
            phone_hash=compute_lookup_hash("+919876543210"),
            email=encrypt_val("pinuser@example.com"),
            email_hash=compute_lookup_hash("pinuser@example.com"),
            upi_id=encrypt_val("9876543210@mlbfd"),
            upi_hash=compute_lookup_hash("9876543210@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            login_pin_hash=hash_pin("847291", rounds=12),
            payment_pin_hash=hash_pin("395816", rounds=12),
            security_question="What is your favorite city?",
            security_answer_hash=hash_pin("bengaluru", rounds=12),
            balance=100000.00,
            known_devices=[{"device_id": "device_trusted_1", "last_verified_at": datetime.utcnow().isoformat()}]
        )
        db.session.add(u)
        db.session.commit()
    return uid


def test_pin_change_success_login_pin(client, app, user_id):
    """Test full login PIN change flow with dual OTP verification."""
    # 1. Initiate PIN change with valid current login PIN (847291) and new valid PIN (739152)
    res = client.post('/api/pin/change', json={
        "user_id": user_id,
        "pin_type": "login",
        "current_pin": "847291",
        "new_pin": "739152"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["status"] == "OTP_SENT"

    # Query active dual OTP records and seed known hashes
    with app.app_context():
        otp_codes = OtpCode.query.filter_by(user_id=user_id, purpose="PIN_CHANGE").all()
        assert len(otp_codes) == 2
        email_rec = next(r for r in otp_codes if r.channel == "EMAIL")
        telegram_rec = next(r for r in otp_codes if r.channel == "TELEGRAM")

        email_rec.code_hash = hash_code_hmac("112233")
        telegram_rec.code_hash = hash_code_hmac("445566")
        db.session.commit()

    # 2. Confirm PIN change with dual codes
    confirm_res = client.post('/api/pin/change/confirm', json={
        "user_id": user_id,
        "email_code": "112233",
        "telegram_code": "445566"
    })
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.get_json()
    assert confirm_data["success"] is True
    assert "Login PIN updated" in confirm_data["message"]

    # Verify user login PIN updated in DB
    with app.app_context():
        u_after = User.query.filter_by(user_id=user_id).first()
        assert verify_pin("739152", u_after.login_pin_hash) is True
        assert verify_pin("847291", u_after.login_pin_hash) is False


def test_pin_change_rejections(client, user_id):
    """Test validation errors: wrong current PIN, weak new PIN, matching other PIN."""
    # 1. Wrong current PIN
    res1 = client.post('/api/pin/change', json={
        "user_id": user_id,
        "pin_type": "login",
        "current_pin": "000001",
        "new_pin": "739152"
    })
    assert res1.status_code == 400
    assert "Invalid current PIN" in res1.get_json()["message"]

    # 2. Weak new PIN (123456)
    res2 = client.post('/api/pin/change', json={
        "user_id": user_id,
        "pin_type": "login",
        "current_pin": "847291",
        "new_pin": "123456"
    })
    assert res2.status_code == 400
    assert "invalid" in res2.get_json()["message"].lower()

    # 3. New PIN identical to current PIN
    res3 = client.post('/api/pin/change', json={
        "user_id": user_id,
        "pin_type": "login",
        "current_pin": "847291",
        "new_pin": "847291"
    })
    assert res3.status_code == 400
    assert "different from current PIN" in res3.get_json()["message"]

    # 4. New login PIN identical to existing payment PIN (395816)
    res4 = client.post('/api/pin/change', json={
        "user_id": user_id,
        "pin_type": "login",
        "current_pin": "847291",
        "new_pin": "395816"
    })
    assert res4.status_code == 400
    assert "must differ" in res4.get_json()["message"].lower()

    # 5. New payment PIN identical to existing login PIN (847291)
    res5 = client.post('/api/pin/change', json={
        "user_id": user_id,
        "pin_type": "payment",
        "current_pin": "395816",
        "new_pin": "847291"
    })
    assert res5.status_code == 400
    assert "must differ" in res5.get_json()["message"].lower()


def test_forgot_pin_flow_success(client, app, user_id):
    """Test complete forgot PIN flow with generic start, dual OTP verify, security question check, JWT revocation, and reduced limits."""
    # 1. Non-existent user returns generic 200 response without leaking
    res_fake = client.post('/api/pin/forgot/start', json={"user_id": "non_existent_ghost"})
    assert res_fake.status_code == 200
    assert "verification codes have been sent" in res_fake.get_json()["message"].lower()

    # 2. Existing user start returns generic message and issues dual OTPs
    res_start = client.post('/api/pin/forgot/start', json={"user_id": user_id})
    assert res_start.status_code == 200
    assert res_start.get_json()["success"] is True

    # Intercept OTPs in DB
    with app.app_context():
        otp_codes = OtpCode.query.filter_by(user_id=user_id, purpose="PIN_RESET").all()
        assert len(otp_codes) == 2
        email_rec = next(r for r in otp_codes if r.channel == "EMAIL")
        telegram_rec = next(r for r in otp_codes if r.channel == "TELEGRAM")
        email_rec.code_hash = hash_code_hmac("654321")
        telegram_rec.code_hash = hash_code_hmac("789123")
        db.session.commit()

    # 3. Verify dual OTPs -> returns 10-minute reset token
    res_verify = client.post('/api/pin/forgot/verify', json={
        "user_id": user_id,
        "email_code": "654321",
        "telegram_code": "789123"
    })
    assert res_verify.status_code == 200
    data_verify = res_verify.get_json()
    assert data_verify["success"] is True
    reset_token = data_verify["reset_token"]
    assert reset_token is not None
    assert data_verify["security_question"] == "What is your favorite city?"

    # Check reset token saved in DB with 10-min expiry
    with app.app_context():
        token_rec = PasswordResetToken.query.filter_by(token=reset_token).first()
        assert token_rec is not None
        assert token_rec.used is False
        assert token_rec.expires_at > datetime.utcnow()

    # 4. Perform PIN reset with case-insensitive security answer ("Bengaluru")
    res_reset = client.post('/api/pin/forgot/reset', json={
        "reset_token": reset_token,
        "security_answer": "  Bengaluru  ",
        "new_pin": "928374",
        "pin_type": "login",
        "device_id": "device_current_session"
    })
    assert res_reset.status_code == 200
    data_reset = res_reset.get_json()
    assert data_reset["success"] is True
    assert "PIN reset successfully" in data_reset["message"]
    assert "access_token" in data_reset
    assert "refresh_token" in data_reset

    # 5. Verify post-reset security effects:
    with app.app_context():
        u_updated = User.query.filter_by(user_id=user_id).first()
        # New PIN works
        assert verify_pin("928374", u_updated.login_pin_hash) is True
        # Token invalidation timestamp set
        assert u_updated.tokens_revoked_at is not None
        # Known devices cleared except the current one
        assert len(u_updated.known_devices) == 1
        assert u_updated.known_devices[0]["device_id"] == "device_current_session"
        # 24-hour reduced limit mode is active
        assert u_updated.is_reduced_limit_active() is True
        assert u_updated.reduced_limit_until > datetime.utcnow()


def test_forgot_pin_rejections(client, app, user_id):
    """Test security answer mismatch, weak PIN, and invalid token."""
    # Seed a valid reset token
    with app.app_context():
        reset_rec = PasswordResetToken(
            token="test_reset_token_xyz",
            user_id=user_id,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            used=False
        )
        db.session.add(reset_rec)
        db.session.commit()

    # 1. Wrong security answer
    res1 = client.post('/api/pin/forgot/reset', json={
        "reset_token": "test_reset_token_xyz",
        "security_answer": "Mumbai",
        "new_pin": "928374"
    })
    assert res1.status_code == 400
    assert "Incorrect security answer" in res1.get_json()["message"]

    # 2. Weak new PIN
    res2 = client.post('/api/pin/forgot/reset', json={
        "reset_token": "test_reset_token_xyz",
        "security_answer": "bengaluru",
        "new_pin": "000000"
    })
    assert res2.status_code == 400
    assert "invalid" in res2.get_json()["message"].lower()

    # 3. Non-existent token
    res3 = client.post('/api/pin/forgot/reset', json={
        "reset_token": "non_existent_token",
        "security_answer": "bengaluru",
        "new_pin": "928374"
    })
    assert res3.status_code == 400
    assert "expired reset token" in res3.get_json()["message"].lower()


def test_forgot_pin_rate_limiting_3_per_hour(client, app, user_id):
    """Test that more than 3 forgot PIN requests in an hour is blocked."""
    # Seed 3 pairs of PIN_RESET records created in the last 10 minutes
    now = datetime.utcnow()
    with app.app_context():
        for i in range(3):
            db.session.add(OtpCode(
                user_id=user_id,
                purpose="PIN_RESET",
                channel="EMAIL",
                code_hash="dummy_hash_e",
                expires_at=now + timedelta(minutes=5),
                created_at=now - timedelta(minutes=i*2)
            ))
            db.session.add(OtpCode(
                user_id=user_id,
                purpose="PIN_RESET",
                channel="TELEGRAM",
                code_hash="dummy_hash_t",
                expires_at=now + timedelta(minutes=5),
                created_at=now - timedelta(minutes=i*2)
            ))
        db.session.commit()

    # The 4th start attempt should be rejected with 429
    res = client.post('/api/pin/forgot/start', json={"user_id": user_id})
    assert res.status_code == 429
    assert "Maximum 3 reset requests per hour" in res.get_json()["message"]


def test_reduced_limit_enforced_in_transfer(client, app, user_id):
    """Test 24-hour reduced limits in /api/transfer (Rs 10,000 / txn, Rs 25,000 / day)."""
    with app.app_context():
        from flask_jwt_extended import create_access_token
        token = create_access_token(identity=user_id)
        # 1. Enable reduced limit mode on user
        u = User.query.filter_by(user_id=user_id).first()
        u.reduced_limit_until = datetime.utcnow() + timedelta(hours=24)
        db.session.commit()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 2. Attempt transfer over reduced per-transaction limit (Rs 12,000 > 10,000)
    res_large = client.post('/api/transfer', headers=headers, json={
        "receiver_upi": "receiver@mlbfd",
        "amount": 12000.0,
        "payment_pin": "395816"
    })
    assert res_large.status_code == 400
    assert "Transaction limit exceeded" in res_large.get_json()["message"]
    assert "24-hour reduced-limit mode" in res_large.get_json()["message"]

    # 3. Seed existing transactions for today totaling Rs 20,000
    with app.app_context():
        today = datetime.utcnow().replace(hour=10, minute=0)
        t1 = Transaction(
            txn_id="TXN-TODAY-01",
            user_id=user_id,
            amount=20000.0,
            sender_upi="9876543210@mlbfd",
            receiver_upi="merchant@mlbfd",
            risk_score=15.0,
            status="APPROVED",
            created_at=today
        )
        db.session.add(t1)
        db.session.commit()

    # 4. Attempt transfer of Rs 6,000 (20,000 + 6,000 = 26,000 > 25,000 reduced daily limit)
    res_daily = client.post('/api/transfer', headers=headers, json={
        "receiver_upi": "receiver@mlbfd",
        "amount": 6000.0,
        "payment_pin": "395816"
    })
    assert res_daily.status_code == 400
    assert "Daily limit exceeded" in res_daily.get_json()["message"]
    assert "reduced-limit mode" in res_daily.get_json()["message"]


def test_jwt_blacklisting_after_reset(client, app, user_id):
    """Test that all JWTs issued before tokens_revoked_at are rejected."""
    with app.app_context():
        from flask_jwt_extended import create_access_token
        old_token = create_access_token(identity=user_id)

    headers_old = {"Authorization": f"Bearer {old_token}"}

    # Verify old token works initially on protected endpoint
    res_before = client.get('/api/telegram/status', headers=headers_old)
    assert res_before.status_code == 200

    # Simulate PIN reset which sets tokens_revoked_at to now
    time.sleep(1.0)
    with app.app_context():
        u = User.query.filter_by(user_id=user_id).first()
        u.tokens_revoked_at = datetime.utcnow()
        db.session.commit()

    # Now using the old token should be blocked by JWT token_in_blocklist_loader
    res_after = client.get('/api/telegram/status', headers=headers_old)
    assert res_after.status_code == 401
    assert "revoked" in res_after.get_json().get("msg", "").lower()
