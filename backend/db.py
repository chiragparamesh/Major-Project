import logging
# pyrefly: ignore [missing-import]
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from config import Config

# Initialize SQLAlchemy
db = SQLAlchemy()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db(app):
    """
    Initialize the Flask app with db. Try to connect to PostgreSQL.
    If PostgreSQL fails, fallback to SQLite.
    """
    pg_url = Config.DATABASE_URL
    sqlite_url = Config.SQLITE_DATABASE_URL
    
    # Check if SQLite is explicitly configured
    if pg_url.startswith("sqlite:"):
        app.config['SQLALCHEMY_DATABASE_URI'] = pg_url
        logger.info(f"✅ Using local SQLite database: {pg_url}")
    else:
        logger.info("Attempting to connect to PostgreSQL database...")
        try:
            # Create a temporary engine to test connection
            engine = create_engine(pg_url, connect_args={"connect_timeout": 3})
            connection = engine.connect()
            connection.close()
            
            # If successful, use PostgreSQL
            app.config['SQLALCHEMY_DATABASE_URI'] = pg_url
            logger.info("✅ Connected to PostgreSQL successfully!")
        except (OperationalError, Exception) as e:
            # PostgreSQL connection failed, fallback to SQLite
            logger.warning(
                f"⚠️ PostgreSQL connection failed. Error: {e}\n"
                f"🔄 Falling back to local SQLite database: {sqlite_url}"
            )
            app.config['SQLALCHEMY_DATABASE_URI'] = sqlite_url
        
    db.init_app(app)
    
    with app.app_context():
        # Create all tables if they don't exist
        db.create_all()
        
        # Schema migration fallbacks for users table
        cols_to_add = [
            ("full_name", "VARCHAR(150)"),
            ("phone", "TEXT"),
            ("email", "TEXT"),
            ("upi_id", "VARCHAR(255)"),
            ("phone_hash", "VARCHAR(64)"),
            ("email_hash", "VARCHAR(64)"),
            ("upi_hash", "VARCHAR(64)"),
            ("status", "VARCHAR(20) DEFAULT 'PENDING'"),
            ("email_verified", "BOOLEAN DEFAULT FALSE"),
            ("telegram_verified", "BOOLEAN DEFAULT FALSE"),
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
            ("daily_limit", "NUMERIC(12, 2) DEFAULT 50000.00"),
            ("tokens_revoked_at", "TIMESTAMP"),
            ("reduced_limit_until", "TIMESTAMP"),
            ("daily_spent_date", "VARCHAR(10)"),
            ("daily_spent_amount", "NUMERIC(12, 2) DEFAULT 0.00")
        ]
        for col_name, col_type in cols_to_add:
            try:
                db.session.execute(db.text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Schema indexes
        indexes_to_add = [
            "CREATE INDEX IF NOT EXISTS idx_users_phone_hash ON users(phone_hash)",
            "CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users(email_hash)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_upi_hash ON users(upi_hash)",
            "CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)",
        ]
        for idx_sql in indexes_to_add:
            try:
                db.session.execute(db.text(idx_sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Schema migration fallback: increase transactions sender_upi and receiver_upi column length
        try:
            db.session.execute(db.text("ALTER TABLE transactions ALTER COLUMN sender_upi TYPE VARCHAR(255)"))
            db.session.execute(db.text("ALTER TABLE transactions ALTER COLUMN receiver_upi TYPE VARCHAR(255)"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Add expires_at and failed_attempts to transactions if not already present
        for col_name, col_type in [("expires_at", "TIMESTAMP"), ("failed_attempts", "INTEGER DEFAULT 0")]:
            try:
                db.session.execute(db.text(f"ALTER TABLE transactions ADD COLUMN {col_name} {col_type}"))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Add user_id to token_blocklist if not already present
        try:
            db.session.execute(db.text("ALTER TABLE token_blocklist ADD COLUMN user_id VARCHAR(50)"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Backfill existing users with lookup hashes if missing
        try:
            from database import User
            from security import compute_lookup_hash, encrypt_val
            from user_manager import normalize_phone
            unhashed = User.query.filter((User.upi_hash == None) | (User.phone_hash == None)).all()
            used_upis = {u.get_decrypted_upi_id() for u in User.query.filter(User.upi_hash != None).all()}
            used_phones = {u.get_decrypted_phone() for u in User.query.filter(User.phone_hash != None).all()}
            for idx, u in enumerate(unhashed, start=1):
                raw_phone = u.phone_number or f"+919876543{idx:03d}"
                norm_phone = normalize_phone(raw_phone)
                if norm_phone in used_phones:
                    norm_phone = f"+91987654{idx:04d}"
                used_phones.add(norm_phone)
                
                ten_digit = norm_phone[3:] if norm_phone.startswith('+91') else norm_phone
                std_upi = f"{ten_digit}@mlbfd"
                if std_upi in used_upis:
                    std_upi = f"987654{idx:04d}@mlbfd"
                used_upis.add(std_upi)

                u.phone = encrypt_val(norm_phone)
                u.upi_id = encrypt_val(std_upi)
                u.phone_hash = compute_lookup_hash(norm_phone)
                u.upi_hash = compute_lookup_hash(std_upi)
                email_addr = f"{u.user_id.split('@')[0]}@mlbfd.local"
                u.email = encrypt_val(email_addr)
                u.email_hash = compute_lookup_hash(email_addr)
                u.full_name = u.user_id.replace('_', ' ').replace('@', ' at ').title()
                u.status = "ACTIVE" if (u.balance and float(u.balance) > 0) else "PENDING"
                u.email_verified = True
                u.login_pin_hash = u.login_pin_hash or u.pin_hash
                u.payment_pin_hash = u.payment_pin_hash or u.pin_hash
            if unhashed:
                db.session.commit()
                logger.info(f"✅ Backfilled {len(unhashed)} users with lookup hashes.")
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Notice on user backfill: {e}")

        logger.info("✅ Database tables initialized.")
