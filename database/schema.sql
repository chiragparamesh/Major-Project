-- Users table
CREATE TABLE IF NOT EXISTS users (
    id                   SERIAL PRIMARY KEY,
    user_id              VARCHAR(50) UNIQUE NOT NULL,
    full_name            VARCHAR(150),
    phone                TEXT,
    email                TEXT,
    upi_id               VARCHAR(255) UNIQUE,
    phone_hash           VARCHAR(64),
    email_hash           VARCHAR(64),
    upi_hash             VARCHAR(64) UNIQUE,
    status               VARCHAR(20) DEFAULT 'PENDING' NOT NULL,
    email_verified       BOOLEAN DEFAULT FALSE,
    telegram_verified    BOOLEAN DEFAULT FALSE,
    telegram_chat_id     TEXT,
    known_devices        JSONB DEFAULT '[]',
    security_question    VARCHAR(255),
    security_answer_hash VARCHAR(255),
    consent_at           TIMESTAMP,
    balance              DECIMAL(12,2) DEFAULT 0.00,
    login_pin_hash       VARCHAR(255),
    payment_pin_hash     VARCHAR(255),
    pin_hash             VARCHAR(255),
    login_failed_attempts INTEGER DEFAULT 0,
    login_locked_until   TIMESTAMP,
    payment_failed_attempts INTEGER DEFAULT 0,
    payment_locked_until TIMESTAMP,
    tokens_revoked_at    TIMESTAMP,
    reduced_limit_until  TIMESTAMP,
    daily_spent_date     VARCHAR(10),
    daily_spent_amount   DECIMAL(12,2) DEFAULT 0.00,
    phone_number         VARCHAR(20),
    device_token         TEXT,
    home_latitude        DECIMAL(10,8),
    home_longitude       DECIMAL(11,8),
    home_accuracy_m      FLOAT,
    home_location_source VARCHAR(20),
    home_area_name       VARCHAR(200),
    is_locked            BOOLEAN DEFAULT FALSE,
    failed_attempts      INTEGER DEFAULT 0,
    locked_until         TIMESTAMP,
    last_balance_reset_at TIMESTAMP,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_phone_hash ON users(phone_hash);
CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users(email_hash);
CREATE INDEX IF NOT EXISTS idx_users_upi_hash ON users(upi_hash);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);

-- Transactions table
CREATE TABLE IF NOT EXISTS transactions (
    id              SERIAL PRIMARY KEY,
    txn_id          VARCHAR(100) UNIQUE NOT NULL,
    user_id         VARCHAR(50) REFERENCES users(user_id),
    sender_upi      VARCHAR(100) NOT NULL,
    receiver_upi    VARCHAR(100) NOT NULL,
    amount          DECIMAL(12,2) NOT NULL,
    status          VARCHAR(30) NOT NULL,
    risk_score      DECIMAL(5,2),
    is_fraud        BOOLEAN DEFAULT FALSE,
    device_id       VARCHAR(100),
    latitude        DECIMAL(10,8),
    longitude       DECIMAL(11,8),
    accuracy_m      FLOAT,
    location_source VARCHAR(20),
    area_name       VARCHAR(200),
    hour            INTEGER,
    day_of_week     INTEGER,
    is_holiday      BOOLEAN DEFAULT FALSE,
    qr_code         TEXT,
    merchant_name   VARCHAR(255),
    mcc_code        VARCHAR(10),
    layer_scores    JSONB,
    flags           JSONB,
    ensemble_confidence DECIMAL(5,4),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP,
    failed_attempts INTEGER DEFAULT 0
);

-- User behavior baseline
CREATE TABLE IF NOT EXISTS user_behavior_baseline (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(50) UNIQUE REFERENCES users(user_id),
    avg_amount      DECIMAL(12,2),
    std_amount      DECIMAL(12,2),
    avg_hour        DECIMAL(5,2),
    txn_count       INTEGER DEFAULT 0,
    known_devices   JSONB DEFAULT '[]',
    known_payees    JSONB DEFAULT '[]',
    mcc_history     JSONB DEFAULT '{}',
    last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trusted payees
CREATE TABLE IF NOT EXISTS trusted_payees (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(50) REFERENCES users(user_id),
    payee_upi       VARCHAR(100) NOT NULL,
    nickname        VARCHAR(100),
    txn_count       INTEGER DEFAULT 0,
    total_amount    DECIMAL(12,2) DEFAULT 0,
    added_date      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, payee_upi)
);

-- Website reputation
CREATE TABLE IF NOT EXISTS website_reputation (
    id              SERIAL PRIMARY KEY,
    domain          VARCHAR(255) UNIQUE NOT NULL,
    is_scam         BOOLEAN DEFAULT FALSE,
    trust_score     DECIMAL(5,2),
    ssl_valid       BOOLEAN,
    domain_age_days INTEGER,
    google_safe     BOOLEAN,
    openphish_flagged BOOLEAN DEFAULT FALSE,
    last_checked    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Scam UPI list
CREATE TABLE IF NOT EXISTS scam_upis (
    id              SERIAL PRIMARY KEY,
    upi_id          VARCHAR(100) UNIQUE NOT NULL,
    reported_count  INTEGER DEFAULT 1,
    reported_by_count INTEGER DEFAULT 1,
    verified        BOOLEAN DEFAULT FALSE,
    added_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Scam reports (crowdsourced)
CREATE TABLE IF NOT EXISTS scam_reports (
    id              SERIAL PRIMARY KEY,
    reporter_id     VARCHAR(50) REFERENCES users(user_id),
    scam_upi        VARCHAR(100) NOT NULL,
    description     TEXT,
    reported_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verified        INTEGER DEFAULT 0
);

-- OTP table
CREATE TABLE IF NOT EXISTS otp_records (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(50) REFERENCES users(user_id),
    txn_id          VARCHAR(100),
    otp_hash        VARCHAR(255) NOT NULL,
    expires_at      TIMESTAMP NOT NULL,
    used            BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Feedback table
CREATE TABLE IF NOT EXISTS feedback (
    id              SERIAL PRIMARY KEY,
    txn_id          VARCHAR(100) REFERENCES transactions(txn_id),
    user_id         VARCHAR(50) REFERENCES users(user_id),
    is_fraud        BOOLEAN NOT NULL,
    predicted_fraud BOOLEAN,
    feedback_text   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(50),
    action          VARCHAR(100) NOT NULL,
    ip_address      VARCHAR(45),
    request_hash    VARCHAR(64),
    response_code   INTEGER,
    risk_score      DECIMAL(5,2),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Model metrics history
CREATE TABLE IF NOT EXISTS model_metrics (
    id              SERIAL PRIMARY KEY,
    model_name      VARCHAR(100) NOT NULL,
    auc_score       DECIMAL(6,4),
    recall          DECIMAL(6,4),
    precision       DECIMAL(6,4),
    f1_score        DECIMAL(6,4),
    accuracy        DECIMAL(6,4),
    trained_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_transactions_receiver_upi ON transactions(receiver_upi);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_trusted_payees_user_id ON trusted_payees(user_id);

-- OTP codes table
CREATE TABLE IF NOT EXISTS otp_codes (
    id                   SERIAL PRIMARY KEY,
    user_id              VARCHAR(50) NOT NULL,
    purpose              VARCHAR(50) NOT NULL,
    channel              VARCHAR(20) NOT NULL,
    code_hash            VARCHAR(64) NOT NULL,
    txn_id               VARCHAR(100),
    expires_at           TIMESTAMP NOT NULL,
    attempts             INTEGER DEFAULT 0 NOT NULL,
    max_attempts         INTEGER DEFAULT 3 NOT NULL,
    used_at              TIMESTAMP,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ip_address           VARCHAR(45),
    dual_group_id        VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_otp_codes_user_purpose ON otp_codes(user_id, purpose);
CREATE INDEX IF NOT EXISTS idx_otp_codes_ip ON otp_codes(ip_address);
CREATE INDEX IF NOT EXISTS idx_otp_codes_dual_group ON otp_codes(dual_group_id);

-- Telegram link tokens table (single-use 10-minute tokens)
CREATE TABLE IF NOT EXISTS telegram_link_tokens (
    token                VARCHAR(64) PRIMARY KEY,
    user_id              VARCHAR(50) NOT NULL,
    expires_at           TIMESTAMP NOT NULL,
    used                 BOOLEAN DEFAULT FALSE NOT NULL,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telegram_link_tokens_user ON telegram_link_tokens(user_id);

-- Token blocklist table (revoked JWTs)
CREATE TABLE IF NOT EXISTS token_blocklist (
    id                   SERIAL PRIMARY KEY,
    jti                  VARCHAR(36) NOT NULL,
    user_id              VARCHAR(50),
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_token_blocklist_jti ON token_blocklist(jti);
CREATE INDEX IF NOT EXISTS idx_token_blocklist_user ON token_blocklist(user_id);

-- Pending PIN changes table
CREATE TABLE IF NOT EXISTS pending_pin_changes (
    id                   SERIAL PRIMARY KEY,
    user_id              VARCHAR(50) NOT NULL,
    pin_type             VARCHAR(20) NOT NULL,
    new_pin_hash         VARCHAR(255) NOT NULL,
    expires_at           TIMESTAMP NOT NULL,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_pin_changes_user ON pending_pin_changes(user_id);

-- Password / PIN reset tokens table
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token                VARCHAR(64) PRIMARY KEY,
    user_id              VARCHAR(50) NOT NULL,
    expires_at           TIMESTAMP NOT NULL,
    used                 BOOLEAN DEFAULT FALSE NOT NULL,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user ON password_reset_tokens(user_id);
