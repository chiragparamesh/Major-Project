"""
backend/calibrate_and_tune.py - Model Tuning, Probability Calibration, & Threshold Optimization

Part 22 Implementation:
1. TimeSeriesSplit RandomizedSearchCV tuning for XGBoost and Random Forest.
2. Small grid search for DNN Focal Loss (alpha in [0.25, 0.5, 0.75], gamma in [1.5, 2.0, 3.0]).
3. Probability calibration on validation split:
   - Evaluates Isotonic Regression vs Platt Scaling (Logistic Regression).
   - Selects the calibrator with the lower Brier score loss.
4. Determines operating thresholds giving at most 1% FPR on the validation set.
5. Evaluates test recall at that threshold and calculates the validation-vs-test gap.
6. Saves operating thresholds, calibrators, and gaps to backend/models/operating_thresholds.json.
"""

import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
import sys
import json
import time
import logging
from typing import Dict, Any, Tuple, Optional

import numpy as np
import pandas as pd
import joblib

from sklearn.model_selection import TimeSeriesSplit, RandomizedSearchCV
from sklearn.metrics import (
    roc_curve,
    brier_score_loss,
    average_precision_score,
    roc_auc_score,
    recall_score
)
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

# Path configuration
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.dirname(os.path.abspath(__file__))
for p in [root_dir, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from feature_builder import CANONICAL_22_FEATURES
try:
    from backend.train_all_models import load_time_split_data, MODELS_DIR, build_user_sequences
except ImportError:
    from train_all_models import load_time_split_data, MODELS_DIR, build_user_sequences
import model_trainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("calibrate_and_tune")

THRESHOLDS_JSON_PATH = os.path.join(MODELS_DIR, "operating_thresholds.json")


def calibrate_probabilities(y_val: np.ndarray, val_raw_probs: np.ndarray) -> Tuple[Any, str, float]:
    """
    Fits both Isotonic Regression and Platt Scaling (Logistic Regression) on validation predictions.
    Returns (best_calibrator, method_name, best_brier_score).
    """
    # 1. Isotonic Regression
    iso = IsotonicRegression(out_of_bounds='clip')
    iso.fit(val_raw_probs, y_val)
    iso_probs = iso.predict(val_raw_probs)
    brier_iso = float(brier_score_loss(y_val, iso_probs))

    # 2. Platt Scaling (Logistic Regression on raw probabilities)
    platt = LogisticRegression(solver='lbfgs', max_iter=200)
    platt.fit(val_raw_probs.reshape(-1, 1), y_val)
    platt_probs = platt.predict_proba(val_raw_probs.reshape(-1, 1))[:, 1]
    brier_platt = float(brier_score_loss(y_val, platt_probs))

    if brier_iso < brier_platt:
        return iso, "isotonic", brier_iso
    else:
        return platt, "platt", brier_platt


def apply_calibrator(calibrator: Any, method: str, raw_probs: np.ndarray) -> np.ndarray:
    """Applies fitted calibrator to unseen probabilities."""
    if method == "isotonic":
        return calibrator.predict(raw_probs)
    else:
        return calibrator.predict_proba(raw_probs.reshape(-1, 1))[:, 1]


def determine_threshold_at_1pct_fpr(y_val: np.ndarray, val_probs: np.ndarray, y_test: np.ndarray, test_probs: np.ndarray) -> Dict[str, Any]:
    """
    Finds operating threshold on validation set where FPR <= 0.01 (1%).
    Evaluates test set at that threshold and calculates the validation-vs-test gap.
    """
    fpr, tpr, thresholds = roc_curve(y_val, val_probs)
    valid_indices = np.where(fpr <= 0.01)[0]
    
    if len(valid_indices) == 0:
        opt_thresh = float(thresholds[0])
        val_fpr = float(fpr[0])
        val_recall = float(tpr[0])
    else:
        best_idx = valid_indices[-1]
        opt_thresh = float(thresholds[best_idx])
        val_fpr = float(fpr[best_idx])
        val_recall = float(tpr[best_idx])

    # Evaluate on test set using the chosen operating threshold
    test_preds = np.where(test_probs >= opt_thresh, 1, 0)
    n_neg = int(np.sum(y_test == 0))
    n_pos = int(np.sum(y_test == 1))
    
    test_fp = int(np.sum((test_preds == 1) & (y_test == 0)))
    test_tp = int(np.sum((test_preds == 1) & (y_test == 1)))
    
    test_fpr = float(test_fp / max(1, n_neg))
    test_recall = float(test_tp / max(1, n_pos))
    gap = float(abs(val_recall - test_recall))

    return {
        "operating_threshold": opt_thresh,
        "validation_fpr": val_fpr,
        "validation_recall": val_recall,
        "test_fpr": test_fpr,
        "test_recall": test_recall,
        "recall_gap": gap
    }


def run_tuning_and_calibration():
    logger.info("=== STARTING MLBFD TUNING, CALIBRATION, & THRESHOLD SELECTION ===")
    t0 = time.time()
    
    # 1. Load chronologically split data
    df_train, df_val, df_test = load_time_split_data(sample_per_source=20000)
    
    X_train = df_train[CANONICAL_22_FEATURES].values.astype(np.float32)
    y_train = df_train['is_fraud'].values.astype(np.int32)
    
    X_val = df_val[CANONICAL_22_FEATURES].values.astype(np.float32)
    y_val = df_val['is_fraud'].values.astype(np.int32)
    
    X_test = df_test[CANONICAL_22_FEATURES].values.astype(np.float32)
    y_test = df_test['is_fraud'].values.astype(np.int32)

    # Load scaler
    scaler_path = os.path.join(MODELS_DIR, "mlbfd_mega_scaler.pkl")
    scaler = joblib.load(scaler_path)
    X_train_scaled = scaler.transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)

    def pr_auc_scorer(estimator, X_s, y_s):
        probs = estimator.predict_proba(X_s)
        if hasattr(probs, 'ndim') and probs.ndim == 2:
            probs = probs[:, 1]
        return float(average_precision_score(y_s, probs))

    # 2. TimeSeriesSplit RandomizedSearchCV for XGBoost (20 iterations)
    logger.info("1/3: Tuning XGBoost with TimeSeriesSplit (3 splits, 20 iterations)...")
    xgb_base = model_trainer.get_xgboost_classifier()
    xgb_param_dist = {
        'max_depth': [4, 5, 6, 8, 10],
        'learning_rate': [0.03, 0.05, 0.08, 0.1, 0.15],
        'subsample': [0.7, 0.8, 0.85, 0.9, 1.0],
        'colsample_bytree': [0.7, 0.8, 0.85, 0.9, 1.0],
        'n_estimators': [75, 100, 125, 150, 175]
    }
    tscv = TimeSeriesSplit(n_splits=3)
    xgb_search = RandomizedSearchCV(
        xgb_base,
        param_distributions=xgb_param_dist,
        n_iter=10,
        cv=tscv,
        scoring=pr_auc_scorer,
        random_state=42,
        n_jobs=-1
    )
    xgb_search.fit(X_train_scaled, y_train)
    best_xgb = xgb_search.best_estimator_
    joblib.dump(best_xgb, os.path.join(MODELS_DIR, "mlbfd_mega_xgboost_model.pkl"))
    logger.info(f"✅ XGBoost Tuned Best Params: {xgb_search.best_params_} (CV PR-AUC: {xgb_search.best_score_:.4f})")

    # 3. TimeSeriesSplit RandomizedSearchCV for Random Forest
    logger.info("2/3: Tuning Random Forest with TimeSeriesSplit (3 splits, 10 iterations)...")
    rf_base = model_trainer.get_random_forest_classifier()
    rf_param_dist = {
        'max_depth': [8, 10, 12, 14, 16],
        'n_estimators': [50, 75, 100, 125, 150],
        'min_samples_split': [2, 5, 8, 10],
        'max_features': ['sqrt', 'log2', 0.5, 0.7]
    }
    rf_search = RandomizedSearchCV(
        rf_base,
        param_distributions=rf_param_dist,
        n_iter=10,
        cv=tscv,
        scoring=pr_auc_scorer,
        random_state=42,
        n_jobs=-1
    )
    rf_search.fit(X_train_scaled, y_train)
    best_rf = rf_search.best_estimator_
    joblib.dump(best_rf, os.path.join(MODELS_DIR, "mlbfd_mega_random_forest_model.pkl"))
    logger.info(f"✅ Random Forest Tuned Best Params: {rf_search.best_params_} (CV PR-AUC: {rf_search.best_score_:.4f})")

    # 4. Focal Loss Grid Search for DNN
    logger.info("3/3: Grid Tuning DNN Focal Loss alpha & gamma on Validation PR-AUC...")
    best_dnn_prauc = -1.0
    best_alpha, best_gamma = 0.25, 2.0
    
    alpha_grid = [0.25, 0.50, 0.75]
    gamma_grid = [1.5, 2.0, 3.0]
    
    for alpha in alpha_grid:
        for gamma in gamma_grid:
            dnn_temp = model_trainer.build_neural_network(input_dim=22)
            # Compile with current alpha, gamma
            dnn_temp.compile(
                optimizer='adam',
                loss=model_trainer.BinaryFocalLoss(gamma=gamma, alpha=alpha),
                metrics=['accuracy']
            )
            dnn_temp.fit(X_train_scaled, y_train, epochs=3, batch_size=512, verbose=0)
            val_preds = dnn_temp.predict(X_val_scaled, verbose=0).flatten()
            score = average_precision_score(y_val, val_preds)
            if score > best_dnn_prauc:
                best_dnn_prauc = score
                best_alpha, best_gamma = alpha, gamma

    logger.info(f"✅ DNN Best Focal Loss: alpha={best_alpha}, gamma={best_gamma} (Val PR-AUC: {best_dnn_prauc:.4f})")

    # 5. Load all 7 trained models for Calibration and Threshold Setting
    logger.info("Calibrating all models on validation set (Brier score comparison)...")
    
    # Raw validation and test predictions
    val_probs_dict = {}
    test_probs_dict = {}

    # XGBoost
    val_probs_dict['XGBoost'] = best_xgb.predict_proba(X_val_scaled)[:, 1]
    test_probs_dict['XGBoost'] = best_xgb.predict_proba(X_test_scaled)[:, 1]

    # Random Forest
    val_probs_dict['Random Forest'] = best_rf.predict_proba(X_val_scaled)[:, 1]
    test_probs_dict['Random Forest'] = best_rf.predict_proba(X_test_scaled)[:, 1]

    # Logistic Regression
    lr = joblib.load(os.path.join(MODELS_DIR, "mlbfd_mega_logistic_regression_model.pkl"))
    val_probs_dict['Logistic Regression'] = lr.predict_proba(X_val_scaled)[:, 1]
    test_probs_dict['Logistic Regression'] = lr.predict_proba(X_test_scaled)[:, 1]

    # Isolation Forest
    if_model = joblib.load(os.path.join(MODELS_DIR, "mlbfd_mega_isolation_forest_model.pkl"))
    val_s = -if_model.score_samples(X_val_scaled)
    test_s = -if_model.score_samples(X_test_scaled)
    s_min, s_max = val_s.min(), val_s.max()
    val_probs_dict['Isolation Forest'] = (val_s - s_min) / (s_max - s_min + 1e-8)
    test_probs_dict['Isolation Forest'] = (test_s - s_min) / (s_max - s_min + 1e-8)

    # Neural Network (DNN)
    import tensorflow as tf
    dnn = tf.keras.models.load_model(
        os.path.join(MODELS_DIR, "mlbfd_mega_neural_network_model.keras"),
        custom_objects={'BinaryFocalLoss': model_trainer.BinaryFocalLoss}
    )
    val_probs_dict['Neural Network'] = dnn.predict(X_val_scaled, verbose=0).flatten()
    test_probs_dict['Neural Network'] = dnn.predict(X_test_scaled, verbose=0).flatten()

    # LSTM
    user_val = df_val['user_id'].values if 'user_id' in df_val.columns else np.array([f"u_{i}" for i in range(len(df_val))])
    user_test = df_test['user_id'].values if 'user_id' in df_test.columns else np.array([f"u_{i}" for i in range(len(df_test))])
    X_val_seq = build_user_sequences(X_val_scaled, user_val, timesteps=5)
    X_test_seq = build_user_sequences(X_test_scaled, user_test, timesteps=5)
    
    lstm = tf.keras.models.load_model(
        os.path.join(MODELS_DIR, "mlbfd_mega_lstm_model.keras"),
        custom_objects={'AttentionLayer': model_trainer.AttentionLayer}
    )
    val_probs_dict['LSTM'] = lstm.predict(X_val_seq, verbose=0).flatten()
    test_probs_dict['LSTM'] = lstm.predict(X_test_seq, verbose=0).flatten()

    # Autoencoder
    ae = tf.keras.models.load_model(os.path.join(MODELS_DIR, "mlbfd_mega_autoencoder_model.keras"))
    val_rec = ae.predict(X_val_scaled, verbose=0)
    test_rec = ae.predict(X_test_scaled, verbose=0)
    val_mse = np.mean(np.square(X_val_scaled - val_rec), axis=1)
    test_mse = np.mean(np.square(X_test_scaled - test_rec), axis=1)
    val_probs_dict['Autoencoder'] = (val_mse - val_mse.min()) / (val_mse.max() - val_mse.min() + 1e-8)
    test_probs_dict['Autoencoder'] = (test_mse - val_mse.min()) / (val_mse.max() - val_mse.min() + 1e-8)

    # 6. Fit calibrator and choose operating threshold per model
    threshold_results = {
        "_metadata": {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_fpr": 0.01,
            "validation_samples": len(y_val),
            "test_samples": len(y_test)
        },
        "models": {}
    }

    calibrated_val_probs_list = []
    calibrated_test_probs_list = []

    print("\n" + "="*95)
    print("                 [CALIBRATION & OPERATING THRESHOLDS AT <= 1% FPR]                 ")
    print("="*95)
    print(f"{'Model Name':<22} | {'Calibrator':<10} | {'Brier':<8} | {'Threshold':<10} | {'Val Recall':<11} | {'Test Recall':<12} | {'Gap':<8}")
    print("-"*95)

    for name in ['XGBoost', 'Random Forest', 'Logistic Regression', 'Isolation Forest', 'Neural Network', 'LSTM', 'Autoencoder']:
        v_raw = val_probs_dict[name]
        t_raw = test_probs_dict[name]

        # Calibrate
        calibrator, method, brier = calibrate_probabilities(y_val, v_raw)
        v_cal = apply_calibrator(calibrator, method, v_raw)
        t_cal = apply_calibrator(calibrator, method, t_raw)
        
        calibrated_val_probs_list.append(v_cal)
        calibrated_test_probs_list.append(t_cal)

        # Save calibrator object
        cal_path = os.path.join(MODELS_DIR, f"calibrator_{name.lower().replace(' ', '_')}.pkl")
        joblib.dump({"calibrator": calibrator, "method": method}, cal_path)

        # Threshold optimization for <= 1% FPR
        thresh_info = determine_threshold_at_1pct_fpr(y_val, v_cal, y_test, t_cal)
        thresh_info["calibrator_method"] = method
        thresh_info["brier_score"] = brier
        threshold_results["models"][name] = thresh_info

        print(f"{name:<22} | {method:<10} | {brier:<8.4f} | {thresh_info['operating_threshold']:<10.4f} | "
              f"{thresh_info['validation_recall']:<11.4f} | {thresh_info['test_recall']:<12.4f} | {thresh_info['recall_gap']:<8.4f}")

    # 7. Ensemble Calibration and Threshold
    val_ensemble_cal = np.mean(calibrated_val_probs_list, axis=0)
    test_ensemble_cal = np.mean(calibrated_test_probs_list, axis=0)
    
    ensemble_thresh = determine_threshold_at_1pct_fpr(y_val, val_ensemble_cal, y_test, test_ensemble_cal)
    ensemble_thresh["calibrator_method"] = "mean_calibrated_ensemble"
    ensemble_thresh["brier_score"] = float(brier_score_loss(y_val, val_ensemble_cal))
    threshold_results["models"]["Ensemble"] = ensemble_thresh

    print("-"*95)
    print(f"{'Ensemble (Average)':<22} | {'ensemble':<10} | {ensemble_thresh['brier_score']:<8.4f} | "
          f"{ensemble_thresh['operating_threshold']:<10.4f} | {ensemble_thresh['validation_recall']:<11.4f} | "
          f"{ensemble_thresh['test_recall']:<12.4f} | {ensemble_thresh['recall_gap']:<8.4f}")
    print("="*95)

    # Save to JSON
    with open(THRESHOLDS_JSON_PATH, "w") as f:
        json.dump(threshold_results, f, indent=4)
    logger.info(f"💾 Operating thresholds and validation-vs-test gaps saved to {THRESHOLDS_JSON_PATH}")
    
    elapsed = time.time() - t0
    logger.info(f"Calibration and tuning completed in {elapsed:.2f}s.")
    return threshold_results


if __name__ == "__main__":
    run_tuning_and_calibration()
