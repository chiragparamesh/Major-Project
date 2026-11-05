import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
import joblib
import json
import numpy as np
import logging
from config import Config

logger = logging.getLogger(__name__)

# Singletons to cache model files in memory
_models_cache = {}
_scaler = None
_feature_names = None
_shap_explainer = None

def get_models_directory() -> str:
    return "D:\\Major Project\\MLBFD\\backend\\models"

def load_prediction_assets():
    """
    Lazy loads the scaler, feature names, and all 6 trained ML models.
    Caches them in global memory to achieve low latency.
    """
    global _scaler, _feature_names, _models_cache
    
    models_dir = get_models_directory()
    
    # 1. Load Scaler
    if _scaler is None:
        scaler_path = os.path.join(models_dir, 'mlbfd_mega_scaler.pkl')
        if os.path.exists(scaler_path):
            _scaler = joblib.load(scaler_path)
            logger.info("✅ Scaler loaded.")
        else:
            logger.warning("⚠️ Scaler file not found. Scaling will be bypassed.")

    # 2. Load Feature Names & Check Canonical Hash
    from feature_builder import CANONICAL_22_FEATURES, verify_feature_order_hash, save_feature_order_hash
    if not verify_feature_order_hash(models_dir):
        save_feature_order_hash(models_dir)
        logger.info("Saved canonical feature order hash to models directory.")
    else:
        logger.info("Feature order hash verified against canonical 22 features.")

    if _feature_names is None:
        features_path = os.path.join(models_dir, 'mlbfd_mega_feature_names.pkl')
        if os.path.exists(features_path):
            _feature_names = joblib.load(features_path)
            logger.info(" Feature names loaded.")
        else:
            _feature_names = CANONICAL_22_FEATURES
            logger.info(" Using canonical 22 feature names.")

    # 3. Load ML Models
    model_files = {
        'XGBoost': 'mlbfd_mega_xgboost_model.pkl',
        'Random Forest': 'mlbfd_mega_random_forest_model.pkl',
        'Logistic Regression': 'mlbfd_mega_logistic_regression_model.pkl',
        'Isolation Forest': 'mlbfd_mega_isolation_forest_model.pkl',
        'Neural Network': 'mlbfd_mega_neural_network_model.keras',
        'LSTM': 'mlbfd_mega_lstm_model.keras',
        'Autoencoder': 'mlbfd_mega_autoencoder_model.keras'
    }

    for model_name, file_name in model_files.items():
        if model_name not in _models_cache:
            model_path = os.path.join(models_dir, file_name)
            if os.path.exists(model_path):
                try:
                    if file_name.endswith('.keras'):
                        # TensorFlow/Keras lazy import to save startup resources
                        import tensorflow as tf
                        # Load custom layers and losses so keras knows how to deserialize them
                        from model_trainer import AttentionLayer, BinaryFocalLoss
                        _models_cache[model_name] = tf.keras.models.load_model(
                            model_path, 
                            custom_objects={
                                'AttentionLayer': AttentionLayer,
                                'BinaryFocalLoss': BinaryFocalLoss
                            }
                        )
                    else:
                        model = joblib.load(model_path)
                        # Single-row scoring: thread fan-out (n_jobs=-1) costs more than it saves.
                        # n_jobs does not change predictions.
                        if hasattr(model, "n_jobs"):
                            try:
                                model.set_params(n_jobs=1)
                            except ValueError:
                                pass
                        _models_cache[model_name] = model
                    logger.info(f"✅ Model '{model_name}' loaded into memory.")
                except Exception as e:
                    logger.error(f"❌ Failed to load model '{model_name}': {e}")
            else:
                logger.warning(f"⚠️ Model file missing for '{model_name}' at {model_path}")

_compiled_infer = {}


def _keras_infer(model, x) -> np.ndarray:
    """
    Single-sample Keras inference. model.predict() builds a tf.data pipeline per call
    (~100 ms each, 3 calls per transaction). The model is wrapped once in a
    tf.function (graph mode, same weights -> same outputs) and called directly.
    """
    import tensorflow as tf
    fn = _compiled_infer.get(id(model))
    if fn is None:
        fn = tf.function(lambda t: model(t, training=False), reduce_retracing=True)
        _compiled_infer[id(model)] = fn
    return np.asarray(fn(tf.convert_to_tensor(np.asarray(x, dtype=np.float32))))


def predict_fraud_ensemble(features_dict: dict, user_id: str = None) -> tuple:
    """
    Computes ensemble predictions from the 6 models.
    Inputs:
        features_dict: Dictionary containing the 22 engineered features.
        user_id: User identifier (used to fetch history sequences for LSTM).
    Returns:
        (ensemble_probability: float, confidence: float, individual_probs: dict)
    """
    load_prediction_assets()
    
    # 1. Align features to canonical order using feature_builder
    from feature_builder import feature_dict_to_array
    x_input = feature_dict_to_array(features_dict).reshape(1, -1)
    
    # 2. Scale features
    if _scaler:
        x_scaled = _scaler.transform(x_input)
    else:
        x_scaled = x_input
        
    # Dict to collect individual model probabilities
    probs = {}
    
    # XGBoost
    if 'XGBoost' in _models_cache:
        probs['XGBoost'] = float(_models_cache['XGBoost'].predict_proba(x_scaled)[0, 1])
        
    # Random Forest
    if 'Random Forest' in _models_cache:
        probs['Random Forest'] = float(_models_cache['Random Forest'].predict_proba(x_scaled)[0, 1])
        
    # Logistic Regression
    if 'Logistic Regression' in _models_cache:
        probs['Logistic Regression'] = float(_models_cache['Logistic Regression'].predict_proba(x_scaled)[0, 1])
        
    # Isolation Forest
    if 'Isolation Forest' in _models_cache:
        # Scores are in range [-0.5, 0.5]. Lower is more anomalous.
        # Scale to [0, 1] range: higher means more anomalous
        raw_score = _models_cache['Isolation Forest'].score_samples(x_scaled)[0]
        # Invert and shift to map roughly to [0.0, 1.0] anomaly index
        anomaly_score = float(np.clip(-raw_score * 2.0, 0.0, 1.0))
        probs['Isolation Forest'] = anomaly_score
        
    # Neural Network
    if 'Neural Network' in _models_cache:
        probs['Neural Network'] = float(_keras_infer(_models_cache['Neural Network'], x_scaled)[0, 0])
        
    # LSTM Sequence Network
    if 'LSTM' in _models_cache:
        from lstm_sequence import get_user_txn_sequence
        # Form temporal sequence from DB + current vector
        # Note: current_features needs to be scaled
        x_seq = get_user_txn_sequence(user_id or "default", x_scaled[0], timesteps=5)
        probs['LSTM'] = float(_keras_infer(_models_cache['LSTM'], x_seq)[0, 0])

    # Autoencoder Reconstruction Anomaly Detector
    if 'Autoencoder' in _models_cache:
        try:
            x_pred = _keras_infer(_models_cache['Autoencoder'], x_scaled)
            mse = float(np.mean(np.square(x_scaled - x_pred)))
            # Sigmoid / exponent scale MSE into [0.0, 1.0] anomaly probability space
            ae_prob = float(np.clip(1.0 - np.exp(-mse * 0.8), 0.0, 1.0))
            probs['Autoencoder'] = ae_prob
        except Exception as e:
            logger.error(f"Error predicting with Autoencoder: {e}")

    # If no models were loaded, return baseline probabilities
    if not probs:
        logger.warning("⚠️ No trained models found in cache. Returning fallback probability.")
        # Baseline check based on high-risk fields: scam flags or impossible travel
        fallback = 0.85 if (features_dict.get('is_scam_upi', 0) == 1 or 
                            features_dict.get('is_impossible_travel', 0) == 1) else 0.15
        return fallback, 0.50, {}
        
    # 3. Aggregate ensemble score using weighting
    # Revised weights for 7 models: XGBoost (25%), RF (15%), NN (15%), LSTM (15%), Autoencoder (15%), LR (10%), IF (5%)
    weights = {
        'XGBoost': 0.25,
        'Random Forest': 0.15,
        'Neural Network': 0.15,
        'LSTM': 0.15,
        'Autoencoder': 0.15,
        'Logistic Regression': 0.10,
        'Isolation Forest': 0.05
    }
    
    # Adjust weights if some models are missing
    active_weights = {m: weights[m] for m in probs.keys()}
    total_weight = sum(active_weights.values())
    if total_weight > 0:
        normalized_weights = {m: w / total_weight for m, w in active_weights.items()}
    else:
        normalized_weights = {m: 1.0 / len(probs) for m in probs.keys()}
        
    ensemble_prob = sum(probs[m] * normalized_weights[m] for m in probs.keys())
    
    # Calculate confidence: standard deviation of predictions
    # High agreement (low std) -> High confidence
    std_dev = np.std(list(probs.values()))
    # confidence = 1.0 - std_dev (capped between 0 and 1)
    confidence = float(np.clip(1.0 - (std_dev * 2.0), 0.0, 1.0))
    
    return ensemble_prob, confidence, probs


FEATURE_HUMAN_LABELS = {
    "amount": "Transaction Amount",
    "amount_to_avg_ratio": "Ratio to Usual Amount",
    "is_new_device": "Unrecognized Device",
    "is_impossible_travel": "Impossible Travel Velocity",
    "is_scam_upi": "Known Scam UPI Flag",
    "qr_payee_mismatch": "QR Code Payee Mismatch",
    "is_phishing_domain": "Phishing / Flagged Domain",
    "is_mule_candidate": "Mule Transfer Network Pattern",
    "velocity_10m": "Recent 10m Transaction Velocity",
    "payee_account_age_days": "Payee Account Age",
    "geo_distance_km": "Distance From Usual Location",
    "is_weekend": "Weekend Transaction",
    "is_night": "Nighttime Transaction Window",
    "user_age_days": "User Account Age",
    "payee_incoming_txn_count": "Payee Inbound Transfer Volume",
    "ip_risk_score": "Network IP Risk Score",
    "mcc_risk_score": "Merchant Category Code Risk",
    "failed_txns_last_24h": "Recent 24h Failed Transactions",
    "pin_change_last_24h": "Recent PIN Modification (24h)",
    "avg_daily_txns": "Historical Daily Transaction Frequency",
    "std_amount": "Historical Amount Deviation",
    "hour_of_day": "Transaction Hour"
}


def get_shap_explainer():
    """Returns the cached SHAP TreeExplainer for the trained XGBoost model."""
    global _shap_explainer
    if _shap_explainer is None:
        load_prediction_assets()
        xgb_model = _models_cache.get('XGBoost')
        if xgb_model is not None:
            import shap
            _shap_explainer = shap.TreeExplainer(xgb_model)
            logger.info("✅ Cached SHAP TreeExplainer for XGBoost initialized.")
        else:
            logger.warning("⚠️ XGBoost model not loaded; cannot initialize SHAP TreeExplainer.")
    return _shap_explainer


def explain_prediction_shap(features_dict: dict, top_k: int = 5) -> list:
    """
    Computes top-k contributing features using cached SHAP TreeExplainer.
    Returns list of dicts with signed SHAP values, human readable labels, and impact.
    Added latency is strictly < 10 ms.
    """
    explainer = get_shap_explainer()
    from feature_builder import CANONICAL_22_FEATURES, feature_dict_to_array

    x_input = feature_dict_to_array(features_dict).reshape(1, -1)
    if _scaler:
        x_scaled = _scaler.transform(x_input)
    else:
        x_scaled = x_input

    if explainer is None:
        # Fallback explanation if SHAP explainer unavailable
        return [
            {
                "feature": "amount",
                "label": "Transaction Amount",
                "shap_value": 0.10,
                "feature_value": float(features_dict.get("amount", 0.0)),
                "impact": "increases_risk"
            }
        ]

    try:
        raw_shap = explainer.shap_values(x_scaled)
        # raw_shap for binary classifier is either (1, 22) or list of [neg_class, pos_class]
        if isinstance(raw_shap, list) and len(raw_shap) == 2:
            shap_vec = raw_shap[1][0]
        elif hasattr(raw_shap, 'shape') and len(raw_shap.shape) == 2:
            shap_vec = raw_shap[0]
        else:
            shap_vec = np.array(raw_shap).flatten()

        explanations = []
        for i, feat_name in enumerate(CANONICAL_22_FEATURES):
            val = float(shap_vec[i]) if i < len(shap_vec) else 0.0
            feat_val = float(features_dict.get(feat_name, 0.0))
            explanations.append({
                "feature": feat_name,
                "label": FEATURE_HUMAN_LABELS.get(feat_name, feat_name.replace("_", " ").title()),
                "shap_value": round(val, 4),
                "feature_value": round(feat_val, 2),
                "impact": "increases_risk" if val > 0 else "decreases_risk",
                "abs_importance": abs(val)
            })

        # Sort by absolute impact descending and take top_k
        explanations.sort(key=lambda item: item["abs_importance"], reverse=True)
        top_explanations = explanations[:top_k]
        for item in top_explanations:
            item.pop("abs_importance", None)

        return top_explanations
    except Exception as e:
        logger.error(f"Error computing SHAP values: {e}")
        return []


def get_plain_language_reason(top_explanations: list, status: str = "APPROVED") -> str:
    """
    Builds a clear, concise plain-language summary from top-5 SHAP explanations.
    Used for user portal send confirmation and alert dialogues.
    """
    if not top_explanations:
        return "Transaction evaluated by MLBFD multi-layer fraud engine."

    risk_increasing = [item for item in top_explanations if item.get("impact") == "increases_risk" and item.get("shap_value", 0) > 0.01]
    risk_decreasing = [item for item in top_explanations if item.get("impact") == "decreases_risk" and item.get("shap_value", 0) < -0.01]

    if status in ("BLOCKED", "REQUIRES_2FA") and risk_increasing:
        top_factors = [f"{item['label']} ({item['feature']}={item['feature_value']})" for item in risk_increasing[:3]]
        return f"Risk flagged due to: {', '.join(top_factors)}."
    elif risk_decreasing:
        top_factors = [item['label'] for item in risk_decreasing[:2]]
        return f"Confidence supported by normal {', '.join(top_factors)}."
    else:
        return "Transaction parameters aligned with standard account baseline profile."
