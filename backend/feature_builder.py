"""
backend/feature_builder.py - Unified Canonical 22-Feature Builder for MLBFD
"""
import os
import json
import hashlib
import datetime
from typing import Dict, List, Optional, Any, Union
import numpy as np

# Canonical 22 features in immutable order
CANONICAL_22_FEATURES = [
    'amount', 'hour', 'day_of_week', 'is_holiday', 'is_weekend',
    'amount_vs_avg_ratio', 'amount_vs_std_zscore',
    'txn_count_last_hour', 'txn_count_last_24h',
    'new_payee_flag', 'new_payee_pct_last_7days', 'days_since_account_created',
    'known_device_flag', 'device_change_count_30days',
    'payee_incoming_txn_count', 'payee_account_age_days', 'is_scam_upi',
    'distance_from_home_km', 'is_impossible_travel',
    'payee_graph_centrality', 'is_mule_candidate', 'is_high_risk_mcc'
]

FEATURE_ORDER_STRING = ",".join(CANONICAL_22_FEATURES)
FEATURE_ORDER_SHA256 = hashlib.sha256(FEATURE_ORDER_STRING.encode("utf-8")).hexdigest()


def get_feature_order_hash() -> str:
    """Returns the SHA-256 hash of the canonical feature order."""
    return FEATURE_ORDER_SHA256


def save_feature_order_hash(directory: str) -> str:
    """Saves feature_order_hash.txt into the specified model directory."""
    os.makedirs(directory, exist_ok=True)
    hash_path = os.path.join(directory, "feature_order_hash.txt")
    with open(hash_path, "w", encoding="utf-8") as f:
        f.write(FEATURE_ORDER_SHA256)
    return hash_path


def verify_feature_order_hash(directory: str) -> bool:
    """Verifies that the model directory's feature_order_hash.txt matches current canonical order."""
    hash_path = os.path.join(directory, "feature_order_hash.txt")
    if not os.path.exists(hash_path):
        return False
    with open(hash_path, "r", encoding="utf-8") as f:
        stored_hash = f.read().strip()
    return stored_hash == FEATURE_ORDER_SHA256


def _extract_val(container: Any, key: str, default: Any = 0.0) -> Any:
    """Safely extracts value from dict, object attribute, or returns default."""
    if container is None:
        return default
    if isinstance(container, dict):
        return container.get(key, default)
    return getattr(container, key, default)


def build_feature_vector(
    txn: Dict[str, Any],
    baseline: Optional[Any] = None,
    graph: Optional[Any] = None,
    device_state: Optional[Any] = None,
    geo_state: Optional[Any] = None,
    payee_state: Optional[Any] = None
) -> Dict[str, float]:
    """
    Constructs the 22 canonical features in exact order from inputs.
    Used universally by API endpoints (/api/transfer, /api/predict_secure),
    rule engines, simulator, and training pipelines.
    """
    # 1. Amount & Time
    amount = float(_extract_val(txn, 'amount', 0.0))
    
    dt = _extract_val(txn, 'timestamp', None) or _extract_val(txn, 'now', None)
    if isinstance(dt, (datetime.datetime, datetime.date)):
        hour = float(dt.hour)
        day_of_week = float(dt.weekday())
    else:
        hour = float(_extract_val(txn, 'hour', 12.0))
        day_of_week = float(_extract_val(txn, 'day_of_week', 2.0))

    is_holiday = float(_extract_val(txn, 'is_holiday', 1.0 if day_of_week in [5.0, 6.0] else 0.0))
    is_weekend = 1.0 if day_of_week in [5.0, 6.0] else 0.0

    # 2. Behavioral Ratios
    avg_amt = float(_extract_val(baseline, 'avg_amount', 1000.0) or 1000.0)
    std_amt = float(_extract_val(baseline, 'std_amount', 200.0) or 200.0)
    
    ratio = float(amount / avg_amt) if avg_amt > 0 else 1.0
    zscore = float((amount - avg_amt) / std_amt) if std_amt > 1e-4 else 0.0
    ratio = float(np.clip(ratio, 0.01, 100.0))
    zscore = float(np.clip(zscore, -3.0, 20.0))

    # 3. Velocities
    txn_count_1h = float(_extract_val(txn, 'txn_count_last_hour', _extract_val(txn, 'txn_count_1h', 1.0)))
    txn_count_24h = float(_extract_val(txn, 'txn_count_last_24h', _extract_val(txn, 'txn_count_24h', 1.0)))

    # 4. Payee Relationship
    receiver_upi = str(_extract_val(txn, 'receiver_upi', _extract_val(txn, 'receiver', '')))
    known_payees = _extract_val(baseline, 'known_payees', []) or []
    
    if payee_state and 'new_payee_flag' in payee_state:
        new_payee_flag = float(_extract_val(payee_state, 'new_payee_flag', 0.0))
    else:
        new_payee_flag = 0.0 if (receiver_upi and receiver_upi in known_payees) else 1.0

    new_payee_pct_7d = float(_extract_val(payee_state, 'new_payee_pct_last_7days', _extract_val(payee_state, 'new_payee_pct_7d', 0.1)))

    # Account age
    days_acct = float(_extract_val(baseline, 'days_since_account_created', _extract_val(baseline, 'days_since_created', 100.0)))

    # 5. Device
    device_id = str(_extract_val(txn, 'device_id', _extract_val(device_state, 'device_id', '')))
    known_devices = _extract_val(baseline, 'known_devices', []) or []
    
    if device_state and 'known_device_flag' in device_state:
        known_dev = float(_extract_val(device_state, 'known_device_flag', 0.0))
    else:
        known_dev = 1.0 if (device_id and device_id in known_devices) else 0.0

    dev_changes = float(_extract_val(device_state, 'device_change_count_30days', len(known_devices) if known_devices else 1.0))

    # 6. Payee Profile & Scam check
    payee_incoming = float(_extract_val(payee_state, 'payee_incoming_txn_count', _extract_val(payee_state, 'incoming_txn_count', 10.0)))
    payee_age = float(_extract_val(payee_state, 'payee_account_age_days', _extract_val(payee_state, 'account_age_days', 150.0)))
    is_scam = float(_extract_val(payee_state, 'is_scam_upi', 0.0))

    # 7. Geo & Travel
    dist_km = float(_extract_val(geo_state, 'distance_from_home_km', _extract_val(geo_state, 'dist_km', 5.0)))
    imp_travel = float(_extract_val(geo_state, 'is_impossible_travel', 0.0))

    # 8. Network Graph
    centrality = float(_extract_val(graph, 'payee_graph_centrality', _extract_val(graph, 'centrality', 0.01)))
    is_mule = float(_extract_val(graph, 'is_mule_candidate', 0.0))

    # 9. Merchant MCC
    mcc_code = str(_extract_val(txn, 'mcc_code', _extract_val(txn, 'mcc', '')))
    if 'is_high_risk_mcc' in txn:
        is_high_risk = float(txn['is_high_risk_mcc'])
    else:
        is_high_risk = 1.0 if mcc_code in ['7995', '6051', '4829'] else 0.0

    # Assemble vector in strict canonical order
    return {
        'amount': amount,
        'hour': hour,
        'day_of_week': day_of_week,
        'is_holiday': is_holiday,
        'is_weekend': is_weekend,
        'amount_vs_avg_ratio': ratio,
        'amount_vs_std_zscore': zscore,
        'txn_count_last_hour': txn_count_1h,
        'txn_count_last_24h': txn_count_24h,
        'new_payee_flag': new_payee_flag,
        'new_payee_pct_last_7days': new_payee_pct_7d,
        'days_since_account_created': days_acct,
        'known_device_flag': known_dev,
        'device_change_count_30days': dev_changes,
        'payee_incoming_txn_count': payee_incoming,
        'payee_account_age_days': payee_age,
        'is_scam_upi': is_scam,
        'distance_from_home_km': dist_km,
        'is_impossible_travel': imp_travel,
        'payee_graph_centrality': centrality,
        'is_mule_candidate': is_mule,
        'is_high_risk_mcc': is_high_risk
    }


def feature_dict_to_array(feature_dict: Dict[str, float]) -> np.ndarray:
    """Converts feature dict to 1D numpy array in canonical feature order."""
    return np.array([float(feature_dict.get(col, 0.0)) for col in CANONICAL_22_FEATURES], dtype=np.float32)


# Save hash at module load to standard locations
_BACKEND_MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "models"))
if os.path.exists(_BACKEND_MODELS_DIR):
    save_feature_order_hash(_BACKEND_MODELS_DIR)
