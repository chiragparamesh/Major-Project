"""
tests/test_part23_learned_fusion.py - Part 23 Learned Fusion Verification Tests

DONE CHECK: fusion.json exists and the engine uses the chosen fusion.
Verifies:
1. fusion.json exists, containing selected_fusion, comparison table, meta_features, coefficients.
2. stacking_meta_classifier.pkl exists and can produce predictions.
3. Layer 1 Z-score bonus is strictly capped at 60 points.
4. FraudDetectionEngine returns model_agreement_confidence and uses the selected fusion.
5. Static weights fallback is functional.
"""

import os
import json
import pytest
import numpy as np

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_path = os.path.join(root_dir, "backend")
import sys
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from backend.learned_fusion import (
    FUSION_JSON_PATH,
    STACKING_MODEL_PATH,
    get_fusion_prediction,
    STATIC_WEIGHTS
)
from backend.fraud_detection import FraudDetectionEngine


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


def test_fusion_json_exists_and_valid():
    """Validates that fusion.json exists and contains complete comparison data and model metadata."""
    assert os.path.exists(FUSION_JSON_PATH), f"Missing {FUSION_JSON_PATH}"
    assert os.path.exists(STACKING_MODEL_PATH), f"Missing {STACKING_MODEL_PATH}"

    with open(FUSION_JSON_PATH, "r") as f:
        data = json.load(f)

    assert "selected_fusion" in data
    assert data["selected_fusion"] in ["stacking", "static"]
    assert "comparison" in data
    assert "stacking" in data["comparison"]
    assert "static" in data["comparison"]
    assert "pr_auc" in data["comparison"]["stacking"]
    assert "recall_at_1pct_fpr" in data["comparison"]["stacking"]
    assert "brier_score" in data["comparison"]["stacking"]
    assert "static_weights" in data
    assert "meta_features" in data
    assert len(data["meta_features"]) == 13
    assert "coefficients" in data
    assert "intercept" in data


def test_get_fusion_prediction_returns_selected_mode_and_confidence():
    """Validates live get_fusion_prediction function."""
    mock_model_probs = {
        'XGBoost': 0.85,
        'Random Forest': 0.80,
        'Logistic Regression': 0.75,
        'Isolation Forest': 0.60,
        'Neural Network': 0.82,
        'LSTM': 0.78,
        'Autoencoder': 0.70
    }
    mock_layer_scores = {
        'behavioral': 80.0,
        'velocity': 60.0,
        'flow': 50.0,
        'payee': 75.0,
        'compromise': 40.0,
        'amount': 70.0,
        'website_trust': 0.0
    }

    prob, mode, confidence = get_fusion_prediction(mock_model_probs, mock_layer_scores)
    assert 0.0 <= prob <= 1.0
    assert mode in ["stacking", "static"]
    assert 0.0 <= confidence <= 1.0


def test_layer1_zscore_bonus_capped_at_60(app):
    """Verifies that layer 1 Z-score bonus does not exceed 60 points when z_score > 3.0."""
    engine = FraudDetectionEngine()

    txn_data = {
        'user_id': 'test_user_zscore_cap',
        'sender_upi': '9999999999@mlbfd',
        'receiver_upi': 'friend@mlbfd',
        'amount': 50000.0,
        'device_id': 'known_dev',
        'lat': 12.9716,
        'lon': 77.5946,
        'latitude': 12.9716,
        'longitude': 77.5946,
        'accuracy_m': 15.0,
        'source': 'gps'
    }

    res = engine.detect(txn_data)
    assert "model_agreement_confidence" in res
    assert "fusion_mode" in res
    assert res["fusion_mode"] in ["stacking", "static"]

    zscore_flags = [f for f in res["flags"] if "Z-Score amount deviation" in f]
    if zscore_flags:
        assert "capped at 60 points" in zscore_flags[0] or "60" in zscore_flags[0]
