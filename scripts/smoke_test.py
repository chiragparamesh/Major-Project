"""
MLBFD end-to-end smoke test (Flask test client, throw-away SQLite DB, mock senders).

    python scripts/smoke_test.py            # mock senders, fraud verdicts forced per step
    python scripts/smoke_test.py --live     # also send ONE real email + Telegram via otp_doctor

The fraud engine verdict is forced (patched) in the transfer steps so each policy path
(approve / 2FA / block) is exercised deterministically; model scoring itself is covered
by tests/test_part24_scenario_suite.py. Codes are read from the mock sender, never printed.
"""
import os
import re
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "backend"))
_tmp = tempfile.mkdtemp(prefix="mlbfd_smoke_")
os.environ["MLBFD_TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_tmp, "smoke.sqlite3").replace("\\", "/")
os.environ["EMAIL_DRY_RUN"] = "true"
os.environ["TELEGRAM_DRY_RUN"] = "true"
os.environ["TELEGRAM_POLLING_ENABLED"] = "false"

import otp_service  # noqa: E402
from app import create_app  # noqa: E402
from db import db  # noqa: E402
from database import User, Transaction  # noqa: E402
from security import generate_form_timing_token  # noqa: E402
from telegram_bot import TelegramBot  # noqa: E402


class Capture(otp_service.BaseOtpSender):
    def __init__(self):
        self.codes = {}

    def send(self, user, channel, message, **kw):
        uid = getattr(user, "user_id", str(user))
        self.codes[(uid, channel)] = re.search(r"\b(\d{6})\b", re.sub(r"<[^>]+>", "", message)).group(1)
        return {"status": "sent", "detail": "", "error_class": ""}


RESULTS = []


def step(name):
    def deco(fn):
        def run(*a, **k):
            t0 = time.perf_counter()
            try:
                detail = fn(*a, **k) or ""
                RESULTS.append(("PASS", name, detail, time.perf_counter() - t0))
            except Exception as e:
                RESULTS.append(("FAIL", name, f"{type(e).__name__}: {e}", time.perf_counter() - t0))
                traceback.print_exc()
        return run
    return deco


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    live = "--live" in sys.argv
    app = create_app(start_bot=False)
    app.config["TESTING"] = True
    c = app.test_client()
    cap = Capture()
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    otp_service.set_sender(cap)
    otp_service.register_channel_sender("EMAIL", cap)
    otp_service.register_channel_sender("TELEGRAM", cap)
    bot = TelegramBot(dry_run=True)
    tokens = {}
    ip = iter(f"198.51.100.{i}" for i in range(1, 250))

    def signup(uid, phone, chat):
        r = c.post("/api/register/start", environ_base={"REMOTE_ADDR": next(ip)}, json={
            "full_name": uid.title(), "user_id": uid, "phone": phone, "email": f"{uid}@gmail.com",
            "login_pin": "918273", "payment_pin": "465728", "security_question": "City?",
            "security_answer": "Pune", "consent": True, "website": "",
            "form_timing_token": generate_form_timing_token(timestamp=time.time() - 5)})
        check(r.status_code == 201, f"register/start {r.status_code} {r.get_json()}")
        body = r.get_json()
        check(body["delivery"] == {"email": "sent", "telegram": "not_linked"}, f"delivery {body['delivery']}")
        check(c.post("/api/register/verify_email", json={"user_id": uid, "code": cap.codes[(uid, "EMAIL")]}).status_code == 200, "verify_email")
        tok = body["telegram_link"].split("?start=")[1]
        bot.handle_update({"message": {"chat": {"id": chat}, "from": {"id": chat}, "text": f"/start {tok}"}})
        st = bot.handle_update({"message": {"chat": {"id": chat}, "from": {"id": chat},
                                            "contact": {"user_id": chat, "phone_number": phone.lstrip("+")}}})
        check(st["status"] == "verified", f"contact {st}")
        check(c.post("/api/register/send_telegram_otp", json={"user_id": uid}).status_code == 200, "send_telegram_otp")
        r = c.post("/api/register/verify_telegram", headers={"X-Device-ID": f"dev-{uid}"},
                   json={"user_id": uid, "code": cap.codes[(uid, "TELEGRAM")]})
        check(r.status_code == 200 and r.get_json()["status"] == "ACTIVE", f"activate {r.get_json()}")
        tokens[uid] = r.get_json()["access_token"]
        return f"ACTIVE, upi {r.get_json()['upi_id'][:3]}***"

    auth = lambda u: {"Authorization": f"Bearer {tokens[u]}"}  # noqa: E731
    verdict = lambda st, score: {"status": st, "risk_score": score, "layers": {}, "flags": ["SMOKE"],  # noqa: E731
                                 "ensemble_confidence": 0.9}

    def pay(uid, rcv, amount, st, score):
        with patch("api.global_fraud_detector.detect", return_value=verdict(st, score)):
            return c.post("/api/transfer", headers=auth(uid), json={
                "payment_pin": "465728", "amount": amount, "receiver_upi": rcv, "device_id": f"dev-{uid}"})

    step("1a register user A (dual OTP)")(lambda: signup("smoke_alice", "+919900000001", 9001))()
    step("1b register user B (dual OTP)")(lambda: signup("smoke_bob", "+919900000002", 9002))()

    @step("2a login known device (no OTP)")
    def _():
        r = c.post("/api/login", json={"user_id": "smoke_alice", "login_pin": "918273", "device_id": "dev-smoke_alice"})
        check(r.get_json().get("status") == "LOGGED_IN", r.get_json())
    _()

    @step("2b login new device (dual OTP)")
    def _():
        r = c.post("/api/login", json={"user_id": "smoke_alice", "login_pin": "918273", "device_id": "dev-new"})
        b = r.get_json()
        check(b["status"] == "OTP_REQUIRED" and b["delivery"] == {"email": "sent", "telegram": "sent"}, b)
        r = c.post("/api/login/verify", json={"user_id": "smoke_alice", "device_id": "dev-new",
                                               "email_code": cap.codes[("smoke_alice", "EMAIL")],
                                               "telegram_code": cap.codes[("smoke_alice", "TELEGRAM")]})
        check(r.status_code == 200 and "access_token" in r.get_json(), r.get_json())
    _()

    @step("3 normal transfer A->B")
    def _():
        r = pay("smoke_alice", "9900000002@mlbfd", 1500, "APPROVED", 10.0)
        check(r.status_code == 200 and r.get_json()["status"] == "APPROVED", r.get_json())
        a = User.query.filter_by(user_id="smoke_alice").first()
        b = User.query.filter_by(user_id="smoke_bob").first()
        db.session.refresh(a); db.session.refresh(b)
        check(float(a.balance) == 98500 and float(b.balance) == 101500, f"balances {a.balance} {b.balance}")
        return "A 98,500 / B 1,01,500"
    _()

    @step("4 unregistered receiver -> 404")
    def _():
        r = pay("smoke_alice", "9999999999@mlbfd", 100, "APPROVED", 5.0)
        check(r.status_code == 404 and r.get_json().get("error") == "USER_NOT_REGISTERED", (r.status_code, r.get_json()))
    _()

    @step("5 high-risk transfer -> dual OTP -> COMPLETED")
    def _():
        r = pay("smoke_alice", "9900000002@mlbfd", 2500, "REQUIRES_2FA", 65.0)
        b = r.get_json()
        check(b["status"] == "REQUIRES_2FA" and b["delivery"] == {"email": "sent", "telegram": "sent"}, b)
        r = c.post("/api/otp/verify", headers=auth("smoke_alice"), json={
            "txn_id": b["txn_id"], "email_code": cap.codes[("smoke_alice", "EMAIL")],
            "telegram_code": cap.codes[("smoke_alice", "TELEGRAM")]})
        check(r.status_code == 200 and r.get_json()["status"] == "COMPLETED", r.get_json())
    _()

    @step("7 PIN change (dual OTP)")
    def _():
        r = c.post("/api/pin/change", headers=auth("smoke_bob"), json={
            "pin_type": "login", "current_pin": "918273", "new_pin": "582914"})
        check(r.status_code == 200 and r.get_json()["delivery"] == {"email": "sent", "telegram": "sent"}, r.get_json())
        r = c.post("/api/pin/change/confirm", headers=auth("smoke_bob"), json={
            "email_code": cap.codes[("smoke_bob", "EMAIL")], "telegram_code": cap.codes[("smoke_bob", "TELEGRAM")]})
        check(r.status_code == 200, r.get_json())
        r = c.post("/api/login", json={"user_id": "smoke_bob", "login_pin": "582914", "device_id": "dev-smoke_bob"})
        check(r.get_json().get("status") == "LOGGED_IN", r.get_json())
        tokens["smoke_bob"] = r.get_json()["access_token"]
    _()

    @step("8 forgot-PIN reset -> reduced limits")
    def _():
        r = c.post("/api/pin/forgot/start", json={"user_id": "smoke_bob"})
        check(r.get_json()["delivery"] == {"email": "sent", "telegram": "sent"}, r.get_json())
        r = c.post("/api/pin/forgot/verify", json={"user_id": "smoke_bob",
                                                    "email_code": cap.codes[("smoke_bob", "EMAIL")],
                                                    "telegram_code": cap.codes[("smoke_bob", "TELEGRAM")]})
        tok = r.get_json()["reset_token"]
        r = c.post("/api/pin/forgot/reset", json={"reset_token": tok, "security_answer": "pune",
                                                   "new_pin": "739151", "pin_type": "payment", "device_id": "dev-smoke_bob"})
        check(r.status_code == 200, r.get_json())
        tokens["smoke_bob"] = r.get_json()["access_token"]
        with patch("api.global_fraud_detector.detect", return_value=verdict("APPROVED", 5.0)):
            r = c.post("/api/transfer", headers=auth("smoke_bob"), json={
                "payment_pin": "739151", "amount": 15000, "receiver_upi": "9900000001@mlbfd", "device_id": "dev-smoke_bob"})
        check(r.status_code in (400, 403) and "10,000" in r.get_json().get("message", ""), (r.status_code, r.get_json()))
        return "Rs 15,000 refused under Rs 10,000/txn reduced limit"
    _()

    @step("6 blocked transfer + freeze link")
    def _():
        r = pay("smoke_alice", "9900000002@mlbfd", 900, "BLOCKED", 92.0)
        b = r.get_json()
        check(b["status"] == "BLOCKED" and b.get("freeze_token"), b)
        r = c.get(f"/api/freeze?token={b['freeze_token']}")
        check(r.status_code == 200, r.get_json())
        check(User.query.filter_by(user_id="smoke_alice").first().status == "FROZEN", "not frozen")
        check(c.get(f"/api/freeze?token={b['freeze_token']}").status_code == 400, "freeze link reusable")
    _()

    @step("10 balance reset (JWT, 1/hour)")
    def _():
        r = c.post("/api/account/reset_balance", headers=auth("smoke_bob"), json={})
        check(r.status_code == 200 and r.get_json()["balance"] == 100000.0, r.get_json())
        check(c.post("/api/account/reset_balance", headers=auth("smoke_bob"), json={}).status_code == 429, "no 1/h limit")
    _()

    @step("11 login lockout after 5 wrong PINs")
    def _():
        codes = [c.post("/api/login", environ_base={"REMOTE_ADDR": "203.0.113.50"},
                        json={"user_id": "smoke_bob", "login_pin": "000111"}).status_code for _ in range(6)]
        check(codes[-1] == 403, f"codes {codes}")
        return f"statuses {codes}"
    _()

    @step("12 rate limit (Flask-Limiter) on /api/login")
    def _():
        codes = [c.post("/api/login", environ_base={"REMOTE_ADDR": "203.0.113.99"},
                        json={"user_id": "nobody", "login_pin": "123987"}).status_code for _ in range(12)]
        check(429 in codes, f"no 429 in {codes}")
        return f"first 429 at request {codes.index(429) + 1}"
    _()

    @step("9 account delete (dual OTP)")
    def _():
        u = User.query.filter_by(user_id="smoke_bob").first()
        u.login_locked_until = None
        db.session.commit()
        c.post("/api/account/delete", headers=auth("smoke_bob"), json={"payment_pin": "739151"})
        r = c.post("/api/account/delete", headers=auth("smoke_bob"), json={
            "payment_pin": "739151", "email_code": cap.codes[("smoke_bob", "EMAIL")],
            "telegram_code": cap.codes[("smoke_bob", "TELEGRAM")]})
        check(r.status_code == 200, r.get_json())
        from security import decrypt_val
        leaks = [t.txn_id for t in Transaction.query.all()
                 if "9900000002" in (decrypt_val(t.sender_upi) or "") + (decrypt_val(t.receiver_upi) or "")]
        check(not leaks, f"ledger still names deleted user: {leaks}")
    _()

    if live:
        @step("LIVE email + Telegram via otp_doctor")
        def _():
            import subprocess
            py = sys.executable
            e = subprocess.run([py, os.path.join(REPO, "backend", "otp_doctor.py"), "--email-test"], capture_output=True, text=True)
            t = subprocess.run([py, os.path.join(REPO, "backend", "otp_doctor.py"), "--telegram-test"], capture_output=True, text=True)
            check(e.returncode == 0, "email-test FAIL (see otp_doctor --email-test)")
            check(t.returncode == 0, "telegram-test FAIL")
        _()

    ctx.pop()
    print("\n" + "=" * 78)
    print(f"{'RESULT':6}  {'STEP':44}  {'ms':>6}  DETAIL")
    print("-" * 78)
    for res, name, detail, dt in RESULTS:
        print(f"{res:6}  {name:44}  {dt * 1000:6.0f}  {str(detail)[:60]}")
    fails = sum(1 for r in RESULTS if r[0] == "FAIL")
    print("-" * 78)
    print(f"{len(RESULTS) - fails}/{len(RESULTS)} PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
