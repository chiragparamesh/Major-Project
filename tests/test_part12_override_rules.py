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
from database import User, Transaction, UserBehaviorBaseline, TrustedPayee, ScamUpi
from security import encrypt_val, compute_lookup_hash, hash_pin
from flask_jwt_extended import create_access_token
from fraud_detection import OVERRIDE_RULES, evaluate_overrides, FraudDetectionEngine, global_fraud_detector


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
            user_id="user_sender_12",
            full_name="Sender User 12",
            phone=encrypt_val("+919876543210"),
            phone_hash=compute_lookup_hash("+919876543210"),
            email=encrypt_val("sender12@example.com"),
            email_hash=compute_lookup_hash("sender12@example.com"),
            upi_id=encrypt_val("9876543210@mlbfd"),
            upi_hash=compute_lookup_hash("9876543210@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            login_pin_hash=hash_pin("847291"),
            payment_pin_hash=hash_pin("395816"),
            balance=100000.00,
            known_devices=[{"device_id": "device_trusted_1", "last_verified_at": datetime.utcnow().isoformat()}]
        )
        receiver = User(
            user_id="user_receiver_12",
            full_name="Receiver User 12",
            phone=encrypt_val("+919876543211"),
            phone_hash=compute_lookup_hash("+919876543211"),
            email=encrypt_val("receiver12@example.com"),
            email_hash=compute_lookup_hash("receiver12@example.com"),
            upi_id=encrypt_val("9876543211@mlbfd"),
            upi_hash=compute_lookup_hash("9876543211@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            login_pin_hash=hash_pin("192837"),
            payment_pin_hash=hash_pin("582914"),
            balance=100000.00
        )
        db.session.add(sender)
        db.session.add(receiver)
        db.session.commit()

        # User baseline for sender: avg_amount = 1000.0
        baseline = UserBehaviorBaseline(
            user_id="user_sender_12",
            avg_amount=1000.0,
            std_amount=100.0,
            txn_count=20,
            known_devices=["device_trusted_1"],
            known_payees=["established_payee@mlbfd"]
        )
        db.session.add(baseline)

        # Established trusted payee added 30 days ago
        trusted_payee = TrustedPayee(
            user_id="user_sender_12",
            payee_upi="established_payee@mlbfd",
            txn_count=10,
            total_amount=10000.0,
            added_date=datetime.utcnow() - timedelta(days=30)
        )
        db.session.add(trusted_payee)
        db.session.commit()

    return "user_sender_12", "user_receiver_12"


def _auth_headers(app, uid):
    with app.app_context():
        token = create_access_token(identity=uid)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }


# ==============================================================================
# UNIT TESTS: evaluate_overrides DIRECT EVALUATION
# ==============================================================================

def test_override_rules_table_structure():
    """Verify OVERRIDE_RULES contains all 8 required rules and is properly structured."""
    assert isinstance(OVERRIDE_RULES, list)
    assert len(OVERRIDE_RULES) == 8
    rule_ids = [r['id'] for r in OVERRIDE_RULES]
    expected_ids = [
        "RULE_SCAM_BLACKLIST",
        "RULE_QR_PAYEE_MISMATCH",
        "RULE_IMPOSSIBLE_TRAVEL_NEW_DEVICE",
        "RULE_MALICIOUS_DOMAIN",
        "RULE_MULE_TOPOLOGY",
        "RULE_NEW_DEVICE_NEW_PAYEE_HIGH_AMOUNT",
        "RULE_EXTREME_AMOUNT_NEW_PAYEE",
        "RULE_NEW_PAYEE_COOLING_CAP"
    ]
    for eid in expected_ids:
        assert eid in rule_ids


def test_rule_1_scam_blacklist():
    """Rule 1: Payee in scam blacklist -> BLOCKED (at least 90)."""
    context = {"is_scam": True}
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=28.0)
    assert override_applied is True
    assert final_score >= 90.0
    assert any("scam blacklist" in r.lower() for r in reasons)


def test_rule_2_qr_payee_mismatch():
    """Rule 2: QR payee mismatch -> BLOCKED (at least 85)."""
    context = {"qr_mismatch": True}
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=15.0)
    assert override_applied is True
    assert final_score >= 85.0
    assert any("qr payee mismatch" in r.lower() for r in reasons)


def test_rule_3_impossible_travel_and_new_device():
    """Rule 3: Impossible travel AND new device -> BLOCKED (at least 85)."""
    context = {"is_impossible_travel": True, "is_new_device": True}
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=35.0)
    assert override_applied is True
    assert final_score >= 85.0
    assert any("impossible travel" in r.lower() for r in reasons)


def test_rule_3_impossible_travel_only_not_triggered():
    """Rule 3: Impossible travel on KNOWN device should NOT trigger this specific hard override."""
    context = {"is_impossible_travel": True, "is_new_device": False}
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=35.0)
    assert override_applied is False
    assert final_score == 35.0


def test_rule_4_website_flagged():
    """Rule 4: Website flagged by Safe Browsing or OpenPhish -> BLOCKED (at least 85)."""
    context = {"website_flagged": True}
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=10.0)
    assert override_applied is True
    assert final_score >= 85.0
    assert any("safe browsing or openphish" in r.lower() for r in reasons)


def test_rule_5_mule_topology():
    """Rule 5: Mule-topology receiver -> at least 70."""
    context = {"is_mule": True}
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=20.0)
    assert override_applied is True
    assert final_score >= 70.0
    assert any("mule-topology" in r.lower() for r in reasons)


def test_rule_6_new_device_new_payee_high_amount():
    """Rule 6: New device AND new payee AND amount over 5x average -> at least 70."""
    context = {
        "is_new_device": True,
        "is_new_payee": True,
        "amount_over_5x_avg": True
    }
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=30.0)
    assert override_applied is True
    assert final_score >= 70.0
    assert any(">5x average" in r for r in reasons)


def test_rule_7_extreme_amount_new_payee():
    """Rule 7: Amount over 10x average AND new payee -> at least 70."""
    context = {
        "is_new_payee": True,
        "amount_over_10x_avg": True
    }
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=25.0)
    assert override_applied is True
    assert final_score >= 70.0
    assert any(">10x average" in r for r in reasons)


def test_rule_8_cooling_off_cap_new_payee_under_24h():
    """Rule 8: Amount over Rs 5,000 to a payee added less than 24 hours ago -> at least 70."""
    context = {
        "amount": 6000.0,
        "payee_added_under_24h": True
    }
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=20.0)
    assert override_applied is True
    assert final_score >= 70.0
    assert any("5,000" in r for r in reasons)


def test_normal_transaction_unaffected():
    """Normal transaction with low weighted score and no anomalies is unaffected."""
    context = {
        "is_scam": False,
        "qr_mismatch": False,
        "is_impossible_travel": False,
        "is_new_device": False,
        "website_flagged": False,
        "is_mule": False,
        "is_new_payee": False,
        "amount_over_5x_avg": False,
        "amount_over_10x_avg": False,
        "payee_added_under_24h": False,
        "amount": 500.0
    }
    final_score, override_applied, reasons = evaluate_overrides({}, {}, context, weighted_score=18.5)
    assert override_applied is False
    assert final_score == 18.5
    assert len(reasons) == 0


# ==============================================================================
# INTEGRATION TESTS: FraudDetectionEngine.detect & Database
# ==============================================================================

def test_engine_detect_scam_blacklist_overrides_to_blocked(app, test_users):
    """Test FraudDetectionEngine.detect with blacklisted scam UPI produces BLOCKED score >= 90."""
    sender_id, _ = test_users
    scam_upi = "scammer_threat@mlbfd"

    with app.app_context():
        # Add scam record
        scam = ScamUpi(upi_id=scam_upi, reported_count=10, verified=True)
        db.session.add(scam)
        db.session.commit()

        engine = FraudDetectionEngine()
        verdict = engine.detect({
            "user_id": sender_id,
            "sender_upi": "9876543210@mlbfd",
            "receiver_upi": scam_upi,
            "amount": 200.0,
            "device_id": "device_trusted_1",
            "latitude": 12.9716,
            "longitude": 77.5946
        })

        assert verdict["status"] == "BLOCKED"
        assert verdict["final_score"] >= 90.0
        assert verdict["override_applied"] is True
        assert any("scam blacklist" in r.lower() for r in verdict["override_reasons"])
        assert "weighted_score" in verdict
        assert "final_score" in verdict


def test_engine_detect_qr_mismatch_overrides_to_blocked(app, test_users):
    """Test QR payee mismatch produces BLOCKED score >= 85."""
    sender_id, _ = test_users

    with app.app_context():
        engine = FraudDetectionEngine()
        # QR encodes upi://pay?pa=attacker@fakebank but user intends to pay receiver
        qr_tampered = "upi://pay?pa=attacker@fakebank&pn=Attacker&am=500"
        verdict = engine.detect({
            "user_id": sender_id,
            "sender_upi": "9876543210@mlbfd",
            "receiver_upi": "9876543211@mlbfd",
            "amount": 500.0,
            "device_id": "device_trusted_1",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "qr_code": qr_tampered
        })

        assert verdict["status"] == "BLOCKED"
        assert verdict["final_score"] >= 85.0
        assert verdict["override_applied"] is True
        assert any("qr payee mismatch" in r.lower() for r in verdict["override_reasons"])


def test_engine_detect_cooling_cap_under_24h_overrides_to_70(app, test_users):
    """Test transfer > Rs 5,000 to brand-new payee (added < 24h) triggers score >= 70."""
    sender_id, receiver_id = test_users

    with app.app_context():
        engine = FraudDetectionEngine()
        verdict = engine.detect({
            "user_id": sender_id,
            "sender_upi": "9876543210@mlbfd",
            "receiver_upi": "9876543211@mlbfd",  # brand new payee, not in trusted_payees
            "amount": 5500.0,
            "device_id": "device_trusted_1",
            "latitude": 12.9716,
            "longitude": 77.5946
        })

        assert verdict["final_score"] >= 70.0
        assert verdict["override_applied"] is True
        assert any("5,000" in r for r in verdict["override_reasons"])


# ==============================================================================
# API ENDPOINT TESTS: /api/predict_secure AND /api/transfer
# ==============================================================================

def test_api_predict_secure_returns_override_fields(client, app, test_users):
    """Test /api/predict_secure and /api/predict-secure return weighted_score, final_score, override_applied, override_reasons."""
    sender_id, _ = test_users
    headers = _auth_headers(app, sender_id)

    payload = {
        "sender_upi": "9876543210@mlbfd",
        "receiver_upi": "established_payee@mlbfd",
        "amount": 300.0,
        "device_id": "device_trusted_1",
        "latitude": 12.9716,
        "longitude": 77.5946
    }

    # Test /api/predict_secure
    res1 = client.post('/api/predict_secure', headers=headers, json=payload)
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert "weighted_score" in data1
    assert "final_score" in data1
    assert "override_applied" in data1
    assert "override_reasons" in data1
    assert data1["override_applied"] is False

    # Test /api/predict-secure alias
    res2 = client.post('/api/predict-secure', headers=headers, json=payload)
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["final_score"] == data1["final_score"]


def test_api_transfer_returns_override_fields(client, app, test_users):
    """Test /api/transfer returns weighted_score, final_score, override_applied, override_reasons in response."""
    sender_id, _ = test_users
    headers = _auth_headers(app, sender_id)

    # 1. Normal transfer to active registered user
    res = client.post('/api/transfer', headers=headers, json={
        "receiver": "9876543211@mlbfd",
        "amount": 400.0,
        "payment_pin": "395816",
        "device_id": "device_trusted_1"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert "weighted_score" in data
    assert "final_score" in data
    assert "override_applied" in data
    assert "override_reasons" in data
