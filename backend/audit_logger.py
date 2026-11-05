import logging
from flask import request
from db import db
from database import AuditLog

logger = logging.getLogger(__name__)

def log_audit_action(user_id: str, action: str, response_code: int = 200, risk_score: float = 0.0, request_hash: str = None):
    """Logs an action to the AuditLog database table"""
    try:
        from flask import has_request_context
        from security import client_ip
        ip_addr = client_ip(request) if has_request_context() else "127.0.0.1"
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            ip_address=ip_addr,
            request_hash=request_hash,
            response_code=response_code,
            risk_score=risk_score
        )
        db.session.add(log_entry)
        db.session.commit()
        logger.info(f"Audit action logged: user={user_id}, action={action}, ip={ip_addr}, code={response_code}")
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
        # Make sure database transaction failures don't crash main execution flow
        try:
            db.session.rollback()
        except Exception:
            logger.exception("audit_logger: rollback after failed audit write also failed")
