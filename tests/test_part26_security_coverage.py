"""
tests/test_part26_security_coverage.py - Security & Attack Vector Test Coverage

Tests:
1. Replay attack rejection (expired X-Timestamp, tampered payload)
2. Revoked JWT token rejection (tokens_revoked_at and TokenBlocklist)
3. Rate limiting enforcement (HTTP 429 Too Many Requests)
"""

import os
import sys
import time
import hmac
import hashlib
import json
from datetime import datetime, timedelta
import pytest

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
for p in [root_dir, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from database import db, User, TokenBlocklist
from security import (
    hash_pin,
    encrypt_val,
    compute_lookup_hash,
    verify_request_signature
)
from config import Config
from flask_jwt_extended import create_access_token


@pytest.fixture
def app_instance():
    os.environ["SECRET_KEY"] = "test_super_secret_signing_key_part26"
    os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_signing_key_part26"
    os.environ["HASH_PEPPER"] = "test_hash_pepper_key"
    os.environ["EMAIL_DRY_RUN"] = "True"
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


def generate_hmac_signature(body_bytes: bytes, timestamp_str: str, secret_key: str = None) -> str:
    key = (secret_key or Config.SECRET_KEY).encode("utf-8")
    msg = body_bytes + timestamp_str.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def test_replay_attack_rejected_with_old_timestamp(client, app_instance):
    """
    Replay attack prevention:
    Requests with an X-Timestamp older than 60 seconds must be rejected.
    """
    with app_instance.app_context():
        user = User(
            user_id="replay_victim_01",
            full_name="Replay Victim",
            phone=encrypt_val("+919876543210"),
            phone_hash=compute_lookup_hash("+919876543210"),
            email=encrypt_val("victim@mlbfd.local"),
            email_hash=compute_lookup_hash("victim@mlbfd.local"),
            upi_id=encrypt_val("9876543210@mlbfd"),
            upi_hash=compute_lookup_hash("9876543210@mlbfd"),
            login_pin_hash=hash_pin("129845"),
            payment_pin_hash=hash_pin("582914"),
            status="ACTIVE",
            balance=100000.0,
            email_verified=True,
            telegram_verified=True
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity="replay_victim_01")

    payload = {"amount": 500.0, "receiver_upi": "9876543210@mlbfd"}
    body_bytes = json.dumps(payload).encode("utf-8")

    # 1. Stale timestamp (300 seconds ago)
    old_timestamp = str(int(time.time()) - 300)
    old_signature = generate_hmac_signature(body_bytes, old_timestamp)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Timestamp": old_timestamp,
        "X-Signature": old_signature
    }

    res_stale = client.post("/api/predict_secure", data=body_bytes, headers=headers)
    assert res_stale.status_code == 400
    data_stale = res_stale.get_json()
    assert "replay" in data_stale["message"].lower() or "signature" in data_stale["message"].lower()

    # 2. Tampered body with fresh timestamp
    fresh_timestamp = str(int(time.time()))
    tampered_bytes = json.dumps({"amount": 50000.0, "receiver_upi": "9876543210@mlbfd"}).encode("utf-8")
    sig_for_original = generate_hmac_signature(body_bytes, fresh_timestamp)

    headers_tampered = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Timestamp": fresh_timestamp,
        "X-Signature": sig_for_original
    }

    res_tampered = client.post("/api/predict_secure", data=tampered_bytes, headers=headers_tampered)
    assert res_tampered.status_code == 400


def test_revoked_jwt_blocked_by_tokens_revoked_at(client, app_instance):
    """
    JWT revocation test:
    When user resets PIN or revokes tokens, tokens_revoked_at invalidates older JWTs.
    """
    with app_instance.app_context():
        user = User(
            user_id="revoked_user_01",
            full_name="Revoked User",
            phone=encrypt_val("+919876543211"),
            phone_hash=compute_lookup_hash("+919876543211"),
            email=encrypt_val("revoked@mlbfd.local"),
            email_hash=compute_lookup_hash("revoked@mlbfd.local"),
            upi_id=encrypt_val("9876543211@mlbfd"),
            upi_hash=compute_lookup_hash("9876543211@mlbfd"),
            login_pin_hash=hash_pin("129845"),
            payment_pin_hash=hash_pin("582914"),
            status="ACTIVE",
            balance=100000.0,
            email_verified=True,
            telegram_verified=True
        )
        db.session.add(user)
        db.session.commit()

        # Issue token at T0
        token = create_access_token(identity="revoked_user_01")

    headers = {"Authorization": f"Bearer {token}"}

    # Verify token works before revocation
    res_before = client.get("/api/telegram/status", headers=headers)
    assert res_before.status_code == 200

    # Simulate token revocation (e.g. after PIN reset)
    with app_instance.app_context():
        u = User.query.filter_by(user_id="revoked_user_01").first()
        # Set tokens_revoked_at to future to guarantee iat <= tokens_revoked_at
        u.tokens_revoked_at = datetime.utcnow() + timedelta(seconds=5)
        db.session.commit()

    # Verify same token is now rejected with 401
    res_after = client.get("/api/telegram/status", headers=headers)
    assert res_after.status_code == 401


def test_revoked_jwt_blocked_by_token_blocklist(client, app_instance):
    """
    JWT revocation test:
    Explicit JTI blacklisting in TokenBlocklist blocks the specific token.
    """
    from flask_jwt_extended import decode_token

    with app_instance.app_context():
        user = User(
            user_id="blocklist_user_01",
            full_name="Blocklist User",
            phone=encrypt_val("+919876543212"),
            phone_hash=compute_lookup_hash("+919876543212"),
            email=encrypt_val("blocklist@mlbfd.local"),
            email_hash=compute_lookup_hash("blocklist@mlbfd.local"),
            upi_id=encrypt_val("9876543212@mlbfd"),
            upi_hash=compute_lookup_hash("9876543212@mlbfd"),
            login_pin_hash=hash_pin("129845"),
            payment_pin_hash=hash_pin("582914"),
            status="ACTIVE",
            balance=100000.0,
            email_verified=True,
            telegram_verified=True
        )
        db.session.add(user)
        db.session.commit()

        token = create_access_token(identity="blocklist_user_01")
        decoded = decode_token(token)
        jti = decoded["jti"]

    headers = {"Authorization": f"Bearer {token}"}

    # Verify token works before blocklist insertion
    res1 = client.get("/api/telegram/status", headers=headers)
    assert res1.status_code == 200

    # Add token to blocklist
    with app_instance.app_context():
        blocked = TokenBlocklist(
            jti=jti,
            user_id="blocklist_user_01"
        )
        db.session.add(blocked)
        db.session.commit()

    # Verify token is blocked with 401
    res2 = client.get("/api/telegram/status", headers=headers)
    assert res2.status_code == 401


def test_rate_limits_enforced_on_restricted_endpoints(client, app_instance):
    """
    Rate limiting test:
    POST /api/pin/forgot/start is rate limited to 3 per hour.
    Exceeding limit returns 429 Too Many Requests.
    """
    with app_instance.app_context():
        user = User(
            user_id="ratelimit_user_01",
            full_name="Rate Limit User",
            phone=encrypt_val("+919876543213"),
            phone_hash=compute_lookup_hash("+919876543213"),
            email=encrypt_val("ratelimit@mlbfd.local"),
            email_hash=compute_lookup_hash("ratelimit@mlbfd.local"),
            upi_id=encrypt_val("9876543213@mlbfd"),
            upi_hash=compute_lookup_hash("9876543213@mlbfd"),
            login_pin_hash=hash_pin("129845"),
            payment_pin_hash=hash_pin("582914"),
            status="ACTIVE",
            balance=100000.0,
            email_verified=True,
            telegram_verified=True
        )
        db.session.add(user)
        db.session.commit()

    payload = {"user_id": "ratelimit_user_01"}

    # Attempt 4 requests (limit is 3 per hour)
    statuses = []
    for _ in range(4):
        res = client.post("/api/pin/forgot/start", json=payload)
        statuses.append(res.status_code)

    assert 429 in statuses, f"Expected HTTP 429 in statuses {statuses} after exceeding 3/hr limit"

