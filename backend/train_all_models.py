"""
backend/train_all_models.py - Honest Time-Split Multi-Model Training Pipeline for MLBFD

Combines real data (PaySim, IEEE-CIS, BAF) with UPI simulator data.
- Strict chronological split: Train (70%), Validation (15%), Test (15%).
- StandardScaler fitted on Train split only (zero future/holdout leakage).
- SMOTE vs Class Weights compared on Validation PR-AUC; never resamples Val or Test.
- 7 ML/DL models:
  1. XGBoost
  2. Random Forest
  3. Logistic Regression
  4. Isolation Forest
  5. Deep Neural Network (DNN) with Focal Loss
  6. Attention LSTM (sequences built strictly per-user, never crossing users)
  7. Deep Reconstruction Autoencoder (fitted on legitimate samples only)
- Early stopping on validation PR-AUC.
- Resumable: saves each model immediately upon completion with version & metrics JSON.
- Evaluates test holdout metrics: PR-AUC, ROC-AUC, recall at 1% FPR, confusion matrix.
"""

import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
import sys
import json
import time
import hashlib
import logging
from datetime import datetime
from typing import Dict, Tuple, List, Optional, Any

import numpy as np
import pandas as pd
import joblib

from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    precision_score,
    recall_score,
    f1_score,
    accuracy_score,
    confusion_matrix,
    roc_curve
)
from imblearn.over_sampling import SMOTE

# Ensure parent and backend are in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.dirname(os.path.abspath(__file__))
for p in [root_dir, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from feature_builder import (
    CANONICAL_22_FEATURES,
    save_feature_order_hash,
    verify_feature_order_hash,
    get_feature_order_hash
)
import model_trainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_all_models")

MODELS_DIR = os.path.join(backend_dir, "models")
DATA_DIR = os.path.join(root_dir, "data")
DATA_VERSION = "v2_honest_parquet_simulator"


def ensure_models_dir():
    os.makedirs(MODELS_DIR, exist_ok=True)
    save_feature_order_hash(MODELS_DIR)


def calculate_recall_at_1pct_fpr(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Calculates true positive rate (recall) at exactly 1% false positive rate."""
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    idx = np.where(fpr <= 0.01)[0]
    if len(idx) == 0:
        return 0.0
    return float(tpr[idx[-1]])


def load_time_split_data(sample_per_source: int = 20000) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Loads clean parquet datasets from real sources and UPI simulator.
    Splits each source chronologically: Train (70%), Val (15%), Test (15%).
    Then combines split partitions across all sources.
    This guarantees strict time ordering, zero future leakage, and natural fraud ratios in all 3 splits.
    """
    sources = ['paysim', 'ieee', 'baf', 'simulator']
    train_dfs, val_dfs, test_dfs = [], [], []
    
    for src in sources:
        pq_path = os.path.join(DATA_DIR, f"{src}_clean.parquet")
        if not os.path.exists(pq_path):
            raise FileNotFoundError(f"Clean parquet missing for {src} at {pq_path}. Run data_loader/simulator first.")
        
        df_src = pd.read_parquet(pq_path)
        df_src['dataset_source'] = src
        
        # Subsample to sample_per_source if larger, preserving time order
        if len(df_src) > sample_per_source:
            stride = len(df_src) // sample_per_source
            df_src = df_src.iloc[::stride].iloc[:sample_per_source].reset_index(drop=True)
            
        n = len(df_src)
        n_tr = int(n * 0.70)
        n_v = int(n * 0.15)
        
        tr_part = df_src.iloc[:n_tr]
        v_part = df_src.iloc[n_tr:n_tr + n_v]
        te_part = df_src.iloc[n_tr + n_v:]
        
        logger.info(f"{src} ({n} rows) -> Train: {len(tr_part)} (Frauds: {tr_part['is_fraud'].sum()}), "
                    f"Val: {len(v_part)} (Frauds: {v_part['is_fraud'].sum()}), "
                    f"Test: {len(te_part)} (Frauds: {te_part['is_fraud'].sum()})")
                    
        train_dfs.append(tr_part)
        val_dfs.append(v_part)
        test_dfs.append(te_part)
        
    df_train = pd.concat(train_dfs, ignore_index=True)
    df_val = pd.concat(val_dfs, ignore_index=True)
    df_test = pd.concat(test_dfs, ignore_index=True)
    
    logger.info(f"Combined Splits -> Train: {len(df_train)} (Frauds: {df_train['is_fraud'].sum()} [{df_train['is_fraud'].mean()*100:.2f}%]), "
                f"Val: {len(df_val)} (Frauds: {df_val['is_fraud'].sum()} [{df_val['is_fraud'].mean()*100:.2f}%]), "
                f"Test: {len(df_test)} (Frauds: {df_test['is_fraud'].sum()} [{df_test['is_fraud'].mean()*100:.2f}%])")
                
    return df_train, df_val, df_test


def build_user_sequences(X_scaled: np.ndarray, user_ids: np.ndarray, timesteps: int = 5) -> np.ndarray:
    """
    Constructs 3D LSTM sequence tensors (samples, timesteps, features)
    strictly within each user's boundary, NEVER crossing users.
    """
    n_samples, n_feats = X_scaled.shape
    X_seq = np.zeros((n_samples, timesteps, n_feats), dtype=np.float32)
    
    # Track historical indices for each user
    user_history_map = {}
    for i in range(n_samples):
        uid = user_ids[i] if user_ids is not None else i
        if uid not in user_history_map:
            user_history_map[uid] = []
        user_history_map[uid].append(i)
        
        hist = user_history_map[uid]
        # Take last min(timesteps, len(hist)) indices
        current_window = hist[-timesteps:]
        k = len(current_window)
        # Place window at the end of the sequence
        for step_idx, row_idx in enumerate(current_window):
            dest_t = timesteps - k + step_idx
            X_seq[i, dest_t, :] = X_scaled[row_idx]
            
        # If fewer than timesteps, pad earliest positions with first observed row
        if k < timesteps:
            first_row = X_scaled[hist[0]]
            for dest_t in range(timesteps - k):
                X_seq[i, dest_t, :] = first_row
                
    return X_seq


def train_and_evaluate_all(force_retrain: bool = False):
    """
    Main training execution function satisfying all Part 21 requirements.
    """
    logger.info("=== STARTING MLBFD HONEST MULTI-MODEL TRAINING PIPELINE ===")
    t_start = time.time()
    ensure_models_dir()
    
    # 1. Load and split data chronologically per source (70% Train, 15% Val, 15% Test)
    df_train, df_val, df_test = load_time_split_data(sample_per_source=20000)
    
    X_train = df_train[CANONICAL_22_FEATURES].values.astype(np.float32)
    y_train = df_train['is_fraud'].values.astype(np.int32)
    user_train = df_train['user_id'].values if 'user_id' in df_train.columns else np.array([f"u_{i}" for i in range(len(df_train))])

    X_val = df_val[CANONICAL_22_FEATURES].values.astype(np.float32)
    y_val = df_val['is_fraud'].values.astype(np.int32)
    user_val = df_val['user_id'].values if 'user_id' in df_val.columns else np.array([f"u_{i}" for i in range(len(df_val))])

    X_test = df_test[CANONICAL_22_FEATURES].values.astype(np.float32)
    y_test = df_test['is_fraud'].values.astype(np.int32)
    user_test = df_test['user_id'].values if 'user_id' in df_test.columns else np.array([f"u_{i}" for i in range(len(df_test))])

    # 3. Fit StandardScaler on Train split only
    scaler_path = os.path.join(MODELS_DIR, 'mlbfd_mega_scaler.pkl')
    scaler = StandardScaler()
    scaler.fit(X_train)
    joblib.dump(scaler, scaler_path)
    joblib.dump(CANONICAL_22_FEATURES, os.path.join(MODELS_DIR, 'mlbfd_mega_feature_names.pkl'))
    logger.info("Saved StandardScaler and canonical feature names.")
    
    X_train_scaled = scaler.transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)

    # 4. Compare SMOTE vs Class Weights on Validation PR-AUC
    logger.info("Comparing SMOTE vs Class Weights on Validation PR-AUC...")
    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    scale_pos_weight = float(n_neg / max(1, n_pos))
    
    # Candidate A: Class Weights
    clf_weighted = model_trainer.get_logistic_regression()
    clf_weighted.fit(X_train_scaled, y_train)
    val_probs_weighted = clf_weighted.predict_proba(X_val_scaled)[:, 1]
    prauc_weighted = average_precision_score(y_val, val_probs_weighted)
    
    # Candidate B: SMOTE
    try:
        smote = SMOTE(random_state=42)
        X_train_smote, y_train_smote = smote.fit_resample(X_train_scaled, y_train)
        clf_smote = model_trainer.get_logistic_regression()
        clf_smote.fit(X_train_smote, y_train_smote)
        val_probs_smote = clf_smote.predict_proba(X_val_scaled)[:, 1]
        prauc_smote = average_precision_score(y_val, val_probs_smote)
    except Exception as e:
        logger.warning(f"SMOTE sampling error: {e}")
        prauc_smote = -1.0
        X_train_smote, y_train_smote = X_train_scaled, y_train

    logger.info(f"Validation PR-AUC comparison: ClassWeights={prauc_weighted:.4f} vs SMOTE={prauc_smote:.4f}")
    if prauc_smote > prauc_weighted:
        logger.info("SMOTE selected as superior rebalancing technique for tree/linear training.")
        X_train_fit, y_train_fit = X_train_smote, y_train_smote
        use_smote = True
    else:
        logger.info("Class Weights selected as superior rebalancing technique.")
        X_train_fit, y_train_fit = X_train_scaled, y_train
        use_smote = False

    # Metrics dictionary (resumable)
    metrics_path = os.path.join(MODELS_DIR, "mlbfd_mega_metrics.json")
    metrics_report = {}
    if os.path.exists(metrics_path) and not force_retrain:
        try:
            with open(metrics_path, "r") as f:
                metrics_report = json.load(f)
        except Exception:
            metrics_report = {}

    # Helper to evaluate test metrics (overall, real datasets, and simulator)
    real_mask = (df_test['dataset_source'] != 'simulator').values
    sim_mask = (df_test['dataset_source'] == 'simulator').values

    def evaluate_model(name: str, probs: np.ndarray) -> Dict[str, Any]:
        preds = np.where(probs >= 0.5, 1, 0)
        pr_auc = float(average_precision_score(y_test, probs))
        roc_auc = float(roc_auc_score(y_test, probs))
        rec_1pct = float(calculate_recall_at_1pct_fpr(y_test, probs))
        acc = float(accuracy_score(y_test, preds))
        prec = float(precision_score(y_test, preds, zero_division=0))
        rec = float(recall_score(y_test, preds, zero_division=0))
        f1 = float(f1_score(y_test, preds, zero_division=0))
        cm = confusion_matrix(y_test, preds).tolist()

        # Real datasets metrics (PaySim, IEEE-CIS, BAF)
        real_metrics = {
            'samples': int(np.sum(real_mask)),
            'frauds': int(np.sum(y_test[real_mask])),
            'pr_auc': float(average_precision_score(y_test[real_mask], probs[real_mask])),
            'roc_auc': float(roc_auc_score(y_test[real_mask], probs[real_mask])),
            'recall_at_1pct_fpr': float(calculate_recall_at_1pct_fpr(y_test[real_mask], probs[real_mask]))
        }

        # Simulator dataset metrics
        sim_metrics = {
            'samples': int(np.sum(sim_mask)),
            'frauds': int(np.sum(y_test[sim_mask])),
            'pr_auc': float(average_precision_score(y_test[sim_mask], probs[sim_mask])),
            'roc_auc': float(roc_auc_score(y_test[sim_mask], probs[sim_mask])),
            'recall_at_1pct_fpr': float(calculate_recall_at_1pct_fpr(y_test[sim_mask], probs[sim_mask]))
        }
        
        res = {
            'pr_auc': pr_auc,
            'roc_auc': roc_auc,
            'recall_at_1pct_fpr': rec_1pct,
            'accuracy': acc,
            'precision': prec,
            'recall': rec,
            'f1_score': f1,
            'confusion_matrix': cm,
            'real_subset': real_metrics,
            'simulator_subset': sim_metrics
        }
        metrics_report[name] = res
        with open(metrics_path, "w") as f:
            json.dump(metrics_report, f, indent=4)
        return res

    # -------------------------------------------------------------------------
    # Model 1: XGBoost
    # -------------------------------------------------------------------------
    xgb_path = os.path.join(MODELS_DIR, "mlbfd_mega_xgboost_model.pkl")
    if os.path.exists(xgb_path) and not force_retrain and 'XGBoost' in metrics_report:
        logger.info("XGBoost artifact already exists. Skipping training.")
    else:
        logger.info("Training Model 1/7: XGBoost Classifier with Early Stopping on Validation PR-AUC...")
        xgb_clf = model_trainer.get_xgboost_classifier()
        xgb_clf.set_params(scale_pos_weight=scale_pos_weight if not use_smote else 1.0, early_stopping_rounds=15, eval_metric="aucpr")
        xgb_clf.fit(X_train_fit, y_train_fit, eval_set=[(X_val_scaled, y_val)], verbose=False)
        joblib.dump(xgb_clf, xgb_path)
        probs_xgb = xgb_clf.predict_proba(X_test_scaled)[:, 1]
        m = evaluate_model('XGBoost', probs_xgb)
        logger.info(f"✅ XGBoost finished. PR-AUC: {m['pr_auc']:.4f}, ROC-AUC: {m['roc_auc']:.4f}, Recall@1%FPR: {m['recall_at_1pct_fpr']:.4f}")

    # -------------------------------------------------------------------------
    # Model 2: Random Forest
    # -------------------------------------------------------------------------
    rf_path = os.path.join(MODELS_DIR, "mlbfd_mega_random_forest_model.pkl")
    if os.path.exists(rf_path) and not force_retrain and 'Random Forest' in metrics_report:
        logger.info("Random Forest artifact already exists. Skipping training.")
    else:
        logger.info("Training Model 2/7: Random Forest Classifier...")
        rf_clf = model_trainer.get_random_forest_classifier()
        if not use_smote:
            rf_clf.set_params(class_weight="balanced")
        rf_clf.fit(X_train_fit, y_train_fit)
        joblib.dump(rf_clf, rf_path)
        probs_rf = rf_clf.predict_proba(X_test_scaled)[:, 1]
        m = evaluate_model('Random Forest', probs_rf)
        logger.info(f"✅ Random Forest finished. PR-AUC: {m['pr_auc']:.4f}, ROC-AUC: {m['roc_auc']:.4f}, Recall@1%FPR: {m['recall_at_1pct_fpr']:.4f}")

    # -------------------------------------------------------------------------
    # Model 3: Logistic Regression
    # -------------------------------------------------------------------------
    lr_path = os.path.join(MODELS_DIR, "mlbfd_mega_logistic_regression_model.pkl")
    if os.path.exists(lr_path) and not force_retrain and 'Logistic Regression' in metrics_report:
        logger.info("Logistic Regression artifact already exists. Skipping training.")
    else:
        logger.info("Training Model 3/7: Logistic Regression...")
        lr_clf = model_trainer.get_logistic_regression()
        lr_clf.fit(X_train_fit, y_train_fit)
        joblib.dump(lr_clf, lr_path)
        probs_lr = lr_clf.predict_proba(X_test_scaled)[:, 1]
        m = evaluate_model('Logistic Regression', probs_lr)
        logger.info(f"✅ Logistic Regression finished. PR-AUC: {m['pr_auc']:.4f}, ROC-AUC: {m['roc_auc']:.4f}, Recall@1%FPR: {m['recall_at_1pct_fpr']:.4f}")

    # -------------------------------------------------------------------------
    # Model 4: Isolation Forest
    # -------------------------------------------------------------------------
    if_path = os.path.join(MODELS_DIR, "mlbfd_mega_isolation_forest_model.pkl")
    if os.path.exists(if_path) and not force_retrain and 'Isolation Forest' in metrics_report:
        logger.info("Isolation Forest artifact already exists. Skipping training.")
    else:
        logger.info("Training Model 4/7: Isolation Forest Anomaly Detector...")
        if_model = model_trainer.get_isolation_forest()
        # Fit on legitimate training transactions only
        X_train_legit = X_train_scaled[y_train == 0]
        if_model.fit(X_train_legit)
        joblib.dump(if_model, if_path)
        
        # Invert score so higher = more anomalous/fraudulent
        if_scores = -if_model.score_samples(X_test_scaled)
        # Normalize scores to [0, 1] range for metric calculation
        min_s, max_s = if_scores.min(), if_scores.max()
        probs_if = (if_scores - min_s) / (max_s - min_s + 1e-8)
        m = evaluate_model('Isolation Forest', probs_if)
        logger.info(f"✅ Isolation Forest finished. PR-AUC: {m['pr_auc']:.4f}, ROC-AUC: {m['roc_auc']:.4f}, Recall@1%FPR: {m['recall_at_1pct_fpr']:.4f}")

    # -------------------------------------------------------------------------
    # Model 5: Deep Neural Network (DNN with Focal Loss)
    # -------------------------------------------------------------------------
    dnn_path = os.path.join(MODELS_DIR, "mlbfd_mega_neural_network_model.keras")
    if os.path.exists(dnn_path) and not force_retrain and 'Neural Network' in metrics_report:
        logger.info("DNN model artifact already exists. Skipping training.")
    else:
        logger.info("Training Model 5/7: Deep Neural Network with Focal Loss...")
        import tensorflow as tf
        from tensorflow.keras.callbacks import EarlyStopping
        
        dnn = model_trainer.build_neural_network(input_dim=22)
        early_stop = EarlyStopping(monitor='val_auc', mode='max', patience=4, restore_best_weights=True)
        
        dnn.fit(
            X_train_scaled, y_train,
            validation_data=(X_val_scaled, y_val),
            epochs=15,
            batch_size=512,
            callbacks=[early_stop],
            verbose=0
        )
        dnn.save(dnn_path)
        probs_dnn = dnn.predict(X_test_scaled, verbose=0).flatten()
        m = evaluate_model('Neural Network', probs_dnn)
        logger.info(f"✅ Neural Network finished. PR-AUC: {m['pr_auc']:.4f}, ROC-AUC: {m['roc_auc']:.4f}, Recall@1%FPR: {m['recall_at_1pct_fpr']:.4f}")

    # -------------------------------------------------------------------------
    # Model 6: Attention LSTM (Per-user sequence construction)
    # -------------------------------------------------------------------------
    lstm_path = os.path.join(MODELS_DIR, "mlbfd_mega_lstm_model.keras")
    if os.path.exists(lstm_path) and not force_retrain and 'LSTM' in metrics_report:
        logger.info("LSTM model artifact already exists. Skipping training.")
    else:
        logger.info("Training Model 6/7: Attention LSTM (Per-user sequences)...")
        import tensorflow as tf
        from tensorflow.keras.callbacks import EarlyStopping
        
        X_train_seq = build_user_sequences(X_train_scaled, user_train, timesteps=5)
        X_val_seq = build_user_sequences(X_val_scaled, user_val, timesteps=5)
        X_test_seq = build_user_sequences(X_test_scaled, user_test, timesteps=5)
        
        lstm = model_trainer.build_lstm_model(timesteps=5, features=22)
        early_stop = EarlyStopping(monitor='val_auc', mode='max', patience=4, restore_best_weights=True)
        
        lstm.fit(
            X_train_seq, y_train,
            validation_data=(X_val_seq, y_val),
            epochs=12,
            batch_size=512,
            callbacks=[early_stop],
            verbose=0
        )
        lstm.save(lstm_path)
        probs_lstm = lstm.predict(X_test_seq, verbose=0).flatten()
        m = evaluate_model('LSTM', probs_lstm)
        logger.info(f"✅ LSTM Attention finished. PR-AUC: {m['pr_auc']:.4f}, ROC-AUC: {m['roc_auc']:.4f}, Recall@1%FPR: {m['recall_at_1pct_fpr']:.4f}")

    # -------------------------------------------------------------------------
    # Model 7: Deep Reconstruction Autoencoder (Unsupervised on Legit only)
    # -------------------------------------------------------------------------
    ae_path = os.path.join(MODELS_DIR, "mlbfd_mega_autoencoder_model.keras")
    if os.path.exists(ae_path) and not force_retrain and 'Autoencoder' in metrics_report:
        logger.info("Autoencoder model artifact already exists. Skipping training.")
    else:
        logger.info("Training Model 7/7: Deep Reconstruction Autoencoder on Legitimate samples...")
        import tensorflow as tf
        from tensorflow.keras.callbacks import EarlyStopping
        
        X_train_legit = X_train_scaled[y_train == 0]
        X_val_legit = X_val_scaled[y_val == 0]
        
        ae = model_trainer.build_autoencoder_model(input_dim=22)
        early_stop = EarlyStopping(monitor='val_loss', mode='min', patience=4, restore_best_weights=True)
        
        ae.fit(
            X_train_legit, X_train_legit,
            validation_data=(X_val_legit, X_val_legit),
            epochs=15,
            batch_size=512,
            callbacks=[early_stop],
            verbose=0
        )
        ae.save(ae_path)
        
        # Test reconstruction error
        X_test_rec = ae.predict(X_test_scaled, verbose=0)
        mse_scores = np.mean(np.square(X_test_scaled - X_test_rec), axis=1)
        # Normalize to probability-like score
        min_mse, max_mse = mse_scores.min(), mse_scores.max()
        probs_ae = (mse_scores - min_mse) / (max_mse - min_mse + 1e-8)
        m = evaluate_model('Autoencoder', probs_ae)
        logger.info(f"✅ Autoencoder finished. PR-AUC: {m['pr_auc']:.4f}, ROC-AUC: {m['roc_auc']:.4f}, Recall@1%FPR: {m['recall_at_1pct_fpr']:.4f}")

    # Update metadata in metrics JSON
    metrics_report['_metadata'] = {
        'version': DATA_VERSION,
        'feature_order_sha256': get_feature_order_hash(),
        'train_samples': len(y_train),
        'val_samples': len(y_val),
        'test_samples': len(y_test),
        'timestamp': datetime.utcnow().isoformat(),
        'rebalancing_used': 'SMOTE' if use_smote else 'ClassWeights'
    }
    with open(metrics_path, "w") as f:
        json.dump(metrics_report, f, indent=4)
        
    elapsed = time.time() - t_start
    print("\n" + "="*80)
    print("      [MLBFD HONEST MODEL TRAINING PIPELINE COMPLETE]      ")
    print(f"      Total execution time: {elapsed:.2f} seconds | Data Version: {DATA_VERSION}")
    print("="*80)
    print(f"{'Model':<22} | {'PR-AUC':<8} | {'ROC-AUC':<8} | {'Recall@1%FPR':<13} | {'Recall':<8} | {'Precision':<10}")
    print("-"*80)
    for model_name in ['XGBoost', 'Random Forest', 'Logistic Regression', 'Isolation Forest', 'Neural Network', 'LSTM', 'Autoencoder']:
        if model_name in metrics_report:
            m = metrics_report[model_name]
            print(f"{model_name:<22} | {m['pr_auc']:<8.4f} | {m['roc_auc']:<8.4f} | {m['recall_at_1pct_fpr']:<13.4f} | {m['recall']:<8.4f} | {m['precision']:<10.4f}")
    print("="*80 + "\n")
    return metrics_report


if __name__ == "__main__":
    train_and_evaluate_all(force_retrain=True)
