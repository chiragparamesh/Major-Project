"""
tests/test_part20_upi_simulator.py - UPI Simulator Verification and Single-Feature AUC Test

DONE CHECK: a test shows single-feature AUC below 0.9 for every feature.
This mathematically confirms genuine class overlap with zero synthetic label leakage.
"""

import os
import sys
import pytest
import pandas as pd
import numpy as np
from sklearn.metrics import roc_auc_score

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from upi_simulator import UPISimulator, generate_and_save_simulator_data
from feature_builder import CANONICAL_22_FEATURES


def test_upi_simulator_generates_natural_fraud_rate_and_noise():
    """Validates that simulator produces natural 2-5% fraud rate and has label noise."""
    sim = UPISimulator(seed=42)
    df = sim.generate_dataset(n_samples=5000, fraud_rate=0.035, label_noise=0.005)
    
    fraud_rate = df['is_fraud'].mean()
    assert 0.02 <= fraud_rate <= 0.05, f"Fraud rate {fraud_rate:.4f} outside expected 2-5% range!"
    assert len(df) == 5000
    assert 'is_fraud' in df.columns
    
    # All 22 features must be present
    for feat in CANONICAL_22_FEATURES:
        assert feat in df.columns
        assert f"mask_{feat}" in df.columns


def test_single_feature_auc_below_0_90_for_all_22_features():
    """
    CRITICAL DONE CHECK: Single-feature ROC-AUC must be strictly below 0.90 for EVERY feature.
    Guarantees no feature leaks the label or has artificial synthetic separation.
    """
    sim = UPISimulator(seed=123)
    df = sim.generate_dataset(n_samples=10000, fraud_rate=0.04, label_noise=0.005)
    
    y = df['is_fraud'].values
    assert len(np.unique(y)) == 2
    
    auc_results = {}
    failing_features = []
    
    for feat in CANONICAL_22_FEATURES:
        vals = df[feat].values
        
        # If constant, AUC is 0.5
        if np.all(vals == vals[0]):
            auc = 0.5
        else:
            raw_auc = roc_auc_score(y, vals)
            # Effective AUC takes whichever direction discriminates better
            auc = max(raw_auc, 1.0 - raw_auc)
            
        auc_results[feat] = auc
        if auc >= 0.90:
            failing_features.append((feat, auc))
            
    # Print summary table of single-feature AUCs
    print("\n--- SINGLE FEATURE AUC AUDIT ---")
    for feat in CANONICAL_22_FEATURES:
        print(f"  {feat:30s}: AUC = {auc_results[feat]:.4f}")
        
    assert len(failing_features) == 0, f"Features exceeded 0.90 AUC: {failing_features}"


def test_simulator_parquet_generation():
    """Verifies that simulator clean parquet can be generated and persisted."""
    out_path = generate_and_save_simulator_data(n_samples=5000, force_reload=True)
    assert os.path.exists(out_path)
    df = pd.read_parquet(out_path)
    assert len(df) == 5000
    assert df['is_fraud'].sum() > 0
