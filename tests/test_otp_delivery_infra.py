"""Regression tests for the OTP delivery root causes found on 2026-10-31."""
import os
import smtplib
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import env_loader
import email_sender
import otp_service
import telegram_bot as tg


# ---- env cleaning ----------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ('"abcd efgh"', "abcd efgh"),
    ("'quoted'", "quoted"),
    ("value   # inline comment", "value"),
    ("  spaced  ", "spaced"),
    ("value\r", "value"),
    ("pass#word", "pass#word"),  # '#' without leading space is part of the value
])
def test_clean_value(raw, expected):
    assert env_loader.clean_value(raw) == expected


def test_parse_env_file_bom_crlf_spaces(tmp_path):
    f = tmp_path / ".env"
    f.write_bytes(b"\xef\xbb\xbfEMAIL_USER = me@gmail.com\r\nEMAIL_PASSWORD=\"abcd efgh ijkl mnop\"\r\n# c\r\nX=1 # note\r\n")
    vals = {k: v for _, k, _, v in env_loader.parse_env_file(str(f))}
    assert vals["EMAIL_USER"] == "me@gmail.com"
    assert vals["EMAIL_PASSWORD"] == "abcdefghijklmnop"  # app-password spaces removed
    assert vals["X"] == "1"


def test_load_env_overrides_stale_os_value(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("MLBFD_DOCTOR_PROBE=fresh\n")
    monkeypatch.setattr(env_loader, "ENV_PATH", str(f))
    monkeypatch.setattr(env_loader, "LEGACY_ENV_PATH", str(tmp_path / "none.env"))
    monkeypatch.setenv("MLBFD_DOCTOR_PROBE", "stale")
    monkeypatch.delenv("MLBFD_TESTING", raising=False)
    overridden = env_loader.load_env(force=True)
    assert os.environ["MLBFD_DOCTOR_PROBE"] == "fresh"
    assert overridden == ["MLBFD_DOCTOR_PROBE"]


def test_load_env_keeps_test_pins(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("EMAIL_DRY_RUN=false\n")
    monkeypatch.setattr(env_loader, "ENV_PATH", str(f))
    monkeypatch.setattr(env_loader, "LEGACY_ENV_PATH", str(tmp_path / "none.env"))
    monkeypatch.setenv("MLBFD_TESTING", "1")
    monkeypatch.setenv("EMAIL_DRY_RUN", "true")
    env_loader.load_env(force=True)
    assert os.environ["EMAIL_DRY_RUN"] == "true"


def test_env_str_alias_fallback(monkeypatch):
    monkeypatch.delenv("EMAIL_HOST", raising=False)
    monkeypatch.setenv("SMTP_HOST", " smtp.example.com ")
    assert env_loader.env_str("EMAIL_HOST", "SMTP_HOST") == "smtp.example.com"


# ---- SMTP --------------------------------------------------------------------
def _settings(**kw):
    s = {"host": "smtp.gmail.com", "port": 587, "mode": "auto", "user": "me@gmail.com",
         "password": "abcdefghijklmnop", "from_name": "MLBFD", "from_addr": "me@gmail.com", "timeout": 10}
    s.update(kw)
    return s


def test_smtp_routes_auto_fallback_order():
    assert email_sender._smtp_routes(_settings()) == [("STARTTLS", 587), ("SSL", 465)]
    assert email_sender._smtp_routes(_settings(port=465)) == [("SSL", 465), ("STARTTLS", 587)]
    assert email_sender._smtp_routes(_settings(mode="ssl")) == [("SSL", 465)]


def test_port_587_timeout_falls_back_to_465():
    ssl_server = MagicMock()
    ssl_server.esmtp_features = {"auth": "LOGIN PLAIN"}
    with patch.object(smtplib, "SMTP", side_effect=TimeoutError("timed out")), \
         patch.object(smtplib, "SMTP_SSL", return_value=ssl_server):
        ok, route, exc = email_sender.send_via_smtp(_settings(), "to@example.com", "s", "body")
    assert ok and route == "SSL:465" and exc is None
    ssl_server.sendmail.assert_called_once()


def test_bad_app_password_surfaces_535_and_stops():
    srv = MagicMock()
    srv.esmtp_features = {"auth": "LOGIN PLAIN XOAUTH2"}
    srv.auth.side_effect = smtplib.SMTPAuthenticationError(535, b"5.7.8 BadCredentials")
    with patch.object(smtplib, "SMTP", return_value=srv) as plain, \
         patch.object(smtplib, "SMTP_SSL") as ssl_ctor:
        ok, route, exc = email_sender.send_via_smtp(_settings(), "to@example.com", "s", "body")
    assert not ok and isinstance(exc, smtplib.SMTPAuthenticationError)
    assert srv.auth.call_count == 1          # one mechanism only (no masking disconnect)
    ssl_ctor.assert_not_called()             # auth failure is not retried on another port
    assert plain.call_count == 1


def test_missing_credentials_is_failure_not_fake_success(monkeypatch):
    sender = email_sender.EmailSender(dry_run=False)
    monkeypatch.setattr(email_sender, "smtp_settings", lambda cfg=None: _settings(user="", password=""))
    res = sender.send_email_status("to@example.com", "123456", "SIGNUP", wait=-1)
    assert res["status"] == "failed" and res["error_class"] == "EmailConfigError"


def test_delivery_log_has_no_code_or_address(tmp_path, monkeypatch):
    import otp_delivery_log
    log = tmp_path / "otp_delivery.log"
    monkeypatch.setattr(otp_delivery_log, "LOG_PATH", str(log))
    sender = email_sender.EmailSender(dry_run=True)
    sender.send_email_status("secret.person@example.com", "987654", "LOGIN_NEW_DEVICE", user_id="u1")
    text = log.read_text()
    assert "987654" not in text and "secret.person" not in text and "u1" not in text
    assert '"channel":"EMAIL"' in text and '"ok":true' in text


# ---- Telegram poller -----------------------------------------------------------
def test_polling_starts_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "POLLER_PID_FILE", str(tmp_path / "poller.pid"))
    from types import SimpleNamespace
    bot = tg.TelegramBot(config=SimpleNamespace(TELEGRAM_POLLING_ENABLED=True), dry_run=False)
    monkeypatch.setattr(tg.TelegramBot, "token", property(lambda self: "123456789:" + "A" * 35))
    started = []
    real_thread = threading.Thread

    def fake_thread(*a, **kw):
        t = real_thread(target=lambda: bot._stop_event.wait(5), daemon=True)
        started.append(t)
        return t
    monkeypatch.setattr(tg.threading, "Thread", fake_thread)
    bot.start_polling()
    bot.start_polling()
    assert len(started) == 1
    bot._stop_event.set()


def test_second_process_does_not_poll(tmp_path, monkeypatch):
    pid_file = tmp_path / "poller.pid"
    pid_file.write_text(str(os.getppid()))  # a live, different process
    monkeypatch.setattr(tg, "POLLER_PID_FILE", str(pid_file))
    assert tg._acquire_poller_lock() is False
    pid_file.write_text("999999")           # stale PID is taken over
    assert tg._acquire_poller_lock() is True


def test_reloader_parent_never_polls(monkeypatch):
    from app import create_app
    calls = []
    monkeypatch.setattr(tg.telegram_bot, "start_polling", lambda app=None: calls.append(1))
    create_app(start_bot=False)
    assert calls == []


# ---- per-channel status ----------------------------------------------------------
def test_unlinked_telegram_reports_not_linked():
    user = MagicMock()
    user.user_id = "nolink"
    user.get_decrypted_telegram_chat_id.return_value = None
    res = tg.TelegramOtpSender(tg.TelegramBot(dry_run=True)).send(user, "TELEGRAM", "Your MLBFD code is 123456.")
    assert res["status"] == "not_linked"


def test_sender_exception_is_status_failed_not_swallowed():
    class Boom(otp_service.BaseOtpSender):
        def send(self, *a, **k):
            raise RuntimeError("x")
    with patch.object(otp_service, "get_channel_sender", return_value=Boom()):
        res = otp_service._dispatch("someone", "EMAIL", "m")
    assert res == {"status": "failed", "detail": "sender error", "error_class": "RuntimeError"}


def test_both_senders_registered_at_import():
    otp_service.clear_channel_senders()
    otp_service._register_default_senders()
    r = otp_service.channel_readiness()
    assert r["email"]["sender_registered"] and r["telegram"]["sender_registered"]


# ---- admin gate (was fully public through the tunnel) -----------------------------
def _admin_client():
    from app import create_app
    a = create_app(start_bot=False)
    a.config["TESTING"] = True
    return a.test_client()


def test_admin_api_blocked_through_tunnel(monkeypatch):
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    c = _admin_client()
    assert c.get("/admin/api/users", headers={"CF-Connecting-IP": "8.8.8.8"}).status_code == 403
    assert c.get("/admin", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 403
    assert c.get("/admin/api/users").status_code == 200  # direct loopback


def test_admin_token_header_and_cookie_login(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "unit-test-admin-token-123")
    c = _admin_client()
    # Browser on the server machine still works without a token (token only guards remote/tunnel access).
    assert c.get("/admin/api/users").status_code == 200
    assert c.get("/admin").status_code == 200
    tunnel = {"CF-Connecting-IP": "8.8.8.8"}
    assert c.get("/admin/api/users", headers=tunnel).status_code == 403
    assert c.get("/admin/api/users", headers={**tunnel, "X-Admin-Token": "wrong"}).status_code == 403
    assert c.get("/admin/api/users", headers={**tunnel, "X-Admin-Token": "unit-test-admin-token-123"}).status_code == 200
    r = c.get("/admin?admin_token=unit-test-admin-token-123", headers=tunnel)
    assert r.status_code == 302 and "admin_token" not in r.headers["Location"]
    assert "HttpOnly" in r.headers.get("Set-Cookie", "")
    assert c.get("/admin/api/users", headers=tunnel).status_code == 200  # cookie now set



def test_client_ip_trusts_proxy_headers_only_from_tunnel():
    from security import client_ip
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(environ_base={"REMOTE_ADDR": "127.0.0.1"}, headers={"CF-Connecting-IP": "49.36.1.2"}):
        from flask import request
        assert client_ip(request) == "49.36.1.2"     # via cloudflared
    with app.test_request_context(environ_base={"REMOTE_ADDR": "127.0.0.1"}, headers={"X-Forwarded-For": "49.36.9.9, 10.0.0.1"}):
        from flask import request
        assert client_ip(request) == "49.36.9.9"
    with app.test_request_context(environ_base={"REMOTE_ADDR": "203.0.113.7"}, headers={"X-Forwarded-For": "1.1.1.1"}):
        from flask import request
        assert client_ip(request) == "203.0.113.7"   # direct client cannot spoof


def test_ubts_running_std_matches_population_std():
    import statistics
    from app import create_app
    from db import db
    from database import UserBehaviorBaseline
    from ubts import update_user_baseline
    a = create_app(start_bot=False)
    a.config["TESTING"] = True
    with a.app_context():
        db.create_all()
        amounts = [100, 250, 400, 120, 900, 330]
        for x in amounts:
            update_user_baseline("std_probe_user", x, 12, "d", "p@mlbfd", "0000")
        b = UserBehaviorBaseline.query.filter_by(user_id="std_probe_user").first()
        assert abs(float(b.avg_amount) - statistics.mean(amounts)) < 0.05
        assert abs(float(b.std_amount) - statistics.pstdev(amounts)) < 0.05
        db.session.delete(b)
        db.session.commit()


def test_dual_dispatch_overlaps_slow_email_and_caps_wait(monkeypatch):
    """Telegram is not delayed by SMTP; a slow SMTP answers 'pending' within the cap."""
    import time as _t
    import threading as _th

    class SlowEmail(otp_service.BaseOtpSender):
        def send(self, user, channel, message, **kw):
            done = {"status": "pending", "detail": "", "error_class": ""}
            th = _th.Thread(target=lambda: (_t.sleep(3), done.update(status="sent")), daemon=True)
            th.start()
            if kw.get("wait") == 0:
                return dict(done, _join=lambda timeout: (th.join(max(0, timeout)), dict(done))[1])
            th.join()
            return done

    class FastTg(otp_service.BaseOtpSender):
        def send(self, *a, **k):
            return {"status": "sent", "detail": "", "error_class": ""}

    from app import create_app
    from db import db
    app = create_app(start_bot=False)
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        otp_service.register_channel_sender("EMAIL", SlowEmail())
        otp_service.register_channel_sender("TELEGRAM", FastTg())
        monkeypatch.setattr(otp_service, "EMAIL_WAIT_SECONDS", 1)
        try:
            t0 = _t.monotonic()
            res = otp_service.issue_dual("overlap_user", "LOGIN_NEW_DEVICE")
            took = _t.monotonic() - t0
        finally:
            otp_service.clear_channel_senders()
            otp_service._register_default_senders()
        assert res.channel_status == {"telegram": "sent", "email": "pending"}
        assert took < 2.5


def test_brevo_login_separate_from_inbox(monkeypatch):
    monkeypatch.setenv("EMAIL_HOST", "smtp-relay.brevo.com")
    monkeypatch.setenv("EMAIL_USER", "inbox@gmail.com")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "xsmtpsib-abc")
    monkeypatch.setenv("EMAIL_SMTP_LOGIN", "12345@smtp-brevo.com")
    s = email_sender.smtp_settings()
    assert s["user"] == "12345@smtp-brevo.com" and s["inbox"] == "inbox@gmail.com"
    assert s["from_addr"] == "sender@example.com" and s["provider"] == "brevo"
    monkeypatch.setenv("EMAIL_SMTP_LOGIN", "PASTE_BREVO_SMTP_LOGIN_HERE")
    assert email_sender.smtp_settings()["user"] == ""  # placeholder = not configured
    monkeypatch.delenv("EMAIL_SMTP_LOGIN")
    assert email_sender.smtp_settings()["user"] == "inbox@gmail.com"  # Gmail-style fallback


def test_brevo_from_not_rewritten_to_login():
    srv = MagicMock()
    srv.esmtp_features = {"auth": "LOGIN PLAIN"}
    with patch.object(smtplib, "SMTP", return_value=srv):
        ok, _, _ = email_sender.send_via_smtp(_settings(host="smtp-relay.brevo.com", user="1@smtp-brevo.com",
                                                        from_addr="sender@example.com"), "to@example.com", "s", "b")
    assert ok and srv.sendmail.call_args[0][0] == "sender@example.com"
