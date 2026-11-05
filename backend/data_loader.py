"""
backend/data_loader.py - Real-data Chunked Loaders with Temporal Graph & Zero Leakage
"""
import os
import sys

# Ensure parent directory is accessible for data directory path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import time
import logging
from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("data_loader")

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
RAW_DATASETS_DIR = r"D:\Major Project\Datasets"

PAYSIM_RAW_PATH = os.path.join(RAW_DATASETS_DIR, "Tier1", "PS_20174392719_1491204439457_log.csv")
IEEE_TXN_PATH = os.path.join(RAW_DATASETS_DIR, "Tier1", "train_transaction.csv")
IEEE_ID_PATH = os.path.join(RAW_DATASETS_DIR, "Tier1", "train_identity.csv")
BAF_BASE_PATH = os.path.join(RAW_DATASETS_DIR, "Tier2", "Base.csv")

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


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


class PaySimTemporalProcessor:
    def __init__(self, history_len: int = 25):
        self.history_len = history_len
        self.user_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_len))
        self.user_payees: Dict[str, set] = defaultdict(set)
        self.user_payee_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_len))
        self.user_first_step: Dict[str, float] = {}
        self.payee_incoming_steps: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_len))
        self.payee_first_step: Dict[str, float] = {}
        self.payee_senders: Dict[str, set] = defaultdict(set)
        self.entity_outbound: Dict[str, set] = defaultdict(set)

    def process_row(self, step: float, amount: float, orig: str, dest: str) -> Dict[str, float]:
        hour = float(step % 24)
        day_of_week = float((step // 24) % 7)
        is_weekend = 1.0 if day_of_week >= 5.0 else 0.0
        is_holiday = 0.0

        history = self.user_history[orig]
        if history:
            amounts = [a for _, a in history]
            mean_amt = float(np.mean(amounts))
            std_amt = float(np.std(amounts)) if len(amounts) >= 2 else 0.0
            ratio = float(amount / mean_amt) if mean_amt > 0 else 1.0
            zscore = float((amount - mean_amt) / std_amt) if std_amt > 1e-4 else 0.0
            zscore = float(np.clip(zscore, -3.0, 15.0))
            ratio = float(np.clip(ratio, 0.01, 50.0))

            cnt_1h = sum(1 for s, _ in history if step - 1.0 <= s < step)
            cnt_24h = sum(1 for s, _ in history if step - 24.0 <= s < step)
        else:
            ratio = 1.0
            zscore = 0.0
            cnt_1h = 0
            cnt_24h = 0

        seen_payees = self.user_payees[orig]
        new_payee_flag = 1.0 if (dest not in seen_payees) else 0.0

        payee_hist_7d = [p for s, p in self.user_payee_history[orig] if step - 168.0 <= s < step]
        if payee_hist_7d:
            first_time_cnt = sum(1 for p in payee_hist_7d if p not in seen_payees)
            new_payee_pct_7d = float(first_time_cnt / len(payee_hist_7d))
        else:
            new_payee_pct_7d = 0.0

        if orig in self.user_first_step:
            days_acct = float((step - self.user_first_step[orig]) / 24.0)
        else:
            days_acct = 0.0

        incoming_txns = float(len(self.payee_incoming_steps[dest]))
        if dest in self.payee_first_step:
            payee_age_days = float((step - self.payee_first_step[dest]) / 24.0)
        else:
            payee_age_days = 0.0

        in_degree = float(len(self.payee_senders[dest]))
        out_degree = float(len(self.entity_outbound[dest]))
        centrality = float(min(1.0, in_degree / 100.0))
        is_mule = 1.0 if (in_degree >= 5.0 and out_degree >= 2.0) else 0.0

        self.user_history[orig].append((step, amount))
        if len(self.user_payees[orig]) < 50:
            self.user_payees[orig].add(dest)
        self.user_payee_history[orig].append((step, dest))
        if orig not in self.user_first_step:
            self.user_first_step[orig] = step

        self.payee_incoming_steps[dest].append(step)
        if len(self.payee_senders[dest]) < 50:
            self.payee_senders[dest].add(orig)
        if len(self.entity_outbound[orig]) < 50:
            self.entity_outbound[orig].add(dest)
        if dest not in self.payee_first_step:
            self.payee_first_step[dest] = step

        return {
            'amount': float(amount),
            'hour': hour,
            'day_of_week': day_of_week,
            'is_holiday': is_holiday,
            'is_weekend': is_weekend,
            'amount_vs_avg_ratio': ratio,
            'amount_vs_std_zscore': zscore,
            'txn_count_last_hour': float(cnt_1h),
            'txn_count_last_24h': float(cnt_24h),
            'new_payee_flag': new_payee_flag,
            'new_payee_pct_last_7days': new_payee_pct_7d,
            'days_since_account_created': days_acct,
            'known_device_flag': 0.0,
            'device_change_count_30days': 0.0,
            'payee_incoming_txn_count': incoming_txns,
            'payee_account_age_days': payee_age_days,
            'is_scam_upi': 0.0,
            'distance_from_home_km': 0.0,
            'is_impossible_travel': 0.0,
            'payee_graph_centrality': centrality,
            'is_mule_candidate': is_mule,
            'is_high_risk_mcc': 0.0
        }


def load_paysim_parquet(max_samples: int = 50000, chunk_size: int = 25000, force_reload: bool = False) -> str:
    ensure_data_dir()
    out_path = os.path.join(DATA_DIR, "paysim_clean.parquet")
    if os.path.exists(out_path) and not force_reload:
        logger.info(f"PaySim parquet already exists at {out_path}. Skipping.")
        return out_path

    logger.info(f"Processing PaySim from {PAYSIM_RAW_PATH} (max_samples={max_samples})...")
    if not os.path.exists(PAYSIM_RAW_PATH):
        raise FileNotFoundError(f"PaySim raw dataset missing at {PAYSIM_RAW_PATH}")

    processor = PaySimTemporalProcessor()
    processed_records = []
    
    total_scanned = 0
    fraud_found = 0
    non_fraud_found = 0

    use_cols = ['step', 'amount', 'nameOrig', 'nameDest', 'isFraud']
    
    for chunk in pd.read_csv(PAYSIM_RAW_PATH, chunksize=chunk_size, usecols=use_cols, low_memory=False):
        for row in chunk.itertuples(index=False):
            step = float(row.step)
            amount = float(row.amount)
            orig = str(row.nameOrig)
            dest = str(row.nameDest)
            is_fraud = int(row.isFraud)

            feats = processor.process_row(step, amount, orig, dest)
            feats['is_fraud'] = is_fraud
            
            if is_fraud == 1:
                processed_records.append(feats)
                fraud_found += 1
            else:
                if non_fraud_found < max_samples and (total_scanned % 15 == 0):
                    processed_records.append(feats)
                    non_fraud_found += 1

            total_scanned += 1
            if len(processed_records) >= max_samples:
                break
        if len(processed_records) >= max_samples:
            break

    df = pd.DataFrame(processed_records)
    
    for col in CANONICAL_22_FEATURES:
        if col in ['known_device_flag', 'device_change_count_30days', 'is_scam_upi',
                    'distance_from_home_km', 'is_impossible_travel', 'is_high_risk_mcc']:
            df[f"mask_{col}"] = False
        else:
            df[f"mask_{col}"] = True
            
    df['source'] = 'paysim'
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved PaySim clean parquet: {df.shape[0]} rows (Frauds: {fraud_found}) to {out_path}")
    return out_path


class IEEETemporalProcessor:
    def __init__(self, history_len: int = 25):
        self.history_len = history_len
        self.account_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_len))
        self.account_devices: Dict[str, set] = defaultdict(set)
        self.account_first_dt: Dict[str, float] = {}

    def process_row(self, dt: float, amount: float, card1: str, addr1: str, device_info: Optional[str]) -> Dict[str, float]:
        acct_key = f"{card1}_{addr1}" if addr1 else str(card1)

        hour = float((dt // 3600) % 24)
        day_of_week = float((dt // 86400) % 7)
        is_weekend = 1.0 if day_of_week in [5.0, 6.0] else 0.0

        hist = self.account_history[acct_key]
        if hist:
            amounts = [a for _, a in hist]
            mean_amt = float(np.mean(amounts))
            std_amt = float(np.std(amounts)) if len(amounts) >= 2 else 0.0
            ratio = float(amount / mean_amt) if mean_amt > 0 else 1.0
            zscore = float((amount - mean_amt) / std_amt) if std_amt > 1e-4 else 0.0
            zscore = float(np.clip(zscore, -3.0, 15.0))
            ratio = float(np.clip(ratio, 0.01, 50.0))

            cnt_1h = sum(1 for t, _ in hist if dt - 3600.0 <= t < dt)
            cnt_24h = sum(1 for t, _ in hist if dt - 86400.0 <= t < dt)
        else:
            ratio = 1.0
            zscore = 0.0
            cnt_1h = 0
            cnt_24h = 0

        if acct_key in self.account_first_dt:
            days_acct = float((dt - self.account_first_dt[acct_key]) / 86400.0)
        else:
            days_acct = 0.0

        known_dev = 1.0 if (device_info and str(device_info).strip() != '' and str(device_info).lower() != 'nan') else 0.0
        seen_devices = self.account_devices[acct_key]
        dev_change_cnt = float(len(seen_devices))

        self.account_history[acct_key].append((dt, amount))
        if acct_key not in self.account_first_dt:
            self.account_first_dt[acct_key] = dt
        if device_info and str(device_info).lower() != 'nan' and len(self.account_devices[acct_key]) < 20:
            self.account_devices[acct_key].add(str(device_info))

        return {
            'amount': float(amount),
            'hour': hour,
            'day_of_week': day_of_week,
            'is_holiday': 0.0,
            'is_weekend': is_weekend,
            'amount_vs_avg_ratio': ratio,
            'amount_vs_std_zscore': zscore,
            'txn_count_last_hour': float(cnt_1h),
            'txn_count_last_24h': float(cnt_24h),
            'new_payee_flag': 0.0,
            'new_payee_pct_last_7days': 0.0,
            'days_since_account_created': days_acct,
            'known_device_flag': known_dev,
            'device_change_count_30days': dev_change_cnt,
            'payee_incoming_txn_count': 0.0,
            'payee_account_age_days': 0.0,
            'is_scam_upi': 0.0,
            'distance_from_home_km': 0.0,
            'is_impossible_travel': 0.0,
            'payee_graph_centrality': 0.0,
            'is_mule_candidate': 0.0,
            'is_high_risk_mcc': 0.0
        }


def load_ieee_parquet(max_samples: int = 50000, chunk_size: int = 25000, force_reload: bool = False) -> str:
    ensure_data_dir()
    out_path = os.path.join(DATA_DIR, "ieee_clean.parquet")
    if os.path.exists(out_path) and not force_reload:
        logger.info(f"IEEE-CIS parquet already exists at {out_path}. Skipping.")
        return out_path

    logger.info(f"Processing IEEE-CIS from {IEEE_TXN_PATH} (max_samples={max_samples})...")
    if not os.path.exists(IEEE_TXN_PATH):
        raise FileNotFoundError(f"IEEE-CIS transaction dataset missing at {IEEE_TXN_PATH}")

    id_map = {}
    if os.path.exists(IEEE_ID_PATH):
        logger.info(f"Loading identity mapping from {IEEE_ID_PATH}...")
        for id_chunk in pd.read_csv(IEEE_ID_PATH, chunksize=chunk_size, usecols=['TransactionID', 'DeviceInfo'], low_memory=False):
            for r in id_chunk.itertuples(index=False):
                id_map[int(r.TransactionID)] = str(r.DeviceInfo)

    processor = IEEETemporalProcessor()
    processed_records = []

    fraud_found = 0
    non_fraud_found = 0
    total_scanned = 0

    use_cols = ['TransactionID', 'isFraud', 'TransactionDT', 'TransactionAmt', 'card1', 'addr1']
    
    for chunk in pd.read_csv(IEEE_TXN_PATH, chunksize=chunk_size, usecols=use_cols, low_memory=False):
        for row in chunk.itertuples(index=False):
            txn_id = int(row.TransactionID)
            is_fraud = int(row.isFraud)
            dt = float(row.TransactionDT)
            amt = float(row.TransactionAmt)
            card1 = str(row.card1)
            addr1 = str(row.addr1) if pd.notnull(row.addr1) else ""
            dev_info = id_map.get(txn_id, None)

            feats = processor.process_row(dt, amt, card1, addr1, dev_info)
            feats['is_fraud'] = is_fraud

            if is_fraud == 1:
                processed_records.append(feats)
                fraud_found += 1
            else:
                if non_fraud_found < max_samples and (total_scanned % 5 == 0):
                    processed_records.append(feats)
                    non_fraud_found += 1

            total_scanned += 1
            if len(processed_records) >= max_samples:
                break
        if len(processed_records) >= max_samples:
            break

    df = pd.DataFrame(processed_records)
    
    for col in CANONICAL_22_FEATURES:
        if col in ['new_payee_flag', 'new_payee_pct_last_7days', 'is_scam_upi',
                    'payee_incoming_txn_count', 'payee_account_age_days',
                    'distance_from_home_km', 'is_impossible_travel', 'payee_graph_centrality',
                    'is_mule_candidate', 'is_high_risk_mcc']:
            df[f"mask_{col}"] = False
        else:
            df[f"mask_{col}"] = True

    df['source'] = 'ieee'
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved IEEE-CIS clean parquet: {df.shape[0]} rows (Frauds: {fraud_found}) to {out_path}")
    return out_path


def load_baf_parquet(max_samples: int = 50000, chunk_size: int = 25000, force_reload: bool = False) -> str:
    ensure_data_dir()
    out_path = os.path.join(DATA_DIR, "baf_clean.parquet")
    if os.path.exists(out_path) and not force_reload:
        logger.info(f"BAF parquet already exists at {out_path}. Skipping.")
        return out_path

    logger.info(f"Processing BAF Base from {BAF_BASE_PATH} (max_samples={max_samples})...")
    if not os.path.exists(BAF_BASE_PATH):
        raise FileNotFoundError(f"BAF Base dataset missing at {BAF_BASE_PATH}")

    processed_records = []
    fraud_found = 0
    non_fraud_found = 0
    total_scanned = 0

    use_cols = ['fraud_bool', 'income', 'customer_age', 'velocity_6h', 'velocity_24h',
                'device_distinct_emails_8w', 'device_os', 'foreign_request', 'phone_home_valid']

    for chunk in pd.read_csv(BAF_BASE_PATH, chunksize=chunk_size, usecols=use_cols, low_memory=False):
        for row in chunk.itertuples(index=False):
            is_fraud = int(row.fraud_bool)
            income = float(getattr(row, 'income', 0.5) or 0.5)
            cust_age = float(getattr(row, 'customer_age', 30.0) or 30.0)
            v6 = float(getattr(row, 'velocity_6h', 0.0) or 0.0)
            v24 = float(getattr(row, 'velocity_24h', 0.0) or 0.0)
            dev_emails = float(getattr(row, 'device_distinct_emails_8w', 1.0) or 1.0)
            foreign = int(getattr(row, 'foreign_request', 0) or 0)
            phone_home = int(getattr(row, 'phone_home_valid', 1) or 1)

            amt = float(income * 10000.0)
            is_mule = 1.0 if (foreign == 1 and phone_home == 0) else 0.0
            known_dev = 1.0 if dev_emails <= 1.0 else 0.0

            feats = {
                'amount': amt,
                'hour': 12.0,
                'day_of_week': 2.0,
                'is_holiday': 0.0,
                'is_weekend': 0.0,
                'amount_vs_avg_ratio': 1.0,
                'amount_vs_std_zscore': 0.0,
                'txn_count_last_hour': float(v6 / 6.0),
                'txn_count_last_24h': float(v24),
                'new_payee_flag': 0.0,
                'new_payee_pct_last_7days': 0.0,
                'days_since_account_created': float(cust_age * 365.0),
                'known_device_flag': known_dev,
                'device_change_count_30days': float(dev_emails),
                'payee_incoming_txn_count': 0.0,
                'payee_account_age_days': 0.0,
                'is_scam_upi': 0.0,
                'distance_from_home_km': 0.0,
                'is_impossible_travel': 0.0,
                'payee_graph_centrality': 0.0,
                'is_mule_candidate': is_mule,
                'is_high_risk_mcc': 0.0,
                'is_fraud': is_fraud
            }

            if is_fraud == 1:
                processed_records.append(feats)
                fraud_found += 1
            else:
                if non_fraud_found < max_samples and (total_scanned % 8 == 0):
                    processed_records.append(feats)
                    non_fraud_found += 1

            total_scanned += 1
            if len(processed_records) >= max_samples:
                break
        if len(processed_records) >= max_samples:
            break

    df = pd.DataFrame(processed_records)
    
    for col in CANONICAL_22_FEATURES:
        if col in ['txn_count_last_hour', 'txn_count_last_24h', 'days_since_account_created',
                    'known_device_flag', 'device_change_count_30days', 'is_mule_candidate']:
            df[f"mask_{col}"] = True
        else:
            df[f"mask_{col}"] = False

    df['source'] = 'baf'
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved BAF clean parquet: {df.shape[0]} rows (Frauds: {fraud_found}) to {out_path}")
    return out_path


def load_all_sources(max_samples_per_source: int = 50000, force_reload: bool = False) -> Dict[str, str]:
    paths = {}
    paths['paysim'] = load_paysim_parquet(max_samples=max_samples_per_source, force_reload=force_reload)
    paths['ieee'] = load_ieee_parquet(max_samples=max_samples_per_source, force_reload=force_reload)
    paths['baf'] = load_baf_parquet(max_samples=max_samples_per_source, force_reload=force_reload)
    return paths


if __name__ == "__main__":
    t0 = time.time()
    print("=== STARTING MLBFD REAL DATA CHUNKED LOADERS ===")
    out_paths = load_all_sources(max_samples_per_source=50000)
    print(f"All loaders completed in {time.time() - t0:.2f}s:")
    for src, p in out_paths.items():
        print(f" - {src}: {p} ({os.path.getsize(p) / (1024*1024):.2f} MB)")
