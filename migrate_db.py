"""
migrate_db.py - Root runner for backend/migrate_db.py (the single implementation).
The previous full copy here had drifted (missing 7 columns and the otp_records cleanup).
"""
import os
import sys

backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.migrate_db import run_migration, find_sqlite_db_path, backup_database  # noqa: E402,F401

if __name__ == "__main__":
    run_migration()
