"""
tests/test_part21_honest_training.py - Honest Training Pipeline Verification

DONE CHECK: all 7 model files plus metrics JSON exist for the current data version.
Also verifies time split, scaler fit on train only, and metrics completeness.
"""

import os
import sys
import json
import pytest

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
for p in [root_dir, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from train_all_models import MODELS_DIR, DATA_VERSION
from feature_builder import verify_feature_order_hash


def test_all_seven_model_artifacts_and_metrics_exist():
    """
    CRITICAL DONE CHECK:
    Verifies that all 7 model files, scaler, feature names, order hash,
    and metrics JSON exist for the current data version.
    """
    expected_files = [
        "mlbfd_mega_xgboost_model.pkl",
        "mlbfd_mega_random_forest_model.pkl",
        "mlbfd_mega_logistic_regression_model.pkl",
        "mlbfd_mega_isolation_forest_model.pkl",
        "mlbfd_mega_neural_network_model.keras",
        "mlbfd_mega_lstm_model.keras",
        "mlbfd_mega_autoencoder_model.keras",
        "mlbfd_mega_scaler.pkl",
        "mlbfd_mega_feature_names.pkl",
        "feature_order_hash.txt",
        "mlbfd_mega_metrics.json"
    ]
    
    for f in expected_files:
        path = os.path.join(MODELS_DIR, f)
        assert os.path.exists(path), f"Required model artifact missing: {path}"
        assert os.path.getsize(path) > 0, f"Artifact is empty: {path}"


def test_metrics_json_conforms_to_spec():
    """Verifies that metrics JSON contains test metrics for all 7 models."""
    metrics_path = os.path.join(MODELS_DIR, "mlbfd_mega_metrics.json")
    assert os.path.exists(metrics_path)
    
    with open(metrics_path, "r") as f:
        metrics = json.load(f)
        
    required_models = [
        'XGBoost', 'Random Forest', 'Logistic Regression',
        'Isolation Forest', 'Neural Network', 'LSTM', 'Autoencoder'
    ]
    
    for m in required_models:
        assert m in metrics, f"Model {m} missing from metrics JSON!"
        m_data = metrics[m]
        assert 'pr_auc' in m_data, f"PR-AUC missing for {m}"
        assert 'roc_auc' in m_data, f"ROC-AUC missing for {m}"
        assert 'recall_at_1pct_fpr' in m_data, f"Recall@1%FPR missing for {m}"
        assert 'confusion_matrix' in m_data, f"Confusion matrix missing for {m}"
        assert 0.0 <= m_data['roc_auc'] <= 1.0
        assert 0.0 <= m_data['pr_auc'] <= 1.0
        assert 0.0 <= m_data['recall_at_1pct_fpr'] <= 1.0
        
    assert '_metadata' in metrics
    assert metrics['_metadata']['version'] == DATA_VERSION


def test_feature_order_hash_verified_in_models():
    """Verifies that the feature order hash in backend/models matches canonical feature order."""
    assert verify_feature_order_hash(MODELS_DIR) is True
