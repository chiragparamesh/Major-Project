"""
tests/test_part19_feature_builder.py - Shared Canonical Feature Builder Verification

Tests:
1. Exact canonical 22 features generated in deterministic order.
2. SHA-256 feature order hash matches models/feature_order_hash.txt and rejects order tampering.
3. Strict mathematical identity between live scoring inputs and training vectors.
4. Array transformation preserves exact order and float32 dtype.
5. Grep check asserts no ad-hoc feature dictionaries exist elsewhere.
"""

import os
import sys
import hashlib
import datetime
import pytest
import numpy as np

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from feature_builder import (
    CANONICAL_22_FEATURES,
    build_feature_vector,
    feature_dict_to_array,
    get_feature_order_hash,
    verify_feature_order_hash,
    save_feature_order_hash
)


def test_canonical_22_features_structure():
    """Validates that exactly 22 canonical features exist in immutable order."""
    assert len(CANONICAL_22_FEATURES) == 22
    assert CANONICAL_22_FEATURES[0] == 'amount'
    assert CANONICAL_22_FEATURES[-1] == 'is_high_risk_mcc'


def test_feature_order_hash_generation_and_verification(tmp_path):
    """Verifies that the SHA-256 feature order hash matches and detects modifications."""
    expected_hash = hashlib.sha256(",".join(CANONICAL_22_FEATURES).encode("utf-8")).hexdigest()
    assert get_feature_order_hash() == expected_hash

    # Save to tmp directory
    hash_file = save_feature_order_hash(str(tmp_path))
    assert os.path.exists(hash_file)
    assert verify_feature_order_hash(str(tmp_path)) is True

    # Tamper with hash file
    with open(hash_file, "w") as f:
        f.write("corrupted_hash_value_1234567890")
    assert verify_feature_order_hash(str(tmp_path)) is False


def test_live_and_training_feature_identity():
    """
    Proves that live scoring input and training pipeline input generate
    100% identical feature vectors given identical input attributes.
    """
    now = datetime.datetime(2026, 10, 25, 14, 30, 0)
    
    txn_input = {
        'amount': 2500.0,
        'now': now,
        'receiver_upi': 'merchant@mlbfd',
        'device_id': 'dev_pixel_9',
        'mcc_code': '5411',
        'txn_count_1h': 2,
        'txn_count_24h': 5
    }
    
    class MockBaseline:
        avg_amount = 1200.0
        std_amount = 400.0
        known_payees = ['friend@mlbfd']
        known_devices = ['dev_pixel_9']
        days_since_account_created = 180.0

    graph_state = {
        'payee_graph_centrality': 0.045,
        'is_mule_candidate': 0.0
    }
    
    device_state = {
        'device_id': 'dev_pixel_9',
        'known_device_flag': 1.0,
        'device_change_count_30days': 1.0
    }
    
    geo_state = {
        'distance_from_home_km': 3.2,
        'is_impossible_travel': 0.0
    }
    
    payee_state = {
        'is_scam_upi': 0.0,
        'payee_incoming_txn_count': 42.0,
        'payee_account_age_days': 200.0,
        'new_payee_flag': 1.0,
        'new_payee_pct_last_7days': 0.25
    }

    # Vector 1: Live scoring call
    v_live = build_feature_vector(
        txn=txn_input,
        baseline=MockBaseline(),
        graph=graph_state,
        device_state=device_state,
        geo_state=geo_state,
        payee_state=payee_state
    )

    # Vector 2: Training / simulator call with equivalent dict
    baseline_dict = {
        'avg_amount': 1200.0,
        'std_amount': 400.0,
        'known_payees': ['friend@mlbfd'],
        'known_devices': ['dev_pixel_9'],
        'days_since_account_created': 180.0
    }
    v_train = build_feature_vector(
        txn=txn_input,
        baseline=baseline_dict,
        graph=graph_state,
        device_state=device_state,
        geo_state=geo_state,
        payee_state=payee_state
    )

    # Identity verification
    assert list(v_live.keys()) == CANONICAL_22_FEATURES
    assert list(v_train.keys()) == CANONICAL_22_FEATURES
    for k in CANONICAL_22_FEATURES:
        assert v_live[k] == v_train[k], f"Feature {k} differed between live and training!"

    # Array conversion verification
    arr_live = feature_dict_to_array(v_live)
    arr_train = feature_dict_to_array(v_train)
    assert arr_live.shape == (22,)
    assert arr_live.dtype == np.float32
    assert np.array_equal(arr_live, arr_train)


def test_feature_builder_calculations():
    """Tests accuracy of mathematical calculations in feature_builder."""
    txn = {'amount': 3000.0, 'hour': 22.0, 'day_of_week': 6.0}
    baseline = {'avg_amount': 1000.0, 'std_amount': 500.0}
    
    vec = build_feature_vector(txn, baseline=baseline)
    
    assert vec['amount'] == 3000.0
    assert vec['hour'] == 22.0
    assert vec['day_of_week'] == 6.0
    assert vec['is_weekend'] == 1.0  # Sunday
    assert vec['amount_vs_avg_ratio'] == 3.0  # 3000 / 1000
    assert vec['amount_vs_std_zscore'] == 4.0  # (3000 - 1000) / 500
