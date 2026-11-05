"""
feature_builder.py - Root re-export module for backend.feature_builder
"""
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import backend.feature_builder as _bfb

from backend.feature_builder import (
    CANONICAL_22_FEATURES,
    FEATURE_ORDER_SHA256,
    build_feature_vector,
    feature_dict_to_array,
    get_feature_order_hash,
    save_feature_order_hash,
    verify_feature_order_hash
)

if __name__ == "__main__":
    print(f"Canonical 22 Features: {len(CANONICAL_22_FEATURES)}")
    print(f"Feature Order Hash: {get_feature_order_hash()}")
