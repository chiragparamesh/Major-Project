"""Repository-wide pytest bootstrap.

Runs before any test module is imported, so it can pin configuration that
`backend/config.py` reads at import time.

Why this file exists
--------------------
`create_app()` calls `init_db()`, which creates the SQLAlchemy engine from
`DATABASE_URL` *before* a test fixture can override `SQLALCHEMY_DATABASE_URI`.
Flask-SQLAlchemy 3.x caches engines in `init_app()` and explicitly ignores
later config changes, so a per-test `sqlite:///:memory:` override is a no-op.
Without this file every test run would use (and then `drop_all()`) the real
`backend/instance/mlbfd.sqlite3` database.

The test suite therefore runs against a throw-away SQLite file. This file does
not change what any test asserts; it only isolates the durability layer.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# env_loader must not override values pinned here.
os.environ["MLBFD_TESTING"] = "1"

# --- Isolate the database -------------------------------------------------
_TEST_DIR = Path(tempfile.mkdtemp(prefix="mlbfd_pytest_"))
_TEST_DB = _TEST_DIR / "mlbfd_test.sqlite3"
# Must be set before backend/config.Config is imported by any test module.
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"

# --- Deterministic, non-secret defaults for CI/local runs -----------------
# `backend/config.py` validates these at import time. Real values from a
# developer's .env still win because setdefault never overwrites.
os.environ.setdefault("MLBFD_SECRET_KEY", "pytest-only-mlbfd-secret-key-0123456789abcdef")
os.environ.setdefault("JWT_SECRET_KEY", "pytest-only-jwt-secret-key-0123456789abcdef")
os.environ.setdefault("HASH_PEPPER", "pytest-only-pepper-0123456789abcdef")
# Forced (not setdefault): the suite must never reach real SMTP/Telegram.
os.environ["EMAIL_DRY_RUN"] = "true"
os.environ["TELEGRAM_DRY_RUN"] = "true"
os.environ["TELEGRAM_POLLING_ENABLED"] = "false"
# Admin gate tests expect "no token = loopback only"; a developer .env token must not leak in.
os.environ["ADMIN_API_TOKEN"] = ""


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_DIR, ignore_errors=True)
