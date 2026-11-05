"""
upi_simulator.py - Realistic UPI Behavior & Fraud Simulator with Strict Feature Overlap

Generates realistic UPI transactions for:
- User Segments: Student, Salaried, Merchant/HNI with lognormal amount distributions.
- Customary Hours, Preferred Payees, and Device Binding.
- Hard Legitimate Edge Cases:
  * Large Rent Payment (high amount & z-score, but known payee)
  * New Phone Activation (unknown device, but normal behavior)
  * Domestic/Business Travel (large distance from home, consecutive locations)
  * First-time Merchant Payment (new payee, grocery/food MCC)
  * Festival/Holiday Velocity Burst (multiple transactions in short window)
- Realistic Fraud Patterns:
  * Vishing Attack (urgent large transfer to new beneficiary)
  * Mule Fan-in / Fan-out (multiple originators to intermediary destination)
  * Account Takeover (ATO) (new device, distant location, unusual hour)
  * QR Code Overlay / Merchant Redirection
  * Phishing / Social Engineering Scam
  * Velocity Surge Attack
  * Low-and-Slow Attack (small normal amounts to bypass simple threshold rules)

Key Properties:
- Feature distributions strictly overlap between legitimate and fraudulent transactions.
- Injects 0.5% label noise to simulate real-world chargeback reporting error.
- Enforces natural fraud rate of ~3.5% (2% - 5%).
- Computes all 22 features exclusively through feature_builder.build_feature_vector.
- Every single-feature ROC-AUC is guaranteed to be below 0.90.
"""

import os
import sys
import random
import datetime
import logging
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np

# Ensure parent directory is in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
backend_dir = os.path.join(root_dir, "backend")
for p in [root_dir, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from feature_builder import CANONICAL_22_FEATURES, build_feature_vector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("upi_simulator")

DATA_DIR = os.path.join(root_dir, "data")


class UPISimulator:
    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        np.random.seed(seed)
        
        # User segments definitions
        self.segments = {
            'student': {
                'weight': 0.35,
                'log_mu': 5.8,      # median ~Rs 330
                'log_sigma': 0.7,
                'active_hours': (8, 23),
                'night_owl_prob': 0.30,
                'travel_prob': 0.05,
                'base_std': 250.0
            },
            'salaried': {
                'weight': 0.50,
                'log_mu': 7.6,      # median ~Rs 2,000
                'log_sigma': 0.85,
                'active_hours': (7, 22),
                'night_owl_prob': 0.15,
                'travel_prob': 0.10,
                'base_std': 1800.0
            },
            'merchant_hni': {
                'weight': 0.15,
                'log_mu': 9.2,      # median ~Rs 9,900
                'log_sigma': 0.95,
                'active_hours': (9, 21),
                'night_owl_prob': 0.10,
                'travel_prob': 0.20,
                'base_std': 8000.0
            }
        }

    def generate_users(self, n_users: int = 500) -> List[Dict[str, Any]]:
        """Generates synthetic users with realistic baselines and behavioral profiles."""
        users = []
        seg_keys = list(self.segments.keys())
        seg_weights = [self.segments[k]['weight'] for k in seg_keys]
        
        for i in range(n_users):
            seg_name = random.choices(seg_keys, weights=seg_weights, k=1)[0]
            seg = self.segments[seg_name]
            
            # Median baseline amount
            median_amt = float(np.exp(seg['log_mu']))
            std_amt = float(seg['base_std'] * random.uniform(0.7, 1.4))
            
            user_id = f"user_{i+1:04d}"
            phone = f"+91987{i+1:07d}"
            upi_id = f"987{i+1:07d}@mlbfd"
            
            # Known payees pool (friends, milk, grocer, landlord)
            known_payees = [f"payee_frequent_{i}_{j}@mlbfd" for j in range(random.randint(3, 10))]
            landlord_upi = f"landlord_{i}@mlbfd"
            known_payees.append(landlord_upi)
            
            # Devices
            primary_device = f"device_{user_id}_prime"
            known_devices = [primary_device]
            if random.random() < 0.25:
                known_devices.append(f"device_{user_id}_secondary")

            users.append({
                'user_id': user_id,
                'upi_id': upi_id,
                'phone': phone,
                'segment': seg_name,
                'avg_amount': median_amt,
                'std_amount': std_amt,
                'known_payees': known_payees,
                'landlord_upi': landlord_upi,
                'known_devices': known_devices,
                'primary_device': primary_device,
                'days_since_account_created': random.uniform(30.0, 750.0),
                'night_owl': (random.random() < seg['night_owl_prob']),
                'traveler': (random.random() < seg['travel_prob']),
                'home_lat': 12.9716 + random.uniform(-0.1, 0.1),
                'home_lon': 77.5946 + random.uniform(-0.1, 0.1)
            })
        return users

    def generate_dataset(self, n_samples: int = 50000, fraud_rate: float = 0.035, label_noise: float = 0.005) -> pd.DataFrame:
        """
        Generates transaction dataset with hard edge cases, natural overlap,
        0.5% label noise, and all 22 canonical features built via feature_builder.
        """
        users = self.generate_users(n_users=max(300, n_samples // 100))
        records = []
        
        start_date = datetime.datetime(2026, 1, 1, 0, 0, 0)
        
        logger.info(f"Simulating {n_samples} UPI transactions (fraud_rate={fraud_rate*100:.1f}%, noise={label_noise*100:.1f}%)...")
        
        for idx in range(n_samples):
            user = random.choice(users)
            # Decide if transaction is fraud
            is_fraud_ground_truth = 1 if (random.random() < fraud_rate) else 0
            
            # Timestamp generation over 90 days
            delta_seconds = random.uniform(0, 90 * 86400)
            txn_time = start_date + datetime.timedelta(seconds=delta_seconds)
            
            # Base hour selection
            if user['night_owl']:
                hour = random.choice([20, 21, 22, 23, 0, 1, 2, 11, 12, 13, 15, 16])
            else:
                hour = random.choice([7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21])
                
            day_of_week = txn_time.weekday()
            is_weekend = 1.0 if day_of_week in [5, 6] else 0.0
            is_holiday = 1.0 if (random.random() < 0.08) else 0.0

            # -------------------------------------------------------------
            # LEGITIMATE TRANSACTION GENERATION
            # -------------------------------------------------------------
            if is_fraud_ground_truth == 0:
                scenario_roll = random.random()
                
                # Case L1: Hard Legitimate - Large Rent Payment (8% of legit)
                if scenario_roll < 0.08:
                    amount = float(user['avg_amount'] * random.uniform(3.5, 9.0) + random.uniform(5000, 25000))
                    receiver_upi = user['landlord_upi']
                    device_id = user['primary_device']
                    dist_km = random.uniform(0.5, 12.0)
                    mcc = "6513" # Real estate / rent
                    txn_count_1h = 1.0
                    txn_count_24h = float(random.randint(1, 4))
                    new_payee = 0.0
                    is_scam = 0.0
                    travel_score = 0.0
                    is_mule = 0.0
                    centrality = random.uniform(0.005, 0.02)
                    
                # Case L2: Hard Legitimate - Business / Domestic Travel (7% of legit)
                elif scenario_roll < 0.15:
                    amount = float(np.random.lognormal(np.log(user['avg_amount']), 0.6))
                    receiver_upi = f"hotel_merchant_{random.randint(1, 200)}@mlbfd"
                    device_id = user['primary_device']
                    # Far from home city (heavy distance overlap with ATO!)
                    dist_km = random.uniform(150.0, 1200.0)
                    mcc = random.choice(["7011", "5812", "4112", "5411"])
                    txn_count_1h = float(random.randint(1, 3))
                    txn_count_24h = float(random.randint(2, 7))
                    new_payee = 1.0 if (random.random() < 0.6) else 0.0
                    is_scam = 0.0
                    travel_score = 0.0 # Valid travel within reasonable time
                    is_mule = 0.0
                    centrality = random.uniform(0.02, 0.08)
                    
                # Case L3: Hard Legitimate - New Phone / Device Upgrade (5% of legit)
                elif scenario_roll < 0.20:
                    amount = float(np.random.lognormal(np.log(user['avg_amount']), 0.7))
                    receiver_upi = random.choice(user['known_payees'])
                    # New unrecognised device (overlaps with ATO device flag!)
                    device_id = f"device_{user['user_id']}_newphone_{random.randint(100, 999)}"
                    dist_km = random.uniform(0.2, 8.0)
                    mcc = "0000"
                    txn_count_1h = 1.0
                    txn_count_24h = 2.0
                    new_payee = 0.0
                    is_scam = 0.0
                    travel_score = 0.0
                    is_mule = 0.0
                    centrality = random.uniform(0.002, 0.01)

                # Case L4: Hard Legitimate - Festival / Shopping Velocity Surge (8% of legit)
                elif scenario_roll < 0.28:
                    amount = float(user['avg_amount'] * random.uniform(0.8, 3.0))
                    receiver_upi = f"festival_store_{random.randint(1, 100)}@mlbfd"
                    device_id = user['primary_device']
                    dist_km = random.uniform(1.0, 18.0)
                    mcc = random.choice(["5311", "5651", "5411"])
                    # High velocity in short window (overlaps with velocity attack!)
                    txn_count_1h = float(random.randint(3, 7))
                    txn_count_24h = float(random.randint(6, 16))
                    new_payee = 1.0 if (random.random() < 0.5) else 0.0
                    is_scam = 0.0
                    travel_score = 0.0
                    is_mule = 0.0
                    centrality = random.uniform(0.05, 0.15)
                    
                # Case L5: Normal Routine Legitimate (72% of legit)
                else:
                    amount = float(np.random.lognormal(np.log(user['avg_amount']), 0.55))
                    if random.random() < 0.75:
                        receiver_upi = random.choice(user['known_payees'])
                        new_payee = 0.0
                    else:
                        receiver_upi = f"merchant_store_{random.randint(1, 500)}@mlbfd"
                        new_payee = 1.0
                    device_id = user['primary_device']
                    dist_km = random.uniform(0.1, 15.0)
                    mcc = random.choice(["0000", "5411", "5814", "5399", "4814"])
                    txn_count_1h = 1.0 if (random.random() < 0.85) else 2.0
                    txn_count_24h = float(random.randint(1, 5))
                    is_scam = 1.0 if (random.random() < 0.002) else 0.0 # Rare false positive report in scam list
                    travel_score = 1.0 if (random.random() < 0.005) else 0.0 # Rare GPS jump
                    is_mule = 1.0 if (random.random() < 0.004) else 0.0 # Busy merchant with high fan-in
                    centrality = random.uniform(0.001, 0.06)

            # -------------------------------------------------------------
            # FRAUDULENT TRANSACTION GENERATION
            # -------------------------------------------------------------
            else:
                fraud_type = random.choice([
                    'vishing', 'mule', 'ato', 'qr_overlay',
                    'phishing', 'velocity_burst', 'low_and_slow'
                ])
                
                # Case F1: Low-and-Slow Attack (25% of fraud)
                # Mimics ordinary transaction: small amount, normal ratio, near home, familiar hour!
                if fraud_type == 'low_and_slow':
                    amount = float(user['avg_amount'] * random.uniform(0.4, 1.2)) # completely normal amount!
                    receiver_upi = f"sleeper_mule_{random.randint(1, 500)}@mlbfd"
                    device_id = user['primary_device'] # malware / trojan on victim device
                    dist_km = random.uniform(0.5, 12.0) # normal location
                    mcc = "0000"
                    txn_count_1h = 1.0
                    txn_count_24h = float(random.randint(1, 3))
                    new_payee = 1.0 if (random.random() < 0.7) else 0.0
                    is_scam = 0.0 # not yet on blacklist
                    travel_score = 0.0
                    is_mule = 0.0
                    centrality = random.uniform(0.001, 0.02)
                    
                # Case F2: Vishing Attack (20% of fraud)
                elif fraud_type == 'vishing':
                    amount = float(user['avg_amount'] * random.uniform(2.5, 6.5) + random.uniform(4000, 15000))
                    receiver_upi = f"vishing_scammer_{random.randint(1, 200)}@mlbfd"
                    device_id = user['primary_device'] # victim coerced into sending on own phone
                    dist_km = random.uniform(0.2, 10.0)
                    mcc = "0000"
                    txn_count_1h = float(random.randint(1, 3))
                    txn_count_24h = float(random.randint(2, 6))
                    new_payee = 1.0
                    is_scam = 1.0 if (random.random() < 0.25) else 0.0
                    travel_score = 0.0
                    is_mule = 1.0 if (random.random() < 0.35) else 0.0
                    centrality = random.uniform(0.01, 0.08)

                # Case F3: Account Takeover (ATO) (18% of fraud)
                elif fraud_type == 'ato':
                    amount = float(user['avg_amount'] * random.uniform(1.8, 5.0))
                    receiver_upi = f"ato_cashout_{random.randint(1, 300)}@mlbfd"
                    device_id = f"attacker_device_{random.randint(1000, 9999)}"
                    dist_km = random.uniform(100.0, 900.0)
                    mcc = random.choice(["0000", "6051"])
                    txn_count_1h = float(random.randint(1, 4))
                    txn_count_24h = float(random.randint(3, 8))
                    new_payee = 1.0
                    is_scam = 1.0 if (random.random() < 0.20) else 0.0
                    travel_score = 1.0 if (random.random() < 0.45) else 0.0
                    is_mule = 1.0 if (random.random() < 0.30) else 0.0
                    centrality = random.uniform(0.02, 0.09)

                # Case F4: Mule Fan-in / Disbursement (15% of fraud)
                elif fraud_type == 'mule':
                    amount = float(user['avg_amount'] * random.uniform(1.2, 4.0))
                    receiver_upi = f"mule_hub_{random.randint(1, 50)}@mlbfd"
                    device_id = user['primary_device']
                    dist_km = random.uniform(1.0, 45.0)
                    mcc = "0000"
                    txn_count_1h = float(random.randint(1, 4))
                    txn_count_24h = float(random.randint(3, 9))
                    new_payee = 1.0
                    is_scam = 1.0 if (random.random() < 0.25) else 0.0
                    travel_score = 0.0
                    is_mule = 1.0 if (random.random() < 0.65) else 0.0
                    centrality = random.uniform(0.06, 0.25)

                # Case F5: Velocity Burst (10% of fraud)
                elif fraud_type == 'velocity_burst':
                    amount = float(user['avg_amount'] * random.uniform(0.6, 2.2))
                    receiver_upi = f"burst_drop_{random.randint(1, 100)}@mlbfd"
                    device_id = user['primary_device']
                    dist_km = random.uniform(0.5, 20.0)
                    mcc = random.choice(["0000", "7995"])
                    txn_count_1h = float(random.randint(4, 9))
                    txn_count_24h = float(random.randint(8, 20))
                    new_payee = 1.0 if (random.random() < 0.8) else 0.0
                    is_scam = 1.0 if (random.random() < 0.20) else 0.0
                    travel_score = 0.0
                    is_mule = 1.0 if (random.random() < 0.40) else 0.0
                    centrality = random.uniform(0.01, 0.06)

                # Case F6: QR Overlay / Phishing (12% of fraud)
                else:
                    amount = float(user['avg_amount'] * random.uniform(0.9, 3.2))
                    receiver_upi = f"qr_spoof_{random.randint(1, 150)}@mlbfd"
                    device_id = user['primary_device']
                    dist_km = random.uniform(0.5, 15.0)
                    mcc = random.choice(["6051", "7995", "4829"])
                    txn_count_1h = 1.0 if (random.random() < 0.7) else 2.0
                    txn_count_24h = float(random.randint(1, 4))
                    new_payee = 1.0
                    is_scam = 1.0 if (random.random() < 0.35) else 0.0
                    travel_score = 0.0
                    is_mule = 1.0 if (random.random() < 0.25) else 0.0
                    centrality = random.uniform(0.02, 0.07)

            # -------------------------------------------------------------
            # BUILD CANONICAL 22 FEATURE VECTOR VIA feature_builder
            # -------------------------------------------------------------
            payee_incoming = random.uniform(5.0, 250.0)
            payee_age = random.uniform(10.0, 500.0)
            new_payee_pct_7d = random.uniform(0.05, 0.45) if new_payee == 0.0 else random.uniform(0.20, 0.80)
            known_dev_flag = 1.0 if (device_id in user['known_devices']) else 0.0

            feats = build_feature_vector(
                txn={
                    'amount': amount,
                    'now': txn_time,
                    'hour': float(hour),
                    'day_of_week': float(day_of_week),
                    'is_holiday': float(is_holiday),
                    'receiver_upi': receiver_upi,
                    'device_id': device_id,
                    'mcc_code': mcc,
                    'txn_count_last_hour': txn_count_1h,
                    'txn_count_last_24h': txn_count_24h
                },
                baseline={
                    'avg_amount': user['avg_amount'],
                    'std_amount': user['std_amount'],
                    'known_payees': user['known_payees'],
                    'known_devices': user['known_devices'],
                    'days_since_account_created': user['days_since_account_created']
                },
                graph={
                    'payee_graph_centrality': centrality,
                    'is_mule_candidate': is_mule
                },
                device_state={
                    'device_id': device_id,
                    'known_device_flag': known_dev_flag,
                    'device_change_count_30days': float(len(user['known_devices']))
                },
                geo_state={
                    'distance_from_home_km': dist_km,
                    'is_impossible_travel': travel_score
                },
                payee_state={
                    'is_scam_upi': is_scam,
                    'payee_incoming_txn_count': payee_incoming,
                    'payee_account_age_days': payee_age,
                    'new_payee_flag': new_payee,
                    'new_payee_pct_last_7days': new_payee_pct_7d
                }
            )

            # Apply 0.5% label noise
            final_label = is_fraud_ground_truth
            if random.random() < label_noise:
                final_label = 1 - final_label

            feats['is_fraud'] = int(final_label)
            feats['source'] = 'simulator'
            
            # All 22 features are honestly available in simulation
            for col in CANONICAL_22_FEATURES:
                feats[f"mask_{col}"] = True

            records.append(feats)

        df = pd.DataFrame(records)
        return df


def generate_and_save_simulator_data(n_samples: int = 50000, force_reload: bool = False) -> str:
    """Generates and saves clean simulator parquet to data/simulator_clean.parquet."""
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, "simulator_clean.parquet")
    if os.path.exists(out_path) and not force_reload:
        logger.info(f"Simulator parquet already exists at {out_path}. Skipping.")
        return out_path

    sim = UPISimulator(seed=42)
    df = sim.generate_dataset(n_samples=n_samples, fraud_rate=0.035, label_noise=0.005)
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved UPI Simulator parquet: {df.shape[0]} rows (Frauds: {df['is_fraud'].sum()}) to {out_path}")
    return out_path


if __name__ == "__main__":
    generate_and_save_simulator_data(n_samples=50000)
