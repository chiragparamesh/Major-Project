import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from db import db
from database import User, OtpCode
from otp_service import (
    issue, verify, issue_dual, verify_dual,
    FakeClock, set_clock, reset_clock, get_clock,
    MockOtpSender, set_sender, get_sender,
    OtpRateLimitError, OtpCooldownError,
    hash_code_hmac
)

@pytest.fixture(scope="module")
def app_ctx():
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        yield app

@pytest.fixture(autouse=True)
def setup_teardown_clock_and_sender(app_ctx):
    # Setup fresh fake clock starting at fixed point
    clock = FakeClock(datetime(2026, 1, 1, 12, 0, 0))
    set_clock(clock)
    mock_sender = MockOtpSender()
    set_sender(mock_sender)

    # Clean up test user otp_codes
    OtpCode.query.filter(OtpCode.user_id.like("otp_test_%")).delete()
    db.session.commit()

    yield

    reset_clock()
    OtpCode.query.filter(OtpCode.user_id.like("otp_test_%")).delete()
    db.session.commit()

def test_otp_codes_table_schema(app_ctx):
    # Verify all expected columns are present on OtpCode model
    required_cols = [
        "id", "user_id", "purpose", "channel", "code_hash",
        "txn_id", "expires_at", "attempts", "max_attempts",
        "used_at", "created_at", "ip_address", "dual_group_id"
    ]
    for col in required_cols:
        assert hasattr(OtpCode, col), f"Missing column {col} on OtpCode table"

def test_otp_expiry_with_fake_clock(app_ctx):
    clock = get_clock()
    user_id = "otp_test_expiry_user"
    purpose = "LOGIN_NEW_DEVICE"
    channel = "EMAIL"

    # Issue code at T=12:00:00
    code = issue(user_id, purpose, channel)
    assert len(code) == 6 and code.isdigit()

    rec = OtpCode.query.filter_by(user_id=user_id, channel=channel).first()
    assert rec.expires_at == datetime(2026, 1, 1, 12, 5, 0)
    assert rec.code_hash == hash_code_hmac(code)

    # Advance clock to 4 minutes 59 seconds (still valid)
    clock.advance(seconds=299)
    # Verification should succeed
    assert verify(user_id, purpose, channel, code) is True

    # Now test an expired code:
    # Advance clock by 31 seconds to bypass cooldown and issue new code
    clock.advance(seconds=31)
    code2 = issue(user_id, purpose, channel)
    # Advance clock by 5 minutes and 1 second -> expired!
    clock.advance(minutes=5, seconds=1)
    assert verify(user_id, purpose, channel, code2) is False

def test_otp_attempts_lockout(app_ctx):
    user_id = "otp_test_attempts_user"
    purpose = "TRANSACTION"
    channel = "EMAIL"
    txn_id = "TXN_ATTEMPTS_01"

    code = issue(user_id, purpose, channel, txn_id=txn_id)

    # Wrong attempt 1 -> fails
    assert verify(user_id, purpose, channel, "000000", txn_id=txn_id) is False
    rec = OtpCode.query.filter_by(user_id=user_id, txn_id=txn_id).first()
    assert rec.attempts == 1

    # Wrong attempt 2 -> fails
    assert verify(user_id, purpose, channel, "111111", txn_id=txn_id) is False
    rec = OtpCode.query.filter_by(user_id=user_id, txn_id=txn_id).first()
    assert rec.attempts == 2

    # Wrong attempt 3 -> fails (hits max_attempts=3)
    assert verify(user_id, purpose, channel, "222222", txn_id=txn_id) is False
    rec = OtpCode.query.filter_by(user_id=user_id, txn_id=txn_id).first()
    assert rec.attempts == 3

    # Attempt 4 with CORRECT code -> MUST FAIL because max attempts were exceeded!
    assert verify(user_id, purpose, channel, code, txn_id=txn_id) is False
    rec = OtpCode.query.filter_by(user_id=user_id, txn_id=txn_id).first()
    assert rec.used_at is None

def test_otp_cooldown_and_hourly_limits(app_ctx):
    clock = get_clock()
    user_id = "otp_test_rate_user"
    purpose = "PIN_RESET"
    channel = "TELEGRAM"
    ip = "192.168.1.100"

    # 1. First issue at T=0
    code1 = issue(user_id, purpose, channel, ip_address=ip)
    assert code1 is not None

    # 2. Immediate second issue (T+5s) -> rejected by 30-second cooldown
    clock.advance(seconds=5)
    with pytest.raises(OtpCooldownError) as exc_info:
        issue(user_id, purpose, channel, ip_address=ip)
    assert "cooldown" in str(exc_info.value).lower()

    # 3. Advance to T+31s -> cooldown passed, issue 2 succeeds
    clock.advance(seconds=26)
    code2 = issue(user_id, purpose, channel, ip_address=ip)
    assert code2 is not None

    # Issue 3 (advance 31s)
    clock.advance(seconds=31)
    issue(user_id, purpose, channel, ip_address=ip)

    # Issue 4 (advance 31s)
    clock.advance(seconds=31)
    issue(user_id, purpose, channel, ip_address=ip)

    # Issue 5 (advance 31s) - reaches limit of 5 per hour
    clock.advance(seconds=31)
    issue(user_id, purpose, channel, ip_address=ip)

    # 6th issue within the same hour -> rejected by hourly limit of 5
    clock.advance(seconds=31)
    with pytest.raises(OtpRateLimitError) as exc_hourly:
        issue(user_id, purpose, channel, ip_address=ip)
    assert "hourly" in str(exc_hourly.value).lower()

    # Advance clock by 1 hour -> hourly limit resets, can issue again
    clock.advance(hours=1, seconds=1)
    code_new_hour = issue(user_id, purpose, channel, ip_address=ip)
    assert code_new_hour is not None

def test_otp_invalidation_of_older_unused_codes(app_ctx):
    clock = get_clock()
    user_id = "otp_test_invalidation_user"
    purpose = "PIN_CHANGE"
    channel = "EMAIL"

    # Issue code 1
    code1 = issue(user_id, purpose, channel)

    # Advance past cooldown and issue code 2
    clock.advance(seconds=35)
    code2 = issue(user_id, purpose, channel)

    # Code 1 must have been invalidated (expired)
    assert verify(user_id, purpose, channel, code1) is False

    # Code 2 must be valid
    assert verify(user_id, purpose, channel, code2) is True

def test_otp_reuse_prevention(app_ctx):
    user_id = "otp_test_reuse_user"
    purpose = "SIGNUP"
    channel = "EMAIL"

    code = issue(user_id, purpose, channel)

    # First verify succeeds
    assert verify(user_id, purpose, channel, code) is True

    # Second verify with identical code MUST FAIL (cannot be reused)
    assert verify(user_id, purpose, channel, code) is False

def test_dual_channel_issue_and_verification(app_ctx):
    clock = get_clock()
    user_id = "otp_test_dual_user"
    purpose = "TRANSACTION"
    txn_id = "TXN_DUAL_999"

    # Issue dual independent codes for EMAIL and TELEGRAM
    codes = issue_dual(user_id, purpose, txn_id=txn_id)
    email_code, telegram_code = codes

    assert len(email_code) == 6 and email_code.isdigit()
    assert len(telegram_code) == 6 and telegram_code.isdigit()
    # Codes must be independent and differ
    assert email_code != telegram_code

    # Dict and attribute access verification on DualOtpResult
    assert codes.email_code == email_code
    assert codes.telegram_code == telegram_code
    assert codes['EMAIL'] == email_code
    assert codes['TELEGRAM'] == telegram_code

    # Verify mock sender received both messages
    sender = get_sender()
    sent_channels = [m['channel'] for m in sender.messages if m['user_id'] == user_id]
    assert 'EMAIL' in sent_channels
    assert 'TELEGRAM' in sent_channels

    # Case 1: Wrong email code + correct telegram code -> FAILS, shared attempts increments to 1
    assert verify_dual(user_id, purpose, "000000", telegram_code, txn_id=txn_id) is False
    rec_email = OtpCode.query.filter_by(user_id=user_id, channel='EMAIL', txn_id=txn_id).first()
    rec_tg = OtpCode.query.filter_by(user_id=user_id, channel='TELEGRAM', txn_id=txn_id).first()
    assert rec_email.attempts == 1
    assert rec_tg.attempts == 1

    # Case 2: Correct email code + wrong telegram code -> FAILS, shared attempts increments to 2
    assert verify_dual(user_id, purpose, email_code, "000000", txn_id=txn_id) is False
    rec_email = OtpCode.query.filter_by(user_id=user_id, channel='EMAIL', txn_id=txn_id).first()
    rec_tg = OtpCode.query.filter_by(user_id=user_id, channel='TELEGRAM', txn_id=txn_id).first()
    assert rec_email.attempts == 2
    assert rec_tg.attempts == 2

    # Case 3: Both correct -> SUCCEEDS and consumes BOTH codes
    assert verify_dual(user_id, purpose, email_code, telegram_code, txn_id=txn_id) is True
    rec_email = OtpCode.query.filter_by(user_id=user_id, channel='EMAIL', txn_id=txn_id).first()
    rec_tg = OtpCode.query.filter_by(user_id=user_id, channel='TELEGRAM', txn_id=txn_id).first()
    assert rec_email.used_at is not None
    assert rec_tg.used_at is not None

    # Case 4: Cannot reuse consumed dual codes
    assert verify_dual(user_id, purpose, email_code, telegram_code, txn_id=txn_id) is False

def test_dual_channel_shared_attempts_lockout(app_ctx):
    user_id = "otp_test_dual_lockout_user"
    purpose = "PIN_CHANGE"
    txn_id = "TXN_DUAL_LOCK_88"

    codes = issue_dual(user_id, purpose, txn_id=txn_id)
    email_code, telegram_code = codes

    # 3 wrong attempts on shared counter
    assert verify_dual(user_id, purpose, "111111", telegram_code, txn_id=txn_id) is False
    assert verify_dual(user_id, purpose, email_code, "222222", txn_id=txn_id) is False
    assert verify_dual(user_id, purpose, "333333", "444444", txn_id=txn_id) is False

    # Attempt 4 with BOTH correct codes -> MUST FAIL because shared attempts reached max (3)
    assert verify_dual(user_id, purpose, email_code, telegram_code, txn_id=txn_id) is False

    rec_email = OtpCode.query.filter_by(user_id=user_id, channel='EMAIL', txn_id=txn_id).first()
    assert rec_email.attempts == 3
    assert rec_email.used_at is None
