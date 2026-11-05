"""
MLBFD Production WSGI Server using Waitress
Serves the Flask application on 0.0.0.0:5000 with 8 worker threads.
Enforces SQLite WAL mode, validates critical security keys, and handles initialization.
"""
import os
import sys
import sqlite3
import functools

print = functools.partial(print, flush=True)  # banner visible even when stdout is redirected

# 1. Load environment variables from repo root and backend/.env
repo_root = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(repo_root, "backend")

# Insert backend directory into sys.path
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from env_loader import load_env  # noqa: E402

# Root .env overrides stale OS variables; a server started before an .env edit must be restarted.
load_env()

# 2. Validate critical secrets on startup
REQUIRED_SECRETS = [
    ("MLBFD_SECRET_KEY", 32),
    ("JWT_SECRET_KEY", 32),
    ("HASH_PEPPER", 16)
]

missing_or_invalid = []
for secret_name, min_len in REQUIRED_SECRETS:
    val = os.getenv(secret_name)
    if not val or len(val) < min_len:
        missing_or_invalid.append(f"{secret_name} (must be at least {min_len} chars)")

if missing_or_invalid:
    error_msg = "CRITICAL SECURITY CONFIGURATION ERROR:\nMissing or invalid environment variables:\n - " + "\n - ".join(missing_or_invalid)
    print(error_msg, file=sys.stderr)
    raise RuntimeError(error_msg)

# 3. Import app factory and database
from app import create_app
from db import db
import waitress

def enforce_sqlite_wal(app):
    """Ensure SQLite database uses Write-Ahead Logging (WAL) and synchronous=NORMAL."""
    with app.app_context():
        try:
            # Execute directly via SQLAlchemy session
            db.session.execute(db.text("PRAGMA journal_mode=WAL;"))
            db.session.execute(db.text("PRAGMA synchronous=NORMAL;"))
            db.session.commit()
            print("[INFO] SQLite WAL mode and synchronous=NORMAL successfully configured.")
        except Exception as e:
            print(f"[WARN] SQLite WAL PRAGMA via session: {e}")

    # Also attempt direct sqlite3 connection if db file exists
    db_paths = [
        os.path.join(backend_dir, "instance", "mlbfd.sqlite3"),
        os.path.join(backend_dir, "mlbfd.sqlite3"),
        os.path.join(repo_root, "mlbfd.sqlite3"),
    ]
    for p in db_paths:
        if os.path.exists(p):
            try:
                conn = sqlite3.connect(p)
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
                conn.commit()
                conn.close()
                print(f"[INFO] SQLite WAL mode confirmed on {p}")
            except Exception as e:
                print(f"[WARN] Direct SQLite WAL pragma on {p}: {e}")

def print_otp_banner():
    """Loud OTP readiness warnings; names/status only, never values."""
    import otp_service
    from env_loader import load_env
    warnings = otp_service.startup_banner_lines()
    overridden = load_env()
    if overridden:
        warnings.append(f".env overrides stale OS variables: {', '.join(sorted(overridden))}")
    if warnings:
        print("!" * 70)
        print("  OTP DELIVERY WARNINGS")
        for w in warnings:
            print(f"  !! {w}")
        print("  Run: python backend/otp_doctor.py --email-test / --telegram-test")
        print("!" * 70)
    else:
        print("  OTP channels configured (EMAIL + TELEGRAM). Probing SMTP login in the background...")

    def _probe():
        from email_sender import probe_smtp_login
        if otp_service.channel_readiness()["email"]["dry_run"]:
            return
        ok, detail = probe_smtp_login()
        if ok:
            print(f"  [OTP] {detail}")
        else:
            print("!" * 70)
            print(f"  !! EMAIL OTP WILL FAIL: {detail}")
            print("  !! Fix EMAIL_PASSWORD (Gmail app password), restart, run otp_doctor.py --email-test")
            print("!" * 70)
    import threading
    threading.Thread(target=_probe, daemon=True, name="smtp-probe").start()


def lan_address():
    """This machine's address on the local network (no traffic is sent; UDP connect only picks the route)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def ensure_port_free(host: str, port: int):
    """
    Windows lets a second process bind a port that is already in use, so an old server
    (with old code and old .env values) silently keeps answering. Refuse to start instead.
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind((host, port))
    except OSError:
        print(f"[ERROR] Port {port} is already in use by another process (probably an older MLBFD server).",
              file=sys.stderr)
        print(f"        Find it: netstat -ano | findstr :{port}   then: Stop-Process -Id <PID>", file=sys.stderr)
        sys.exit(1)
    finally:
        s.close()


def main():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("FLASK_PORT", 5000)))
    ensure_port_free(host, port)
    threads = int(os.getenv("WAITRESS_THREADS", 8))

    print("=" * 70)
    print("  MLBFD: Machine Learning Based Fraud Detection Server")
    print("=" * 70)
    print(f"  Local Portal:         http://localhost:{port}/")
    print(f"  User Login:           http://localhost:{port}/user/login")
    print(f"  Admin Portal:         http://localhost:{port}/admin")
    print(f"  Alerts Queue:         http://localhost:{port}/admin/alerts")
    print(f"  API Endpoint:         http://localhost:{port}/api")
    lan_ip = lan_address()
    if lan_ip:
        print(f"  SHARE ON SAME WI-FI:  http://{lan_ip}:{port}/user/register   (other laptops; admin stays on this laptop)")
    print(f"  Network Host:         http://{host}:{port}/")
    print(f"  Server Engine:        Waitress WSGI ({threads} worker threads)")
    print("=" * 70)
    print("  To expose securely via Cloudflare Tunnel:")
    print(f"    cloudflared tunnel --url http://localhost:{port}")
    print("=" * 70)

    app = create_app()
    print_otp_banner()

    # Trigger db.create_all() inside app context
    with app.app_context():
        db.create_all()

    enforce_sqlite_wal(app)

    print(f"\n[READY] Waitress server listening on http://{host}:{port} with {threads} threads...\n")
    # cloudflared connects from 127.0.0.1 and sets X-Forwarded-Proto: https. Trusting only
    # that header from the local tunnel makes request.host_url https:// (freeze links in
    # emails/Telegram). Client IPs are resolved separately by security.client_ip().
    waitress.serve(app, host=host, port=port, threads=threads,
                   trusted_proxy="127.0.0.1", trusted_proxy_headers={"x-forwarded-proto"},
                   clear_untrusted_proxy_headers=False)

if __name__ == "__main__":
    main()

