import os
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from imblearn.over_sampling import SMOTE
import joblib
import logging

logger = logging.getLogger(__name__)

# Unified canonical features imported strictly from feature_builder
from feature_builder import CANONICAL_22_FEATURES
FEATURE_COLS = CANONICAL_22_FEATURES

def get_dataset_paths():
    """Gets absolute paths to the datasets stored in D:\\Major Project\\Datasets"""
    base_dir = "D:\\Major Project\\Datasets"
    paths = {
        'paysim': os.path.join(base_dir, 'Tier1', 'PS_20174392719_1491204439457_log.csv'),
        'ieee_txn': os.path.join(base_dir, 'Tier1', 'train_transaction.csv'),
        'variant_base': os.path.join(base_dir, 'Tier2', 'Base.csv'),
        'variant_1': os.path.join(base_dir, 'Tier2', 'Variant I.csv')
    }
    return paths

def load_and_preprocess_raw_data(sample_size=100000) -> tuple:
    """
    Loads transaction datasets from disk, maps their schema to our feature engineered layout,
    uses stratified sampling to balance memory, and returns (X_train, X_test, y_train, y_test).
    """
    paths = get_dataset_paths()
    
    dfs = []
    
    # Loader helper with stratified sampling (keeps all fraud, samples non-fraud)
    def load_stratified(path, amount_col, label_col, name="dataset"):
        if not os.path.exists(path):
            logger.warning(f"Dataset path not found: {path}")
            return None
            
        logger.info(f"Loading {name} from {path}...")
        # Since files can be huge, we read in chunks or sample
        # Let's inspect column names
        try:
            chunks = pd.read_csv(path, nrows=5)
            cols = chunks.columns.tolist()
            
            # Read only required columns to save memory
            use_cols = []
            if amount_col in cols:
                use_cols.append(amount_col)
            if label_col in cols:
                use_cols.append(label_col)
                
            # If the dataset has step or hour indicators, load them
            step_col = next((c for c in cols if c.lower() in ['step', 'hour', 'transactiondt']), None)
            if step_col:
                use_cols.append(step_col)
                
            # Read full file for label column to find all fraud indexes
            full_labels = pd.read_csv(path, usecols=[label_col])
            fraud_idx = full_labels[full_labels[label_col] == 1].index.tolist()
            legit_idx = full_labels[full_labels[label_col] == 0].index.tolist()
            
            # Keep all fraud rows, but sample legit rows to avoid OOM
            max_legit = min(len(legit_idx), sample_size // 2)
            sampled_legit_idx = list(np.random.choice(legit_idx, size=max_legit, replace=False))
            
            all_target_idx = fraud_idx + sampled_legit_idx
            all_target_idx.sort()
            
            # Load selected rows
            # We can use skiprows to read only these rows
            # A helper way is to load in chunks and filter
            df = pd.DataFrame()
            chunk_size = 100000
            for chunk in pd.read_csv(path, usecols=use_cols, chunksize=chunk_size):
                df = pd.concat([df, chunk.iloc[chunk.index.isin(all_target_idx)]])
                
            logger.info(f"Loaded {df.shape[0]} rows from {name} ({len(fraud_idx)} fraud, {len(df) - len(fraud_idx)} legit)")
            
            # Align column names
            df = df.rename(columns={amount_col: 'amount', label_col: 'is_fraud'})
            
            # Extract step/hour if exists
            if step_col and step_col in df.columns:
                if step_col.lower() == 'transactiondt':
                    # IEEE-CIS time is seconds from start
                    df['hour'] = (df[step_col] // 3600) % 24
                else:
                    df['hour'] = df[step_col] % 24
            else:
                df['hour'] = np.random.randint(0, 24, size=len(df))
                
            return df[['amount', 'hour', 'is_fraud']]
            
        except Exception as e:
            logger.error(f"Failed to load {name}: {e}")
            return None

    # Load from PaySim
    df_ps = load_stratified(paths['paysim'], 'amount', 'isFraud', "PaySim")
    if df_ps is not None:
        dfs.append(df_ps)
        
    # Load from IEEE-CIS
    df_ieee = load_stratified(paths['ieee_txn'], 'TransactionAmt', 'isFraud', "IEEE-CIS")
    if df_ieee is not None:
        dfs.append(df_ieee)
        
    # Load from Base Variant (Tier2)
    df_base = load_stratified(paths['variant_base'], 'intended_balcon_amount', 'fraud_bool', "Variant Base")
    if df_base is not None:
        dfs.append(df_base)

    # Load from Variant I (Tier2)
    df_v1 = load_stratified(paths['variant_1'], 'intended_balcon_amount', 'fraud_bool', "Variant I")
    if df_v1 is not None:
        dfs.append(df_v1)

    if not dfs:
        raise RuntimeError("No datasets were successfully loaded. Make sure the dataset files exist on your D: drive.")
        
    # Merge datasets
    merged_df = pd.concat(dfs, ignore_index=True)
    logger.info(f"Merged dataset created: {merged_df.shape[0]} total rows")
    
    # Feature engineering simulation of operational features
    logger.info("Engineering behavioral and velocity features...")
    n_rows = len(merged_df)
    
    # Let's seed generator for reproducibility
    np.random.seed(42)
    
    # 1. Hour and Day of Week
    merged_df['day_of_week'] = np.random.randint(0, 7, size=n_rows)
    merged_df['is_holiday'] = np.random.choice([0, 1], p=[0.9, 0.1], size=n_rows)
    merged_df['is_weekend'] = merged_df['day_of_week'].apply(lambda d: 1 if d >= 5 else 0)
    
    # 2. Behavioral Ratios (Relative to average)
    # NOTE: Synthetic Gaussian overlays conditional on is_fraud (loc=4.5, loc=6.0) have been completely removed
    # in Part 21 to eliminate label leakage. Live training and inference exclusively use feature_builder.py.
    
    # Z-scores (unconditional baseline)
    z_scores = np.random.normal(loc=0.5, scale=0.8, size=n_rows)
    merged_df['amount_vs_std_zscore'] = np.clip(z_scores, -2, 15)
    
    # Ratio to average (unconditional baseline)
    ratios = np.random.normal(loc=1.1, scale=0.4, size=n_rows)
    merged_df['amount_vs_avg_ratio'] = np.clip(ratios, 0.1, 30.0)
    
    # 3. Velocities (Transaction count last hour and last 24h)
    v_hour = np.random.choice([1, 2, 3, 4], p=[0.8, 0.15, 0.04, 0.01], size=n_rows)
    merged_df['txn_count_last_hour'] = v_hour
    
    v_day = v_hour + np.random.randint(1, 10, size=n_rows)
    merged_df['txn_count_last_24h'] = v_day
    
    # 4. Payee parameters
    new_payee = np.random.choice([0, 1], p=[0.85, 0.15], size=n_rows)
    merged_df['new_payee_flag'] = new_payee
    
    new_payee_pct = np.random.uniform(0.0, 0.3, size=n_rows)
    merged_df['new_payee_pct_last_7days'] = new_payee_pct
    
    acct_age = np.random.randint(30, 365 * 2, size=n_rows)
    merged_df['days_since_account_created'] = acct_age
    
    # 5. Device Parameters
    known_device = np.random.choice([0, 1], p=[0.05, 0.95], size=n_rows)
    merged_df['known_device_flag'] = known_device
    
    dev_switches = np.random.choice([0, 1, 2], p=[0.9, 0.08, 0.02], size=n_rows)
    merged_df['device_change_count_30days'] = dev_switches
    
    # 6. Payee profiles
    payee_txns = np.random.randint(10, 1000, size=n_rows)
    merged_df['payee_incoming_txn_count'] = payee_txns
    
    payee_age = np.random.randint(30, 1000, size=n_rows)
    merged_df['payee_account_age_days'] = payee_age
    
    # Scam matching
    is_scam = np.random.choice([0, 1], p=[0.999, 0.001], size=n_rows)
    merged_df['is_scam_upi'] = is_scam
    
    # 7. Spatial Parameters
    dist = np.random.uniform(0.1, 20.0, size=n_rows)
    merged_df['distance_from_home_km'] = dist
    
    imp_travel = np.random.choice([0, 1], p=[0.99, 0.01], size=n_rows)
    merged_df['is_impossible_travel'] = imp_travel
    
    # 8. Network Graph Features
    centrality = np.random.uniform(0.0001, 0.01, size=n_rows)
    merged_df['payee_graph_centrality'] = centrality
    
    is_mule = np.random.choice([0, 1], p=[0.995, 0.005], size=n_rows)
    merged_df['is_mule_candidate'] = is_mule
    
    # 9. Merchant MCC Check
    mcc_high_risk = np.random.choice([0, 1], p=[0.92, 0.08], size=n_rows)
    merged_df['is_high_risk_mcc'] = mcc_high_risk

    # Extract target and features
    X = merged_df[FEATURE_COLS]
    y = merged_df['is_fraud']
    
    # Train-test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    logger.info(f"Oversampling training set with SMOTE (Original Train size: {X_train.shape[0]}, Fraud distribution: {y_train.sum()}/{len(y_train) - y_train.sum()})")
    
    # Initialize SMOTE to fix class imbalance
    smote = SMOTE(random_state=42)
    X_train_res, y_train_res = smote.fit_resample(X_train, y_train)
    
    logger.info(f"SMOTE Completed. Resampled Train size: {X_train_res.shape[0]} (Fraud: {y_train_res.sum()}, Legit: {len(y_train_res) - y_train_res.sum()})")
    
    # Standard scaling
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_res)
    X_test_scaled = scaler.transform(X_test)
    
    # Save the scaler and feature columns names for real-time model loading
    scaler_path = "D:\\Major Project\\MLBFD\\backend\\models\\mlbfd_mega_scaler.pkl"
    joblib.dump(scaler, scaler_path)
    
    features_name_path = "D:\\Major Project\\MLBFD\\backend\\models\\mlbfd_mega_feature_names.pkl"
    joblib.dump(FEATURE_COLS, features_name_path)
    
    logger.info(f"Saved scaler to {scaler_path} and feature names to {features_name_path}")
    
    return X_train_scaled, X_test_scaled, y_train_res, y_test
