"""
calibrate_and_tune.py - Root runner for backend.calibrate_and_tune
"""
import os
import sys

backend_dir = os.path.join(os.path.dirname(__file__), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import backend.calibrate_and_tune as _bct
from backend.calibrate_and_tune import run_tuning_and_calibration

if __name__ == "__main__":
    run_tuning_and_calibration()
