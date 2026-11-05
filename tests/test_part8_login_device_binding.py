import pytest
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

# Add backend directory to sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, OtpCode
from security import encrypt_val, compute_lookup_hash, hash_pin
from otp_service import hash_code_hmac
from user_manager import bind_device


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
def active_user(app):
    with app.app_context():
        user = User(
            user_id="active_login_user",
            full_name="Active Login User",
            phone=encrypt_val("+919876543210"),
            phone_hash=compute_lookup_hash("+919876543210"),
            email=encrypt_val("active@example.com"),
            email_hash=compute_lookup_hash("active@example.com"),
            upi_id=encrypt_val("9876543210@mlbfd"),
            upi_hash=compute_lookup_hash("9876543210@mlbfd"),
            status="ACTIVE",
            balance=100000.00,
            login_pin_hash=hash_pin("819273", rounds=12),
            payment_pin_hash=hash_pin("465719", rounds=12),
            pin_hash=hash_pin("819273", rounds=12),
            email_verified=True,
            telegram_verified=True,
            telegram_chat_id=encrypt_val("12345678"),
            known_devices=[]
        )
        db.session.add(user)
        db.session.commit()
        return user


def test_unknown_device_requires_dual_otp(client, active_user, app):
    # Attempt login with unknown device
    res = client.post("/api/login", json={
        "user_id": "active_login_user",
        "login_pin": "819273",
        "device_id": "brand-new-device-uuid-1"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "OTP_REQUIRED"
    assert "access_token" not in data

    # Verify that dual OTPs were issued for LOGIN_NEW_DEVICE
    with app.app_context():
        email_otp = OtpCode.query.filter_by(user_id="active_login_user", purpose="LOGIN_NEW_DEVICE", channel="EMAIL").first()
        tg_otp = OtpCode.query.filter_by(user_id="active_login_user", purpose="LOGIN_NEW_DEVICE", channel="TELEGRAM").first()
        assert email_otp is not None
        assert tg_otp is not None
        assert email_otp.dual_group_id == tg_otp.dual_group_id


def test_login_verify_binds_device_and_issues_tokens(client, active_user, app):
    # 1. Trigger OTP requirement
    client.post("/api/login", json={
        "user_id": "active_login_user",
        "login_pin": "819273",
        "device_id": "device-uuid-to-bind"
    })

    with app.app_context():
        # Set known test codes
        otps = OtpCode.query.filter_by(user_id="active_login_user", purpose="LOGIN_NEW_DEVICE").all()
        for r in otps:
            if r.channel == "EMAIL":
                r.code_hash = hash_code_hmac("111222")
            elif r.channel == "TELEGRAM":
                r.code_hash = hash_code_hmac("333444")
        db.session.commit()

    # 2. Submit wrong code -> fails
    res_bad = client.post("/api/login/verify", json={
        "user_id": "active_login_user",
        "email_code": "000000",
        "telegram_code": "333444",
        "device_id": "device-uuid-to-bind"
    })
    assert res_bad.status_code == 400
    assert "invalid" in res_bad.get_json()["message"].lower()

    # 3. Submit correct dual codes -> binds device and returns tokens
    res_good = client.post("/api/login/verify", json={
        "user_id": "active_login_user",
        "email_code": "111222",
        "telegram_code": "333444",
        "device_id": "device-uuid-to-bind"
    })
    assert res_good.status_code == 200
    good_data = res_good.get_json()
    assert good_data["status"] == "LOGGED_IN"
    assert "access_token" in good_data
    assert "refresh_token" in good_data

    # 4. Subsequent login with the now-trusted device -> Direct login without OTP!
    res_direct = client.post("/api/login", json={
        "user_id": "active_login_user",
        "login_pin": "819273",
        "device_id": "device-uuid-to-bind"
    })
    assert res_direct.status_code == 200
    direct_data = res_direct.get_json()
    assert direct_data["status"] == "LOGGED_IN"
    assert "access_token" in direct_data
    assert "refresh_token" in direct_data


def test_device_trust_expires_after_30_days(client, active_user, app):
    with app.app_context():
        u = User.query.filter_by(user_id="active_login_user").first()
        old_time = (datetime.utcnow() - timedelta(days=35)).isoformat()
        u.known_devices = [{
            "device_id": "expired-device-uuid",
            "last_verified": old_time
        }]
        db.session.commit()

    # Login with expired device -> Must ask for OTP again!
    res = client.post("/api/login", json={
        "user_id": "active_login_user",
        "login_pin": "819273",
        "device_id": "expired-device-uuid"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "OTP_REQUIRED"
    assert "access_token" not in data


def test_frozen_and_pending_accounts_cannot_login(client, app):
    with app.app_context():
        frozen = User(
            user_id="frozen_user",
            full_name="Frozen User",
            status="FROZEN",
            login_pin_hash=hash_pin("819273", rounds=12),
            balance=100000.00
        )
        pending = User(
            user_id="pending_user",
            full_name="Pending User",
            status="PENDING",
            login_pin_hash=hash_pin("819273", rounds=12),
            balance=0.00
        )
        db.session.add_all([frozen, pending])
        db.session.commit()

    # Frozen login attempt
    res_f = client.post("/api/login", json={
        "user_id": "frozen_user",
        "login_pin": "819273",
        "device_id": "dev-1"
    })
    assert res_f.status_code == 403
    assert "active" in res_f.get_json()["message"].lower() or "frozen" in res_f.get_json()["message"].lower()

    # Pending login attempt
    res_p = client.post("/api/login", json={
        "user_id": "pending_user",
        "login_pin": "819273",
        "device_id": "dev-1"
    })
    assert res_p.status_code == 403


def test_refresh_token_endpoint(client, active_user):
    # 1. Bind device and get tokens
    from flask_jwt_extended import create_refresh_token
    with client.application.app_context():
        ref_tok = create_refresh_token(identity="active_login_user")

    # 2. Use refresh token to get new access token
    res = client.post("/api/refresh", headers={
        "Authorization": f"Bearer {ref_tok}"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "access_token" in data
