import time
import os
import sys
import pytest
from unittest.mock import patch

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import SignupIpLog, User
from security import generate_form_timing_token, is_disposable_email, check_honeypot, verify_form_fill_timing


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["TURNSTILE_SECRET_KEY"] = "MOCK"
    app.config["TURNSTILE_SITE_KEY"] = "MOCK"

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _valid_registration_payload(user_id="user_bot_1", email="userbot1@gmail.com", phone="9876500001"):
    return {
        "full_name": "Test User",
        "user_id": user_id,
        "phone": phone,
        "email": email,
        "login_pin": "948271",
        "payment_pin": "183920",
        "security_question": "What is the name of your first school?",
        "security_answer": "Kendriya Vidyalaya",
        "consent": True,
        "website": "",
        "form_started_at": time.time() - 4.0,  # 4 seconds ago
        "form_timing_token": generate_form_timing_token(timestamp=time.time() - 4.0)
    }


def test_honeypot_rejection(client):
    """Filled honeypot field must trigger 400 BOT_DETECTED."""
    payload = _valid_registration_payload(user_id="hp_bot")
    payload["website"] = "http://spam-link.com"

    resp = client.post("/api/register/start", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "BOT_DETECTED"


def test_fast_form_fill_rejection(client):
    """Submissions faster than 3 seconds must trigger 400 BOT_DETECTED."""
    payload = _valid_registration_payload(user_id="fast_bot")
    # Form filled in 0.5 seconds
    payload["form_started_at"] = time.time() - 0.5
    payload["form_timing_token"] = generate_form_timing_token(timestamp=time.time() - 0.5)

    resp = client.post("/api/register/start", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "BOT_DETECTED"
    assert "too quickly" in data["message"].lower()


def test_disposable_email_rejection(client):
    """Disposable email domains must be rejected with 400 DISPOSABLE_EMAIL_BLOCKED."""
    payload = _valid_registration_payload(user_id="disp_user", email="throwaway@tempmail.com")

    resp = client.post("/api/register/start", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "DISPOSABLE_EMAIL_BLOCKED"


def test_ip_signup_rate_limiting(client):
    """A single IP cannot create more than 3 accounts in 24 hours."""
    client_ip = "192.168.1.55"

    for i in range(1, 4):
        payload = _valid_registration_payload(
            user_id=f"ip_test_user_{i}",
            email=f"iptest{i}@gmail.com",
            phone=f"987650001{i}"
        )
        resp = client.post("/api/register/start", json=payload, environ_base={"REMOTE_ADDR": client_ip})
        assert resp.status_code == 201, f"User {i} failed: {resp.get_json()}"

    # 4th signup from the same IP must be rejected with 429
    payload_4th = _valid_registration_payload(
        user_id="ip_test_user_4",
        email="iptest4@gmail.com",
        phone="9876500014"
    )
    resp_4 = client.post("/api/register/start", json=payload_4th, environ_base={"REMOTE_ADDR": client_ip})
    assert resp_4.status_code == 429
    data_4 = resp_4.get_json()
    assert data_4["error"] == "IP_SIGNUP_LIMIT_EXCEEDED"


def test_turnstile_verification_real_key_mocked(client):
    """When TURNSTILE_SECRET_KEY is configured, valid response passes, invalid fails."""
    from config import Config
    orig_secret = getattr(Config, "TURNSTILE_SECRET_KEY", "MOCK")
    try:
        Config.TURNSTILE_SECRET_KEY = "0x4AAAAAA_test_secret"

        payload = _valid_registration_payload(user_id="turnstile_user", phone="9876500099", email="turnstile@gmail.com")
        payload["turnstile_token"] = "bad_token"

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"success": False, "error-codes": ["invalid-input-response"]}

            resp = client.post("/api/register/start", json=payload)
            assert resp.status_code == 400
            assert resp.get_json()["error"] == "BOT_DETECTED"

        # Now mock valid token
        payload["turnstile_token"] = "good_turnstile_token"
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"success": True}

            resp = client.post("/api/register/start", json=payload)
            assert resp.status_code == 201
            assert resp.get_json()["success"] is True
    finally:
        Config.TURNSTILE_SECRET_KEY = orig_secret


def test_timing_token_endpoint(client):
    """GET /api/register/timing_token returns token and turnstile site key."""
    resp = client.get("/api/register/timing_token")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "timing_token" in data
    assert "turnstile_site_key" in data
