"""
End-to-end OTP flows through the Flask test client with capturing mock senders:
signup (email -> Telegram link -> Telegram code), new-device login, a REQUIRES_2FA
transfer and forgot-PIN reset. Codes are read from the captured messages, never logged.
"""
import os
import re
import sys
import time
from unittest.mock import patch

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from flask_jwt_extended import create_access_token

import otp_service
from app import create_app
from db import db
from database import User, TelegramLinkToken, Transaction
from security import encrypt_val, compute_lookup_hash, hash_pin, generate_form_timing_token


class CapturingSender(otp_service.BaseOtpSender):
    """Records the last code per (user, channel); reports a per-channel status."""

    def __init__(self, status=None):
        self.codes = {}
        self.status = status or {}

    def send(self, user, channel, message, **kwargs):
        uid = getattr(user, "user_id", str(user))
        m = re.search(r"\b(\d{6})\b", re.sub(r"<[^>]+>", "", message))
        self.codes[(uid, channel)] = m.group(1)
        return {"status": self.status.get(channel, "sent"), "detail": "", "error_class": ""}

    def code(self, uid, channel):
        return self.codes[(uid, channel)]


@pytest.fixture
def app():
    test_app = create_app(start_bot=False)
    test_app.config.update({"TESTING": True})
    with test_app.app_context():
        db.create_all()
        otp_service.reset_clock()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sender(app):
    cap = CapturingSender()
    otp_service.set_sender(cap)
    otp_service.register_channel_sender("EMAIL", cap)
    otp_service.register_channel_sender("TELEGRAM", cap)
    yield cap
    otp_service.clear_channel_senders()
    otp_service._register_default_senders()


@pytest.fixture
def client(app):
    return app.test_client()


def _active_user(uid, phone, balance=50000.0):
    u = User(
        user_id=uid, full_name=uid,
        phone=encrypt_val(phone), phone_hash=compute_lookup_hash(phone),
        email=encrypt_val(f"{uid}@example.com"), email_hash=compute_lookup_hash(f"{uid}@example.com"),
        upi_id=encrypt_val(f"{phone[-10:]}@mlbfd"), upi_hash=compute_lookup_hash(f"{phone[-10:]}@mlbfd"),
        status="ACTIVE", email_verified=True, telegram_verified=True,
        telegram_chat_id=encrypt_val("5550001"),
        login_pin_hash=hash_pin("121212"), payment_pin_hash=hash_pin("654321"),
        security_question="City?", security_answer_hash=hash_pin("pune", rounds=4),
        balance=balance,
    )
    db.session.add(u)
    db.session.commit()
    return u


def test_signup_dual_channel_end_to_end(client, app, sender):
    res = client.post("/api/register/start", json={
        "full_name": "E2E User", "user_id": "e2e_user", "phone": "+919812345670",
        "email": "e2e.user@gmail.com", "login_pin": "918273", "payment_pin": "465728",
        "security_question": "School?", "security_answer": "National", "consent": True,
    })
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    assert body["delivery"] == {"email": "sent", "telegram": "not_linked"}
    assert body["telegram_link"].startswith("https://t.me/")
    assert "?start=" in body["telegram_link"]

    # Telegram code is refused until the bot is linked.
    assert client.post("/api/register/send_telegram_otp", json={"user_id": "e2e_user"}).status_code == 400

    assert client.post("/api/register/verify_email", json={
        "user_id": "e2e_user", "code": sender.code("e2e_user", "EMAIL")}).status_code == 200

    # Simulate the bot: /start <token> then a contact share by the same Telegram user.
    from telegram_bot import TelegramBot
    bot = TelegramBot(dry_run=True)
    token = body["telegram_link"].split("?start=")[1]
    assert bot.handle_update({"message": {"chat": {"id": 777}, "from": {"id": 42},
                                          "text": f"/start {token}"}})["status"] == "start_token_linked"
    # Spoofed contact (someone else's) is rejected.
    assert bot.handle_update({"message": {"chat": {"id": 777}, "from": {"id": 42},
                                          "contact": {"user_id": 43, "phone_number": "919812345670"}}}
                             )["status"] == "contact_spoof_rejected"
    assert bot.handle_update({"message": {"chat": {"id": 777}, "from": {"id": 42},
                                          "contact": {"user_id": 42, "phone_number": "919812345670"}}}
                             )["status"] == "verified"
    st = client.get("/api/telegram/status?user_id=e2e_user").get_json()
    assert st["telegram_linked"] and st["telegram_verified"]

    res = client.post("/api/register/send_telegram_otp", json={"user_id": "e2e_user"})
    assert res.status_code == 200 and res.get_json()["delivery"] == {"telegram": "sent"}
    res = client.post("/api/register/verify_telegram", headers={"X-Device-ID": "dev-e2e"},
                      json={"user_id": "e2e_user", "code": sender.code("e2e_user", "TELEGRAM")})
    assert res.status_code == 200
    assert res.get_json()["status"] == "ACTIVE"


def test_signup_email_failure_reports_reason_and_rolls_back(client, app):
    failing = CapturingSender(status={"EMAIL": "failed"})
    otp_service.set_sender(failing)
    otp_service.register_channel_sender("EMAIL", failing)
    try:
        with patch.dict(app.config, {"TESTING": False}):
            res = client.post("/api/register/start", json={
                "full_name": "Fail User", "user_id": "fail_user", "phone": "+919812345671",
                "email": "fail.user@gmail.com", "login_pin": "918273", "payment_pin": "465728",
                "security_question": "School?", "security_answer": "National", "consent": True,
                "website": "", "form_timing_token": generate_form_timing_token(timestamp=time.time() - 4.0),
            })
        assert res.status_code == 502, res.get_json()
        body = res.get_json()
        assert body["error"] == "OTP_DISPATCH_FAILED"
        assert body["delivery"]["email"] == "failed"
        assert User.query.filter_by(user_id="fail_user").first() is None
    finally:
        otp_service.clear_channel_senders()
        otp_service._register_default_senders()


def test_new_device_login_dual_otp(client, app, sender):
    _active_user("login_user", "+919812345672")
    res = client.post("/api/login", json={"user_id": "login_user", "login_pin": "121212", "device_id": "new-dev"})
    body = res.get_json()
    assert res.status_code == 200 and body["status"] == "OTP_REQUIRED"
    assert body["delivery"] == {"email": "sent", "telegram": "sent"}
    res = client.post("/api/login/verify", json={
        "user_id": "login_user", "device_id": "new-dev",
        "email_code": sender.code("login_user", "EMAIL"),
        "telegram_code": sender.code("login_user", "TELEGRAM")})
    assert res.status_code == 200
    assert "access_token" in res.get_json()


def test_requires_2fa_transfer_dual_otp(client, app, sender):
    _active_user("payer", "+919812345673")
    _active_user("payee", "+919812345674")
    jwt = create_access_token(identity="payer")
    verdict = {"status": "REQUIRES_2FA", "risk_score": 65.0, "layers": {}, "flags": ["VELOCITY"],
               "ensemble_confidence": 0.8}
    with patch("api.global_fraud_detector.detect", return_value=verdict):
        res = client.post("/api/transfer", headers={"Authorization": f"Bearer {jwt}"}, json={
            "payment_pin": "654321", "amount": 2500.0, "receiver_upi": "9812345674@mlbfd",
            "sender_upi": "9812345673@mlbfd", "device_id": "dev"})
    body = res.get_json()
    assert body["status"] == "REQUIRES_2FA" and body["delivery"] == {"email": "sent", "telegram": "sent"}
    txn_id = body["txn_id"]
    res = client.post("/api/otp/verify", headers={"Authorization": f"Bearer {jwt}"}, json={
        "txn_id": txn_id, "email_code": sender.code("payer", "EMAIL"),
        "telegram_code": sender.code("payer", "TELEGRAM")})
    assert res.status_code == 200, res.get_json()
    assert Transaction.query.filter_by(txn_id=txn_id).first().status != "PENDING"


def test_pin_reset_dual_otp_and_per_channel_resend(client, app, sender):
    _active_user("reset_user", "+919812345675")
    res = client.post("/api/pin/forgot/start", json={"user_id": "reset_user"})
    assert res.get_json()["delivery"] == {"email": "sent", "telegram": "sent"}

    # Resend inside the 30 s cooldown is refused; after it, only that channel is re-issued.
    res = client.post("/api/otp/resend", json={"user_id": "reset_user", "purpose": "PIN_RESET", "channel": "telegram"})
    assert res.status_code == 429
    old_email = sender.code("reset_user", "EMAIL")
    fake = otp_service.FakeClock(otp_service.get_clock().now())
    otp_service.set_clock(fake)
    try:
        fake.advance(seconds=31)
        res = client.post("/api/otp/resend", json={"user_id": "reset_user", "purpose": "PIN_RESET", "channel": "telegram"})
        assert res.status_code == 200 and res.get_json()["delivery"] == {"telegram": "sent"}
        assert sender.code("reset_user", "EMAIL") == old_email
        res = client.post("/api/pin/forgot/verify", json={
            "user_id": "reset_user", "email_code": old_email,
            "telegram_code": sender.code("reset_user", "TELEGRAM")})
        assert res.status_code == 200 and res.get_json()["reset_token"]
    finally:
        otp_service.reset_clock()


def test_resend_requires_jwt_for_transaction(client, app, sender):
    _active_user("noauth", "+919812345676")
    res = client.post("/api/otp/resend", json={"user_id": "noauth", "purpose": "TRANSACTION", "channel": "email"})
    assert res.status_code == 401


def test_health_otp_is_admin_only(client, app):
    assert client.get("/api/health/otp", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403
    res = client.get("/api/health/otp")  # test client = loopback, no proxy headers
    assert res.status_code == 200
    body = res.get_json()
    assert set(body["channels"]) == {"email", "telegram"}
    assert body["policy"]["expiry_seconds"] == 300
    flat = str(body)
    for name in ("EMAIL_PASSWORD", "TELEGRAM_BOT_TOKEN"):
        v = os.environ.get(name, "")
        if len(v) > 6:
            assert v not in flat


def test_concurrent_debits_cannot_double_spend(app):
    """Two debits of 600 against a 1000 balance: exactly one succeeds (conditional UPDATE)."""
    import api
    _active_user("spender", "+919812345677", balance=1000.0)
    assert api._move_funds("spender", None, 600) is True
    assert api._move_funds("spender", None, 600) is False
    db.session.commit()
    u = User.query.filter_by(user_id="spender").first()
    db.session.refresh(u)
    assert float(u.balance) == 400.0


def test_debit_and_credit_commit_together(app):
    import api
    _active_user("from_u", "+919812345678", balance=1000.0)
    to_u = _active_user("to_u", "+919812345679", balance=0.0)
    assert api._move_funds("from_u", to_u, 250) is True
    db.session.rollback()  # simulate a crash before commit: neither side moves
    assert float(User.query.filter_by(user_id="from_u").first().balance) == 1000.0
    assert float(User.query.filter_by(user_id="to_u").first().balance) == 0.0


@pytest.mark.parametrize("bad", [-500, 0, "abc", "nan", "inf", 1e12, 10.555, None])
def test_transfer_rejects_invalid_amounts(client, app, sender, bad):
    _active_user("amt_payer", "+919812345680")
    _active_user("amt_payee", "+919812345681")
    jwt = create_access_token(identity="amt_payer")
    res = client.post("/api/transfer", headers={"Authorization": f"Bearer {jwt}"}, json={
        "payment_pin": "654321", "amount": bad, "receiver_upi": "9812345681@mlbfd",
        "sender_upi": "9812345680@mlbfd", "device_id": "dev"})
    assert res.status_code == 400 and res.get_json()["error"] == "INVALID_AMOUNT"
    assert float(User.query.filter_by(user_id="amt_payee").first().balance) == 50000.0


def test_account_delete_anonymizes_encrypted_ledger(client, app, sender):
    from security import decrypt_val
    gone = _active_user("gone_user", "+919812345682")
    other = _active_user("other_user", "+919812345683")
    for uid, snd, rcv in (("gone_user", "9812345682@mlbfd", "9812345683@mlbfd"),
                          ("other_user", "9812345683@mlbfd", "9812345682@mlbfd")):
        db.session.add(Transaction(txn_id=f"T_{uid}", user_id=uid, sender_upi=encrypt_val(snd),
                                   receiver_upi=encrypt_val(rcv), amount=10, status="APPROVED"))
    db.session.commit()
    jwt = create_access_token(identity="gone_user")
    h = {"Authorization": f"Bearer {jwt}"}
    client.post("/api/account/delete", headers=h, json={"payment_pin": "654321"})
    res = client.post("/api/account/delete", headers=h, json={
        "payment_pin": "654321", "email_code": sender.code("gone_user", "EMAIL"),
        "telegram_code": sender.code("gone_user", "TELEGRAM")})
    assert res.status_code == 200, res.get_json()
    for t in Transaction.query.all():
        assert "9812345682" not in (decrypt_val(t.sender_upi) or "")
        assert "9812345682" not in (decrypt_val(t.receiver_upi) or "")


def test_registered_mlbfd_payee_not_flagged_as_bad_suffix(app):
    from fraud_detection import global_fraud_detector
    _active_user("sfx_payer", "+919812345684")
    _active_user("sfx_payee", "+919812345685")
    v = global_fraud_detector.detect({"user_id": "sfx_payer", "sender_upi": "9812345684@mlbfd", "receiver_upi": "9812345685@mlbfd",
                                      "amount": 100.0, "device_id": "dev"})
    assert not any("Suspicious bank suffix" in f for f in v["flags"])


def test_token_returned_by_pin_reset_is_not_instantly_revoked(client, app, sender):
    _active_user("fresh_tok", "+919812345686")
    client.post("/api/pin/forgot/start", json={"user_id": "fresh_tok"})
    r = client.post("/api/pin/forgot/verify", json={
        "user_id": "fresh_tok", "email_code": sender.code("fresh_tok", "EMAIL"),
        "telegram_code": sender.code("fresh_tok", "TELEGRAM")})
    r = client.post("/api/pin/forgot/reset", json={"reset_token": r.get_json()["reset_token"],
                                                   "security_answer": "pune", "new_pin": "739151",
                                                   "pin_type": "login", "device_id": "d1"})
    tok = r.get_json()["access_token"]
    res = client.get("/api/telegram/status", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200, res.get_json()


def test_admin_models_metrics_come_from_training_file(client, app):
    res = client.get("/admin/api/models/metrics")
    body = res.get_json()
    assert res.status_code == 200 and body["success"]
    names = {m["model_name"] for m in body["metrics"]}
    assert {"XGBoost", "Random Forest", "LSTM"} <= names
    xgb = next(m for m in body["metrics"] if m["model_name"] == "XGBoost")
    assert 0 < xgb["auc_score"] < 1 and "recall_at_1pct_fpr" in xgb


def test_admin_unlock_clears_all_lockouts_and_refuses_pending(client, app):
    from datetime import datetime, timedelta
    u = _active_user("lock_me", "+919812345687")
    u.login_failed_attempts = 5
    u.login_locked_until = datetime.utcnow() + timedelta(minutes=15)
    u.payment_failed_attempts = 3
    u.payment_locked_until = datetime.utcnow() + timedelta(minutes=30)
    db.session.commit()
    assert client.post("/admin/api/users/lock_me/toggle-lock", json={"lock": True}).status_code == 200
    assert User.query.filter_by(user_id="lock_me").first().status == "FROZEN"
    assert client.post("/admin/api/users/lock_me/toggle-lock", json={"lock": False}).status_code == 200
    u = User.query.filter_by(user_id="lock_me").first()
    db.session.refresh(u)
    assert u.status == "ACTIVE" and not u.login_locked_until and not u.payment_locked_until
    assert u.login_failed_attempts == 0 and u.payment_failed_attempts == 0

    pend = _active_user("pend_user", "+919812345688")
    pend.status = "PENDING"
    db.session.commit()
    r = client.post("/admin/api/users/pend_user/toggle-lock", json={"lock": False})
    assert r.status_code == 409
    assert User.query.filter_by(user_id="pend_user").first().status == "PENDING"
    assert client.post("/admin/api/users/nobody/toggle-lock", json={"lock": True}).status_code == 404
