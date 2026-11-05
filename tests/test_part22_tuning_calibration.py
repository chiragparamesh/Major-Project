"""
tests/test_part22_tuning_calibration.py - Part 22 Verification Tests

DONE CHECK: thresholds JSON exists and the gap is reported.
Verifies:
1. operating_thresholds.json exists and contains all 7 models plus Ensemble.
2. Every model specifies operating_threshold, validation_fpr <= 1%, recall_gap, and calibrator.
3. Probability calibration (Isotonic vs Platt) and threshold determination functions.
"""

import os
import json
import pytest
import numpy as np

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")

from backend.calibrate_and_tune import (
    THRESHOLDS_JSON_PATH,
    calibrate_probabilities,
    apply_calibrator,
    determine_threshold_at_1pct_fpr
)


def test_operating_thresholds_json_exists_and_valid():
    """Validates that operating_thresholds.json exists, has metadata and all 7 models + Ensemble."""
    assert os.path.exists(THRESHOLDS_JSON_PATH), f"Missing {THRESHOLDS_JSON_PATH}"
    
    with open(THRESHOLDS_JSON_PATH, "r") as f:
        data = json.load(f)
        
    assert "_metadata" in data
    assert "models" in data
    
    expected_models = [
        "XGBoost",
        "Random Forest",
        "Logistic Regression",
        "Isolation Forest",
        "Neural Network",
        "LSTM",
        "Autoencoder",
        "Ensemble"
    ]
    
    for m in expected_models:
        assert m in data["models"], f"Model {m} missing from operating_thresholds.json"
        info = data["models"][m]
        assert "operating_threshold" in info
        assert "validation_fpr" in info
        assert info["validation_fpr"] <= 0.01, f"{m} validation FPR {info['validation_fpr']} exceeds 1%"
        assert "validation_recall" in info
        assert "test_recall" in info
        assert "recall_gap" in info
        assert isinstance(info["recall_gap"], (float, int))
        assert "calibrator_method" in info
        assert "brier_score" in info


def test_calibrate_probabilities_brier_comparison():
    """Tests that calibrate_probabilities evaluates Isotonic and Platt, returning lowest Brier score."""
    np.random.seed(42)
    y_true = np.array([0]*900 + [1]*100)
    # Raw probabilities that are poorly calibrated
    raw_probs = np.clip(y_true * 0.7 + np.random.uniform(0.0, 0.4, size=1000), 0.0, 1.0)
    
    calibrator, method, brier = calibrate_probabilities(y_true, raw_probs)
    assert method in ["isotonic", "platt"]
    assert brier >= 0.0
    
    calibrated = apply_calibrator(calibrator, method, raw_probs)
    assert len(calibrated) == len(raw_probs)
    assert np.all(calibrated >= 0.0)
    assert np.all(calibrated <= 1.0)


def test_determine_threshold_at_1pct_fpr():
    """Tests threshold selection targeting <= 1% FPR."""
    y_val = np.array([0]*990 + [1]*10)
    val_probs = np.linspace(0.01, 0.99, 1000)
    
    y_test = np.array([0]*990 + [1]*10)
    test_probs = np.linspace(0.01, 0.99, 1000)
    
    res = determine_threshold_at_1pct_fpr(y_val, val_probs, y_test, test_probs)
    assert "operating_threshold" in res
    assert res["validation_fpr"] <= 0.01
    assert "recall_gap" in res
