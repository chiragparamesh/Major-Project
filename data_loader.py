"""
data_loader.py - Root re-export module for backend.data_loader
"""
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import backend.data_loader as _bdl

from backend.data_loader import (
    CANONICAL_22_FEATURES,
    DATA_DIR,
    PaySimTemporalProcessor,
    IEEETemporalProcessor,
    load_paysim_parquet,
    load_ieee_parquet,
    load_baf_parquet,
    load_all_sources
)

if __name__ == "__main__":
    _bdl.load_all_sources()
