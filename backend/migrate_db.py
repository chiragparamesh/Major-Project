#!/usr/bin/env python3
"""
MLBFD Database Migration Script
Upgrades the User model schema in mlbfd.sqlite3:
- Backs up mlbfd.sqlite3 prior to changes
- Adds user_id (unique), full_name, phone, email, upi_id, phone_hash, email_hash, upi_hash,
  status, email_verified, telegram_verified, telegram_chat_id, known_devices,
  security_question, security_answer_hash, consent_at, login_pin_hash, payment_pin_hash
- Encrypts sensitive fields (phone, email, upi_id, telegram_chat_id) with Fernet AES-256
- Computes HMAC-SHA256 lookup hashes for blind indexing
- Backfills existing users with valid normalized data
"""

import os
import sys
import shutil
import sqlite3
import re
from datetime import datetime
from pathlib import Path

# Add backend directory to path
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR / "backend" if (SCRIPT_DIR / "backend").exists() else SCRIPT_DIR
sys.path.insert(0, str(BACKEND_DIR))

from config import Config
from security import encrypt_val, decrypt_val, compute_lookup_hash

def find_sqlite_db_path() -> Path:
    candidates = [
        BACKEND_DIR / "instance" / "mlbfd.sqlite3",
        SCRIPT_DIR / "backend" / "instance" / "mlbfd.sqlite3",
        SCRIPT_DIR / "instance" / "mlbfd.sqlite3",
        BACKEND_DIR / "mlbfd.sqlite3",
        SCRIPT_DIR / "mlbfd.sqlite3",
    ]
    for c in candidates:
        if c.exists():
            return c
    # If not found yet, default to backend/instance/mlbfd.sqlite3
    target = BACKEND_DIR / "instance" / "mlbfd.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target

def backup_database(db_path: Path) -> Path:
    """Creates a timestamped backup and a .bak copy of the database file."""
    if not db_path.exists():
        print(f"[BACKUP] No existing database found at {db_path} to back up. Creating new one.")
        return None
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_file = db_path.parent / f"{db_path.stem}_backup_{timestamp}.sqlite3"
    shutil.copy2(db_path, backup_file)
    # Also maintain stable .bak copy
    stable_bak = db_path.parent / f"{db_path.name}.bak"
    shutil.copy2(db_path, stable_bak)
    print(f"[BACKUP] Created backup: {backup_file} ({os.path.getsize(backup_file)} bytes)")
    return backup_file

def normalize_phone(phone_input: str) -> str:
    if not phone_input:
        return ""
    cleaned = re.sub(r'[\s\-\(\)\.]', '', str(phone_input).strip())
    if cleaned.startswith('+91') and len(cleaned) == 13 and cleaned[3:].isdigit():
        return cleaned
    if cleaned.startswith('91') and len(cleaned) == 12 and cleaned.isdigit():
        return f"+{cleaned}"
    if cleaned.startswith('0') and len(cleaned) == 11 and cleaned.isdigit():
        return f"+91{cleaned[1:]}"
    if len(cleaned) == 10 and cleaned.isdigit():
        return f"+91{cleaned}"
    return cleaned

def run_migration():
    print("=" * 60)
    print("           MLBFD DATABASE MIGRATION & DATA UPGRADE          ")
    print("=" * 60)
    
    db_path = find_sqlite_db_path()
    print(f"[INIT] Database target: {db_path}")
    
    backup_path = backup_database(db_path)
    
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    
    # 1. Ensure users table exists with base schema
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id VARCHAR(50) UNIQUE NOT NULL,
        pin_hash VARCHAR(255),
        balance DECIMAL(12,2) DEFAULT 0.00,
        phone_number VARCHAR(20),
        device_token TEXT,
        home_latitude DECIMAL(10,8),
        home_longitude DECIMAL(11,8),
        is_locked BOOLEAN DEFAULT 0,
        failed_attempts INTEGER DEFAULT 0,
        locked_until TIMESTAMP,
        daily_limit DECIMAL(12,2) DEFAULT 50000.00,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    
    # 2. Check existing columns in users table
    cur.execute("PRAGMA table_info(users);")
    existing_cols = {col[1] for col in cur.fetchall()}
    print(f"[SCHEMA] Existing columns in 'users': {sorted(list(existing_cols))}")
    
    # Columns to add if missing
    new_columns = [
        ("full_name", "VARCHAR(150)"),
        ("phone", "TEXT"),
        ("email", "TEXT"),
        ("upi_id", "VARCHAR(255)"),
        ("phone_hash", "VARCHAR(64)"),
        ("email_hash", "VARCHAR(64)"),
        ("upi_hash", "VARCHAR(64)"),
        ("status", "VARCHAR(20) DEFAULT 'PENDING'"),
        ("email_verified", "BOOLEAN DEFAULT 0"),
        ("telegram_verified", "BOOLEAN DEFAULT 0"),
        ("telegram_chat_id", "TEXT"),
        ("known_devices", "TEXT DEFAULT '[]'"),
        ("security_question", "VARCHAR(255)"),
        ("security_answer_hash", "VARCHAR(255)"),
        ("consent_at", "TIMESTAMP"),
        ("login_pin_hash", "VARCHAR(255)"),
        ("payment_pin_hash", "VARCHAR(255)"),
        ("login_failed_attempts", "INTEGER DEFAULT 0"),
        ("login_locked_until", "TIMESTAMP"),
        ("payment_failed_attempts", "INTEGER DEFAULT 0"),
        ("payment_locked_until", "TIMESTAMP"),
        ("last_balance_reset_at", "TIMESTAMP"),
        ("home_accuracy_m", "FLOAT"),
        ("home_location_source", "VARCHAR(20)"),
        ("home_area_name", "VARCHAR(200)")
    ]
    
    for col_name, col_type in new_columns:
        if col_name not in existing_cols:
            print(f"[SCHEMA] Adding column to users: {col_name} ({col_type})")
            cur.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type};")

    # Check transaction columns
    cur.execute("PRAGMA table_info(transactions);")
    existing_txn_cols = [row[1] for row in cur.fetchall()]
    new_txn_cols = [
        ("accuracy_m", "FLOAT"),
        ("location_source", "VARCHAR(20)"),
        ("area_name", "VARCHAR(200)")
    ]
    for col_name, col_type in new_txn_cols:
        if col_name not in existing_txn_cols:
            print(f"[SCHEMA] Adding column to transactions: {col_name} ({col_type})")
            cur.execute(f"ALTER TABLE transactions ADD COLUMN {col_name} {col_type};")
            
    # Ensure otp_codes table exists
    cur.execute("""
    CREATE TABLE IF NOT EXISTS otp_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id VARCHAR(50) NOT NULL,
        purpose VARCHAR(50) NOT NULL,
        channel VARCHAR(20) NOT NULL,
        code_hash VARCHAR(64) NOT NULL,
        txn_id VARCHAR(100),
        expires_at TIMESTAMP NOT NULL,
        attempts INTEGER DEFAULT 0 NOT NULL,
        max_attempts INTEGER DEFAULT 3 NOT NULL,
        used_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
        ip_address VARCHAR(45),
        dual_group_id VARCHAR(64)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_otp_codes_user_purpose ON otp_codes(user_id, purpose);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_otp_codes_ip ON otp_codes(ip_address);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_otp_codes_dual_group ON otp_codes(dual_group_id);")

    # Legacy single-channel otp_records (old otp_manager.py) is unused; otp_codes is the only OTP store.
    # Dropped only when empty so no data is ever lost.
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='otp_records';")
    if cur.fetchone():
        cur.execute("SELECT COUNT(*) FROM otp_records;")
        legacy_rows = cur.fetchone()[0]
        if legacy_rows == 0:
            print("[SCHEMA] Dropping unused legacy table otp_records")
            cur.execute("DROP TABLE otp_records;")
        else:
            print(f"[SCHEMA] Keeping legacy otp_records ({legacy_rows} rows); it is no longer read")
    conn.commit()
    
    # 3. Create Indexes
    indexes = [
        ("idx_users_phone_hash", "CREATE INDEX IF NOT EXISTS idx_users_phone_hash ON users(phone_hash);"),
        ("idx_users_email_hash", "CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users(email_hash);"),
        ("idx_users_upi_hash", "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_upi_hash ON users(upi_hash);"),
        ("idx_users_status", "CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);"),
    ]
    for idx_name, idx_sql in indexes:
        try:
            cur.execute(idx_sql)
        except Exception as e:
            print(f"[SCHEMA] Index notice on {idx_name}: {e}")
    conn.commit()
    
    # 4. Migrate and Upgrade Existing Data
    cur.execute("SELECT id, user_id, pin_hash, balance, phone_number, created_at, phone_hash, upi_hash FROM users;")
    rows = cur.fetchall()
    print(f"[DATA] Found {len(rows)} user record(s) to inspect / upgrade.")
    
    used_phones = set()
    used_upis = set()
    
    for idx, (uid_pk, user_id, pin_hash, balance, phone_number, created_at, p_hash, u_hash) in enumerate(rows, start=1):
        if p_hash and u_hash:
            print(f"[DATA] User id={uid_pk} ('{user_id}') already migrated. Skipping.")
            continue

        # Determine normalized phone
        raw_phone = phone_number or f"+9198765432{idx:02d}"
        norm_phone = normalize_phone(raw_phone)
        
        # Avoid duplicate phone/UPI collision across legacy test accounts
        if norm_phone in used_phones:
            norm_phone = f"+919876543{idx:03d}"
        used_phones.add(norm_phone)
        
        ten_digit = norm_phone[3:]
        std_upi = f"{ten_digit}@mlbfd"
        if std_upi in used_upis:
            std_upi = f"9876543{idx:03d}@mlbfd"
        used_upis.add(std_upi)
        
        # Calculate ciphertexts and blind lookup hashes
        enc_phone = encrypt_val(norm_phone)
        enc_upi = encrypt_val(std_upi)
        email_addr = f"{user_id.split('@')[0]}@mlbfd.local"
        enc_email = encrypt_val(email_addr)
        
        new_phone_hash = compute_lookup_hash(norm_phone)
        new_upi_hash = compute_lookup_hash(std_upi)
        new_email_hash = compute_lookup_hash(email_addr)
        
        user_status = "ACTIVE" if (balance is not None and float(balance) > 0) else "PENDING"
        name_display = user_id.replace("_", " ").replace("@", " at ").title()
        now_iso = datetime.utcnow().isoformat()
        
        cur.execute("""
            UPDATE users SET
                full_name = COALESCE(full_name, ?),
                phone = ?,
                email = ?,
                upi_id = ?,
                phone_hash = ?,
                email_hash = ?,
                upi_hash = ?,
                status = ?,
                email_verified = 1,
                telegram_verified = 0,
                known_devices = COALESCE(known_devices, '[]'),
                consent_at = COALESCE(consent_at, ?),
                login_pin_hash = COALESCE(login_pin_hash, ?),
                payment_pin_hash = COALESCE(payment_pin_hash, ?)
            WHERE id = ?;
        """, (
            name_display,
            enc_phone,
            enc_email,
            enc_upi,
            new_phone_hash,
            new_email_hash,
            new_upi_hash,
            user_status,
            created_at or now_iso,
            pin_hash,
            pin_hash,
            uid_pk
        ))
        print(f"[DATA] Upgraded user id={uid_pk} ('{user_id}') -> Phone: {norm_phone}, UPI: {std_upi}, Status: {user_status}")
        
    conn.commit()
    conn.close()
    print("[SUCCESS] Database migration completed successfully.")
    return True

if __name__ == "__main__":
    run_migration()
