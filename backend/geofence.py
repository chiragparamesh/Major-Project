import time
import threading
import logging
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime
from typing import Optional, Tuple
import requests

from database import User, Transaction
from db import db

logger = logging.getLogger(__name__)

# Earth's radius in kilometers
R_EARTH_KM = 6371.0

# Rate limiting and cache locks for Nominatim API (max 1 req/sec per OSM policy)
_nominatim_lock = threading.Lock()
_last_nominatim_request_time = 0.0
_REVERSE_GEOCODE_CACHE = {}

# Well-known landmarks for instant deterministic resolution and offline tests
KNOWN_AREAS = [
    (12.9982, 77.5530, "Rajajinagar, Bengaluru"),
    (12.9716, 77.5946, "MG Road, Bengaluru"),
    (12.9352, 77.6245, "Koramangala, Bengaluru"),
    (12.9784, 77.6408, "Indiranagar, Bengaluru"),
    (12.9141, 77.6411, "HSR Layout, Bengaluru"),
    (13.0358, 77.5970, "Hebbal, Bengaluru"),
    (12.9279, 77.6271, "BTM Layout, Bengaluru"),
    (12.9250, 77.5938, "Jayanagar, Bengaluru"),
    (12.9698, 77.7499, "Whitefield, Bengaluru"),
    (12.8452, 77.6602, "Electronic City, Bengaluru"),
]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """
    Calculate the great-circle distance between two points on the Earth's surface
    specified in decimal degrees (latitude and longitude).
    """
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
    except (ValueError, TypeError):
        return 0.0

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R_EARTH_KM * c


def reverse_geocode(lat: float, lon: float) -> str:
    """
    Reverse-geocodes (lat, lon) to a human-readable area name using Nominatim API.
    - Enforces max 1 request per second rate-limit with custom User-Agent header.
    - Caches responses in memory.
    - Checks well-known landmark table for instant resolution.
    """
    global _last_nominatim_request_time
    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return "Unknown Location"

    # 1. Check known landmark areas (radius ~ 2 km)
    for k_lat, k_lon, k_name in KNOWN_AREAS:
        if haversine_km(lat, lon, k_lat, k_lon) <= 2.5:
            return k_name

    # 2. Check cache (keyed to 3 decimal places ~ 110m resolution)
    cache_key = (round(lat, 3), round(lon, 3))
    if cache_key in _REVERSE_GEOCODE_CACHE:
        return _REVERSE_GEOCODE_CACHE[cache_key]

    # 3. Call Nominatim API with rate limiting
    with _nominatim_lock:
        now = time.time()
        elapsed = now - _last_nominatim_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

        headers = {
            "User-Agent": "MLBFD-FraudDetection/1.0 (fraud-desk@mlbfd.org; https://github.com/mlbfd)"
        }
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=16&addressdetails=1"

        try:
            resp = requests.get(url, headers=headers, timeout=5)
            _last_nominatim_request_time = time.time()

            if resp.status_code == 200:
                data = resp.json()
                address = data.get("address", {})

                suburb = address.get("suburb") or address.get("neighbourhood") or address.get("residential")
                road = address.get("road")
                city = address.get("city") or address.get("town") or address.get("county") or address.get("state_district")

                parts = []
                if suburb:
                    parts.append(suburb)
                elif road:
                    parts.append(road)

                if city and city not in parts:
                    parts.append(city)

                area_name = ", ".join(parts) if parts else (data.get("display_name", "Unknown Area").split(",")[0].strip())
                if len(_REVERSE_GEOCODE_CACHE) >= 5000:  # bounded memory
                    _REVERSE_GEOCODE_CACHE.pop(next(iter(_REVERSE_GEOCODE_CACHE)))
                _REVERSE_GEOCODE_CACHE[cache_key] = area_name
                return area_name
        except (requests.exceptions.RequestException, ValueError) as e:
            _last_nominatim_request_time = time.time()
            logger.warning(f"Nominatim reverse geocoding lookup failed ({type(e).__name__})")

    # Honest fallback: never invent a city for an unresolved coordinate.
    return "Unknown Area"


_geo_pool = None


def reverse_geocode_nonblocking(lat, lon):
    """
    For the payment path: landmark/cache hit returns immediately; otherwise the
    Nominatim lookup (1 req/s, may sleep) is started in the background to warm the
    cache and None is returned, so a transfer never waits on OpenStreetMap.
    """
    global _geo_pool
    try:
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        return None
    for k_lat, k_lon, k_name in KNOWN_AREAS:
        if haversine_km(lat, lon, k_lat, k_lon) <= 2.5:
            return k_name
    hit = _REVERSE_GEOCODE_CACHE.get((round(lat, 3), round(lon, 3)))
    if hit:
        return hit
    if _geo_pool is None:
        from concurrent.futures import ThreadPoolExecutor
        _geo_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nominatim")
    _geo_pool.submit(reverse_geocode, lat, lon)
    return None


def check_geofence(user_id: str, current_lat: float, current_lon: float, accuracy_m: Optional[float] = None) -> Tuple[int, list]:
    """
    Check if the transaction occurs far away from the user's home location.
    Home coordinates are stored in the User record.
    If accuracy_m is over 5000 skip the geofence penalties (+20/+40).
    Returns: (score, list of warning flags)
    """
    # Low accuracy safeguard (Part 16): Skip geofence penalty if accuracy > 5000m
    if accuracy_m is not None:
        try:
            if float(accuracy_m) > 5000.0:
                return 0, [f"Geofence check skipped: location accuracy too low ({float(accuracy_m):.0f}m > 5000m)"]
        except (ValueError, TypeError):
            pass

    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.home_latitude is None or user.home_longitude is None:
        return 0, []

    distance = haversine_km(
        user.home_latitude, user.home_longitude,
        current_lat, current_lon
    )

    if distance > 500:
        return 40, [f"Transaction is {distance:.1f}km away from home (geofence warning > 500km)"]
    elif distance > 100:
        return 20, [f"Transaction is {distance:.1f}km away from home (geofence warning > 100km)"]

    return 0, []


def check_impossible_travel(user_id: str, current_lat: float, current_lon: float, current_time: datetime = None) -> Tuple[int, list]:
    """
    Validate if the speed required to travel from the last transaction location
    to the current transaction location is humanly possible (e.g. max plane speed: 900 km/h).
    Returns: (score, list of warning flags)
    """
    if current_time is None:
        current_time = datetime.utcnow()

    # Get the user's last transaction with coordinates
    last_txn = Transaction.query.filter_by(user_id=user_id)\
                                .filter(Transaction.latitude.isnot(None))\
                                .filter(Transaction.longitude.isnot(None))\
                                .order_by(Transaction.created_at.desc())\
                                .first()

    if not last_txn or last_txn.latitude is None or last_txn.longitude is None:
        return 0, []

    distance = haversine_km(
        last_txn.latitude, last_txn.longitude,
        current_lat, current_lon
    )

    # Calculate time delta in hours
    time_diff_seconds = (current_time - last_txn.created_at).total_seconds()
    hours_elapsed = time_diff_seconds / 3600.0

    if hours_elapsed <= 0:
        if distance > 1.0:
            return 50, ["Impossible Travel: Instant transactions at different geographical locations"]
        return 0, []

    required_speed = distance / hours_elapsed

    # Max commercial plane speed is approx 900 km/h
    if required_speed > 900.0:
        return 50, [f"Impossible Travel: Requires speed of {required_speed:.1f} km/h ({distance:.1f}km in {hours_elapsed:.2f}h)"]

    return 0, []
