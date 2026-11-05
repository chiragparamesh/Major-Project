import os
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from db import db
from database import User
from security import encrypt_val, decrypt_val, compute_lookup_hash
from user_manager import (
    find_user_by_upi_or_phone,
    normalize_phone,
    extract_10_digit_phone
)

@pytest.fixture(scope="module")
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app

def test_user_model_columns(app_ctx):
    # Verify all required columns exist on the User model
    required_cols = [
        "user_id", "full_name", "phone", "email", "upi_id",
        "phone_hash", "email_hash", "upi_hash", "status",
        "email_verified", "telegram_verified", "telegram_chat_id",
        "known_devices", "security_question", "security_answer_hash",
        "consent_at", "balance", "login_pin_hash", "payment_pin_hash", "created_at"
    ]
    for col in required_cols:
        assert hasattr(User, col), f"Missing column {col} on User model"

def test_new_user_balance_is_zero_until_activation(app_ctx):
    test_uid = "unit_test_pending_user"
    User.query.filter_by(user_id=test_uid).delete()
    db.session.commit()

    phone = "+919123456789"
    upi = "9123456789@mlbfd"
    new_user = User(
        user_id=test_uid,
        full_name="Unit Test User",
        pin_hash="$2b$12$dummyhashforpin1234567890abcdef",
        login_pin_hash="$2b$12$dummyhashforpin1234567890abcdef",
        payment_pin_hash="$2b$12$dummyhashforpin6543210987abcdef",
        phone=encrypt_val(phone),
        phone_hash=compute_lookup_hash(phone),
        email=encrypt_val("test@mlbfd.local"),
        email_hash=compute_lookup_hash("test@mlbfd.local"),
        upi_id=encrypt_val(upi),
        upi_hash=compute_lookup_hash(upi),
        status="PENDING",
        balance=0.00
    )
    db.session.add(new_user)
    db.session.commit()

    saved = User.query.filter_by(user_id=test_uid).first()
    assert saved is not None
    assert saved.status == "PENDING"
    assert float(saved.balance) == 0.00
    assert saved.get_decrypted_phone() == phone
    assert saved.get_decrypted_upi_id() == upi

    # Test activation sets balance to 100,000 INR
    saved.activate_account()
    db.session.commit()

    activated = User.query.filter_by(user_id=test_uid).first()
    assert activated.status == "ACTIVE"
    assert float(activated.balance) == 100000.00

    # Cleanup
    db.session.delete(activated)
    db.session.commit()

def test_find_user_by_upi_or_phone_variations(app_ctx):
    uid = "lookup_test_user"
    User.query.filter_by(user_id=uid).delete()
    db.session.commit()

    phone = "+919811122233"
    upi = "9811122233@mlbfd"
    test_user = User(
        user_id=uid,
        full_name="Lookup Test",
        pin_hash="$2b$12$dummyhashforpin1234567890abcdef",
        login_pin_hash="$2b$12$dummyhashforpin1234567890abcdef",
        payment_pin_hash="$2b$12$dummyhashforpin6543210987abcdef",
        phone=encrypt_val(phone),
        phone_hash=compute_lookup_hash(phone),
        upi_id=encrypt_val(upi),
        upi_hash=compute_lookup_hash(upi),
        status="ACTIVE",
        balance=100000.00
    )
    db.session.add(test_user)
    db.session.commit()

    # 1. Lookup by 10-digit phone
    by_10 = find_user_by_upi_or_phone("9811122233")
    assert by_10 is not None
    assert by_10.user_id == uid

    # 2. Lookup by +91 phone
    by_plus91 = find_user_by_upi_or_phone("+919811122233")
    assert by_plus91 is not None
    assert by_plus91.user_id == uid

    # 3. Lookup by formatted phone
    by_formatted = find_user_by_upi_or_phone("+91 98111-22233")
    assert by_formatted is not None
    assert by_formatted.user_id == uid

    # 4. Lookup by UPI ID
    by_upi = find_user_by_upi_or_phone("9811122233@mlbfd")
    assert by_upi is not None
    assert by_upi.user_id == uid

    # 5. Lookup by user_id directly
    by_uid = find_user_by_upi_or_phone(uid)
    assert by_uid is not None
    assert by_uid.user_id == uid

    # 6. Lookup non-existent
    assert find_user_by_upi_or_phone("0000000000") is None
    assert find_user_by_upi_or_phone("unknown@mlbfd") is None

    # Cleanup
    db.session.delete(test_user)
    db.session.commit()

def test_phone_normalization():
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("+919876543210") == "+919876543210"
    assert normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    assert extract_10_digit_phone("+919876543210") == "9876543210"
    assert extract_10_digit_phone("9876543210") == "9876543210"

def test_migration_script_execution():
    from migrate_db import run_migration, find_sqlite_db_path
    db_path = find_sqlite_db_path()
    assert db_path.exists(), "mlbfd.sqlite3 must exist"
    # Running migration again is idempotent
    result = run_migration()
    assert result is True
