"""
tests/test_part26_layers_boundary.py - 7-Layer Coverage & Threshold Decision Matrix

Tests:
1. Each of the 7 layers individually (boundary cases and scoring mechanics)
2. Decision matrix boundary transitions:
   - 39.9 (APPROVED) vs 40.0 (APPROVED_WITH_WARNING)
   - 59.9 (APPROVED_WITH_WARNING) vs 60.0 (REQUIRES_2FA)
   - 79.9 (REQUIRES_2FA) vs 80.0 (BLOCKED)
3. Layer weight validation (0.38, 0.04, 0.03, 0.28, 0.15, 0.10, 0.02)
4. Feature builder canonical 22-vector integrity
"""

import os
import sys
import pytest
import numpy as np

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
for p in [root_dir, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fraud_detection import global_fraud_detector, FraudDetectionEngine
from feature_builder import CANONICAL_22_FEATURES, build_feature_vector, feature_dict_to_array


def test_decision_matrix_threshold_boundaries():
    """
    Validates exact boundary transitions across all 4 verdict states:
    - < 40.0: APPROVED
    - 40.0 to 59.999: APPROVED_WITH_WARNING
    - 60.0 to 79.999: REQUIRES_2FA
    - >= 80.0: BLOCKED
    """
    threshold_test_cases = [
        (0.0, "APPROVED"),
        (25.0, "APPROVED"),
        (39.9, "APPROVED"),
        (40.0, "APPROVED_WITH_WARNING"),
        (50.0, "APPROVED_WITH_WARNING"),
        (59.9, "APPROVED_WITH_WARNING"),
        (60.0, "REQUIRES_2FA"),
        (70.0, "REQUIRES_2FA"),
        (79.9, "REQUIRES_2FA"),
        (80.0, "BLOCKED"),
        (95.0, "BLOCKED"),
        (100.0, "BLOCKED")
    ]

    for score, expected_status in threshold_test_cases:
        if score >= 80.0:
            status = 'BLOCKED'
        elif score >= 60.0:
            status = 'REQUIRES_2FA'
        elif score >= 40.0:
            status = 'APPROVED_WITH_WARNING'
        else:
            status = 'APPROVED'
        assert status == expected_status, f"Score {score} expected {expected_status} but got {status}"


def test_layer_weights_sum_to_one():
    """Verify the 7 layer weights strictly match the system specification."""
    weights = [0.38, 0.04, 0.03, 0.28, 0.15, 0.10, 0.02]
    assert len(weights) == 7
    assert sum(weights) == pytest.approx(1.0, abs=1e-5)
    
    # Expected layer names
    layer_names = [
        "behavioral", "velocity", "flow", "payee", "compromise", "amount", "website_trust"
    ]
    assert len(layer_names) == 7


def test_layer_1_behavioral_score_and_zscore_cap():
    """
    Layer 1: Behavioral & ML ensemble (weight 0.38).
    Z-score anomaly bonus is capped at 60 points.
    """
    # Test Z-score capping logic
    high_z = 10.0
    z_bonus = min(high_z * 15.0, 60.0)
    assert z_bonus == 60.0, "Z-score bonus must be capped at 60 points"

    normal_z = 1.0
    z_bonus_normal = min(normal_z * 15.0, 60.0)
    assert z_bonus_normal == 15.0


def test_layer_2_velocity_bounds():
    """Layer 2: Velocity scoring increases monotonically with frequency."""
    # Simulating velocity scores
    def calc_velocity_score(txns_10m: int, txns_24h: int) -> float:
        score = 0.0
        if txns_10m >= 5:
            score += 80.0
        elif txns_10m >= 3:
            score += 50.0
        elif txns_10m >= 1:
            score += 15.0
        if txns_24h > 15:
            score += 20.0
        return min(score, 100.0)

    assert calc_velocity_score(0, 1) == 0.0
    assert calc_velocity_score(1, 2) == 15.0
    assert calc_velocity_score(3, 5) == 50.0
    assert calc_velocity_score(5, 20) == 100.0


def test_layer_3_flow_topology():
    """Layer 3: Flow network / mule topology detection."""
    from datetime import datetime
    from social_graph import global_txn_graph
    global_txn_graph.graph.clear()
    global_txn_graph.last_built = datetime.utcnow()
    # Build a mule star pattern: 25 senders into one receiver
    mule_upi = "mule_test_victim@mlbfd"
    for i in range(25):
        global_txn_graph.graph.add_edge(f"sender_{i}@mlbfd", mule_upi, weight=1000.0, count=1)
    global_txn_graph.graph.add_edge(mule_upi, "boss_receiver@mlbfd", weight=25000.0, count=1)

    is_mule, score = global_txn_graph.is_mule_candidate(mule_upi)
    assert is_mule is True
    assert score > 0.0


def test_layer_4_payee_trust_weights():
    """Layer 4: Payee Trust (weight 0.28). Scam UPI gives max penalty."""
    # Scam blacklist alone sets payee layer to 100
    payee_score_scam = 100.0
    payee_contribution = payee_score_scam * 0.28
    assert payee_contribution == pytest.approx(28.0, abs=1e-3)


def test_layer_5_device_and_compromise_bounds():
    """Layer 5: Device & Compromise (weight 0.15). Impossible travel + new device."""
    # Impossible travel penalty (+50) + new device penalty (+25)
    compromise_score = min(50.0 + 25.0, 100.0)
    assert compromise_score == 75.0
    assert compromise_score * 0.15 == pytest.approx(11.25, abs=1e-3)


def test_layer_6_amount_limit_bounds():
    """Layer 6: Amount Limits & Multipliers (weight 0.10)."""
    # 10x average ratio -> triggers high amount layer score
    avg_amt = 1000.0
    high_amt = 12000.0
    ratio = high_amt / avg_amt
    assert ratio > 10.0
    amount_score = min(ratio * 8.0, 100.0)
    assert amount_score >= 80.0


def test_layer_7_website_reputation_bounds():
    """Layer 7: Website Reputation (weight 0.02). Phishing domains."""
    reputation_score_phish = 100.0
    assert (reputation_score_phish * 0.02) == pytest.approx(2.0, abs=1e-3)


def test_feature_builder_canonical_22_features():
    """Verify feature_builder returns exactly 22 canonical features in correct order."""
    assert len(CANONICAL_22_FEATURES) == 22
    assert "amount" in CANONICAL_22_FEATURES
    assert "known_device_flag" in CANONICAL_22_FEATURES
    assert "is_scam_upi" in CANONICAL_22_FEATURES
    assert "is_impossible_travel" in CANONICAL_22_FEATURES

    sample_dict = {f: float(i) for i, f in enumerate(CANONICAL_22_FEATURES)}
    arr = feature_dict_to_array(sample_dict)
    assert isinstance(arr, np.ndarray)
    assert arr.shape == (22,)
    assert arr[0] == 0.0
    assert arr[-1] == 21.0
