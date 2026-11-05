from datetime import timedelta
import os

from env_loader import load_env, env_str, env_bool

# Repo-root .env is primary and overrides stale OS variables of the same name
# (see env_loader). backend/.env only fills keys the root .env lacks.
ENV_OVERRIDDEN = load_env()

class Config:
    # Flask Settings
    SECRET_KEY = os.getenv("MLBFD_SECRET_KEY")
    if not SECRET_KEY or len(SECRET_KEY) < 32:
        raise ValueError("MLBFD_SECRET_KEY must be set in environment variables and be at least 32 characters long.")
    
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    if not JWT_SECRET_KEY or len(JWT_SECRET_KEY) < 32:
        raise ValueError("JWT_SECRET_KEY must be set in environment variables and be at least 32 characters long.")
        
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    
    # Database Settings
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "mlbfd_db")
    DB_USER = os.getenv("DB_USER", "mlbfd_user")
    DB_PASS = os.getenv("DB_PASS", "")  # PostgreSQL is optional; no default password in code
    
    # We build the URL dynamically, but also allow custom override
    DATABASE_URL = os.getenv(
        "DATABASE_URL", 
        f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    
    # SQLite Backup Database File Path
    SQLITE_DATABASE_URL = "sqlite:///mlbfd.sqlite3"
    
    # API Keys
    GOOGLE_SAFE_BROWSING_API_KEY = env_str("GOOGLE_SAFE_BROWSING_API_KEY", default="MOCK")
    FIREBASE_SERVER_KEY = os.getenv("FIREBASE_SERVER_KEY", "MOCK")  # legacy FCM key (deprecated by Google)
    # Service-account JSON for the Firebase Admin SDK; relative paths resolve from the repo root.
    FIREBASE_CREDENTIALS_FILE = env_str("FIREBASE_CREDENTIALS_FILE")
    OPENPHISH_API_KEY = os.getenv("OPENPHISH_API_KEY", "MOCK")


    # Email SMTP Settings (Gmail App Password / Brevo SMTP)
    # Canonical EMAIL_* names; legacy SMTP_* names are read only as fallback.
    EMAIL_HOST = env_str("EMAIL_HOST", "SMTP_HOST", default="smtp.gmail.com")
    EMAIL_PORT = int(env_str("EMAIL_PORT", "SMTP_PORT", default="587"))
    EMAIL_SMTP_MODE = env_str("EMAIL_SMTP_MODE", default="auto")
    EMAIL_USER = env_str("EMAIL_USER", "SMTP_USER")
    # SMTP relay login when it differs from the mailbox (Brevo: xxxx@smtp-brevo.com)
    EMAIL_SMTP_LOGIN = env_str("EMAIL_SMTP_LOGIN")
    EMAIL_PASSWORD = env_str("EMAIL_PASSWORD", "SMTP_PASS")
    EMAIL_FROM_NAME = env_str("EMAIL_FROM_NAME", default="MLBFD")
    EMAIL_FROM = env_str("EMAIL_FROM", "SMTP_FROM", "EMAIL_USER", default="no-reply@mlbfd.local")
    EMAIL_DRY_RUN = env_bool("EMAIL_DRY_RUN", False)

    # Telegram Bot Settings (Requests-based, BotFather token)
    TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
    TELEGRAM_BOT_USERNAME = env_str("TELEGRAM_BOT_USERNAME", default="mlbfd_otp_bot").lstrip("@")
    TELEGRAM_POLLING_ENABLED = env_bool("TELEGRAM_POLLING_ENABLED", True)
    TELEGRAM_DRY_RUN = env_bool("TELEGRAM_DRY_RUN", False)
    # Cloudflare Turnstile Settings (Bot Protection)
    TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
    TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
    
    # Application Logic Constants
    VIRTUAL_BALANCE = float(os.getenv("VIRTUAL_BALANCE", 100000.0))
    RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", 30))
    OTP_EXPIRY_SECONDS = int(os.getenv("OTP_EXPIRY_SECONDS", 300))
    SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", 15))
    TRUSTED_PAYEE_MIN_TXNS = int(os.getenv("TRUSTED_PAYEE_MIN_TXNS", 3))
    SCAM_LIST_REFRESH_HOURS = int(os.getenv("SCAM_LIST_REFRESH_HOURS", 6))
    
    # Reduced Limit Mode (24-hour post PIN reset)
    REDUCED_TXN_LIMIT = float(os.getenv("REDUCED_TXN_LIMIT", 10000.0))
    REDUCED_DAILY_LIMIT = float(os.getenv("REDUCED_DAILY_LIMIT", 25000.0))
    
    # Flask-SQLAlchemy Configuration
    SQLALCHEMY_TRACK_MODIFICATIONS = False
