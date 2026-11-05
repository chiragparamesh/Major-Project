import sys
import os
import sqlite3

# Admin maintenance script: resets EVERY account balance. Requires --yes.
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)
if "--yes" not in sys.argv:
    sys.exit("Refusing: this resets ALL user balances to Rs. 100,000. Re-run with --yes.")

from app import create_app
from database import User
from db import db

print("=== 1. Resetting balances in PostgreSQL (Flask App Context) ===")
app = create_app()
with app.app_context():
    users = User.query.all()
    count = 0
    for u in users:
        u.balance = 100000.00
        count += 1
    db.session.commit()
    print(f"Updated {count} user accounts in PostgreSQL to balance = Rs. 100,000.00")

print("\n=== 2. Resetting balances in SQLite Database ===")
sqlite_path = os.path.join(backend_dir, "instance", "mlbfd.sqlite3")
if os.path.exists(sqlite_path):
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = 100000.00")
    sqlite_count = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"Updated {sqlite_count} user accounts in SQLite to balance = Rs. 100,000.00")
else:
    print("SQLite file not found at", sqlite_path)
