import pytest
import os
import sys
from datetime import datetime

# Add backend directory to sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, Transaction
from security import encrypt_val, compute_lookup_hash, hash_pin
from flask_jwt_extended import create_access_token


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
def sender_uid(app):
    uid = "sender_user_01"
    with app.app_context():
        u = User(
            user_id=uid,
            full_name="Sender Person",
            phone=encrypt_val("+919876543210"),
            phone_hash=compute_lookup_hash("+919876543210"),
            email=encrypt_val("sender@example.com"),
            email_hash=compute_lookup_hash("sender@example.com"),
            upi_id=encrypt_val("9876543210@mlbfd"),
            upi_hash=compute_lookup_hash("9876543210@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            login_pin_hash=hash_pin("847291", rounds=12),
            payment_pin_hash=hash_pin("395816", rounds=12),
            balance=100000.00,
            known_devices=[{"device_id": "device_sender", "last_verified_at": datetime.utcnow().isoformat()}]
        )
        db.session.add(u)
        db.session.commit()
    return uid


@pytest.fixture
def receiver_active_uid(app):
    uid = "receiver_user_02"
    with app.app_context():
        u = User(
            user_id=uid,
            full_name="Chirag Patil",
            phone=encrypt_val("+919876543211"),
            phone_hash=compute_lookup_hash("+919876543211"),
            email=encrypt_val("receiver@example.com"),
            email_hash=compute_lookup_hash("receiver@example.com"),
            upi_id=encrypt_val("9876543211@mlbfd"),
            upi_hash=compute_lookup_hash("9876543211@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            login_pin_hash=hash_pin("192837", rounds=12),
            payment_pin_hash=hash_pin("582914", rounds=12),
            balance=100000.00,
            known_devices=[{"device_id": "device_receiver", "last_verified_at": datetime.utcnow().isoformat()}]
        )
        db.session.add(u)
        db.session.commit()
    return uid


@pytest.fixture
def receiver_frozen_uid(app):
    uid = "receiver_frozen_03"
    with app.app_context():
        u = User(
            user_id=uid,
            full_name="Frozen User",
            phone=encrypt_val("+919876543212"),
            phone_hash=compute_lookup_hash("+919876543212"),
            email=encrypt_val("frozen@example.com"),
            email_hash=compute_lookup_hash("frozen@example.com"),
            upi_id=encrypt_val("9876543212@mlbfd"),
            upi_hash=compute_lookup_hash("9876543212@mlbfd"),
            status="FROZEN",
            email_verified=True,
            telegram_verified=True,
            login_pin_hash=hash_pin("192837", rounds=12),
            payment_pin_hash=hash_pin("582914", rounds=12),
            balance=50000.00
        )
        db.session.add(u)
        db.session.commit()
    return uid


def _get_auth_headers(app, uid):
    with app.app_context():
        token = create_access_token(identity=uid)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }


def test_unregistered_receiver_returns_404_no_ledger_row(client, app, sender_uid):
    """Test sending money to a non-existent receiver returns HTTP 404 BEFORE scoring and creates no ledger row."""
    headers = _get_auth_headers(app, sender_uid)

    res = client.post('/api/transfer', headers=headers, json={
        "receiver": "9999999999@mlbfd",
        "amount": 500.0,
        "payment_pin": "395816"
    })
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "USER_NOT_REGISTERED"
    assert "This user is not registered on MLBFD" in data["message"]

    # Assert no transaction ledger entry was created
    with app.app_context():
        txns = Transaction.query.all()
        assert len(txns) == 0

        # Assert sender balance was untouched
        sender = User.query.filter_by(user_id=sender_uid).first()
        assert float(sender.balance) == 100000.00


def test_frozen_receiver_returns_404_no_ledger_row(client, app, sender_uid, receiver_frozen_uid):
    """Test sending money to a FROZEN user returns HTTP 404 USER_NOT_REGISTERED before scoring."""
    headers = _get_auth_headers(app, sender_uid)

    res = client.post('/api/transfer', headers=headers, json={
        "receiver": "9876543212@mlbfd",
        "amount": 1000.0,
        "payment_pin": "395816"
    })
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "USER_NOT_REGISTERED"
    assert "This user is not registered on MLBFD" in data["message"]

    # Assert no transaction ledger entry was created
    with app.app_context():
        txns = Transaction.query.all()
        assert len(txns) == 0

        sender = User.query.filter_by(user_id=sender_uid).first()
        assert float(sender.balance) == 100000.00


def test_self_transfer_blocked(client, app, sender_uid):
    """Test sending money to oneself is blocked with 400 SELF_TRANSFER_BLOCKED."""
    headers = _get_auth_headers(app, sender_uid)

    # Attempt self-transfer using own UPI ID
    res = client.post('/api/transfer', headers=headers, json={
        "receiver": "9876543210@mlbfd",
        "amount": 250.0,
        "payment_pin": "395816"
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "SELF_TRANSFER_BLOCKED"
    assert "Self-transfer is not permitted" in data["message"]

    # Attempt self-transfer using own 10-digit phone number
    res_phone = client.post('/api/transfer', headers=headers, json={
        "receiver": "9876543210",
        "amount": 250.0,
        "payment_pin": "395816"
    })
    assert res_phone.status_code == 400
    assert res_phone.get_json()["error"] == "SELF_TRANSFER_BLOCKED"

    # Assert zero ledger entries
    with app.app_context():
        assert Transaction.query.count() == 0


def test_transfer_to_active_registered_user_by_all_identifier_formats(client, app, sender_uid, receiver_active_uid):
    """Test transfer succeeds with receiver as UPI id, 10-digit phone, and +91 phone."""
    headers = _get_auth_headers(app, sender_uid)

    # Format 1: 10-digit phone number
    res1 = client.post('/api/transfer', headers=headers, json={
        "receiver": "9876543211",
        "amount": 500.0,
        "payment_pin": "395816"
    })
    assert res1.status_code == 200
    assert res1.get_json()["success"] is True

    # Format 2: +91 E.164 phone number
    res2 = client.post('/api/transfer', headers=headers, json={
        "receiver": "+919876543211",
        "amount": 500.0,
        "payment_pin": "395816"
    })
    assert res2.status_code == 200
    assert res2.get_json()["success"] is True

    # Format 3: Canonical UPI ID
    res3 = client.post('/api/transfer', headers=headers, json={
        "receiver": "9876543211@mlbfd",
        "amount": 500.0,
        "payment_pin": "395816"
    })
    assert res3.status_code == 200
    assert res3.get_json()["success"] is True

    # Verify balances updated correctly (3 * 500 = 1500 transferred)
    with app.app_context():
        sender = User.query.filter_by(user_id=sender_uid).first()
        receiver = User.query.filter_by(user_id=receiver_active_uid).first()
        assert float(sender.balance) == 100000.00 - 1500.0
        assert float(receiver.balance) == 100000.00 + 1500.0


def test_lookup_payee_endpoint(client, app, sender_uid, receiver_active_uid, receiver_frozen_uid):
    """Test GET /api/lookup_payee?q= confirmation card endpoint."""
    headers = _get_auth_headers(app, sender_uid)

    # 1. Lookup active registered user by phone -> 200 with masked name & UPI
    res = client.get('/api/lookup_payee?q=9876543211', headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["registered"] is True
    # Masked name: "Chirag Patil" -> "C****g P***l"
    assert "*" in data["masked_name"]
    assert "Patil" not in data["masked_name"]
    # Masked UPI: "9876543211@mlbfd"
    assert "*" in data["masked_upi"]
    assert data["receiver_upi"] == "9876543211@mlbfd"

    # 2. Lookup non-registered user -> 404 USER_NOT_REGISTERED
    res_fake = client.get('/api/lookup_payee?q=9999999999', headers=headers)
    assert res_fake.status_code == 404
    assert res_fake.get_json()["error"] == "USER_NOT_REGISTERED"

    # 3. Lookup frozen user -> 404 USER_NOT_REGISTERED
    res_frozen = client.get('/api/lookup_payee?q=9876543212@mlbfd', headers=headers)
    assert res_frozen.status_code == 404
    assert res_frozen.get_json()["error"] == "USER_NOT_REGISTERED"

    # 4. Lookup self -> 400 SELF_TRANSFER_BLOCKED
    res_self = client.get('/api/lookup_payee?q=9876543210@mlbfd', headers=headers)
    assert res_self.status_code == 400
    assert res_self.get_json()["error"] == "SELF_TRANSFER_BLOCKED"
