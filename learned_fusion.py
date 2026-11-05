"""
learned_fusion.py - Root runner for backend.learned_fusion
"""
import os
import sys

backend_dir = os.path.join(os.path.dirname(__file__), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import backend.learned_fusion as _blf
from backend.learned_fusion import (
    train_and_evaluate_fusion,
    get_fusion_prediction,
    FUSION_JSON_PATH,
    STACKING_MODEL_PATH,
    STATIC_WEIGHTS
)

if __name__ == "__main__":
    train_and_evaluate_fusion()
