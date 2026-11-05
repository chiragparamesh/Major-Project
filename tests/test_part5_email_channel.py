import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import smtplib
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import create_app
from db import db
from database import User, OtpCode
from email_sender import EmailSender, EmailOtpSender, default_email_sender, register_as_email_sender
from otp_service import issue, issue_dual, set_clock, FakeClock, reset_clock, register_channel_sender, clear_channel_senders

@pytest.fixture(scope="module")
def app_ctx():
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        yield app

@pytest.fixture(autouse=True)
def setup_teardown_email_test(app_ctx):
    clock = FakeClock()
    set_clock(clock)
    default_email_sender.sent_emails.clear()
    
    # Ensure dry run is active during tests
    old_dry_run = os.environ.get("EMAIL_DRY_RUN")
    os.environ["EMAIL_DRY_RUN"] = "true"

    OtpCode.query.filter(OtpCode.user_id.like("email_test_%")).delete()
    db.session.commit()

    yield

    reset_clock()
    clear_channel_senders()
    default_email_sender.sent_emails.clear()
    if old_dry_run is not None:
        os.environ["EMAIL_DRY_RUN"] = old_dry_run
    else:
        os.environ.pop("EMAIL_DRY_RUN", None)

    OtpCode.query.filter(OtpCode.user_id.like("email_test_%")).delete()
    db.session.commit()

def test_email_formatting_plain_and_html():
    sender = EmailSender()
    code = "582914"
    purpose = "SIGNUP"

    subject, plain_text, html = sender.format_email_content(code, purpose)

    # Required sentence: "Your MLBFD code is 123456. Valid for 5 minutes. Purpose: <purpose>. Never share this code."
    expected_phrase = f"Your MLBFD code is {code}. Valid for 5 minutes. Purpose: {purpose}. Never share this code."
    assert expected_phrase in plain_text
    assert expected_phrase in html
    assert subject == f"[MLBFD] Your Verification Code - {purpose}"
    assert "<html>" in html.lower()

def test_transaction_email_shows_amount_and_masked_receiver():
    sender = EmailSender()
    code = "918273"
    purpose = "TRANSACTION"
    amount = 12500.50
    receiver = "john.doe@okaxis"

    subject, plain_text, html = sender.format_email_content(
        code=code, purpose=purpose, amount=amount, receiver=receiver
    )

    # Checks for amount and masked receiver
    assert "Rs. 12,500.50" in plain_text
    assert "j******e@okaxis" in plain_text
    assert "Rs. 12,500.50" in html
    assert "j******e@okaxis" in html
    assert "Your MLBFD code is 918273. Valid for 5 minutes. Purpose: TRANSACTION. Never share this code." in plain_text

def test_email_dry_run_flag():
    sender = EmailSender()
    assert sender.is_dry_run is True

    to = "customer@example.com"
    success, msg = sender.send_email(to, "654321", "LOGIN_NEW_DEVICE", background=False)

    assert success is True
    assert len(sender.sent_emails) == 1
    sent = sender.sent_emails[0]
    assert sent["to"] == to
    assert "654321" in sent["plain_text"]
    assert "[MLBFD]" in sent["subject"]

def test_email_background_thread_dispatch():
    sender = EmailSender(dry_run=False)
    assert sender.is_dry_run is False
    with patch.object(sender, "_send_smtp_sync", return_value=True) as mock_sync:
        success, msg = sender.send_email("background@example.com", "123456", "TRANSACTION", background=True)
        assert success is True
        # Allow background thread a moment to run
        time.sleep(0.1)
        assert mock_sync.call_count == 1

def test_email_retry_on_failure_and_clean_error():
    sender = EmailSender(dry_run=False)
    assert sender.is_dry_run is False
    with patch.object(sender, "_send_smtp_sync", side_effect=smtplib.SMTPException("Connection refused")) as mock_sync:
        # Synchronous call to inspect clean return value
        success, msg = sender.send_email("fail@example.com", "123456", "PIN_RESET", background=False)
        assert success is False
        assert "Failed to send email" in msg
        # Confirms 1 initial attempt + 1 retry = 2 calls
        assert mock_sync.call_count == 2

def test_otp_service_integration_via_email_sender(app_ctx):
    user_id = "email_test_user@mlbfd"
    purpose = "SIGNUP"

    # Register EmailOtpSender as EMAIL channel dispatcher
    register_as_email_sender()

    # Issue code via otp_service
    code = issue(user_id, purpose, channel="EMAIL")
    assert len(code) == 6

    # Verify default_email_sender recorded the dispatched email
    assert len(default_email_sender.sent_emails) == 1
    sent = default_email_sender.sent_emails[0]
    assert sent["to"] == user_id
    assert code in sent["plain_text"]
    assert "Valid for 5 minutes" in sent["plain_text"]

def test_dual_issue_sends_email_via_email_sender(app_ctx):
    user_id = "email_test_dual_user@mlbfd"
    purpose = "TRANSACTION"

    register_as_email_sender()
    default_email_sender.sent_emails.clear()

    codes = issue_dual(user_id, purpose, txn_id="TXN_EM_DUAL_1")
    email_code, telegram_code = codes

    # Email part should be sent through default_email_sender
    assert len(default_email_sender.sent_emails) == 1
    sent = default_email_sender.sent_emails[0]
    assert sent["to"] == user_id
    assert email_code in sent["plain_text"]
