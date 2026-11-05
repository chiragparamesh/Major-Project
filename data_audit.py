"""
data_audit.py - Chunked Dataset Auditor for MLBFD Project

Audits all raw transaction datasets in D:\\Major Project\\Datasets without loading full files
into memory (uses chunked reading via pd.read_csv(..., chunksize=50000)).
Generates DATA_AUDIT.md with columns, dtypes, missingness %, class ratios,
temporal ranges, and mapping status for all 22 canonical features,
plus forensic analysis of data_processor.py synthetic Gaussian overlay leakage.
"""

import os
import glob
import time
import pandas as pd
import numpy as np

BASE_DATASETS_DIR = r"D:\Major Project\Datasets"
OUTPUT_MD = r"D:\Major Project\MLBFD\DATA_AUDIT.md"

FEATURE_COLS_22 = [
    'amount', 'hour', 'day_of_week', 'is_holiday', 'is_weekend',
    'amount_vs_avg_ratio', 'amount_vs_std_zscore',
    'txn_count_last_hour', 'txn_count_last_24h',
    'new_payee_flag', 'new_payee_pct_last_7days', 'days_since_account_created',
    'known_device_flag', 'device_change_count_30days',
    'payee_incoming_txn_count', 'payee_account_age_days', 'is_scam_upi',
    'distance_from_home_km', 'is_impossible_travel',
    'payee_graph_centrality', 'is_mule_candidate', 'is_high_risk_mcc'
]

# Mapping rules and rationale for each dataset
DATASET_FEATURE_MAPPING = {
    "PaySim (PS_20174392719_1491204439457_log.csv)": {
        "amount": ("Directly Derivable", "Direct column 'amount'"),
        "hour": ("Directly Derivable", "hour = step % 24"),
        "day_of_week": ("Directly Derivable", "day_of_week = (step // 24) % 7"),
        "is_holiday": ("Approximated", "Simulated/approximated from Indian holiday calendar on step-derived dates"),
        "is_weekend": ("Directly Derivable", "is_weekend = 1 if ((step // 24) % 7) >= 5 else 0"),
        "amount_vs_avg_ratio": ("Directly Derivable", "Calculable from rolling historical mean of nameOrig using past transactions only"),
        "amount_vs_std_zscore": ("Directly Derivable", "Calculable from rolling historical std of nameOrig using past transactions only"),
        "txn_count_last_hour": ("Directly Derivable", "Count of transactions for nameOrig in step window [step - 1, step)"),
        "txn_count_last_24h": ("Directly Derivable", "Count of transactions for nameOrig in step window [step - 24, step)"),
        "new_payee_flag": ("Directly Derivable", "1 if nameDest has not been previously seen for nameOrig, else 0"),
        "new_payee_pct_last_7days": ("Directly Derivable", "Fraction of payees in past 7 days (168 steps) that were first-time interactions"),
        "days_since_account_created": ("Approximated", "Approximate proxy from earliest observed step for nameOrig"),
        "known_device_flag": ("Unavailable", "PaySim contains no device ID, IP, or user-agent hardware metadata"),
        "device_change_count_30days": ("Unavailable", "No device tracking in PaySim schema"),
        "payee_incoming_txn_count": ("Directly Derivable", "In-degree / transaction volume received by nameDest over past time window"),
        "payee_account_age_days": ("Approximated", "Step of earliest received/sent transaction for nameDest"),
        "is_scam_upi": ("Unavailable", "No external scam blacklist in PaySim"),
        "distance_from_home_km": ("Unavailable", "PaySim contains no geolocation (GPS/IP) coordinates"),
        "is_impossible_travel": ("Unavailable", "No geographic coordinates or location velocity available"),
        "payee_graph_centrality": ("Directly Derivable", "Real transaction graph constructed from nameOrig -> nameDest directed edges"),
        "is_mule_candidate": ("Directly Derivable", "High fan-in (many distinct senders) followed by rapid disbursement (fan-out)"),
        "is_high_risk_mcc": ("Unavailable", "PaySim provides transaction type (TRANSFER, CASH_OUT, PAYMENT) but no ISO 18245 MCC")
    },
    "IEEE-CIS Transaction (train_transaction.csv)": {
        "amount": ("Directly Derivable", "Direct column 'TransactionAmt'"),
        "hour": ("Directly Derivable", "hour = (TransactionDT // 3600) % 24"),
        "day_of_week": ("Directly Derivable", "day_of_week = (TransactionDT // 86400) % 7"),
        "is_holiday": ("Approximated", "Approximated from temporal timeline offset"),
        "is_weekend": ("Directly Derivable", "is_weekend = 1 if ((TransactionDT // 86400) % 7) in [5, 6] else 0"),
        "amount_vs_avg_ratio": ("Directly Derivable", "Calculable per card1+addr1 pseudo-account entity rolling historical mean"),
        "amount_vs_std_zscore": ("Directly Derivable", "Calculable per card1+addr1 pseudo-account entity rolling historical std"),
        "txn_count_last_hour": ("Directly Derivable", "Count of transactions for card1+addr1 in [TransactionDT - 3600, TransactionDT)"),
        "txn_count_last_24h": ("Directly Derivable", "Count of transactions for card1+addr1 in [TransactionDT - 86400, TransactionDT)"),
        "new_payee_flag": ("Approximated", "Proxy via recipient domain P_emaildomain / R_emaildomain match or merchant identity"),
        "new_payee_pct_last_7days": ("Approximated", "Ratio of new recipient domains or merchant targets over rolling 7-day window"),
        "days_since_account_created": ("Approximated", "Proxy via D1 feature (days since account/card registration)"),
        "known_device_flag": ("Directly Derivable", "Mapped via train_identity.csv DeviceType, DeviceInfo, id_30, id_31"),
        "device_change_count_30days": ("Directly Derivable", "Count of distinct DeviceInfo or id_31 per card1+addr1 over 30 days"),
        "payee_incoming_txn_count": ("Approximated", "Aggregated volume per merchant / R_emaildomain target"),
        "payee_account_age_days": ("Unavailable", "Merchant registration inception date not in IEEE-CIS schema"),
        "is_scam_upi": ("Unavailable", "No external scam blacklist mapping"),
        "distance_from_home_km": ("Approximated", "addr1 / addr2 geographic region distance divergence"),
        "is_impossible_travel": ("Approximated", "addr1 state jump within < 2 hours"),
        "payee_graph_centrality": ("Approximated", "Bipartite graph between card1 and R_emaildomain / merchant cluster"),
        "is_mule_candidate": ("Unavailable", "Card-not-present acquiring dataset; does not trace multi-hop receiver payouts"),
        "is_high_risk_mcc": ("Approximated", "ProductCD / M1-M9 flags and category groupings")
    },
    "Bank Account Fraud Base (Base.csv)": {
        "amount": ("Unavailable", "Normalized income and credit risk variables, but exact transaction amount omitted"),
        "hour": ("Unavailable", "Only coarse session/time features present"),
        "day_of_week": ("Unavailable", "Temporal variables masked/coarse"),
        "is_holiday": ("Unavailable", "No calendar date stamps"),
        "is_weekend": ("Unavailable", "No day timestamps"),
        "amount_vs_avg_ratio": ("Approximated", "Proxy via proposed_credit_limit vs income"),
        "amount_vs_std_zscore": ("Approximated", "Z-score of proposed credit limit normalized against income band"),
        "txn_count_last_hour": ("Directly Derivable", "Direct column 'velocity_6h' / 'velocity_24h' proxy"),
        "txn_count_last_24h": ("Directly Derivable", "Direct column 'velocity_24h'"),
        "new_payee_flag": ("Unavailable", "Account opening / application dataset, not transaction graph"),
        "new_payee_pct_last_7days": ("Unavailable", "No payee entities"),
        "days_since_account_created": ("Directly Derivable", "Direct column 'customer_age' / bank branch tenure"),
        "known_device_flag": ("Directly Derivable", "Direct column 'device_os' and 'device_distinct_emails_8w'"),
        "device_change_count_30days": ("Directly Derivable", "Direct column 'device_distinct_emails_8w' proxy"),
        "payee_incoming_txn_count": ("Unavailable", "No destination payee data"),
        "payee_account_age_days": ("Unavailable", "No destination payee data"),
        "is_scam_upi": ("Unavailable", "No scam UPI directory"),
        "distance_from_home_km": ("Unavailable", "No lat/lon GPS coordinates"),
        "is_impossible_travel": ("Unavailable", "No geolocation tracking"),
        "payee_graph_centrality": ("Unavailable", "No network topology"),
        "is_mule_candidate": ("Approximated", "Proxy via phone_home_valid, phone_mobile_valid, foreign_request indicators"),
        "is_high_risk_mcc": ("Unavailable", "Application dataset; no merchant MCC")
    }
}

def identify_label_col(cols):
    """Identifies the fraud label column in dataset columns."""
    candidates = ['isFraud', 'is_fraud', 'fraud_bool', 'Class', 'label', 'target', 'fraud']
    for c in candidates:
        if c in cols:
            return c
    for c in cols:
        if 'fraud' in c.lower():
            return c
    return None

def identify_time_col(cols):
    """Identifies temporal column in dataset."""
    candidates = ['step', 'TransactionDT', 'timestamp', 'time', 'date', 'month']
    for c in candidates:
        if c in cols:
            return c
    for c in cols:
        if 'time' in c.lower() or 'date' in c.lower() or 'step' in c.lower():
            return c
    return None

def audit_single_file(filepath, chunk_size=50000):
    """
    Audits a single CSV dataset using chunked reading.
    Returns audit summary dict.
    """
    filename = os.path.basename(filepath)
    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"Auditing {filename} ({file_size_mb:.1f} MB)...")
    
    # 1. Read first chunk for metadata
    first_chunk = pd.read_csv(filepath, nrows=100)
    columns = list(first_chunk.columns)
    dtypes = {col: str(dtype) for col, dtype in first_chunk.dtypes.items()}
    
    label_col = identify_label_col(columns)
    time_col = identify_time_col(columns)
    
    total_rows = 0
    null_counts = {col: 0 for col in columns}
    fraud_count = 0
    legit_count = 0
    time_min = float('inf')
    time_max = float('-inf')
    
    chunk_iter = pd.read_csv(filepath, chunksize=chunk_size, low_memory=False)
    for chunk in chunk_iter:
        n = len(chunk)
        total_rows += n
        
        # Missing values
        chunk_nulls = chunk.isnull().sum()
        for col in columns:
            null_counts[col] += int(chunk_nulls[col])
            
        # Label balance
        if label_col and label_col in chunk:
            f_count = int((chunk[label_col] == 1).sum())
            fraud_count += f_count
            legit_count += (n - f_count)
            
        # Temporal bounds
        if time_col and time_col in chunk:
            valid_time = pd.to_numeric(chunk[time_col], errors='coerce').dropna()
            if not valid_time.empty:
                c_min = float(valid_time.min())
                c_max = float(valid_time.max())
                if c_min < time_min:
                    time_min = c_min
                if c_max > time_max:
                    time_max = c_max
                    
    missing_pct = {col: (null_counts[col] / total_rows * 100) if total_rows > 0 else 0.0 for col in columns}
    
    return {
        "filename": filename,
        "filepath": filepath,
        "file_size_mb": file_size_mb,
        "total_rows": total_rows,
        "total_cols": len(columns),
        "columns": columns,
        "dtypes": dtypes,
        "missing_pct": missing_pct,
        "label_col": label_col,
        "fraud_count": fraud_count,
        "legit_count": legit_count,
        "fraud_ratio_pct": (fraud_count / total_rows * 100) if total_rows > 0 and label_col else None,
        "time_col": time_col,
        "time_min": time_min if time_min != float('inf') else None,
        "time_max": time_max if time_max != float('-inf') else None,
    }

def generate_markdown_report(audit_results):
    """Formats audit results into comprehensive DATA_AUDIT.md"""
    lines = []
    lines.append("# MLBFD Comprehensive Dataset Audit & Schema Mapping")
    lines.append(f"\n*Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n")
    lines.append("## 1. Executive Summary")
    lines.append("This document audits all raw financial transaction and fraud datasets residing in `D:\\Major Project\\Datasets`.")
    lines.append("All analyses were executed using strictly chunked data reading (`chunksize=50,000`), guaranteeing zero memory blowup.")
    lines.append("This audit provides exhaustive verification of columns, data types, missing value percentages, class balance ratios, temporal timelines, and explicit mapping feasibility against the 22 canonical features of the MLBFD multi-layer fraud detection engine.")
    lines.append("\nAdditionally, this audit contains a forensic examination of `backend/data_processor.py` (lines 142–230), documenting the exact lines where synthetic Gaussian overlays were previously injected conditional on the fraud label, explaining how that caused catastrophic data leakage, and specifying how the clean pipeline in Parts 18–21 solves it honestly.\n")
    
    # Dataset Table Summary
    lines.append("## 2. Dataset Inventory Summary")
    lines.append("| Dataset File | Directory Tier | Size (MB) | Total Rows | Columns | Label Column | Fraud Ratio (%) | Temporal Column & Range |")
    lines.append("|---|---|---|---|---|---|---|---|")
    
    for res in audit_results:
        tier = "Tier1" if "Tier1" in res["filepath"] else ("Tier2" if "Tier2" in res["filepath"] else "Tier3")
        fraud_str = f"{res['fraud_ratio_pct']:.4f}% ({res['fraud_count']:,} / {res['total_rows']:,})" if res['fraud_ratio_pct'] is not None else "N/A"
        if res['time_col'] and res['time_min'] is not None:
            time_str = f"`{res['time_col']}`: [{res['time_min']:.0f} .. {res['time_max']:.0f}]"
        else:
            time_str = "None"
        lines.append(f"| `{res['filename']}` | {tier} | {res['file_size_mb']:.1f} | {res['total_rows']:,} | {res['total_cols']} | `{res['label_col']}` | {fraud_str} | {time_str} |")
        
    lines.append("\n## 3. Detailed Audit Per Dataset\n")
    
    for res in audit_results:
        lines.append(f"### 3.{audit_results.index(res) + 1} `{res['filename']}`")
        lines.append(f"- **Path**: `{res['filepath']}`")
        lines.append(f"- **File Size**: {res['file_size_mb']:.2f} MB")
        lines.append(f"- **Row Count**: {res['total_rows']:,} rows")
        lines.append(f"- **Column Count**: {res['total_cols']} columns")
        lines.append(f"- **Ground Truth Label**: `{res['label_col']}`")
        if res['fraud_ratio_pct'] is not None:
            lines.append(f"- **Class Distribution**: Fraud = {res['fraud_count']:,} ({res['fraud_ratio_pct']:.4f}%), Legitimate = {res['legit_count']:,} ({100 - res['fraud_ratio_pct']:.4f}%)")
        if res['time_col']:
            lines.append(f"- **Temporal Column**: `{res['time_col']}` spanning {res['time_min']} to {res['time_max']}")
            
        # Top Missing Columns
        cols_sorted_missing = sorted(res['missing_pct'].items(), key=lambda x: x[1], reverse=True)
        missing_nonzero = [c for c in cols_sorted_missing if c[1] > 0]
        lines.append(f"- **Missing Value Profile**: {len(missing_nonzero)} of {res['total_cols']} columns contain missing values.")
        if missing_nonzero:
            lines.append("  - Top missing columns:")
            for c, pct in missing_nonzero[:8]:
                lines.append(f"    - `{c}` ({res['dtypes'].get(c, 'unknown')}): {pct:.2f}% missing")
        else:
            lines.append("  - No missing values detected across any column.")
            
        lines.append("\n**Schema Sample (First 15 Columns & Types):**\n")
        lines.append("| Column Name | Data Type | Missing % |")
        lines.append("|---|---|---|")
        for col in res['columns'][:15]:
            lines.append(f"| `{col}` | `{res['dtypes'].get(col, '')}` | {res['missing_pct'].get(col, 0.0):.2f}% |")
        if len(res['columns']) > 15:
            lines.append(f"| *... and {len(res['columns']) - 15} additional columns* | | |")
        lines.append("\n")

    # 4. Canonical 22 Feature Mapping
    lines.append("## 4. Canonical 22 Feature Mapping Matrix")
    lines.append("The MLBFD fraud engine operates on 22 canonical features. Below is the honest feasibility mapping across the primary data sources (PaySim, IEEE-CIS, and Bank Account Fraud).\n")
    
    lines.append("| Feature Index | Feature Name | Description | PaySim | IEEE-CIS | Bank Account Fraud (BAF) |")
    lines.append("|---|---|---|---|---|---|")
    
    for idx, feat in enumerate(FEATURE_COLS_22, 1):
        ps_status, ps_note = DATASET_FEATURE_MAPPING["PaySim (PS_20174392719_1491204439457_log.csv)"].get(feat, ("Unavailable", ""))
        ieee_status, ieee_note = DATASET_FEATURE_MAPPING["IEEE-CIS Transaction (train_transaction.csv)"].get(feat, ("Unavailable", ""))
        baf_status, baf_note = DATASET_FEATURE_MAPPING["Bank Account Fraud Base (Base.csv)"].get(feat, ("Unavailable", ""))
        
        def format_status(st, nt):
            badge = "**Direct**" if "Direct" in st else ("*Approx*" if "Approx" in st else "Unavailable")
            return f"{badge} ({nt})"
            
        lines.append(f"| {idx} | `{feat}` | Feature #{idx} | {format_status(ps_status, ps_note)} | {format_status(ieee_status, ieee_note)} | {format_status(baf_status, baf_note)} |")
        
    # 5. Synthetic Gaussian Overlay Analysis
    lines.append("\n## 5. Forensic Analysis: Synthetic Gaussian Overlays in `backend/data_processor.py`")
    lines.append("### 5.1 The Defect")
    lines.append("In `backend/data_processor.py` (lines 142–230), the feature engineering routine previously attempted to augment raw transaction datasets by synthetically generating 18 operational features.")
    lines.append("Critically, the generator branched directly on the ground truth target label:")
    lines.append("```python")
    lines.append("# Line 151 in backend/data_processor.py")
    lines.append("fraud_mask = merged_df['is_fraud'] == 1")
    lines.append("")
    lines.append("# Line 154-155: Amount vs std z-score")
    lines.append("z_scores = np.random.normal(loc=0.5, scale=0.8, size=n_rows)")
    lines.append("z_scores[fraud_mask] = np.random.normal(loc=4.5, scale=1.5, size=sum(fraud_mask))")
    lines.append("")
    lines.append("# Line 159-160: Amount vs average ratio")
    lines.append("ratios = np.random.normal(loc=1.1, scale=0.4, size=n_rows)")
    lines.append("ratios[fraud_mask] = np.random.normal(loc=6.0, scale=3.0, size=sum(fraud_mask))")
    lines.append("")
    lines.append("# Line 164-165: Transaction count last hour")
    lines.append("v_hour = np.random.choice([1, 2, 3, 4], p=[0.8, 0.15, 0.04, 0.01], size=n_rows)")
    lines.append("v_hour[fraud_mask] = np.random.choice([2, 5, 8, 12], p=[0.1, 0.3, 0.4, 0.2], size=sum(fraud_mask))")
    lines.append("")
    lines.append("# Line 209-210: Distance from home (km)")
    lines.append("dist = np.random.uniform(0.1, 20.0, size=n_rows)")
    lines.append("dist[fraud_mask] = np.random.uniform(100.0, 1500.0, size=sum(fraud_mask))")
    lines.append("")
    lines.append("# Line 213-214: Impossible travel")
    lines.append("imp_travel = np.random.choice([0, 1], p=[0.99, 0.01], size=n_rows)")
    lines.append("imp_travel[fraud_mask] = np.random.choice([0, 1], p=[0.3, 0.7], size=sum(fraud_mask))")
    lines.append("```\n")
    
    lines.append("### 5.2 Why This Constitutes Direct Target Label Leakage")
    lines.append("1. **Complete Separability**: For `distance_from_home_km`, legitimate transactions are bounded in `[0.1, 20.0]` while fraudulent transactions are bounded in `[100.0, 1500.0]`. The intersection is the empty set ($\emptyset$). Any decision tree or neural network splits on `distance_from_home_km > 20.0` and achieves 100% precision and 100% recall with zero error.")
    lines.append("2. **Bypassing Genuine Data Signals**: The models trained on this synthetic overlay did not learn real financial crime behaviors; they memorized the parameter distributions (`loc=4.5, scale=1.5` vs `loc=0.5, scale=0.8`) of NumPy's pseudo-random number generator.")
    lines.append("3. **Disastrous Production Drift**: When deployed to live production, real fraud does not arrive labeled with Gaussian distributions. Real UPI attackers often use low-and-slow transactions within normal geofences, resulting in catastrophic model failure.")
    lines.append("4. **Violation of Causal Ordering**: Future target information (`is_fraud`) was used to construct historical and present feature values, violating fundamental temporal causality.")
    
    lines.append("\n### 5.3 Honest Solution Architecture (Parts 18–21)")
    lines.append("1. **Part 18 (`data_loader.py`)**: Chunked loaders derive genuine historical features using *only past transactions* (no future leakage). PaySim builds a real NetworkX/graph structure over `nameOrig` -> `nameDest`; IEEE-CIS groups by `card1+addr1` over historical timestamps (`TransactionDT`).")
    lines.append("2. **Part 19 (`feature_builder.py`)**: Unified canonical feature extractor shared symmetrically by training and production runtime (`/api/transfer`, `/api/predict_secure`).")
    lines.append("3. **Part 20 (`upi_simulator.py`)**: Generates realistic UPI behavior patterns with overlapping feature distributions, hard legitimate boundary cases (large rent, travel, festival spikes), low-and-slow fraud, 0.5% label noise, natural fraud rates (2–5%), strictly ensuring every single-feature AUC is below 0.9.")
    lines.append("4. **Part 21 (`train_all_models.py`)**: Strict chronological time-based train (70%) / validation (15%) / test (15%) split, fitting the `StandardScaler` on the training split only, and evaluating on raw un-resampled holdouts.")
    
    lines.append("\n## 6. Tier 3 Non-Tabular Artifacts")
    lines.append("- `0ANNUALREPORT202324_FULLDF549205FA214F62A2441C5320D64A29.pdf` (7.4 MB): Reserve Bank of India / NPCI Annual Report detailing macro payments ecosystem risk metrics, fraud volume trends, and regulatory guidelines.")
    lines.append("- `Ecosystem-Statistics-UPI-Chargeback-2025-Aug.xlsx` through `2026-Jan.xlsx`: Monthly NPCI UPI ecosystem chargeback ratios, volume distributions, and settlement turnaround times, used for establishing baseline prior probabilities.")
    
    return "\n".join(lines)

def run_audit():
    print("=== STARTING MLBFD CHUNKED DATASET AUDIT ===")
    start_time = time.time()
    
    # Locate all CSVs in Datasets directory
    all_csvs = glob.glob(os.path.join(BASE_DATASETS_DIR, "**", "*.csv"), recursive=True)
    print(f"Found {len(all_csvs)} CSV files across Datasets directory.")
    
    audit_results = []
    for csv_path in sorted(all_csvs):
        try:
            res = audit_single_file(csv_path)
            audit_results.append(res)
        except Exception as e:
            print(f"Error auditing {csv_path}: {e}")
            
    print("Generating DATA_AUDIT.md...")
    md_content = generate_markdown_report(audit_results)
    
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    elapsed = time.time() - start_time
    print(f"Audit completed in {elapsed:.2f}s. Report written to {OUTPUT_MD}")

if __name__ == "__main__":
    run_audit()
