"""
upi_simulator.py - Root re-export module for backend.upi_simulator
"""
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.upi_simulator import (
    UPISimulator,
    generate_and_save_simulator_data
)

if __name__ == "__main__":
    generate_and_save_simulator_data()
