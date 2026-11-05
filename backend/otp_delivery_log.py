"""
Append-only OTP delivery log (logs/otp_delivery.log).

One line per delivery attempt: channel, purpose, hashed user id, outcome and
exception class. Never contains an OTP code, an email address, a phone number
or a chat id.
"""
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone

from env_loader import REPO_ROOT

LOG_PATH = os.path.join(REPO_ROOT, "logs", "otp_delivery.log")
_lock = threading.Lock()
logger = logging.getLogger(__name__)


def user_hash(user_id) -> str:
    return hashlib.sha256(str(user_id or "").encode("utf-8")).hexdigest()[:12]


def record(channel: str, purpose: str, user_id, ok: bool, detail: str = "", error_class: str = "", route: str = ""):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "channel": str(channel or "").upper(),
        "purpose": str(purpose or "").upper(),
        "user": user_hash(user_id),
        "ok": bool(ok),
        "detail": str(detail or "")[:120],
        "error_class": error_class or "",
        "route": route or "",
    }
    line = json.dumps(entry, separators=(",", ":"))
    try:
        with _lock:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError as e:
        logger.error(f"otp_delivery_log: cannot write log ({type(e).__name__})")
    (logger.info if ok else logger.warning)(f"otp_delivery {line}")
