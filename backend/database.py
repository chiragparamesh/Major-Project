from datetime import datetime
from db import db
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

# JSON type helper that automatically uses JSONB on PostgreSQL and JSON/Text on SQLite
JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(150), nullable=True)

    # Encrypted fields (stored as Fernet ciphertext)
    phone = db.Column(db.Text, nullable=True)  # Fernet encrypted +91XXXXXXXXXX
    email = db.Column(db.Text, nullable=True)  # Fernet encrypted email
    upi_id = db.Column(db.String(255), unique=True, nullable=True)  # Fernet encrypted <10-digit>@mlbfd
    telegram_chat_id = db.Column(db.Text, nullable=True)  # Fernet encrypted telegram chat id

    # Blind indexed HMAC-SHA256 lookup hashes
    phone_hash = db.Column(db.String(64), nullable=True, index=True)
    email_hash = db.Column(db.String(64), nullable=True, index=True)
    upi_hash = db.Column(db.String(64), unique=True, nullable=True, index=True)

    # Account status & Verification (PENDING, ACTIVE, FROZEN)
    status = db.Column(db.String(20), default='PENDING', nullable=False, index=True)
    email_verified = db.Column(db.Boolean, default=False)
    telegram_verified = db.Column(db.Boolean, default=False)

    # Security & Devices
    known_devices = db.Column(JSON_TYPE, default=lambda: [])
    security_question = db.Column(db.String(255), nullable=True)
    security_answer_hash = db.Column(db.String(255), nullable=True)
    consent_at = db.Column(db.DateTime, nullable=True)

    # Balance: 0 until activation
    balance = db.Column(db.Numeric(12, 2), default=0.00)

    # PIN Hashes
    login_pin_hash = db.Column(db.String(255), nullable=True)
    payment_pin_hash = db.Column(db.String(255), nullable=True)
    pin_hash = db.Column(db.String(255), nullable=True)  # legacy PIN compatibility

    # Dual PIN Lockouts stored in DB
    login_failed_attempts = db.Column(db.Integer, default=0)
    login_locked_until = db.Column(db.DateTime, nullable=True)
    payment_failed_attempts = db.Column(db.Integer, default=0)
    payment_locked_until = db.Column(db.DateTime, nullable=True)

    # Token Invalidation & Reduced Limits Mode (24-hr post PIN reset)
    tokens_revoked_at = db.Column(db.DateTime, nullable=True)
    reduced_limit_until = db.Column(db.DateTime, nullable=True)
    daily_spent_date = db.Column(db.String(10), nullable=True)
    daily_spent_amount = db.Column(db.Numeric(12, 2), default=0.00)

    # Legacy fields
    phone_number = db.Column(db.String(20), nullable=True)
    device_token = db.Column(db.Text, nullable=True)
    home_latitude = db.Column(db.Numeric(10, 8), nullable=True)
    home_longitude = db.Column(db.Numeric(11, 8), nullable=True)
    home_accuracy_m = db.Column(db.Float, nullable=True)
    home_location_source = db.Column(db.String(20), nullable=True)
    home_area_name = db.Column(db.String(200), nullable=True)
    is_locked = db.Column(db.Boolean, default=False)
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    daily_limit = db.Column(db.Numeric(12, 2), default=50000.00)
    last_balance_reset_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_login_locked(self, now: datetime = None) -> bool:
        now = now or datetime.utcnow()
        return bool(self.login_locked_until and self.login_locked_until > now)

    def is_payment_locked(self, now: datetime = None) -> bool:
        now = now or datetime.utcnow()
        return bool(self.payment_locked_until and self.payment_locked_until > now)

    def is_reduced_limit_active(self, now: datetime = None) -> bool:
        now = now or datetime.utcnow()
        return bool(self.reduced_limit_until and self.reduced_limit_until > now)

    # Helper methods for encrypted fields
    def get_decrypted_phone(self) -> str:
        from security import decrypt_val
        return decrypt_val(self.phone) if self.phone else (self.phone_number or "")

    def get_decrypted_email(self) -> str:
        from security import decrypt_val
        return decrypt_val(self.email) if self.email else ""

    def get_decrypted_upi_id(self) -> str:
        from security import decrypt_val
        return decrypt_val(self.upi_id) if self.upi_id else ""

    def get_decrypted_telegram_chat_id(self) -> str:
        from security import decrypt_val
        return decrypt_val(self.telegram_chat_id) if self.telegram_chat_id else ""

    def activate_account(self, initial_balance: float = 100000.00):
        """Activates account and initializes virtual balance"""
        self.status = "ACTIVE"
        if float(self.balance or 0.0) == 0.0:
            self.balance = initial_balance

    # Relationships
    transactions = db.relationship('Transaction', backref='user', lazy=True)
    baseline = db.relationship('UserBehaviorBaseline', backref='user', uselist=False, lazy=True)
    trusted_payees = db.relationship('TrustedPayee', backref='user', lazy=True)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    txn_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('users.user_id'), nullable=False, index=True)
    sender_upi = db.Column(db.String(255), nullable=False)
    receiver_upi = db.Column(db.String(255), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(30), nullable=False)  # APPROVED, APPROVED_WITH_WARNING, REQUIRES_2FA, BLOCKED
    risk_score = db.Column(db.Numeric(5, 2))
    is_fraud = db.Column(db.Boolean, default=False)
    device_id = db.Column(db.String(100))
    latitude = db.Column(db.Numeric(10, 8))
    longitude = db.Column(db.Numeric(11, 8))
    accuracy_m = db.Column(db.Float, nullable=True)
    location_source = db.Column(db.String(20), nullable=True)
    area_name = db.Column(db.String(200), nullable=True)
    hour = db.Column(db.Integer)
    day_of_week = db.Column(db.Integer)
    is_holiday = db.Column(db.Boolean, default=False)
    qr_code = db.Column(db.Text)
    merchant_name = db.Column(db.String(255))
    mcc_code = db.Column(db.String(10))
    layer_scores = db.Column(JSON_TYPE)
    flags = db.Column(JSON_TYPE)
    ensemble_confidence = db.Column(db.Numeric(5, 4))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    failed_attempts = db.Column(db.Integer, default=0, nullable=True)

class UserBehaviorBaseline(db.Model):
    __tablename__ = 'user_behavior_baseline'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('users.user_id'), unique=True, nullable=False, index=True)
    avg_amount = db.Column(db.Numeric(12, 2), default=0.0)
    std_amount = db.Column(db.Numeric(12, 2), default=0.0)
    avg_hour = db.Column(db.Numeric(5, 2), default=0.0)
    txn_count = db.Column(db.Integer, default=0)
    known_devices = db.Column(JSON_TYPE, default=lambda: [])
    known_payees = db.Column(JSON_TYPE, default=lambda: [])
    mcc_history = db.Column(JSON_TYPE, default=lambda: {})
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TrustedPayee(db.Model):
    __tablename__ = 'trusted_payees'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('users.user_id'), nullable=False, index=True)
    payee_upi = db.Column(db.String(100), nullable=False)
    nickname = db.Column(db.String(100))
    txn_count = db.Column(db.Integer, default=0)
    total_amount = db.Column(db.Numeric(12, 2), default=0.0)
    added_date = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'payee_upi', name='_user_payee_uc'),)

class WebsiteReputation(db.Model):
    __tablename__ = 'website_reputation'
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255), unique=True, nullable=False, index=True)
    is_scam = db.Column(db.Boolean, default=False)
    trust_score = db.Column(db.Numeric(5, 2), default=0.0)
    ssl_valid = db.Column(db.Boolean, default=False)
    domain_age_days = db.Column(db.Integer, default=-1)
    google_safe = db.Column(db.Boolean, default=True)
    openphish_flagged = db.Column(db.Boolean, default=False)
    last_checked = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScamUpi(db.Model):
    __tablename__ = 'scam_upis'
    id = db.Column(db.Integer, primary_key=True)
    upi_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    reported_count = db.Column(db.Integer, default=1)
    reported_by_count = db.Column(db.Integer, default=1)
    verified = db.Column(db.Boolean, default=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScamReport(db.Model):
    __tablename__ = 'scam_reports'
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.String(50), db.ForeignKey('users.user_id'))
    scam_upi = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    reported_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified = db.Column(db.Integer, default=0)

class OtpCode(db.Model):
    __tablename__ = 'otp_codes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False, index=True)
    purpose = db.Column(db.String(50), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False)
    code_hash = db.Column(db.String(64), nullable=False)
    txn_id = db.Column(db.String(100), nullable=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=3, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True, index=True)
    dual_group_id = db.Column(db.String(64), nullable=True, index=True)

class Feedback(db.Model):
    __tablename__ = 'feedback'
    id = db.Column(db.Integer, primary_key=True)
    txn_id = db.Column(db.String(100), db.ForeignKey('transactions.txn_id'), nullable=False)
    user_id = db.Column(db.String(50), db.ForeignKey('users.user_id'), nullable=False)
    is_fraud = db.Column(db.Boolean, nullable=False)
    predicted_fraud = db.Column(db.Boolean)
    feedback_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), index=True)
    action = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(45))
    request_hash = db.Column(db.String(64))
    response_code = db.Column(db.Integer)
    risk_score = db.Column(db.Numeric(5, 2))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ModelMetrics(db.Model):
    __tablename__ = 'model_metrics'
    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(100), nullable=False)
    auc_score = db.Column(db.Numeric(6, 4))
    recall = db.Column(db.Numeric(6, 4))
    precision = db.Column(db.Numeric(6, 4))
    f1_score = db.Column(db.Numeric(6, 4))
    accuracy = db.Column(db.Numeric(6, 4))
    trained_at = db.Column(db.DateTime, default=datetime.utcnow)

class TokenBlocklist(db.Model):
    __tablename__ = 'token_blocklist'
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, index=True)
    user_id = db.Column(db.String(50), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TelegramLinkToken(db.Model):
    __tablename__ = 'telegram_link_tokens'
    token = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.String(50), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class PendingPinChange(db.Model):
    __tablename__ = 'pending_pin_changes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False, index=True)
    pin_type = db.Column(db.String(20), nullable=False)
    new_pin_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'
    token = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.String(50), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class AccountFreezeToken(db.Model):
    __tablename__ = 'account_freeze_tokens'
    token = db.Column(db.String(255), primary_key=True)
    user_id = db.Column(db.String(50), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class SignupIpLog(db.Model):
    __tablename__ = 'signup_ip_logs'
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.String(50), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


def find_user_by_upi_or_phone(identifier: str):
    """Convenience proxy to find_user_by_upi_or_phone in user_manager"""
    from user_manager import find_user_by_upi_or_phone as _finder
    return _finder(identifier)

