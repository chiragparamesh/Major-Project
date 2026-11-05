"""
train_all_models.py - Root runner for backend.train_all_models
"""
import os
import sys

backend_dir = os.path.join(os.path.dirname(__file__), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import backend.train_all_models as _btm
from backend.train_all_models import (
    train_and_evaluate_all,
    load_time_split_data,
    build_user_sequences,
    DATA_VERSION,
    MODELS_DIR
)

if __name__ == "__main__":
    train_and_evaluate_all(force_retrain=True)
