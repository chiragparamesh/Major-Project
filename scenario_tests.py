"""
scenario_tests.py - Root runner for backend/scenario_tests.py (the single implementation).
"""
import os
import sys

backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.scenario_tests import *  # noqa: E402,F401,F403
from backend.scenario_tests import run_all_scenario_checks_and_generate_report  # noqa: E402

if __name__ == "__main__":
    run_all_scenario_checks_and_generate_report()
