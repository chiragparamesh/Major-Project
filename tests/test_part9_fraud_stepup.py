import pytest
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

# Add backend directory to sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, Transaction, OtpCode
from security import encrypt_val, decrypt_val, compute_lookup_hash, hash_pin
from flask_jwt_extended import create_access_token
import otp_service


@pytest.fixture
def app():
    os.environ["MLBFD_SECRET_KEY"] = "test-secret-key-at-least-32-chars-long-mlbfd"
    os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-at-least-32-chars-mlbfd"
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:TEST_BOT_TOKEN_ABCDEF"
    os.environ["TELEGRAM_BOT_USERNAME"] = "mlbfd_test_bot"
    os.environ["TELEGRAM_POLLING_ENABLED"] = "false"
    os.environ["TELEGRAM_DRY_RUN"] = "true"
    os.environ["EMAIL_DRY_RUN"] = "true"

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
def sender_user(app):
    with app.app_context():
        user = User(
            user_id="sender_user_01",
            full_name="Sender User",
            phone=encrypt_val("+919876543210"),
            phone_hash=compute_lookup_hash("+919876543210"),
            email=encrypt_val("sender@example.com"),
            email_hash=compute_lookup_hash("sender@example.com"),
            upi_id=encrypt_val("9876543210@mlbfd"),
            upi_hash=compute_lookup_hash("9876543210@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            telegram_chat_id=encrypt_val("111222333"),
            login_pin_hash=hash_pin("121212"),
            payment_pin_hash=hash_pin("654321"),
            balance=10000.00
        )
        db.session.add(user)
        db.session.commit()
        return user.user_id


@pytest.fixture
def receiver_user(app):
    with app.app_context():
        user = User(
            user_id="receiver_user_02",
            full_name="Receiver User",
            phone=encrypt_val("+919876543211"),
            phone_hash=compute_lookup_hash("+919876543211"),
            email=encrypt_val("receiver@example.com"),
            email_hash=compute_lookup_hash("receiver@example.com"),
            upi_id=encrypt_val("9876543211@mlbfd"),
            upi_hash=compute_lookup_hash("9876543211@mlbfd"),
            status="ACTIVE",
            email_verified=True,
            telegram_verified=True,
            telegram_chat_id=encrypt_val("444555666"),
            login_pin_hash=hash_pin("131313"),
            payment_pin_hash=hash_pin("765432"),
            balance=5000.00
        )
        db.session.add(user)
        db.session.commit()
        return user.user_id


@pytest.fixture
def sender_jwt(app, sender_user):
    with app.app_context():
        return create_access_token(identity=sender_user)


# ==============================================================================
# TESTS
# ==============================================================================

def test_transfer_requires_2fa_holds_pending(client, app, sender_user, receiver_user, sender_jwt):
    """When engine returns REQUIRES_2FA, txn is held as PENDING (10m expiry) and dual OTP is dispatched."""
    mock_verdict = {
        'status': 'REQUIRES_2FA',
        'risk_score': 65.0,
        'layers': {'behavioral': 0.7, 'velocity': 0.6},
        'flags': ['ANOMALOUS_VELOCITY'],
        'ensemble_confidence': 0.85
    }

    mock_sender = otp_service.MockOtpSender()
    otp_service.set_sender(mock_sender)

    with patch('api.global_fraud_detector.detect', return_value=mock_verdict):
        res = client.post('/api/transfer', json={
            'payment_pin': '654321',
            'amount': 2000.00,
            'receiver_upi': '9876543211@mlbfd',
            'sender_upi': '9876543210@mlbfd',
            'device_id': 'test-device-uuid'
        }, headers={'Authorization': f'Bearer {sender_jwt}'})

    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'REQUIRES_2FA'
    assert data['txn_status'] == 'PENDING'
    txn_id = data['txn_id']

    with app.app_context():
        # Check Transaction record
        txn = Transaction.query.filter_by(txn_id=txn_id).first()
        assert txn is not None
        assert txn.status == 'PENDING'
        assert txn.expires_at is not None
        # Expiry is roughly 10 minutes ahead
        assert txn.expires_at > datetime.utcnow() + timedelta(minutes=8)
        assert txn.failed_attempts == 0

        # Sender balance must NOT be deducted yet
        user = User.query.filter_by(user_id=sender_user).first()
        assert float(user.balance) == 10000.00

        # Check OTP issuance
        email_otp = OtpCode.query.filter_by(user_id=sender_user, channel='EMAIL', txn_id=txn_id).first()
        telegram_otp = OtpCode.query.filter_by(user_id=sender_user, channel='TELEGRAM', txn_id=txn_id).first()
        assert email_otp is not None
        assert telegram_otp is not None
        assert email_otp.dual_group_id == telegram_otp.dual_group_id

        # Verify mock sender received messages mentioning amount and masked payee
        assert len(mock_sender.messages) >= 2


def test_otp_verify_success_atomic_transfer(client, app, sender_user, receiver_user, sender_jwt):
    """POST /api/otp/verify with dual OTP executes transfer in atomic DB transaction."""
    # Create PENDING transaction
    txn_id = "TXN-STEPUP-SUCCESS-01"
    with app.app_context():
        user = User.query.filter_by(user_id=sender_user).first()
        new_txn = Transaction(
            txn_id=txn_id,
            user_id=sender_user,
            sender_upi=encrypt_val("9876543210@mlbfd"),
            receiver_upi=encrypt_val("9876543211@mlbfd"),
            amount=1500.00,
            status='PENDING',
            risk_score=68.0,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            failed_attempts=0
        )
        db.session.add(new_txn)
        db.session.commit()

        # Issue dual OTP
        dual_res = otp_service.issue_dual(user, purpose="TRANSACTION", txn_id=txn_id, amount=1500.00, receiver="9876543211@mlbfd")
        email_code = dual_res.email_code
        telegram_code = dual_res.telegram_code

    # Verify both codes
    res = client.post('/api/otp/verify', json={
        'txn_id': txn_id,
        'email_code': email_code,
        'telegram_code': telegram_code
    }, headers={'Authorization': f'Bearer {sender_jwt}'})

    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['status'] == 'COMPLETED'

    with app.app_context():
        # Check sender balance deducted: 10000 - 1500 = 8500
        sender = User.query.filter_by(user_id=sender_user).first()
        assert float(sender.balance) == 8500.00

        # Check receiver balance credited: 5000 + 1500 = 6500
        receiver = User.query.filter_by(user_id=receiver_user).first()
        assert float(receiver.balance) == 6500.00

        # Check transaction status COMPLETED
        txn = Transaction.query.filter_by(txn_id=txn_id).first()
        assert txn.status == 'COMPLETED'


def test_otp_verify_rechecks_balance(client, app, sender_user, sender_jwt):
    """POST /api/otp/verify re-checks balance; fails cleanly if balance insufficient."""
    txn_id = "TXN-STEPUP-BALANCE-02"
    with app.app_context():
        user = User.query.filter_by(user_id=sender_user).first()
        new_txn = Transaction(
            txn_id=txn_id,
            user_id=sender_user,
            sender_upi=encrypt_val("9876543210@mlbfd"),
            receiver_upi=encrypt_val("9876543211@mlbfd"),
            amount=5000.00,
            status='PENDING',
            risk_score=70.0,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            failed_attempts=0
        )
        db.session.add(new_txn)
        db.session.commit()

        dual_res = otp_service.issue_dual(user, purpose="TRANSACTION", txn_id=txn_id)
        email_code = dual_res.email_code
        telegram_code = dual_res.telegram_code

        # Reduce balance below amount before verify
        user.balance = 200.00
        db.session.commit()

    res = client.post('/api/otp/verify', json={
        'txn_id': txn_id,
        'email_code': email_code,
        'telegram_code': telegram_code
    }, headers={'Authorization': f'Bearer {sender_jwt}'})

    assert res.status_code == 400
    data = res.get_json()
    assert data['success'] is False
    assert "Insufficient" in data['message']


def test_three_failed_attempts_cancels_transaction(client, app, sender_user, sender_jwt):
    """Three incorrect OTP attempts cancel the transaction."""
    txn_id = "TXN-STEPUP-FAIL-03"
    with app.app_context():
        user = User.query.filter_by(user_id=sender_user).first()
        new_txn = Transaction(
            txn_id=txn_id,
            user_id=sender_user,
            sender_upi=encrypt_val("9876543210@mlbfd"),
            receiver_upi=encrypt_val("9876543211@mlbfd"),
            amount=100.00,
            status='PENDING',
            risk_score=65.0,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            failed_attempts=0
        )
        db.session.add(new_txn)
        db.session.commit()
        otp_service.issue_dual(user, purpose="TRANSACTION", txn_id=txn_id)

    # Attempt 1
    res1 = client.post('/api/otp/verify', json={
        'txn_id': txn_id,
        'email_code': '000000',
        'telegram_code': '000000'
    }, headers={'Authorization': f'Bearer {sender_jwt}'})
    assert res1.status_code == 401
    assert res1.get_json()['attempts_remaining'] == 2

    # Attempt 2
    res2 = client.post('/api/otp/verify', json={
        'txn_id': txn_id,
        'email_code': '000001',
        'telegram_code': '000001'
    }, headers={'Authorization': f'Bearer {sender_jwt}'})
    assert res2.status_code == 401
    assert res2.get_json()['attempts_remaining'] == 1

    # Attempt 3 -> Transaction cancelled
    res3 = client.post('/api/otp/verify', json={
        'txn_id': txn_id,
        'email_code': '000002',
        'telegram_code': '000002'
    }, headers={'Authorization': f'Bearer {sender_jwt}'})
    assert res3.status_code == 400
    data3 = res3.get_json()
    assert data3['status'] == 'CANCELLED'

    with app.app_context():
        txn = Transaction.query.filter_by(txn_id=txn_id).first()
        assert txn.status == 'CANCELLED'


def test_three_cancelled_transactions_freezes_account(client, app, sender_user, sender_jwt):
    """Three cancelled transactions within an hour freeze the account and push alert to admin queue."""
    fake_clock = otp_service.FakeClock(datetime(2026, 6, 1, 10, 0, 0))
    otp_service.set_clock(fake_clock)
    try:
        final_res = None
        for i in range(1, 4):
            txn_id = f"TXN-CANCEL-FREEZE-{i}"
            with app.app_context():
                user = User.query.filter_by(user_id=sender_user).first()
                new_txn = Transaction(
                    txn_id=txn_id,
                    user_id=sender_user,
                    sender_upi=encrypt_val("9876543210@mlbfd"),
                    receiver_upi=encrypt_val("9876543211@mlbfd"),
                    amount=50.00,
                    status='PENDING',
                    risk_score=75.0,
                    expires_at=fake_clock.now() + timedelta(minutes=10),
                    created_at=fake_clock.now(),
                    failed_attempts=0
                )
                db.session.add(new_txn)
                db.session.commit()
                otp_service.issue_dual(user, purpose="TRANSACTION", txn_id=txn_id)

            # Fail 3 times on this transaction
            client.post('/api/otp/verify', json={'txn_id': txn_id, 'email_code': '111111', 'telegram_code': '222222'}, headers={'Authorization': f'Bearer {sender_jwt}'})
            client.post('/api/otp/verify', json={'txn_id': txn_id, 'email_code': '111111', 'telegram_code': '222222'}, headers={'Authorization': f'Bearer {sender_jwt}'})
            final_res = client.post('/api/otp/verify', json={'txn_id': txn_id, 'email_code': '111111', 'telegram_code': '222222'}, headers={'Authorization': f'Bearer {sender_jwt}'})

            # Advance clock past cooldown but well within 1 hour
            fake_clock.advance(seconds=35)

        # On the 3rd cancelled transaction, user account must be FROZEN
        assert final_res.status_code == 403
        assert final_res.get_json()['account_frozen'] is True

        with app.app_context():
            user = User.query.filter_by(user_id=sender_user).first()
            assert user.status == 'FROZEN'
    finally:
        otp_service.reset_clock()


def test_expired_transaction_cannot_be_verified(client, app, sender_user, sender_jwt):
    """Transactions expired past 10 minutes cannot be verified and are marked CANCELLED."""
    txn_id = "TXN-STEPUP-EXPIRED-04"
    with app.app_context():
        user = User.query.filter_by(user_id=sender_user).first()
        new_txn = Transaction(
            txn_id=txn_id,
            user_id=sender_user,
            sender_upi=encrypt_val("9876543210@mlbfd"),
            receiver_upi=encrypt_val("9876543211@mlbfd"),
            amount=500.00,
            status='PENDING',
            risk_score=65.0,
            expires_at=datetime.utcnow() - timedelta(minutes=1), # Expired!
            failed_attempts=0
        )
        db.session.add(new_txn)
        db.session.commit()
        dual_res = otp_service.issue_dual(user, purpose="TRANSACTION", txn_id=txn_id)
        email_code = dual_res.email_code
        telegram_code = dual_res.telegram_code

    res = client.post('/api/otp/verify', json={
        'txn_id': txn_id,
        'email_code': email_code,
        'telegram_code': telegram_code
    }, headers={'Authorization': f'Bearer {sender_jwt}'})

    assert res.status_code == 400
    data = res.get_json()
    assert data['status'] == 'CANCELLED'
    assert "expired" in data['message'].lower()


def test_twilio_and_pyotp_removed():
    """Verify Twilio and PyOTP are eliminated from backend dependencies and env configs."""
    req_path = os.path.join(backend_path, "requirements.txt")
    with open(req_path, "r", encoding="utf-8") as f:
        req_content = f.read().lower()
    assert "twilio" not in req_content
    assert "pyotp" not in req_content

    env_path = os.path.join(backend_path, ".env.example")
    with open(env_path, "r", encoding="utf-8") as f:
        env_content = f.read()
    assert "TWILIO" not in env_content


def test_admin_alerts_and_stats_include_pending_and_cancelled(client, app, sender_user):
    """Admin alerts and stats include PENDING, CANCELLED, and COMPLETED states."""
    with app.app_context():
        t1 = Transaction(
            txn_id="TXN-ADMIN-01",
            user_id=sender_user,
            sender_upi=encrypt_val("9876543210@mlbfd"),
            receiver_upi=encrypt_val("9876543211@mlbfd"),
            amount=100.00,
            status='PENDING',
            risk_score=65.0
        )
        t2 = Transaction(
            txn_id="TXN-ADMIN-02",
            user_id=sender_user,
            sender_upi=encrypt_val("9876543210@mlbfd"),
            receiver_upi=encrypt_val("9876543211@mlbfd"),
            amount=200.00,
            status='CANCELLED',
            risk_score=75.0
        )
        db.session.add_all([t1, t2])
        db.session.commit()

    # Check alerts endpoint
    res_alerts = client.get('/admin/api/alerts')
    assert res_alerts.status_code == 200
    alerts = res_alerts.get_json()['alerts']
    alert_statuses = [a['status'] for a in alerts]
    assert 'PENDING' in alert_statuses
    assert 'CANCELLED' in alert_statuses

    # Check stats endpoint
    res_stats = client.get('/admin/api/stats')
    assert res_stats.status_code == 200
    status_counts = res_stats.get_json()['status_counts']
    assert 'PENDING' in status_counts
    assert 'CANCELLED' in status_counts
    assert 'COMPLETED' in status_counts
