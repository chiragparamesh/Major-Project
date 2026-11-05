import time
import os
import sys
from datetime import datetime, timedelta
import pytest
from unittest.mock import patch

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from db import db
from database import User, Transaction
from security import encrypt_val, compute_lookup_hash, hash_pin, generate_form_timing_token
from geofence import reverse_geocode, check_geofence, haversine_km


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["TURNSTILE_SECRET_KEY"] = "MOCK"

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _create_user(user_id="user_loc", balance=50000.00, home_lat=12.9716, home_lon=77.5946, phone="+919876543210"):
    user = User(
        user_id=user_id,
        full_name="Location Test User",
        phone=encrypt_val(phone),
        phone_hash=compute_lookup_hash(phone),
        email=encrypt_val(f"{user_id}@gmail.com"),
        email_hash=compute_lookup_hash(f"{user_id}@gmail.com"),
        upi_id=encrypt_val(f"{phone[-10:]}@mlbfd"),
        upi_hash=compute_lookup_hash(f"{phone[-10:]}@mlbfd"),
        status="ACTIVE",
        email_verified=True,
        telegram_verified=True,
        balance=balance,
        login_pin_hash=hash_pin("123456"),
        payment_pin_hash=hash_pin("654321"),
        home_latitude=home_lat,
        home_longitude=home_lon,
        home_accuracy_m=15.0,
        home_location_source="manual_pin",
        home_area_name="Bengaluru",
        consent_at=datetime.utcnow(),
        phone_number=phone
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_reverse_geocode_rajajinagar_landmark():
    """Coordinates near Rajajinagar must reverse geocode to 'Rajajinagar, Bengaluru'."""
    area = reverse_geocode(12.9982, 77.5530)
    assert "Rajajinagar" in area
    assert "Bengaluru" in area


def test_reverse_geocode_caching():
    """Subsequent lookups for the same coordinates should use cache."""
    # First call
    area1 = reverse_geocode(12.9352, 77.6245)
    assert "Koramangala" in area1
    # Second call (hits cache)
    area2 = reverse_geocode(12.9352, 77.6245)
    assert area1 == area2


def test_reverse_geocode_api_endpoint(client):
    """GET /api/reverse_geocode returns area name and coordinates."""
    resp = client.get("/api/reverse_geocode?lat=12.9982&lon=77.5530")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "Rajajinagar" in data["area_name"]

    # Missing params return 400
    bad_resp = client.get("/api/reverse_geocode")
    assert bad_resp.status_code == 400


def test_signup_stores_rajajinagar_pin_and_area(client):
    """Signup with Rajajinagar coordinates saves area name, accuracy, and source."""
    payload = {
        "full_name": "Rajaji Resident",
        "user_id": "rajaji_user",
        "phone": "9876500077",
        "email": "rajaji@gmail.com",
        "login_pin": "948271",
        "payment_pin": "183920",
        "security_question": "What is the name of your first school?",
        "security_answer": "National Public School",
        "consent": True,
        "lat": 12.9982,
        "lon": 77.5530,
        "accuracy_m": 12.0,
        "source": "manual_pin",
        "form_started_at": time.time() - 4.0,
        "form_timing_token": generate_form_timing_token(timestamp=time.time() - 4.0)
    }

    resp = client.post("/api/register/start", json=payload)
    assert resp.status_code == 201

    user = User.query.filter_by(user_id="rajaji_user").first()
    assert user is not None
    assert abs(float(user.home_latitude) - 12.9982) < 0.001
    assert abs(float(user.home_longitude) - 77.5530) < 0.001
    assert user.home_accuracy_m == 12.0
    assert user.home_location_source == "manual_pin"
    assert "Rajajinagar" in user.home_area_name


def test_geofence_penalty_skip_when_accuracy_over_5000m(client):
    """If accuracy_m > 5000, geofence penalties (+20/+40) must be skipped."""
    sender = _create_user(user_id="sender_geo", balance=20000.00, home_lat=12.9716, home_lon=77.5946)
    
    # Mumbai coordinates (approx 840 km from Bengaluru > 500 km)
    mumbai_lat, mumbai_lon = 19.0760, 72.8777

    # Case A: High accuracy (50m) -> Triggers 40-point geofence penalty
    score_high_acc, flags_high_acc = check_geofence(
        user_id="sender_geo",
        current_lat=mumbai_lat,
        current_lon=mumbai_lon,
        accuracy_m=50.0
    )
    assert score_high_acc == 40
    assert any("> 500km" in f for f in flags_high_acc)

    # Case B: Low accuracy (6000m > 5000m threshold) -> Penalty skipped (0 points)
    score_low_acc, flags_low_acc = check_geofence(
        user_id="sender_geo",
        current_lat=mumbai_lat,
        current_lon=mumbai_lon,
        accuracy_m=6000.0
    )
    assert score_low_acc == 0
    assert any("skipped" in f.lower() for f in flags_low_acc)


def test_transfer_stores_location_source_and_accuracy(client):
    """POST /api/transfer records accuracy_m, location_source, and area_name on Transaction."""
    sender = _create_user(user_id="txn_loc_sender", balance=20000.00, phone="+919876543201")
    receiver = _create_user(user_id="txn_loc_receiver", balance=5000.00, phone="+919876543202")

    from flask_jwt_extended import create_access_token
    token = create_access_token(identity="txn_loc_sender")

    payload = {
        "receiver": "9876543202@mlbfd",
        "amount": 500.00,
        "payment_pin": "654321",
        "lat": 12.9982,
        "lon": 77.5530,
        "accuracy_m": 8.5,
        "source": "manual_pin"
    }

    resp = client.post(
        "/api/transfer",
        json=payload,
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] in ("APPROVED", "APPROVED_WITH_WARNING", "REQUIRES_2FA")

    # Check transaction in DB
    txn = Transaction.query.filter_by(user_id="txn_loc_sender").order_by(Transaction.created_at.desc()).first()
    assert txn is not None
    assert abs(float(txn.latitude) - 12.9982) < 0.001
    assert abs(float(txn.longitude) - 77.5530) < 0.001
    assert txn.accuracy_m == 8.5
    assert txn.location_source == "manual_pin"
    assert "Rajajinagar" in txn.area_name


def test_map_picker_exists_in_portal_template(client):
    """Verify that Leaflet map picker elements exist in user dashboard template."""
    dashboard_path = os.path.join(backend_path, "..", "dashboard", "templates", "user_dashboard.html")
    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "id=\"map-modal\"" in content
    assert "id=\"leaflet-map\"" in content
    assert "Rajajinagar Pin" in content
    assert "Confirm Location" in content
    assert "leaflet.js" in content
