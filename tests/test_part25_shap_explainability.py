"""
tests/test_part25_shap_explainability.py - SHAP Explainability & Top-5 Feature Attributions

DONE CHECK: API responses contain the top-5 list and both pages display it. Added latency under 10 ms.
"""

import os
import sys
import time
import json
import pytest

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
for p in [root_dir, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from database import db, User, Transaction, UserBehaviorBaseline
from predictor import (
    get_shap_explainer,
    explain_prediction_shap,
    get_plain_language_reason,
    load_prediction_assets,
    _models_cache
)
from security import hash_pin, encrypt_val, compute_lookup_hash


@pytest.fixture
def app_instance():
    os.environ["SECRET_KEY"] = "test_secret_for_part25"
    os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_for_part25"
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


def test_shap_explainer_cached_and_returns_top5():
    """Verify that get_shap_explainer caches the TreeExplainer and explain_prediction_shap returns top 5."""
    load_prediction_assets()
    explainer1 = get_shap_explainer()
    explainer2 = get_shap_explainer()
    assert explainer1 is not None
    assert explainer1 is explainer2, "TreeExplainer instance must be cached in memory"

    sample_features = {
        "amount": 80000.0,
        "amount_to_avg_ratio": 20.0,
        "is_new_device": 1.0,
        "is_impossible_travel": 1.0,
        "is_scam_upi": 1.0,
        "geo_distance_km": 650.0,
        "hour_of_day": 2.0
    }
    explanations = explain_prediction_shap(sample_features, top_k=5)
    assert isinstance(explanations, list)
    assert len(explanations) == 5

    for item in explanations:
        assert "feature" in item
        assert "label" in item
        assert "shap_value" in item
        assert "feature_value" in item
        assert "impact" in item
        assert item["impact"] in ["increases_risk", "decreases_risk"]
        assert isinstance(item["shap_value"], float)


def test_shap_added_latency_strictly_under_10ms():
    """Verify added latency for SHAP TreeExplainer calculation is strictly < 10 ms."""
    load_prediction_assets()
    get_shap_explainer()  # Warm up

    sample_features = {
        "amount": 5500.0,
        "amount_to_avg_ratio": 4.5,
        "is_new_device": 0.0,
        "velocity_10m": 1.0
    }

    # Run 50 iterations to measure average latency
    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        _ = explain_prediction_shap(sample_features, top_k=5)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    avg_latency = sum(latencies) / len(latencies)
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
    print(f"\n[SHAP Bench] Avg: {avg_latency:.3f} ms, P95: {p95_latency:.3f} ms")
    assert avg_latency < 10.0, f"Average SHAP latency {avg_latency:.3f}ms exceeds 10ms target"


def test_plain_language_reason_generation():
    """Verify get_plain_language_reason produces clear, human-readable summaries."""
    explanations = [
        {"feature": "amount", "label": "Transaction Amount", "shap_value": 1.25, "feature_value": 90000.0, "impact": "increases_risk"},
        {"feature": "is_new_device", "label": "Unrecognized Device", "shap_value": 0.85, "feature_value": 1.0, "impact": "increases_risk"},
        {"feature": "payee_account_age_days", "label": "Payee Account Age", "shap_value": -0.30, "feature_value": 180.0, "impact": "decreases_risk"}
    ]
    blocked_reason = get_plain_language_reason(explanations, status="BLOCKED")
    assert "Risk flagged due to:" in blocked_reason
    assert "Transaction Amount" in blocked_reason

    safe_explanations = [
        {"feature": "is_new_device", "label": "Device Recognition", "shap_value": -0.45, "feature_value": 0.0, "impact": "decreases_risk"},
        {"feature": "geo_distance_km", "label": "Distance From Usual Location", "shap_value": -0.25, "feature_value": 2.0, "impact": "decreases_risk"}
    ]
    safe_reason = get_plain_language_reason(safe_explanations, status="APPROVED")
    assert "normal" in safe_reason.lower() or "baseline" in safe_reason.lower()


def test_api_predict_secure_and_transfer_return_top5(client, app_instance):
    """
    DONE CHECK PART 1:
    API responses (/api/predict_secure and /api/transfer) contain the top-5 list and plain language reason.
    """
    from flask_jwt_extended import create_access_token

    with app_instance.app_context():
        # Create active sender and receiver
        sender = User(
            user_id="shap_sender_01",
            full_name="SHAP Sender",
            phone=encrypt_val("+919876500001"),
            phone_hash=compute_lookup_hash("+919876500001"),
            email=encrypt_val("shapsender@mlbfd.local"),
            email_hash=compute_lookup_hash("shapsender@mlbfd.local"),
            upi_id=encrypt_val("9876500001@mlbfd"),
            upi_hash=compute_lookup_hash("9876500001@mlbfd"),
            login_pin_hash=hash_pin("184920"),
            payment_pin_hash=hash_pin("930182"),
            status="ACTIVE",
            balance=100000.0,
            email_verified=True,
            telegram_verified=True,
            known_devices=["shap_device_01"]
        )
        receiver = User(
            user_id="shap_receiver_01",
            full_name="SHAP Receiver",
            phone=encrypt_val("+919876500002"),
            phone_hash=compute_lookup_hash("+919876500002"),
            email=encrypt_val("shapreceiver@mlbfd.local"),
            email_hash=compute_lookup_hash("shapreceiver@mlbfd.local"),
            upi_id=encrypt_val("9876500002@mlbfd"),
            upi_hash=compute_lookup_hash("9876500002@mlbfd"),
            login_pin_hash=hash_pin("295810"),
            payment_pin_hash=hash_pin("840291"),
            status="ACTIVE",
            balance=100000.0,
            email_verified=True,
            telegram_verified=True
        )
        baseline = UserBehaviorBaseline(
            user_id="shap_sender_01",
            avg_amount=1500.0,
            std_amount=300.0,
            txn_count=15
        )
        db.session.add_all([sender, receiver, baseline])
        db.session.commit()

        token = create_access_token(identity="shap_sender_01")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 1. Test /api/predict_secure
    predict_payload = {
        "receiver_upi": "9876500002@mlbfd",
        "sender_upi": "9876500001@mlbfd",
        "amount": 25000.0,
        "device_id": "shap_device_01",
        "latitude": 12.9716,
        "longitude": 77.5946
    }
    res_predict = client.post("/api/predict_secure", json=predict_payload, headers=headers)
    assert res_predict.status_code == 200
    data_predict = res_predict.get_json()
    assert "top_5_features" in data_predict or "shap_explanations" in data_predict
    top5_p = data_predict.get("top_5_features") or data_predict.get("shap_explanations")
    assert isinstance(top5_p, list)
    assert len(top5_p) <= 5
    assert len(top5_p) > 0
    assert "plain_language_reason" in data_predict
    assert len(data_predict["plain_language_reason"]) > 0

    # 2. Test /api/transfer
    transfer_payload = {
        "receiver": "9876500002@mlbfd",
        "amount": 1200.0,
        "payment_pin": "930182",
        "device_id": "shap_device_01",
        "latitude": 12.9716,
        "longitude": 77.5946
    }
    res_transfer = client.post("/api/transfer", json=transfer_payload, headers=headers)
    assert res_transfer.status_code in [200, 202]
    data_transfer = res_transfer.get_json()
    assert "top_5_features" in data_transfer or "shap_explanations" in data_transfer
    top5_t = data_transfer.get("top_5_features") or data_transfer.get("shap_explanations")
    assert isinstance(top5_t, list)
    assert len(top5_t) <= 5
    assert len(top5_t) > 0
    assert "plain_language_reason" in data_transfer


def test_ui_templates_display_shap_and_plain_language():
    """
    DONE CHECK PART 2:
    Both pages display it:
    - alerts.html displays SHAP horizontal bar chart & feature attributions
    - user_dashboard.html (send screen) displays plain-language engine explanation
    """
    alerts_path = os.path.join(root_dir, "dashboard", "templates", "alerts.html")
    assert os.path.exists(alerts_path)
    with open(alerts_path, "r", encoding="utf-8") as f:
        alerts_html = f.read()

    # Verify SHAP horizontal bar chart in alerts.html
    assert "shap-bar-chart-container" in alerts_html or "SHAP Feature Attributions" in alerts_html
    assert "Increases Risk" in alerts_html
    assert "Decreases Risk" in alerts_html

    user_dash_path = os.path.join(root_dir, "dashboard", "templates", "user_dashboard.html")
    assert os.path.exists(user_dash_path)
    with open(user_dash_path, "r", encoding="utf-8") as f:
        user_html = f.read()

    # Verify plain-language explanation in user_dashboard.html
    assert "plain-language-reason-container" in user_html or "plain-language-reason-text" in user_html
    assert "Engine Explanation" in user_html or "AI Assessment" in user_html

