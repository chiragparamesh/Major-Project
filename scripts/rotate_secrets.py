"""
Generate fresh random MLBFD_SECRET_KEY, JWT_SECRET_KEY, HASH_PEPPER (and optionally
MLBFD_CLIENT_SECRET / ADMIN_API_TOKEN) and, only with --apply, write them into .env.

WARNING: MLBFD_SECRET_KEY is the Fernet key for every encrypted column (phone, email,
UPI id, Telegram chat id) AND the key of the blind lookup hashes and OTP HMACs.
Rotating it makes existing encrypted data and lookups unreadable, so --apply requires
--fresh-db, which MOVES (never deletes) the current SQLite database into backups/ so
the server starts with an empty database. All JWTs, freeze links and pending OTPs die.

Nothing is rotated automatically. Values are never printed.

Usage:
    python scripts/rotate_secrets.py                  # dry run: shows what would change
    python scripts/rotate_secrets.py --apply --fresh-db
"""
import argparse
import os
import re
import secrets
import shutil
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(REPO, ".env")
DB_CANDIDATES = [os.path.join(REPO, "backend", "instance", "mlbfd.sqlite3"),
                 os.path.join(REPO, "backend", "mlbfd.sqlite3"),
                 os.path.join(REPO, "mlbfd.sqlite3")]
KEYS = {
    "MLBFD_SECRET_KEY": lambda: secrets.token_hex(32),
    "JWT_SECRET_KEY": lambda: secrets.token_hex(32),
    "HASH_PEPPER": lambda: secrets.token_hex(24),
    "MLBFD_CLIENT_SECRET": lambda: secrets.token_urlsafe(32),
    "ADMIN_API_TOKEN": lambda: secrets.token_urlsafe(24),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write new values into .env (backup kept)")
    ap.add_argument("--fresh-db", action="store_true", help="move the SQLite database to backups/")
    a = ap.parse_args()

    if not os.path.exists(ENV):
        sys.exit(".env not found at repo root")
    text = open(ENV, encoding="utf-8").read()
    new = {k: gen() for k, gen in KEYS.items()}
    print("Will set: " + ", ".join(KEYS) + " (values hidden)")
    print(__doc__.split("Nothing is rotated")[0].strip().split("\n\n", 1)[1])
    if not a.apply:
        print("\nDry run only. Re-run with --apply --fresh-db to rotate.")
        return
    if not a.fresh_db:
        sys.exit("Refusing: rotating MLBFD_SECRET_KEY without --fresh-db leaves unreadable data.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups = os.path.join(REPO, "backups")
    os.makedirs(backups, exist_ok=True)
    shutil.copy2(ENV, os.path.join(backups, f".env.before_rotate_{stamp}"))
    for k, v in new.items():
        if re.search(rf"^{k}=.*$", text, flags=re.M):
            text = re.sub(rf"^{k}=.*$", f"{k}={v}", text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{k}={v}\n"
    with open(ENV, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    moved = 0
    for db in DB_CANDIDATES:
        for suffix in ("", "-wal", "-shm"):
            p = db + suffix
            if os.path.exists(p):
                shutil.move(p, os.path.join(backups, f"{os.path.basename(p)}.before_rotate_{stamp}"))
                moved += 1
    print(f"Rotated {len(new)} values in .env; .env backup and {moved} DB file(s) moved to backups/.")
    print("Next: python backend/migrate_db.py (if needed), restart the server, re-register users,")
    print("and rebuild the APK with --dart-define=MLBFD_CLIENT_SECRET=<value from .env>.")


if __name__ == "__main__":
    main()
