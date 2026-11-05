import time
import os
import sys
from datetime import datetime, timedelta
import pytest
from unittest.mock import patch

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, Transaction
from security import (
    encrypt_val, compute_lookup_hash, hash_pin,
    mask_phone, mask_email, generate_form_timing_token
)
import otp_service


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["TURNSTILE_SECRET_KEY"] = "MOCK"

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _create_active_user(user_id="user_p15", balance=25000.00, phone="+919876543210", email="ramesh.kumar@gmail.com"):
    norm_phone = phone
    user = User(
        user_id=user_id,
        full_name="Ramesh Kumar",
        phone=encrypt_val(norm_phone),
        phone_hash=compute_lookup_hash(norm_phone),
        email=encrypt_val(email),
        email_hash=compute_lookup_hash(email),
        upi_id=encrypt_val(f"{norm_phone[-10:]}@mlbfd"),
        upi_hash=compute_lookup_hash(f"{norm_phone[-10:]}@mlbfd"),
        status="ACTIVE",
        email_verified=True,
        telegram_verified=True,
        telegram_chat_id=encrypt_val("123456789"),
        balance=balance,
        login_pin_hash=hash_pin("123456"),
        payment_pin_hash=hash_pin("654321"),
        security_question="What city were you born in?",
        security_answer_hash=hash_pin("bengaluru"),
        consent_at=datetime.utcnow() - timedelta(days=2),
        phone_number=norm_phone
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_mask_phone_and_email_helpers():
    """Verify phone and email masking per Section D Part 15."""
    assert mask_phone("+919876543210") == "+91********10"
    assert mask_phone("9876543210") == "********10"
    assert mask_phone("12") == "12"
    assert mask_phone(None) == ""

    assert mask_email("ramesh.kumar@gmail.com") == "r***r@gmail.com"
    assert mask_email("ab@domain.com") == "a***@domain.com"
    assert mask_email("a@domain.com") == "a***@domain.com"
    assert mask_email(None) == ""


def test_consent_at_recorded_on_registration(client):
    """Signup must require consent and save consent_at timestamp."""
    payload = {
        "full_name": "Consent Test",
        "user_id": "consent_user",
        "phone": "9876500055",
        "email": "consent@gmail.com",
        "login_pin": "948271",
        "payment_pin": "183920",
        "security_question": "What is the name of your first school?",
        "security_answer": "KV School",
        "consent": True,
        "form_started_at": time.time() - 4.0,
        "form_timing_token": generate_form_timing_token(timestamp=time.time() - 4.0)
    }

    resp = client.post("/api/register/start", json=payload)
    assert resp.status_code == 201

    user = User.query.filter_by(user_id="consent_user").first()
    assert user is not None
    assert user.consent_at is not None
    assert isinstance(user.consent_at, datetime)


def test_reset_balance_endpoint(client):
    """POST /api/account/reset_balance restores ₹100,000, max once per hour."""
    user = _create_active_user(user_id="reset_user", balance=500.00)

    # Without a JWT another person could reset any account by user_id -> 401
    assert client.post("/api/account/reset_balance", json={"user_id": "reset_user"}).status_code == 401
    from flask_jwt_extended import create_access_token
    auth = {"Authorization": f"Bearer {create_access_token(identity='reset_user')}"}

    # First reset succeeds
    resp = client.post("/api/account/reset_balance", json={}, headers=auth)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["balance"] == 100000.00

    refreshed_user = User.query.filter_by(user_id="reset_user").first()
    assert float(refreshed_user.balance) == 100000.00
    assert refreshed_user.last_balance_reset_at is not None

    # Immediate second reset attempt fails with 429
    resp_again = client.post("/api/account/reset_balance", json={}, headers=auth)
    assert resp_again.status_code == 429
    data_again = resp_again.get_json()
    assert data_again["error"] == "RATE_LIMITED"


def test_account_delete_flow_and_anonymization(client):
    """POST /api/account/delete requires payment PIN + dual OTP, scrubs PII, and anonymizes ledger."""
    user = _create_active_user(user_id="del_user", phone="+919876543299", email="delete.me@gmail.com")

    # Add ledger transactions involving this user
    user_upi = f"9876543299@mlbfd"
    txn1 = Transaction(
        txn_id="TXN_DEL_001",
        user_id="del_user",
        sender_upi=user_upi,
        receiver_upi="merchant@mlbfd",
        amount=1500.00,
        status="APPROVED",
        device_id="dev_xyz123",
        latitude=12.9716,
        longitude=77.5946
    )
    txn2 = Transaction(
        txn_id="TXN_DEL_002",
        user_id="other_user",
        sender_upi="sender@mlbfd",
        receiver_upi=user_upi,
        amount=3000.00,
        status="APPROVED"
    )
    db.session.add_all([txn1, txn2])
    db.session.commit()

    # 1. Calling without payment PIN fails
    resp = client.post("/api/account/delete", json={"user_id": "del_user"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "PIN_REQUIRED"

    # 2. Calling with wrong payment PIN fails
    resp_wrong_pin = client.post("/api/account/delete", json={"user_id": "del_user", "payment_pin": "000000"})
    assert resp_wrong_pin.status_code == 401
    assert resp_wrong_pin.get_json()["error"] == "INVALID_PIN"

    # 3. Calling with valid payment PIN without OTPs triggers OTP dispatch
    with patch.object(otp_service, "issue_dual", return_value=("111111", "222222")) as mock_issue:
        resp_otp_req = client.post("/api/account/delete", json={"user_id": "del_user", "payment_pin": "654321"})
        assert resp_otp_req.status_code == 200
        assert resp_otp_req.get_json()["status"] == "OTP_REQUIRED"
        assert mock_issue.called

    # 4. Calling with wrong OTP fails
    with patch.object(otp_service, "verify_dual", return_value=(False, "Incorrect verification code.")):
        resp_bad_otp = client.post("/api/account/delete", json={
            "user_id": "del_user",
            "payment_pin": "654321",
            "email_code": "000000",
            "telegram_code": "000000"
        })
        assert resp_bad_otp.status_code == 400
        assert resp_bad_otp.get_json()["error"] == "OTP_INVALID"

    # 5. Calling with valid payment PIN and valid dual OTP executes deletion
    with patch.object(otp_service, "verify_dual", return_value=(True, "")):
        resp_ok = client.post("/api/account/delete", json={
            "user_id": "del_user",
            "payment_pin": "654321",
            "email_code": "111111",
            "telegram_code": "222222"
        })
        assert resp_ok.status_code == 200
        assert resp_ok.get_json()["success"] is True

    # 6. Verify PII scrubbing on User record
    scrubbed = User.query.filter_by(user_id="del_user").first()
    assert scrubbed.status == "DELETED"
    assert scrubbed.full_name == "Deleted User"
    assert scrubbed.phone is None
    assert scrubbed.email is None
    assert scrubbed.upi_id is None
    assert scrubbed.login_pin_hash is None
    assert scrubbed.payment_pin_hash is None
    assert scrubbed.tokens_revoked_at is not None

    # 7. Verify ledger anonymization
    t1 = Transaction.query.filter_by(txn_id="TXN_DEL_001").first()
    assert t1.sender_upi == "deleted_user@mlbfd"
    assert t1.device_id is None
    assert t1.latitude is None

    t2 = Transaction.query.filter_by(txn_id="TXN_DEL_002").first()
    assert t2.receiver_upi == "deleted_user@mlbfd"


def test_admin_portal_users_api_masks_phone_and_email(client):
    """GET /admin/api/users must return masked phone and email."""
    _create_active_user(user_id="admin_mask_user", phone="+919876543210", email="ramesh.kumar@gmail.com")

    resp = client.get("/admin/api/users")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    users = data["users"]
    target = next((u for u in users if u["user_id"] == "admin_mask_user"), None)
    assert target is not None
    assert target["phone_number"] == "+91********10"
    assert target["email"] == "r***r@gmail.com"


def test_demo_banner_in_templates(client):
    """Verify demo banner appears in portal templates."""
    # Check admin template
    admin_resp = client.get("/admin")
    if admin_resp.status_code == 200:
        assert b"MLBFD demo - virtual money only" in admin_resp.data

    # Check user login page
    login_resp = client.get("/login")
    if login_resp.status_code == 200:
        assert b"MLBFD demo - virtual money only" in login_resp.data

    # Check register page
    reg_resp = client.get("/register")
    if reg_resp.status_code == 200:
        assert b"MLBFD demo - virtual money only" in reg_resp.data
