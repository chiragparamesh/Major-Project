import pytest
import os
import sys
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Add backend directory to sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, TelegramLinkToken
from security import encrypt_val, decrypt_val, compute_lookup_hash
from telegram_bot import TelegramBot, TelegramOtpSender, send_telegram
from otp_service import issue, register_channel_sender, clear_channel_senders


@pytest.fixture
def app():
    os.environ["MLBFD_SECRET_KEY"] = "test-secret-key-at-least-32-chars-long-mlbfd"
    os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-at-least-32-chars-mlbfd"
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:TEST_BOT_TOKEN_ABCDEF"
    os.environ["TELEGRAM_BOT_USERNAME"] = "mlbfd_test_bot"
    os.environ["TELEGRAM_POLLING_ENABLED"] = "false"
    os.environ["TELEGRAM_DRY_RUN"] = "false"

    test_app = create_app()
    test_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sample_user(app):
    with app.app_context():
        user = User(
            user_id="tg_user_1",
            full_name="Telegram Test User",
            phone=encrypt_val("+919876543210"),
            phone_hash=compute_lookup_hash("+919876543210"),
            email=encrypt_val("tg_user@example.com"),
            email_hash=compute_lookup_hash("tg_user@example.com"),
            status="ACTIVE",
            balance=100000.00,
            pin_hash="dummy_pin_hash",
            login_pin_hash="dummy_login_hash",
            payment_pin_hash="dummy_payment_hash"
        )
        db.session.add(user)
        db.session.commit()
        return user


def test_telegram_link_token_generation(app, sample_user):
    with app.app_context():
        bot = TelegramBot()
        token, url = bot.create_link_token("tg_user_1", expires_in_minutes=10)

        assert token is not None and len(token) > 16
        assert url == f"https://t.me/mlbfd_test_bot?start={token}"

        link_rec = TelegramLinkToken.query.filter_by(token=token).first()
        assert link_rec is not None
        assert link_rec.user_id == "tg_user_1"
        assert link_rec.used is False
        assert link_rec.expires_at > datetime.utcnow()


def test_api_telegram_link_token_endpoint(client, sample_user):
    # Without user_id -> 400
    res = client.post("/api/telegram/link_token", json={})
    assert res.status_code == 400

    # With nonexistent user_id -> 404
    res = client.post("/api/telegram/link_token", json={"user_id": "nonexistent"})
    assert res.status_code == 404

    # ACTIVE account without a JWT -> 401 (otherwise anyone could re-link a victim's Telegram)
    res = client.post("/api/telegram/link_token", json={"user_id": "tg_user_1"})
    assert res.status_code == 401

    # Same account with its own JWT -> 200
    from flask_jwt_extended import create_access_token
    with client.application.app_context():
        jwt_token = create_access_token(identity="tg_user_1")
    res = client.post("/api/telegram/link_token", json={},
                      headers={"Authorization": f"Bearer {jwt_token}"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "token" in data
    assert f"?start={data['token']}" in data["link_url"]
    assert data["bot_username"] == "mlbfd_test_bot"


def test_start_command_with_valid_and_expired_token(app, sample_user):
    with app.app_context():
        bot = TelegramBot()
        token, _ = bot.create_link_token("tg_user_1", expires_in_minutes=10)

        mock_post = MagicMock(return_value=MagicMock(status_code=200, text='{"ok": true}'))
        with patch("requests.post", mock_post):
            # 1. Process valid /start <token>
            update = {
                "update_id": 1,
                "message": {
                    "chat": {"id": 987654321},
                    "from": {"id": 987654321, "first_name": "Test"},
                    "text": f"/start {token}"
                }
            }
            res = bot.handle_update(update)
            assert res["status"] == "start_token_linked"
            assert res["user_id"] == "tg_user_1"

            # Check DB updated
            u = User.query.filter_by(user_id="tg_user_1").first()
            assert u.get_decrypted_telegram_chat_id() == "987654321"
            assert u.telegram_verified is False

            # Verify request_contact button was in reply_markup
            args, kwargs = mock_post.call_args
            payload = kwargs.get("json", {})
            assert "reply_markup" in payload
            kb = payload["reply_markup"].get("keyboard", [[]])[0][0]
            assert kb.get("request_contact") is True

            # 2. Try using the same token again -> should fail as used
            update2 = {
                "update_id": 2,
                "message": {
                    "chat": {"id": 987654321},
                    "from": {"id": 987654321},
                    "text": f"/start {token}"
                }
            }
            res2 = bot.handle_update(update2)
            assert res2["status"] == "invalid_or_expired_token"


def test_contact_verification_success_and_mismatch(app, sample_user):
    with app.app_context():
        bot = TelegramBot()
        u = User.query.filter_by(user_id="tg_user_1").first()
        u.telegram_chat_id = encrypt_val("55512345")
        u.telegram_verified = False
        db.session.commit()

        mock_post = MagicMock(return_value=MagicMock(status_code=200, text='{"ok": true}'))
        with patch("requests.post", mock_post):
            # 1. Contact spoof attempt (contact.user_id != message.from.id)
            spoof_update = {
                "update_id": 10,
                "message": {
                    "chat": {"id": 55512345},
                    "from": {"id": 55512345},
                    "contact": {
                        "phone_number": "+919876543210",
                        "user_id": 999999999  # DIFFERENT from message.from.id
                    }
                }
            }
            res = bot.handle_update(spoof_update)
            assert res["status"] == "contact_spoof_rejected"
            u_check = User.query.filter_by(user_id="tg_user_1").first()
            assert u_check.telegram_verified is False

            # 2. Phone mismatch attempt
            mismatch_update = {
                "update_id": 11,
                "message": {
                    "chat": {"id": 55512345},
                    "from": {"id": 55512345},
                    "contact": {
                        "phone_number": "+919111111111",  # Different number
                        "user_id": 55512345
                    }
                }
            }
            res2 = bot.handle_update(mismatch_update)
            assert res2["status"] == "phone_mismatch_unlinked"
            u_check = User.query.filter_by(user_id="tg_user_1").first()
            assert u_check.telegram_chat_id is None
            assert u_check.telegram_verified is False

            # 3. Matching phone number
            # Re-link chat_id
            u_check.telegram_chat_id = encrypt_val("55512345")
            db.session.commit()

            match_update = {
                "update_id": 12,
                "message": {
                    "chat": {"id": 55512345},
                    "from": {"id": 55512345},
                    "contact": {
                        "phone_number": "9876543210",  # Normalizes to +919876543210
                        "user_id": 55512345
                    }
                }
            }
            res3 = bot.handle_update(match_update)
            assert res3["status"] == "verified"
            u_final = User.query.filter_by(user_id="tg_user_1").first()
            assert u_final.telegram_verified is True


def test_send_telegram_success_and_403_unlink(app, sample_user):
    with app.app_context():
        bot = TelegramBot()
        u = User.query.filter_by(user_id="tg_user_1").first()
        u.telegram_chat_id = encrypt_val("777888999")
        u.telegram_verified = True
        db.session.commit()

        # 1. Success
        mock_success = MagicMock(return_value=MagicMock(status_code=200, text='{"ok": true}'))
        with patch("requests.post", mock_success):
            ok, msg = bot.send_telegram(u, "Test Message")
            assert ok is True
            assert msg == "Message sent"

        # 2. HTTP 403 Forbidden (bot was blocked by user) -> unlinks user
        mock_403 = MagicMock(return_value=MagicMock(status_code=403, text='{"ok": false, "description": "Forbidden: bot was blocked by the user"}'))
        with patch("requests.post", mock_403):
            ok, msg = bot.send_telegram(u, "Test Message 2")
            assert ok is False
            assert "unlinked" in msg.lower()

            u_after = User.query.filter_by(user_id="tg_user_1").first()
            assert u_after.telegram_chat_id is None
            assert u_after.telegram_verified is False


def test_api_telegram_status_endpoint(client, sample_user, app):
    # ACTIVE accounts need their own JWT (no unauthenticated link-state lookup)
    assert client.get("/api/telegram/status?user_id=tg_user_1").status_code == 401
    from flask_jwt_extended import create_access_token
    with app.app_context():
        auth = {"Authorization": f"Bearer {create_access_token(identity='tg_user_1')}"}

    # Unlinked user
    res = client.get("/api/telegram/status", headers=auth)
    assert res.status_code == 200
    data = res.get_json()
    assert data["telegram_linked"] is False
    assert data["telegram_verified"] is False

    # Linked but not verified
    with app.app_context():
        u = User.query.filter_by(user_id="tg_user_1").first()
        u.telegram_chat_id = encrypt_val("111222")
        u.telegram_verified = False
        db.session.commit()

    res = client.get("/api/telegram/status", headers=auth)
    assert res.status_code == 200
    data = res.get_json()
    assert data["telegram_linked"] is True
    assert data["telegram_verified"] is False

    # Verified
    with app.app_context():
        u = User.query.filter_by(user_id="tg_user_1").first()
        u.telegram_verified = True
        db.session.commit()

    res = client.get("/api/telegram/status", headers=auth)
    assert res.status_code == 200
    data = res.get_json()
    assert data["telegram_linked"] is True
    assert data["telegram_verified"] is True


def test_telegram_otp_service_integration(app, sample_user):
    with app.app_context():
        u = User.query.filter_by(user_id="tg_user_1").first()
        u.telegram_chat_id = encrypt_val("888777666")
        u.telegram_verified = True
        db.session.commit()

        bot = TelegramBot()
        otp_sender = TelegramOtpSender(bot)
        register_channel_sender("TELEGRAM", otp_sender)

        mock_post = MagicMock(return_value=MagicMock(status_code=200, text='{"ok": true}'))
        with patch("requests.post", mock_post):
            code = issue(u, purpose="LOGIN_NEW_DEVICE", channel="TELEGRAM")
            assert code is not None and len(code) == 6

            args, kwargs = mock_post.call_args
            payload = kwargs.get("json", {})
            msg_text = payload.get("text", "")

            # Exact required wording check
            assert "Your MLBFD code is" in msg_text
            assert "Valid for 5 minutes." in msg_text
            assert "Purpose: LOGIN_NEW_DEVICE" in msg_text
            assert "Never share this code." in msg_text

        clear_channel_senders()

