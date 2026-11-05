from flask_limiter import Limiter


def _limiter_key():
    # Per real client (Cloudflare tunnel aware), not per tunnel connection.
    from security import client_ip
    return client_ip()


# In-memory storage is fine for the single-process Waitress deployment.
limiter = Limiter(
    key_func=_limiter_key,
    default_limits=["300 per hour"],
    storage_uri="memory://",
)
