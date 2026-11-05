import pytest
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Add backend directory to sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, OtpCode, TelegramLinkToken
from security import encrypt_val, decrypt_val, compute_lookup_hash
from otp_service import get_channel_sender, register_channel_sender, clear_channel_senders, MockOtpSender
from user_manager import cleanup_expired_pending_accounts


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


def test_register_start_validation_and_creation(client, app):
    # Missing fields
    res = client.post("/api/register/start", json={
        "full_name": "Test User",
        "user_id": "test_user_7"
    })
    assert res.status_code == 400
    assert "required" in res.get_json()["message"].lower()

    # Missing consent
    res = client.post("/api/register/start", json={
        "full_name": "Test User",
        "user_id": "test_user_7",
        "phone": "+919876543210",
        "email": "test7@example.com",
        "login_pin": "847291",
        "payment_pin": "519374",
        "security_question": "First school?",
        "security_answer": "St Marys",
        "consent": False
    })
    assert res.status_code == 400
    assert "consent" in res.get_json()["message"].lower()

    # Identical PINs rejection
    res = client.post("/api/register/start", json={
        "full_name": "Test User",
        "user_id": "test_user_7",
        "phone": "+919876543210",
        "email": "test7@example.com",
        "login_pin": "847291",
        "payment_pin": "847291",
        "security_question": "First school?",
        "security_answer": "St Marys",
        "consent": True
    })
    assert res.status_code == 400
    assert "differ" in res.get_json()["message"].lower()

    # Successful start
    res = client.post("/api/register/start", json={
        "full_name": "Test User",
        "user_id": "test_user_7",
        "phone": "+919876543210",
        "email": "test7@example.com",
        "login_pin": "847291",
        "payment_pin": "519374",
        "security_question": "First school?",
        "security_answer": "St Marys",
        "consent": True
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data["success"] is True
    assert data["user_id"] == "test_user_7"
    assert "telegram_link" in data
    assert "start=" in data["telegram_link"]

    # Verify user state in DB
    with app.app_context():
        u = User.query.filter_by(user_id="test_user_7").first()
        assert u is not None
        assert u.status == "PENDING"
        assert float(u.balance) == 0.00
        assert u.email_verified is False
        assert u.telegram_verified is False
        assert u.upi_id is None


def test_register_start_collision_generic_message(client):
    # 1. Register first user
    res1 = client.post("/api/register/start", json={
        "full_name": "User One",
        "user_id": "user_collision_1",
        "phone": "+919988776655",
        "email": "collision1@example.com",
        "login_pin": "718293",
        "payment_pin": "384719",
        "security_question": "City?",
        "security_answer": "Bengaluru",
        "consent": True
    })
    assert res1.status_code == 201

    # 2. Duplicate phone with different user_id and email -> generic message
    res2 = client.post("/api/register/start", json={
        "full_name": "User Two",
        "user_id": "user_collision_2",
        "phone": "+919988776655",  # SAME PHONE
        "email": "collision2@example.com",
        "login_pin": "718293",
        "payment_pin": "384719",
        "security_question": "City?",
        "security_answer": "Bengaluru",
        "consent": True
    })
    assert res2.status_code == 400
    msg = res2.get_json()["message"]
    # Generic message without leaking whether phone, email, or user_id collided
    assert "already exists" in msg.lower() or "in progress" in msg.lower()
    assert "phone" not in msg.lower()
    assert "email" not in msg.lower()


def test_expired_pending_account_cleanup(app):
    with app.app_context():
        old_time = datetime.utcnow() - timedelta(minutes=40)
        old_pending = User(
            user_id="old_pending_user",
            full_name="Old Pending",
            status="PENDING",
            created_at=old_time,
            balance=0.00
        )
        db.session.add(old_pending)
        db.session.commit()

        # Run cleanup
        count = cleanup_expired_pending_accounts(max_age_minutes=30)
        assert count >= 1

        # Old pending user was deleted
        assert User.query.filter_by(user_id="old_pending_user").first() is None


def test_nothing_activates_with_only_one_verification(client, app):
    # 1. Start registration
    res = client.post("/api/register/start", json={
        "full_name": "Solo Verify User",
        "user_id": "solo_user",
        "phone": "+919123456789",
        "email": "solo@example.com",
        "login_pin": "829103",
        "payment_pin": "472910",
        "security_question": "Pet?",
        "security_answer": "Bruno",
        "consent": True
    })
    assert res.status_code == 201

    # 2. Get issued email OTP code from DB
    with app.app_context():
        u = User.query.filter_by(user_id="solo_user").first()
        assert u.status == "PENDING"
        assert float(u.balance) == 0.00

        # Query latest SIGNUP OTP for EMAIL
        email_otp = OtpCode.query.filter_by(user_id="solo_user", channel="EMAIL", purpose="SIGNUP").first()
        assert email_otp is not None

        # Verify email code
        from otp_service import hash_code_hmac
        # We can extract the code by verifying with a known code or test helper
        # In test environment, let's mock/test with verify
        # To test verify with exact code: set a known code hash in record for testing
        test_code = "654321"
        email_otp.code_hash = hash_code_hmac(test_code)
        db.session.commit()

    # 3. Verify EMAIL ONLY
    res_email = client.post("/api/register/verify_email", json={
        "user_id": "solo_user",
        "code": "654321"
    })
    assert res_email.status_code == 200
    data_email = res_email.get_json()
    assert data_email["email_verified"] is True

    # Check that account is STILL PENDING with 0 balance (NOT activated!)
    with app.app_context():
        u = User.query.filter_by(user_id="solo_user").first()
        assert u.status == "PENDING"
        assert float(u.balance) == 0.00
        assert u.upi_id is None


def test_full_activation_flow_with_dual_verification(client, app):
    # 1. Start registration
    res = client.post("/api/register/start", json={
        "full_name": "Full Verify User",
        "user_id": "full_user",
        "phone": "+919876543219",
        "email": "full@example.com",
        "login_pin": "918273",
        "payment_pin": "465728",
        "security_question": "School?",
        "security_answer": "National High",
        "consent": True
    })
    assert res.status_code == 201

    with app.app_context():
        # Set known email OTP
        from otp_service import hash_code_hmac
        email_otp = OtpCode.query.filter_by(user_id="full_user", channel="EMAIL", purpose="SIGNUP").first()
        email_otp.code_hash = hash_code_hmac("112233")

        # Simulate Telegram link & contact check completion
        u = User.query.filter_by(user_id="full_user").first()
        u.telegram_chat_id = encrypt_val("998877")
        u.telegram_verified = True
        db.session.commit()

    # 2. Verify Email
    res_e = client.post("/api/register/verify_email", json={
        "user_id": "full_user",
        "code": "112233"
    })
    assert res_e.status_code == 200

    # 3. Request Telegram OTP
    res_tg_send = client.post("/api/register/send_telegram_otp", json={"user_id": "full_user"})
    assert res_tg_send.status_code == 200

    with app.app_context():
        tg_otp = OtpCode.query.filter_by(user_id="full_user", channel="TELEGRAM", purpose="SIGNUP").order_by(OtpCode.id.desc()).first()
        assert tg_otp is not None
        tg_otp.code_hash = hash_code_hmac("445566")
        db.session.commit()

    # 4. Verify Telegram OTP with X-Device-ID header -> FULL ACTIVATION!
    res_tg_verify = client.post(
        "/api/register/verify_telegram",
        headers={"X-Device-ID": "test-device-uuid-999"},
        json={"user_id": "full_user", "code": "445566"}
    )
    assert res_tg_verify.status_code == 200
    act_data = res_tg_verify.get_json()

    assert act_data["success"] is True
    assert act_data["status"] == "ACTIVE"
    assert act_data["balance"] == 100000.00
    assert act_data["upi_id"] == "9876543219@mlbfd"
    assert "access_token" in act_data
    assert "refresh_token" in act_data

    # Verify database state
    with app.app_context():
        u_final = User.query.filter_by(user_id="full_user").first()
        assert u_final.status == "ACTIVE"
        assert float(u_final.balance) == 100000.00
        assert u_final.get_decrypted_upi_id() == "9876543219@mlbfd"
        # Device bound
        assert any(d.get("device_id") == "test-device-uuid-999" for d in u_final.known_devices)
