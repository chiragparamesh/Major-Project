import os
import time
import json
import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
    precision_recall_curve, auc, confusion_matrix, mean_squared_error, mean_absolute_error
)

# Add backend directory to sys.path
import sys
sys.path.append(r"d:\Major Project\MLBFD\backend")

from data_processor import load_and_preprocess_raw_data, FEATURE_COLS
from lstm_sequence import create_lstm_sequences
import predictor

def generate_all_assets():
    output_dir = r"d:\Major Project\paper_assets"
    os.makedirs(output_dir, exist_ok=True)
    models_dir = r"d:\Major Project\MLBFD\backend\models"

    print("Loading dataset for evaluation...")
    X_train_scaled, X_test_scaled, y_train_res, y_test = load_and_preprocess_raw_data(sample_size=15000)
    
    # Load all models
    print("Loading trained models...")
    predictor.load_prediction_assets()
    models_cache = predictor._models_cache
    
    # Evaluate each model
    results = []
    per_class_results = []
    cm_results = []
    latency_results = []

    # Prepare sequence for LSTM
    X_test_seq = create_lstm_sequences(X_test_scaled, timesteps=5)

    # Dictionary of test inputs
    model_inputs = {
        'XGBoost': X_test_scaled,
        'Random Forest': X_test_scaled,
        'Logistic Regression': X_test_scaled,
        'Isolation Forest': X_test_scaled,
        'Neural Network': X_test_scaled,
        'LSTM': X_test_seq,
        'Autoencoder': X_test_scaled
    }

    # Model file sizes
    model_file_names = {
        'XGBoost': 'mlbfd_mega_xgboost_model.pkl',
        'Random Forest': 'mlbfd_mega_random_forest_model.pkl',
        'Logistic Regression': 'mlbfd_mega_logistic_regression_model.pkl',
        'Isolation Forest': 'mlbfd_mega_isolation_forest_model.pkl',
        'Neural Network': 'mlbfd_mega_neural_network_model.keras',
        'LSTM': 'mlbfd_mega_lstm_model.keras',
        'Autoencoder': 'mlbfd_mega_autoencoder_model.keras'
    }

    model_probs_dict = {}

    for name in ['XGBoost', 'Random Forest', 'Logistic Regression', 'Isolation Forest', 'Neural Network', 'LSTM', 'Autoencoder']:
        print(f"Evaluating {name}...")
        m = models_cache[name]
        fpath = os.path.join(models_dir, model_file_names[name])
        file_size_mb = os.path.getsize(fpath) / (1024 * 1024) if os.path.exists(fpath) else 0.0

        start_time = time.time()
        if name in ['XGBoost', 'Random Forest', 'Logistic Regression']:
            probs = m.predict_proba(X_test_scaled)[:, 1]
            preds = (probs >= 0.5).astype(int)
        elif name == 'Isolation Forest':
            scores = -m.score_samples(X_test_scaled)
            raw_preds = m.predict(X_test_scaled)
            preds = np.where(raw_preds == -1, 1, 0)
            # MinMax scale scores for ROC/PR
            probs = (scores - scores.min()) / (scores.max() - scores.min() + 1e-8)
        elif name == 'Neural Network':
            probs = m.predict(X_test_scaled, verbose=0).flatten()
            preds = (probs >= 0.5).astype(int)
        elif name == 'LSTM':
            probs = m.predict(X_test_seq, verbose=0).flatten()
            preds = (probs >= 0.5).astype(int)
        elif name == 'Autoencoder':
            X_pred = m.predict(X_test_scaled, verbose=0)
            mse_scores = np.mean(np.square(X_test_scaled - X_pred), axis=1)
            probs = 1.0 / (1.0 + np.exp(-np.clip((mse_scores - np.mean(mse_scores)) / (np.std(mse_scores) + 1e-8), -10, 10)))
            preds = (probs >= 0.5).astype(int)

        elapsed_ms = (time.time() - start_time) * 1000
        latency_per_sample_us = (elapsed_ms / len(y_test)) * 1000

        model_probs_dict[name] = probs

        # Metrics
        acc = accuracy_score(y_test, preds)
        prec_macro = precision_score(y_test, preds, average='macro', zero_division=0)
        rec_macro = recall_score(y_test, preds, average='macro', zero_division=0)
        f1_macro = f1_score(y_test, preds, average='macro', zero_division=0)

        prec_weighted = precision_score(y_test, preds, average='weighted', zero_division=0)
        rec_weighted = recall_score(y_test, preds, average='weighted', zero_division=0)
        f1_weighted = f1_score(y_test, preds, average='weighted', zero_division=0)

        roc_auc = roc_auc_score(y_test, probs)
        p_curve, r_curve, _ = precision_recall_curve(y_test, probs)
        pr_auc = auc(r_curve, p_curve)

        cm = confusion_matrix(y_test, preds)
        tn, fp, fn, tp = cm.ravel() if cm.shape == (2, 2) else (0, 0, 0, 0)
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        # Per class
        p_c0 = precision_score(y_test, preds, pos_label=0, zero_division=0)
        r_c0 = recall_score(y_test, preds, pos_label=0, zero_division=0)
        f1_c0 = f1_score(y_test, preds, pos_label=0, zero_division=0)

        p_c1 = precision_score(y_test, preds, pos_label=1, zero_division=0)
        r_c1 = recall_score(y_test, preds, pos_label=1, zero_division=0)
        f1_c1 = f1_score(y_test, preds, pos_label=1, zero_division=0)

        results.append({
            'Model': name,
            'Accuracy': round(acc, 4),
            'Precision (Weighted)': round(prec_weighted, 4),
            'Recall (Weighted)': round(rec_weighted, 4),
            'F1-Score (Weighted)': round(f1_weighted, 4),
            'Precision (Macro)': round(prec_macro, 4),
            'Recall (Macro)': round(rec_macro, 4),
            'F1-Score (Macro)': round(f1_macro, 4),
            'ROC-AUC': round(roc_auc, 4),
            'PR-AUC': round(pr_auc, 4),
            'Sensitivity (TPR)': round(sensitivity, 4),
            'Specificity (TNR)': round(specificity, 4)
        })

        per_class_results.append({
            'Model': name,
            'Class 0 (Legit) Precision': round(p_c0, 4),
            'Class 0 (Legit) Recall': round(r_c0, 4),
            'Class 0 (Legit) F1': round(f1_c0, 4),
            'Class 1 (Fraud) Precision': round(p_c1, 4),
            'Class 1 (Fraud) Recall': round(r_c1, 4),
            'Class 1 (Fraud) F1': round(f1_c1, 4)
        })

        cm_results.append({
            'Model': name,
            'True Negatives (TN)': int(tn),
            'False Positives (FP)': int(fp),
            'False Negatives (FN)': int(fn),
            'True Positives (TP)': int(tp)
        })

        latency_results.append({
            'Model': name,
            'Model Size (MB)': round(file_size_mb, 2),
            'Total Inference Time (ms)': round(elapsed_ms, 2),
            'Latency per Sample (us)': round(latency_per_sample_us, 2)
        })

    # Evaluate Weighted MLBFD Ensemble
    print("Evaluating 7-Model MLBFD Ensemble...")
    weights = {
        'XGBoost': 0.25,
        'Random Forest': 0.15,
        'Neural Network': 0.15,
        'LSTM': 0.15,
        'Autoencoder': 0.15,
        'Logistic Regression': 0.10,
        'Isolation Forest': 0.05
    }

    ensemble_probs = np.zeros(len(y_test))
    for m_name, w in weights.items():
        ensemble_probs += model_probs_dict[m_name] * w

    ensemble_preds = (ensemble_probs >= 0.5).astype(int)

    acc = accuracy_score(y_test, ensemble_preds)
    prec_weighted = precision_score(y_test, ensemble_preds, average='weighted', zero_division=0)
    rec_weighted = recall_score(y_test, ensemble_preds, average='weighted', zero_division=0)
    f1_weighted = f1_score(y_test, ensemble_preds, average='weighted', zero_division=0)
    prec_macro = precision_score(y_test, ensemble_preds, average='macro', zero_division=0)
    rec_macro = recall_score(y_test, ensemble_preds, average='macro', zero_division=0)
    f1_macro = f1_score(y_test, ensemble_preds, average='macro', zero_division=0)
    roc_auc = roc_auc_score(y_test, ensemble_probs)
    p_curve, r_curve, _ = precision_recall_curve(y_test, ensemble_probs)
    pr_auc = auc(r_curve, p_curve)

    cm = confusion_matrix(y_test, ensemble_preds)
    tn, fp, fn, tp = cm.ravel() if cm.shape == (2, 2) else (0, 0, 0, 0)
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    p_c0 = precision_score(y_test, ensemble_preds, pos_label=0, zero_division=0)
    r_c0 = recall_score(y_test, ensemble_preds, pos_label=0, zero_division=0)
    f1_c0 = f1_score(y_test, ensemble_preds, pos_label=0, zero_division=0)

    p_c1 = precision_score(y_test, ensemble_preds, pos_label=1, zero_division=0)
    r_c1 = recall_score(y_test, ensemble_preds, pos_label=1, zero_division=0)
    f1_c1 = f1_score(y_test, ensemble_preds, pos_label=1, zero_division=0)

    total_size = sum(r['Model Size (MB)'] for r in latency_results)
    avg_latency = sum(r['Latency per Sample (us)'] for r in latency_results)

    results.append({
        'Model': 'MLBFD Ensemble (7-Model)',
        'Accuracy': round(acc, 4),
        'Precision (Weighted)': round(prec_weighted, 4),
        'Recall (Weighted)': round(rec_weighted, 4),
        'F1-Score (Weighted)': round(f1_weighted, 4),
        'Precision (Macro)': round(prec_macro, 4),
        'Recall (Macro)': round(rec_macro, 4),
        'F1-Score (Macro)': round(f1_macro, 4),
        'ROC-AUC': round(roc_auc, 4),
        'PR-AUC': round(pr_auc, 4),
        'Sensitivity (TPR)': round(sensitivity, 4),
        'Specificity (TNR)': round(specificity, 4)
    })

    per_class_results.append({
        'Model': 'MLBFD Ensemble (7-Model)',
        'Class 0 (Legit) Precision': round(p_c0, 4),
        'Class 0 (Legit) Recall': round(r_c0, 4),
        'Class 0 (Legit) F1': round(f1_c0, 4),
        'Class 1 (Fraud) Precision': round(p_c1, 4),
        'Class 1 (Fraud) Recall': round(r_c1, 4),
        'Class 1 (Fraud) F1': round(f1_c1, 4)
    })

    cm_results.append({
        'Model': 'MLBFD Ensemble (7-Model)',
        'True Negatives (TN)': int(tn),
        'False Positives (FP)': int(fp),
        'False Negatives (FN)': int(fn),
        'True Positives (TP)': int(tp)
    })

    latency_results.append({
        'Model': 'MLBFD Ensemble (7-Model)',
        'Model Size (MB)': round(total_size, 2),
        'Total Inference Time (ms)': 0.0, # parallel / sequential sum
        'Latency per Sample (us)': round(avg_latency, 2)
    })

    # Save DataFrames to CSV
    df_results = pd.DataFrame(results)
    df_results.to_csv(os.path.join(output_dir, "model_performance_comparison.csv"), index=False)

    df_per_class = pd.DataFrame(per_class_results)
    df_per_class.to_csv(os.path.join(output_dir, "per_class_metrics.csv"), index=False)

    df_cm = pd.DataFrame(cm_results)
    df_cm.to_csv(os.path.join(output_dir, "confusion_matrix_summary.csv"), index=False)

    df_lat = pd.DataFrame(latency_results)
    df_lat.to_csv(os.path.join(output_dir, "latency_and_size_summary.csv"), index=False)

    # Feature Importance (for XGBoost & Random Forest)
    xgb_m = models_cache['XGBoost']
    rf_m = models_cache['Random Forest']
    df_fi = pd.DataFrame({
        'Feature': FEATURE_COLS,
        'XGBoost Importance': xgb_m.feature_importances_,
        'Random Forest Importance': rf_m.feature_importances_
    }).sort_values(by='XGBoost Importance', ascending=False)
    df_fi.to_csv(os.path.join(output_dir, "feature_importance.csv"), index=False)

    # Layer Weights CSV
    layer_weights = [
        {'Layer': 'Layer 1 — Behavioral', 'Weight (%)': 38.0, 'Primary Technique': 'XGBoost/RF/NN/LSTM Ensemble Probability'},
        {'Layer': 'Layer 2 — Velocity', 'Weight (%)': 4.0, 'Primary Technique': 'Temporal Window Count (10m, 1h, 24h)'},
        {'Layer': 'Layer 3 — Transaction Flow', 'Weight (%)': 3.0, 'Primary Technique': 'NetworkX Directed Social Graph & Mule Topology'},
        {'Layer': 'Layer 4 — Payee Verification', 'Weight (%)': 28.0, 'Primary Technique': 'Scam Blacklist, QR Tampering & UPI Suffix Check'},
        {'Layer': 'Layer 5 — Account Compromise', 'Weight (%)': 15.0, 'Primary Technique': 'Device Binding, Geo-fence & Impossible Travel'},
        {'Layer': 'Layer 6 — Amount & Limit', 'Weight (%)': 10.0, 'Primary Technique': 'Baseline Z-score Deviation & Regulatory Bounds'},
        {'Layer': 'Layer 7 — Website Trust Score', 'Weight (%)': 2.0, 'Primary Technique': 'Typosquatting, SSL, WHOIS & OpenPhish Checks'}
    ]
    pd.DataFrame(layer_weights).to_csv(os.path.join(output_dir, "layer_weights.csv"), index=False)

    print("Generating high-res plots (300 DPI)...")

    # Plot 1: Model Comparison Bar Chart
    plt.figure(figsize=(14, 7), dpi=300)
    df_plot = df_results.melt(id_vars=['Model'], value_vars=['Accuracy', 'Precision (Weighted)', 'Recall (Weighted)', 'F1-Score (Weighted)', 'ROC-AUC'],
                              var_name='Metric', value_name='Score')
    sns.set_theme(style="whitegrid")
    ax = sns.barplot(data=df_plot, x='Model', y='Score', hue='Metric', palette='viridis')
    plt.title('MLBFD Model Performance Comparison across Metrics', fontsize=14, fontweight='bold', pad=15)
    plt.xticks(rotation=25, ha='right', fontsize=10)
    plt.ylim(0.0, 1.15)
    plt.legend(bbox_to_anchor=(1.02, 1), loc='upper left')
    
    # Add value labels
    for p in ax.patches:
        height = p.get_height()
        if height > 0:
            ax.annotate(f'{height:.2f}',
                        (p.get_x() + p.get_width() / 2., height),
                        ha='center', va='bottom', fontsize=7, rotation=90, xytext=(0, 3),
                        textcoords='offset points')

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "model_comparison_barchart.png"), dpi=300)
    plt.close()

    # Plot 2: ROC Curves
    plt.figure(figsize=(9, 7), dpi=300)
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#17becf']
    
    model_names_all = ['XGBoost', 'Random Forest', 'Logistic Regression', 'Isolation Forest', 'Neural Network', 'LSTM', 'Autoencoder']
    for idx, name in enumerate(model_names_all):
        p = model_probs_dict[name]
        auc_val = roc_auc_score(y_test, p)
        fpr, tpr, _ = matplotlib.mlab.roc_curve if hasattr(matplotlib.mlab, 'roc_curve') else (None, None, None)
        from sklearn.metrics import roc_curve
        fpr, tpr, _ = roc_curve(y_test, p)
        plt.plot(fpr, tpr, label=f'{name} (AUC = {auc_val:.4f})', color=colors[idx % len(colors)], linewidth=2)

    # Plot Ensemble ROC
    fpr_ens, tpr_ens, _ = roc_curve(y_test, ensemble_probs)
    auc_ens = roc_auc_score(y_test, ensemble_probs)
    plt.plot(fpr_ens, tpr_ens, label=f'MLBFD Ensemble (AUC = {auc_ens:.4f})', color='black', linewidth=3, linestyle='--')

    plt.plot([0, 1], [0, 1], 'k:', label='Random Chance (AUC = 0.5000)')
    plt.xlabel('False Positive Rate (FPR)', fontsize=12)
    plt.ylabel('True Positive Rate (TPR)', fontsize=12)
    plt.title('Receiver Operating Characteristic (ROC) Curves', fontsize=14, fontweight='bold', pad=15)
    plt.legend(loc='lower right', fontsize=9)
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "roc_curves.png"), dpi=300)
    plt.close()

    # Plot 3: Precision-Recall Curves
    plt.figure(figsize=(9, 7), dpi=300)
    for idx, name in enumerate(model_names_all):
        p = model_probs_dict[name]
        prec_c, rec_c, _ = precision_recall_curve(y_test, p)
        pr_auc_val = auc(rec_c, prec_c)
        plt.plot(rec_c, prec_c, label=f'{name} (PR-AUC = {pr_auc_val:.4f})', color=colors[idx % len(colors)], linewidth=2)

    prec_ens, rec_ens, _ = precision_recall_curve(y_test, ensemble_probs)
    pr_auc_ens = auc(rec_ens, prec_ens)
    plt.plot(rec_ens, prec_ens, label=f'MLBFD Ensemble (PR-AUC = {pr_auc_ens:.4f})', color='black', linewidth=3, linestyle='--')

    plt.xlabel('Recall', fontsize=12)
    plt.ylabel('Precision', fontsize=12)
    plt.title('Precision-Recall (PR) Curves', fontsize=14, fontweight='bold', pad=15)
    plt.legend(loc='lower left', fontsize=9)
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "pr_curves.png"), dpi=300)
    plt.close()

    # Plot 4: Confusion Matrices Grid
    fig, axes = plt.subplots(2, 4, figsize=(16, 8), dpi=300)
    axes = axes.flatten()

    all_cm_models = cm_results
    for idx, item in enumerate(all_cm_models):
        ax = axes[idx]
        cm_matrix = np.array([[item['True Negatives (TN)'], item['False Positives (FP)']],
                             [item['False Negatives (FN)'], item['True Positives (TP)']]])
        sns.heatmap(cm_matrix, annot=True, fmt='d', cmap='Blues', cbar=False, ax=ax,
                    xticklabels=['Legit (0)', 'Fraud (1)'], yticklabels=['Legit (0)', 'Fraud (1)'])
        ax.set_title(item['Model'], fontsize=11, fontweight='bold')
        ax.set_xlabel('Predicted Label', fontsize=9)
        ax.set_ylabel('True Label', fontsize=9)

    plt.suptitle('Confusion Matrix Summary across Models', fontsize=15, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "confusion_matrices.png"), dpi=300)
    plt.close()

    # Plot 5: Feature Importance Bar Chart
    plt.figure(figsize=(10, 6), dpi=300)
    sns.barplot(data=df_fi.head(10), x='XGBoost Importance', y='Feature', palette='crest')
    plt.title('Top 10 Feature Importances (XGBoost Classifier)', fontsize=14, fontweight='bold', pad=15)
    plt.xlabel('Gini / Gain Importance', fontsize=11)
    plt.ylabel('Feature Name', fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "feature_importance.png"), dpi=300)
    plt.close()

    print("All paper assets successfully generated in:", output_dir)

if __name__ == '__main__':
    generate_all_assets()
