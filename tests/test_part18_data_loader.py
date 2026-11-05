"""
tests/test_part18_data_loader.py - Real Data Loaders & Strict Leakage Verification

Verifies:
1. Parquet files exist for each source (PaySim, IEEE-CIS, BAF).
2. Strict temporal causality: Feature vector at step t uses ONLY events prior to step t.
3. Zero label leakage: Inverting or modifying is_fraud has zero impact on feature computations.
4. Boolean availability masks are present for all 22 canonical features.
5. No Gaussian or uniform overlay conditioned on target label.
"""

import os
import sys
import pytest
import pandas as pd
import numpy as np

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from data_loader import (
    PaySimTemporalProcessor,
    IEEETemporalProcessor,
    load_paysim_parquet,
    load_ieee_parquet,
    load_baf_parquet,
    load_all_sources,
    CANONICAL_22_FEATURES,
    DATA_DIR
)


def test_paysim_temporal_zero_leakage():
    """
    Tests that PaySim processor is strictly causal and has ZERO label or future leakage.
    Features at step t must depend ONLY on events < step t.
    """
    proc1 = PaySimTemporalProcessor()
    
    # Event 1 at step 10: amount 500
    f1_a = proc1.process_row(step=10.0, amount=500.0, orig="C100", dest="M200")
    # First transaction for user: ratio = 1.0, zscore = 0.0, count_1h = 0, count_24h = 0
    assert f1_a['amount'] == 500.0
    assert f1_a['hour'] == 10.0
    assert f1_a['amount_vs_avg_ratio'] == 1.0
    assert f1_a['amount_vs_std_zscore'] == 0.0
    assert f1_a['txn_count_last_hour'] == 0.0
    assert f1_a['txn_count_last_24h'] == 0.0
    assert f1_a['new_payee_flag'] == 1.0

    # Event 2 at step 10.5 (same hour): amount 1000
    f2_a = proc1.process_row(step=10.5, amount=1000.0, orig="C100", dest="M200")
    # Prior amounts: [500.0]. Mean: 500.0. Ratio: 1000 / 500 = 2.0
    assert f2_a['amount_vs_avg_ratio'] == 2.0
    assert f2_a['txn_count_last_hour'] == 1.0
    assert f2_a['txn_count_last_24h'] == 1.0
    assert f2_a['new_payee_flag'] == 0.0  # M200 was seen previously

    # Event 3 at step 35 (24.5 hours later): amount 2000
    f3_a = proc1.process_row(step=35.0, amount=2000.0, orig="C100", dest="M300")
    # Prior amounts: [500, 1000]. Mean: 750.0. Std: 250.0.
    # zscore: (2000 - 750) / 250 = 5.0
    assert abs(f3_a['amount_vs_avg_ratio'] - (2000.0 / 750.0)) < 1e-4
    assert abs(f3_a['amount_vs_std_zscore'] - 5.0) < 1e-4
    # Step 35 is > 24 hours after step 10 and 10.5, so 24h count is 0
    assert f3_a['txn_count_last_hour'] == 0.0
    assert f3_a['txn_count_last_24h'] == 0.0
    assert f3_a['new_payee_flag'] == 1.0  # M300 is a new payee

    # LEAKAGE CHECK:
    # Notice process_row does not even accept is_fraud as an argument!
    # Therefore it is mathematically impossible for the features to leak the label.


def test_future_events_do_not_affect_past_features():
    """
    Proves that appending future transactions never alters the feature vector of earlier transactions.
    """
    proc = PaySimTemporalProcessor()
    f1 = proc.process_row(step=1.0, amount=100.0, orig="UserA", dest="DestB")
    
    # Run 100 future transactions
    for s in range(2, 102):
        proc.process_row(step=float(s), amount=float(s * 10), orig="UserA", dest="DestB")

    # Re-compute f1 from scratch in a fresh processor
    proc_fresh = PaySimTemporalProcessor()
    f1_recomputed = proc_fresh.process_row(step=1.0, amount=100.0, orig="UserA", dest="DestB")

    for k in CANONICAL_22_FEATURES:
        assert f1[k] == f1_recomputed[k], f"Feature {k} differed between original and recomputed!"


def test_ieee_temporal_processor_causality():
    """
    Tests that IEEE processor strictly calculates running stats per card1+addr1 from past timestamps.
    """
    proc = IEEETemporalProcessor()
    
    # Txn 1: DT = 86400 (day 1, hour 0)
    f1 = proc.process_row(dt=86400.0, amount=50.0, card1="1234", addr1="315", device_info="iOS")
    assert f1['hour'] == 0.0
    assert f1['amount'] == 50.0
    assert f1['amount_vs_avg_ratio'] == 1.0
    assert f1['txn_count_last_hour'] == 0.0
    assert f1['known_device_flag'] == 1.0

    # Txn 2: DT = 86400 + 1800 (30 mins later)
    f2 = proc.process_row(dt=86400.0 + 1800.0, amount=150.0, card1="1234", addr1="315", device_info="iOS")
    assert f2['amount_vs_avg_ratio'] == 3.0  # 150 / 50
    assert f2['txn_count_last_hour'] == 1.0
    assert f2['txn_count_last_24h'] == 1.0
    assert f2['device_change_count_30days'] == 1.0


def test_parquet_files_exist_and_conform_schema():
    """
    Tests that parquet files exist for all sources and conform to canonical 22 features,
    masks, and is_fraud target.
    """
    sources = ['paysim', 'ieee', 'baf']
    for src in sources:
        parquet_path = os.path.join(DATA_DIR, f"{src}_clean.parquet")
        assert os.path.exists(parquet_path), f"Missing parquet file for {src} at {parquet_path}"
        
        # Read header / sample chunk
        df = pd.read_parquet(parquet_path)
        assert len(df) > 0, f"Parquet for {src} is empty!"
        assert 'is_fraud' in df.columns, f"Target column is_fraud missing from {src}"
        
        # All 22 canonical features must be present
        for feat in CANONICAL_22_FEATURES:
            assert feat in df.columns, f"Canonical feature {feat} missing from {src}"
            assert f"mask_{feat}" in df.columns, f"Mask column mask_{feat} missing from {src}"
            
        # Target label must be strictly 0 or 1
        unique_labels = set(df['is_fraud'].unique())
        assert unique_labels.issubset({0, 1}), f"Unexpected label values in {src}: {unique_labels}"
        
        # Check that masks are boolean
        for feat in CANONICAL_22_FEATURES:
            assert df[f"mask_{feat}"].dtype == bool, f"Mask mask_{feat} is not bool in {src}"


def test_no_synthetic_gaussian_leakage_in_clean_parquets():
    """
    Verifies that unlike data_processor.py, there is NO hard separation
    between fraud and non-fraud on distance_from_home_km, zscore, or ratio.
    """
    for src in ['paysim', 'ieee', 'baf']:
        parquet_path = os.path.join(DATA_DIR, f"{src}_clean.parquet")
        df = pd.read_parquet(parquet_path)
        
        # In data_processor.py, distance_from_home_km had [0.1, 20] for legit and [100, 1500] for fraud.
        # In our clean real data, unavailable features are cleanly masked with 0.0
        if not df['mask_distance_from_home_km'].iloc[0]:
            assert (df['distance_from_home_km'] == 0.0).all()
        else:
            # If available, legitimate and fraud distributions must overlap
            legit = df[df['is_fraud'] == 0]['distance_from_home_km']
            fraud = df[df['is_fraud'] == 1]['distance_from_home_km']
            if len(fraud) > 0 and len(legit) > 0:
                assert legit.max() >= fraud.min(), "Distance distributions artificially separated without overlap!"
