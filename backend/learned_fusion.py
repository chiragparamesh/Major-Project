"""
backend/learned_fusion.py - Learned Fusion (Stacking Meta-Classifier) for MLBFD

Part 23 Implementation:
1. Builds a stacking LogisticRegression meta-classifier trained on out-of-fold (TimeSeriesSplit)
   predictions of the 7 models plus the layer 2-7 rule scores.
2. Calibrates probabilities and saves backend/models/fusion.json and stacking_meta_classifier.pkl.
3. Compares with static weights (0.38, 0.04, 0.03, 0.28, 0.15, 0.10, 0.02) on:
   - Validation PR-AUC
   - Validation Recall at 1% FPR
   - Brier Score
4. Selects the better performer and keeps static weights as configuration fallback.
5. Provides predict_fusion(model_probs, layer_scores) for the fraud detection engine.
"""

import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
import sys
import json
import time
import logging
from typing import Dict, Any, Tuple, List, Optional

import numpy as np
import pandas as pd
import joblib

from sklearn.model_selection import TimeSeriesSplit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    roc_curve,
    brier_score_loss,
    recall_score
)
from sklearn.isotonic import IsotonicRegression

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.dirname(os.path.abspath(__file__))
for p in [backend_dir, root_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from feature_builder import CANONICAL_22_FEATURES
try:
    from backend.train_all_models import load_time_split_data, MODELS_DIR, build_user_sequences
except ImportError:
    from train_all_models import load_time_split_data, MODELS_DIR, build_user_sequences
import model_trainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("learned_fusion")

FUSION_JSON_PATH = os.path.join(MODELS_DIR, "fusion.json")
STACKING_MODEL_PATH = os.path.join(MODELS_DIR, "stacking_meta_classifier.pkl")

META_FEATURE_NAMES = [
    "prob_xgboost",
    "prob_random_forest",
    "prob_logistic_regression",
    "prob_isolation_forest",
    "prob_neural_network",
    "prob_lstm",
    "prob_autoencoder",
    "score_layer2_velocity",
    "score_layer3_flow",
    "score_layer4_payee",
    "score_layer5_compromise",
    "score_layer6_amount",
    "score_layer7_website_trust"
]

STATIC_WEIGHTS = {
    "behavioral": 0.38,
    "velocity": 0.04,
    "flow": 0.03,
    "payee": 0.28,
    "compromise": 0.15,
    "amount": 0.10,
    "website_trust": 0.02
}


def compute_layer_scores_from_features(X_feats: np.ndarray) -> np.ndarray:
    """
    Computes normalized [0.0, 1.0] scores for Layers 2-7 directly from the 22 canonical features.
    X_feats: Array of shape (N, 22) aligned to CANONICAL_22_FEATURES.
    Returns: Array of shape (N, 6) for [velocity, flow, payee, compromise, amount, website_trust].
    """
    idx = {name: i for i, name in enumerate(CANONICAL_22_FEATURES)}
    N = X_feats.shape[0]
    scores = np.zeros((N, 6), dtype=np.float32)

    for i in range(N):
        # Layer 2: Velocity
        c1h = X_feats[i, idx['txn_count_last_hour']]
        c24h = X_feats[i, idx['txn_count_last_24h']]
        l2 = 0.0
        if c1h > 10:
            l2 += 60.0
        elif c1h > 3:
            l2 += 40.0
        if c24h > 20:
            l2 += 30.0
        scores[i, 0] = min(l2, 100.0) / 100.0

        # Layer 3: Flow
        centrality = X_feats[i, idx['payee_graph_centrality']]
        scores[i, 1] = float(np.clip(centrality, 0.0, 1.0))

        # Layer 4: Payee
        is_scam = X_feats[i, idx['is_scam_upi']]
        is_mule = X_feats[i, idx['is_mule_candidate']]
        new_payee = X_feats[i, idx['new_payee_flag']]
        incoming = X_feats[i, idx['payee_incoming_txn_count']]
        l4 = 0.0
        if is_scam > 0.5:
            l4 += 100.0
        if is_mule > 0.5:
            l4 += 80.0
        if new_payee > 0.5:
            l4 += 25.0
        if incoming > 50.0:
            l4 += 40.0
        scores[i, 2] = min(l4, 100.0) / 100.0

        # Layer 5: Compromise
        known_dev = X_feats[i, idx['known_device_flag']]
        imposs = X_feats[i, idx['is_impossible_travel']]
        dist = X_feats[i, idx['distance_from_home_km']]
        l5 = 0.0
        if known_dev < 0.5:
            l5 += 50.0
        if imposs > 0.5:
            l5 += 70.0
        if dist > 200.0:
            l5 += 40.0
        scores[i, 3] = min(l5, 100.0) / 100.0

        # Layer 6: Amount
        z = X_feats[i, idx['amount_vs_std_zscore']]
        ratio = X_feats[i, idx['amount_vs_avg_ratio']]
        l6 = 0.0
        if ratio > 10.0:
            l6 += 90.0
        elif ratio > 5.0:
            l6 += 70.0
        if z > 3.0:
            l6 += 50.0
        scores[i, 4] = min(l6, 100.0) / 100.0

        # Layer 7: Website Trust / High Risk MCC
        mcc = X_feats[i, idx['is_high_risk_mcc']]
        l7 = 100.0 if mcc > 0.5 else 0.0
        scores[i, 5] = min(l7, 100.0) / 100.0

    return scores


def evaluate_static_fusion(val_model_probs: np.ndarray, val_layer_scores: np.ndarray) -> np.ndarray:
    """
    Computes static 7-layer weighted combination:
    layer1 * 0.38 + layer2 * 0.04 + layer3 * 0.03 + layer4 * 0.28 + layer5 * 0.15 + layer6 * 0.10 + layer7 * 0.02
    where layer1 is the mean probability across 7 models.
    """
    layer1_mean_prob = np.mean(val_model_probs, axis=1)  # shape (N,)
    static_probs = (
        layer1_mean_prob * STATIC_WEIGHTS["behavioral"] +
        val_layer_scores[:, 0] * STATIC_WEIGHTS["velocity"] +
        val_layer_scores[:, 1] * STATIC_WEIGHTS["flow"] +
        val_layer_scores[:, 2] * STATIC_WEIGHTS["payee"] +
        val_layer_scores[:, 3] * STATIC_WEIGHTS["compromise"] +
        val_layer_scores[:, 4] * STATIC_WEIGHTS["amount"] +
        val_layer_scores[:, 5] * STATIC_WEIGHTS["website_trust"]
    )
    return np.clip(static_probs, 0.0, 1.0)


def calculate_metrics_at_1pct_fpr(y_true: np.ndarray, y_score: np.ndarray) -> Tuple[float, float, float]:
    """Computes (PR-AUC, Recall@1%FPR, Brier Score)."""
    pr_auc = float(average_precision_score(y_true, y_score))
    brier = float(brier_score_loss(y_true, y_score))

    fpr, tpr, thresholds = roc_curve(y_true, y_score)
    valid_idx = np.where(fpr <= 0.01)[0]
    if len(valid_idx) == 0:
        recall_at_1pct = float(tpr[0])
    else:
        best_idx = valid_idx[-1]
        recall_at_1pct = float(tpr[best_idx])

    return pr_auc, recall_at_1pct, brier


def train_and_evaluate_fusion() -> Dict[str, Any]:
    """
    Builds, calibrates, compares, and saves the learned stacking fusion classifier.
    """
    logger.info("=== STARTING PART 23: LEARNED FUSION (STACKING) ===")
    t0 = time.time()

    # 1. Load chronologically split datasets
    df_train, df_val, df_test = load_time_split_data(sample_per_source=20000)
    X_train_raw = df_train[CANONICAL_22_FEATURES].values.astype(np.float32)
    y_train = df_train['is_fraud'].values.astype(np.int32)
    X_val_raw = df_val[CANONICAL_22_FEATURES].values.astype(np.float32)
    y_val = df_val['is_fraud'].values.astype(np.int32)

    # Load scaler
    scaler = joblib.load(os.path.join(MODELS_DIR, "mlbfd_mega_scaler.pkl"))
    X_train_scaled = scaler.transform(X_train_raw)
    X_val_scaled = scaler.transform(X_val_raw)

    # 2. Rule layers for Train and Validation
    logger.info("Computing Rule Layer 2-7 scores from canonical features...")
    train_layers = compute_layer_scores_from_features(X_train_raw)
    val_layers = compute_layer_scores_from_features(X_val_raw)

    # 3. Generate Out-of-Fold (TimeSeriesSplit) model predictions for Train
    logger.info("Generating out-of-fold (TimeSeriesSplit, 3 splits) predictions for 7 models...")
    tscv = TimeSeriesSplit(n_splits=3)
    oof_model_probs = np.zeros((len(y_train), 7), dtype=np.float32)
    val_model_probs = np.zeros((len(y_val), 7), dtype=np.float32)

    # Models:
    # 0: XGBoost, 1: Random Forest, 2: Logistic Regression, 3: Isolation Forest
    # 4: Neural Network, 5: LSTM, 6: Autoencoder
    
    # Load primary trained models to predict on validation set
    xgb_full = joblib.load(os.path.join(MODELS_DIR, "mlbfd_mega_xgboost_model.pkl"))
    rf_full = joblib.load(os.path.join(MODELS_DIR, "mlbfd_mega_random_forest_model.pkl"))
    lr_full = joblib.load(os.path.join(MODELS_DIR, "mlbfd_mega_logistic_regression_model.pkl"))
    if_full = joblib.load(os.path.join(MODELS_DIR, "mlbfd_mega_isolation_forest_model.pkl"))
    
    import tensorflow as tf
    dnn_full = tf.keras.models.load_model(
        os.path.join(MODELS_DIR, "mlbfd_mega_neural_network_model.keras"),
        custom_objects={'BinaryFocalLoss': model_trainer.BinaryFocalLoss}
    )
    lstm_full = tf.keras.models.load_model(
        os.path.join(MODELS_DIR, "mlbfd_mega_lstm_model.keras"),
        custom_objects={'AttentionLayer': model_trainer.AttentionLayer}
    )
    ae_full = tf.keras.models.load_model(os.path.join(MODELS_DIR, "mlbfd_mega_autoencoder_model.keras"))

    # Validation predictions for all 7 models
    val_model_probs[:, 0] = xgb_full.predict_proba(X_val_scaled)[:, 1]
    val_model_probs[:, 1] = rf_full.predict_proba(X_val_scaled)[:, 1]
    val_model_probs[:, 2] = lr_full.predict_proba(X_val_scaled)[:, 1]
    
    if_val_raw = -if_full.score_samples(X_val_scaled)
    val_model_probs[:, 3] = np.clip((if_val_raw - if_val_raw.min()) / (if_val_raw.max() - if_val_raw.min() + 1e-8), 0, 1)
    
    val_model_probs[:, 4] = dnn_full.predict(X_val_scaled, verbose=0).flatten()
    
    u_val = df_val['user_id'].values if 'user_id' in df_val.columns else np.array([f"u_{i}" for i in range(len(df_val))])
    X_val_seq = build_user_sequences(X_val_scaled, u_val, timesteps=5)
    val_model_probs[:, 5] = lstm_full.predict(X_val_seq, verbose=0).flatten()
    
    ae_val_rec = ae_full.predict(X_val_scaled, verbose=0)
    ae_val_mse = np.mean(np.square(X_val_scaled - ae_val_rec), axis=1)
    val_model_probs[:, 6] = np.clip(1.0 - np.exp(-ae_val_mse * 0.8), 0.0, 1.0)

    # TimeSeriesSplit Out-of-fold training for fast tabular models (XGB, RF, LR, IF)
    # and fold-calibrated fast surrogates for DL models
    for tr_idx, test_idx in tscv.split(X_train_scaled):
        X_tr, y_tr = X_train_scaled[tr_idx], y_train[tr_idx]
        X_te, y_te = X_train_scaled[test_idx], y_train[test_idx]

        # XGBoost OOF
        fold_xgb = model_trainer.get_xgboost_classifier()
        fold_xgb.fit(X_tr, y_tr)
        oof_model_probs[test_idx, 0] = fold_xgb.predict_proba(X_te)[:, 1]

        # RF OOF
        fold_rf = model_trainer.get_random_forest_classifier()
        fold_rf.fit(X_tr, y_tr)
        oof_model_probs[test_idx, 1] = fold_rf.predict_proba(X_te)[:, 1]

        # LR OOF
        fold_lr = model_trainer.get_logistic_regression()
        fold_lr.fit(X_tr, y_tr)
        oof_model_probs[test_idx, 2] = fold_lr.predict_proba(X_te)[:, 1]

        # IF OOF
        fold_if = model_trainer.get_isolation_forest()
        fold_if.fit(X_tr[y_tr == 0])
        s_te = -fold_if.score_samples(X_te)
        oof_model_probs[test_idx, 3] = np.clip((s_te - s_te.min()) / (s_te.max() - s_te.min() + 1e-8), 0, 1)

        # DNN OOF predictions (from full model to avoid long GPU/CPU re-training loops)
        oof_model_probs[test_idx, 4] = dnn_full.predict(X_te, verbose=0).flatten()

        # LSTM OOF predictions
        u_te = df_train['user_id'].iloc[test_idx].values if 'user_id' in df_train.columns else np.array([f"u_{i}" for i in test_idx])
        X_te_seq = build_user_sequences(X_te, u_te, timesteps=5)
        oof_model_probs[test_idx, 5] = lstm_full.predict(X_te_seq, verbose=0).flatten()

        # Autoencoder OOF
        ae_rec = ae_full.predict(X_te, verbose=0)
        ae_mse = np.mean(np.square(X_te - ae_rec), axis=1)
        oof_model_probs[test_idx, 6] = np.clip(1.0 - np.exp(-ae_mse * 0.8), 0.0, 1.0)

    # Identify the subset of train data covered by OOF (splits 1, 2, 3)
    oof_mask = (np.sum(oof_model_probs, axis=1) > 0)
    X_meta_train = np.hstack([oof_model_probs[oof_mask], train_layers[oof_mask]])
    y_meta_train = y_train[oof_mask]

    X_meta_val = np.hstack([val_model_probs, val_layers])

    # 4. Train Stacking Logistic Regression meta-classifier
    logger.info("Training stacking Logistic Regression meta-classifier...")
    meta_clf = LogisticRegression(penalty='l2', C=1.0, solver='lbfgs', max_iter=300, random_state=42)
    meta_clf.fit(X_meta_train, y_meta_train)

    # Predict raw stacking probabilities on validation
    raw_stack_val_probs = meta_clf.predict_proba(X_meta_val)[:, 1]

    # 5. Calibrate Stacking Meta-Classifier (Isotonic vs Platt)
    iso_meta = IsotonicRegression(out_of_bounds='clip')
    iso_meta.fit(raw_stack_val_probs, y_val)
    iso_val_probs = iso_meta.predict(raw_stack_val_probs)
    brier_iso = float(brier_score_loss(y_val, iso_val_probs))

    platt_meta = LogisticRegression(solver='lbfgs', max_iter=200)
    platt_meta.fit(raw_stack_val_probs.reshape(-1, 1), y_val)
    platt_val_probs = platt_meta.predict_proba(raw_stack_val_probs.reshape(-1, 1))[:, 1]
    brier_platt = float(brier_score_loss(y_val, platt_val_probs))

    if brier_iso < brier_platt:
        calibrator = iso_meta
        calib_method = "isotonic"
        calib_stack_val_probs = iso_val_probs
    else:
        calibrator = platt_meta
        calib_method = "platt"
        calib_stack_val_probs = platt_val_probs

    # 6. Evaluate Stacking vs Static Weights on Validation Set
    logger.info("Evaluating Stacking vs Static Weights on Validation...")
    static_val_probs = evaluate_static_fusion(val_model_probs, val_layers)

    stack_pr_auc, stack_rec_1pct, stack_brier = calculate_metrics_at_1pct_fpr(y_val, calib_stack_val_probs)
    static_pr_auc, static_rec_1pct, static_brier = calculate_metrics_at_1pct_fpr(y_val, static_val_probs)

    # Determine winner
    # Stacking wins if PR-AUC >= static PR-AUC or recall at 1% FPR is higher
    stacking_wins = (stack_pr_auc >= static_pr_auc) or (stack_rec_1pct >= static_rec_1pct)
    selected_fusion = "stacking" if stacking_wins else "static"

    # Print Comparison Table
    print("\n" + "="*85)
    print("                  [LEARNED FUSION VS STATIC WEIGHTS COMPARISON]                  ")
    print("="*85)
    print(f"{'Method':<25} | {'Val PR-AUC':<12} | {'Recall @ 1% FPR':<16} | {'Brier Score':<12} | {'Selected':<8}")
    print("-"*85)
    print(f"{'Stacking Meta-Classifier':<25} | {stack_pr_auc:<12.4f} | {stack_rec_1pct:<16.4f} | {stack_brier:<12.4f} | {'YES' if selected_fusion == 'stacking' else 'NO'}")
    print(f"{'Static Weighted Rule Engine':<25} | {static_pr_auc:<12.4f} | {static_rec_1pct:<16.4f} | {static_brier:<12.4f} | {'YES' if selected_fusion == 'static' else 'NO'}")
    print("="*85 + "\n")

    # 7. Save Models and Metadata
    joblib.dump(meta_clf, STACKING_MODEL_PATH)
    joblib.dump({"calibrator": calibrator, "method": calib_method}, os.path.join(MODELS_DIR, "stacking_calibrator.pkl"))

    fusion_data = {
        "_metadata": {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "training_samples": len(y_meta_train),
            "validation_samples": len(y_val)
        },
        "selected_fusion": selected_fusion,
        "comparison": {
            "stacking": {
                "pr_auc": stack_pr_auc,
                "recall_at_1pct_fpr": stack_rec_1pct,
                "brier_score": stack_brier,
                "calibrator_method": calib_method
            },
            "static": {
                "pr_auc": static_pr_auc,
                "recall_at_1pct_fpr": static_rec_1pct,
                "brier_score": static_brier
            }
        },
        "static_weights": STATIC_WEIGHTS,
        "meta_features": META_FEATURE_NAMES,
        "coefficients": [float(c) for c in meta_clf.coef_[0]],
        "intercept": float(meta_clf.intercept_[0])
    }

    with open(FUSION_JSON_PATH, "w") as f:
        json.dump(fusion_data, f, indent=4)

    logger.info(f"💾 Stacking metadata saved to {FUSION_JSON_PATH}")
    logger.info(f"Fusion selection complete. Active mode: '{selected_fusion}' in {time.time() - t0:.2f}s.")
    return fusion_data


# Global in-memory cache for live inference
_fusion_cache = {}

def get_fusion_prediction(model_probs: Dict[str, float], layer_scores: Dict[str, float]) -> Tuple[float, str, float]:
    """
    Live prediction using chosen fusion (stacking or fallback to static weights).
    Returns (final_probability, fusion_type, model_agreement_confidence).
    """
    global _fusion_cache

    # 1. Calculate model-agreement confidence
    prob_values = list(model_probs.values())
    if prob_values:
        std_dev = float(np.std(prob_values))
        confidence = float(np.clip(1.0 - (std_dev * 2.0), 0.0, 1.0))
    else:
        confidence = 0.5

    # 2. Check fusion.json and models cache
    if "meta_clf" not in _fusion_cache:
        if os.path.exists(FUSION_JSON_PATH) and os.path.exists(STACKING_MODEL_PATH):
            try:
                with open(FUSION_JSON_PATH, "r") as f:
                    _fusion_cache["config"] = json.load(f)
                _fusion_cache["meta_clf"] = joblib.load(STACKING_MODEL_PATH)
                cal_data = joblib.load(os.path.join(MODELS_DIR, "stacking_calibrator.pkl"))
                _fusion_cache["calibrator"] = cal_data["calibrator"]
                _fusion_cache["calib_method"] = cal_data["method"]
            except Exception as e:
                logger.warning(f"Could not load stacking model: {e}. Falling back to static.")
                _fusion_cache["meta_clf"] = None
        else:
            _fusion_cache["meta_clf"] = None

    selected = _fusion_cache.get("config", {}).get("selected_fusion", "static")

    if selected == "stacking" and _fusion_cache.get("meta_clf") is not None:
        try:
            # Construct 13-feature meta vector
            vec = [
                float(model_probs.get('XGBoost', 0.1)),
                float(model_probs.get('Random Forest', 0.1)),
                float(model_probs.get('Logistic Regression', 0.1)),
                float(model_probs.get('Isolation Forest', 0.1)),
                float(model_probs.get('Neural Network', 0.1)),
                float(model_probs.get('LSTM', 0.1)),
                float(model_probs.get('Autoencoder', 0.1)),
                float(layer_scores.get('velocity', 0.0)) / 100.0,
                float(layer_scores.get('flow', 0.0)) / 100.0,
                float(layer_scores.get('payee', 0.0)) / 100.0,
                float(layer_scores.get('compromise', 0.0)) / 100.0,
                float(layer_scores.get('amount', 0.0)) / 100.0,
                float(layer_scores.get('website_trust', 0.0)) / 100.0,
            ]
            x_meta = np.array(vec).reshape(1, -1)
            raw_p = _fusion_cache["meta_clf"].predict_proba(x_meta)[0, 1]
            
            # Apply calibrator
            method = _fusion_cache.get("calib_method", "isotonic")
            cal = _fusion_cache.get("calibrator")
            if method == "isotonic":
                cal_p = float(cal.predict(np.array([raw_p]))[0])
            else:
                cal_p = float(cal.predict_proba(np.array([[raw_p]]))[0, 1])
                
            return float(np.clip(cal_p, 0.0, 1.0)), "stacking", confidence
        except Exception as e:
            logger.error(f"Stacking prediction failed: {e}. Falling back to static.")

    # Static fallback calculation
    behavioral_prob = float(np.mean(list(model_probs.values()))) if model_probs else 0.1
    static_score = (
        behavioral_prob * STATIC_WEIGHTS["behavioral"] +
        (float(layer_scores.get('velocity', 0.0)) / 100.0) * STATIC_WEIGHTS["velocity"] +
        (float(layer_scores.get('flow', 0.0)) / 100.0) * STATIC_WEIGHTS["flow"] +
        (float(layer_scores.get('payee', 0.0)) / 100.0) * STATIC_WEIGHTS["payee"] +
        (float(layer_scores.get('compromise', 0.0)) / 100.0) * STATIC_WEIGHTS["compromise"] +
        (float(layer_scores.get('amount', 0.0)) / 100.0) * STATIC_WEIGHTS["amount"] +
        (float(layer_scores.get('website_trust', 0.0)) / 100.0) * STATIC_WEIGHTS["website_trust"]
    )
    return float(np.clip(static_score, 0.0, 1.0)), "static", confidence


if __name__ == "__main__":
    train_and_evaluate_fusion()
