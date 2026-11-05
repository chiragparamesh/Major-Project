import os
import sys
import subprocess
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager
import pandas as pd

# Project Imports
from config import Config
from db import db, init_db
from api import api_bp
from database import User, Transaction, UserBehaviorBaseline, ModelMetrics, ScamUpi, AuditLog, TokenBlocklist
from security import decrypt_val
from rate_limiter import limiter

def create_app(start_bot=None):
    """start_bot=None: poll Telegram unless TESTING; False: never (e.g. reloader parent)."""
    # Set up template and static folders pointing to the dashboard folder
    current_dir = os.path.dirname(os.path.abspath(__file__))
    dashboard_dir = os.path.abspath(os.path.join(current_dir, "..", "dashboard"))
    template_dir = os.path.join(dashboard_dir, "templates")
    static_dir = os.path.join(dashboard_dir, "static")

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
        static_url_path="/static"
    )
    
    app.config.from_object(Config)
    
    # Enable CORS
    CORS(app)
    
    # Initialize JWT Manager
    jwt = JWTManager(app)
    
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        from database import TokenBlocklist, User
        jti = jwt_payload.get("jti")
        if jti and TokenBlocklist.query.filter_by(jti=jti).first():
            return True
        user_id = jwt_payload.get("sub")
        iat = jwt_payload.get("iat")
        if user_id and iat:
            user = User.query.filter_by(user_id=str(user_id)).first()
            if user and user.tokens_revoked_at:
                iat_dt = datetime.utcfromtimestamp(iat)
                # iat has whole-second precision; tokens_revoked_at has microseconds. Using
                # "<=" revoked the fresh token handed out by PIN reset in the same second.
                if iat_dt < user.tokens_revoked_at.replace(microsecond=0):
                    return True
        return False
    
    # Initialize Rate Limiter
    limiter.init_app(app)
    
    # Initialize Database with SQLite fallback
    init_db(app)
    
    # Register blueprints
    app.register_blueprint(api_bp, url_prefix="/api")

    # Register EMAIL and TELEGRAM channel senders in otp_service
    try:
        from email_sender import register_as_email_sender
        register_as_email_sender()
    except Exception as e:
        app.logger.exception(f"app: FAILED to register email sender — OTPs will use MockSender: {e}")
        app.logger.warning(f"Could not register email sender: {e}")

    try:
        from telegram_bot import register_as_telegram_sender, telegram_bot
        register_as_telegram_sender()

        # Run getUpdates long-polling in ONE daemon thread started from the app factory
        # Guard against the Flask reloader starting it twice:
        # The Werkzeug reloader parent passes start_bot=False; a PID lock in
        # telegram_bot stops any second process (serve.py + app.py) from polling too.
        is_testing = app.config.get("TESTING", False)
        polling_enabled = getattr(Config, "TELEGRAM_POLLING_ENABLED", True)

        if start_bot is not False and not is_testing and polling_enabled:
            telegram_bot.start_polling(app)
    except Exception as e:
        app.logger.exception(f"app: FAILED to register Telegram sender — OTPs will use MockSender: {e}")
        app.logger.warning(f"Could not initialize Telegram bot: {e}")

    
    # ----------------------------------------------------
    # ADMIN GATE: every /admin page and /admin/api endpoint
    # ----------------------------------------------------
    @app.before_request
    def _gate_admin():
        if not request.path.startswith("/admin"):
            return None
        from security import admin_request_allowed, ADMIN_COOKIE
        from env_loader import env_str
        import hmac as _hmac
        token = env_str("ADMIN_API_TOKEN")
        supplied = request.args.get("admin_token")
        if token and supplied and _hmac.compare_digest(supplied, token):
            # One-time login link: set an HttpOnly cookie and drop the token from the URL.
            from flask import redirect
            resp = redirect(request.path)
            resp.set_cookie(ADMIN_COOKIE, token, httponly=True, samesite="Strict",
                            secure=request.is_secure or request.headers.get("X-Forwarded-Proto") == "https",
                            max_age=8 * 3600)
            return resp
        if admin_request_allowed(request):
            return None
        if request.path.startswith("/admin/api"):
            return jsonify({"success": False, "message": "Admin authentication required."}), 403
        return ("Admin portal: open it on the server machine (http://localhost:5000/admin) "
                "or use /admin?admin_token=<ADMIN_API_TOKEN>.", 403)

    # ----------------------------------------------------
    # DASHBOARD HTML VIEWS
    # ----------------------------------------------------
    @app.route("/")
    @app.route("/dashboard")
    def user_dashboard_view():
        return render_template("user_dashboard.html")

    @app.route("/login")
    @app.route("/user/login")
    def user_login_view():
        return render_template("user_login.html")

    @app.route("/register")
    @app.route("/user/register")
    def user_register_view():
        return render_template("user_register.html")

    @app.route("/admin")
    @app.route("/admin/overview")
    def index():
        return render_template("index.html")

    @app.route("/admin/transactions")
    def transactions_view():
        return render_template("transactions.html")

    @app.route("/admin/alerts")
    def alerts_view():
        return render_template("alerts.html")

    @app.route("/admin/users")
    def users_view():
        return render_template("users.html")

    @app.route("/admin/models")
    def models_view():
        return render_template("models.html")

    @app.route("/admin/drift")
    def drift_view():
        return render_template("drift.html")

    # ----------------------------------------------------
    # DASHBOARD API ENDPOINTS
    # ----------------------------------------------------
    @app.route("/admin/api/stats", methods=["GET"])
    def get_dashboard_stats():
        try:
            total_txns = Transaction.query.count()
            total_users = User.query.count()
            
            # Aggregate volume
            txns = Transaction.query.all()
            total_volume = sum(float(t.amount) for t in txns)
            
            # Risk scores & fraud metrics
            avg_risk = sum(float(t.risk_score or 0) for t in txns) / total_txns if total_txns > 0 else 0.0
            blocked_txns = sum(1 for t in txns if t.status == "BLOCKED" or t.is_fraud)
            fraud_rate = (blocked_txns / total_txns * 100) if total_txns > 0 else 0.0
            
            pending_alerts = Transaction.query.filter(Transaction.status.in_(["REQUIRES_2FA", "PENDING"])).count()
            
            # Group by status
            status_counts = {
                "APPROVED": sum(1 for t in txns if t.status == "APPROVED"),
                "COMPLETED": sum(1 for t in txns if t.status == "COMPLETED"),
                "APPROVED_WITH_WARNING": sum(1 for t in txns if t.status == "APPROVED_WITH_WARNING"),
                "REQUIRES_2FA": pending_alerts,
                "PENDING": sum(1 for t in txns if t.status == "PENDING"),
                "CANCELLED": sum(1 for t in txns if t.status == "CANCELLED"),
                "BLOCKED": sum(1 for t in txns if t.status == "BLOCKED")
            }
            
            # Time series daily stats (last 7 days)
            # Group by day
            daily_stats = {}
            for t in txns:
                day_str = t.created_at.strftime("%Y-%m-%d")
                if day_str not in daily_stats:
                    daily_stats[day_str] = {"count": 0, "volume": 0.0, "fraud": 0}
                daily_stats[day_str]["count"] += 1
                daily_stats[day_str]["volume"] += float(t.amount)
                if t.status == "BLOCKED" or t.is_fraud:
                    daily_stats[day_str]["fraud"] += 1
            
            sorted_days = sorted(daily_stats.keys())[-7:]
            chart_data = {
                "labels": sorted_days,
                "counts": [daily_stats[d]["count"] for d in sorted_days],
                "volumes": [daily_stats[d]["volume"] for d in sorted_days],
                "frauds": [daily_stats[d]["fraud"] for d in sorted_days]
            }
            
            return jsonify({
                "success": True,
                "total_transactions": total_txns,
                "total_users": total_users,
                "total_volume": total_volume,
                "average_risk_score": avg_risk,
                "fraud_rate": fraud_rate,
                "pending_alerts": pending_alerts,
                "status_counts": status_counts,
                "chart_data": chart_data
            }), 200
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/admin/api/transactions", methods=["GET"])
    def get_all_transactions():
        try:
            txns = Transaction.query.order_by(Transaction.created_at.desc()).limit(200).all()
            output = []
            for t in txns:
                output.append({
                    "id": t.id,
                    "txn_id": t.txn_id,
                    "user_id": t.user_id,
                    "sender_upi": decrypt_val(t.sender_upi),
                    "receiver_upi": decrypt_val(t.receiver_upi),
                    "amount": float(t.amount),
                    "status": t.status,
                    "risk_score": float(t.risk_score or 0),
                    "is_fraud": t.is_fraud,
                    "device_id": t.device_id,
                    "latitude": float(t.latitude or 0),
                    "longitude": float(t.longitude or 0),
                    "merchant_name": t.merchant_name,
                    "mcc_code": t.mcc_code,
                    "layer_scores": t.layer_scores,
                    "flags": t.flags,
                    "created_at": t.created_at.isoformat() + 'Z'
                })
            return jsonify({"success": True, "transactions": output}), 200
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/admin/api/alerts", methods=["GET"])
    def get_dashboard_alerts():
        try:
            # Alerts include BLOCKED, REQUIRES_2FA, PENDING, and CANCELLED
            txns = Transaction.query.filter(Transaction.status.in_(["BLOCKED", "REQUIRES_2FA", "PENDING", "CANCELLED"])).order_by(Transaction.created_at.desc()).all()
            output = []
            for t in txns:
                ls = t.layer_scores or {}
                output.append({
                    "id": t.id,
                    "txn_id": t.txn_id,
                    "user_id": t.user_id,
                    "sender_upi": decrypt_val(t.sender_upi),
                    "receiver_upi": decrypt_val(t.receiver_upi),
                    "amount": float(t.amount),
                    "status": t.status,
                    "risk_score": float(t.risk_score or 0),
                    "is_fraud": t.is_fraud,
                    "device_id": t.device_id,
                    "layer_scores": ls,
                    "top_5_features": ls.get("top_5_features", []),
                    "shap_explanations": ls.get("shap_explanations", []),
                    "plain_language_reason": ls.get("plain_language_reason", ""),
                    "flags": t.flags,
                    "created_at": t.created_at.isoformat() + 'Z'
                })
            return jsonify({"success": True, "alerts": output}), 200
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/admin/api/users", methods=["GET"])
    def get_all_users():
        try:
            from security import mask_phone, mask_email
            users = User.query.all()
            output = []
            for u in users:
                # Get last transaction details
                last_txn = Transaction.query.filter_by(user_id=u.user_id).order_by(Transaction.created_at.desc()).first()
                last_active = last_txn.created_at.isoformat() + 'Z' if last_txn else "Never"
                raw_phone = u.get_decrypted_phone()
                raw_email = u.get_decrypted_email()
                
                output.append({
                    "id": u.id,
                    "user_id": u.user_id,
                    "full_name": u.full_name,
                    "phone_number": mask_phone(raw_phone),
                    "email": mask_email(raw_email),
                    "status": u.status,
                    "balance": float(u.balance or 0.0),
                    "is_locked": u.is_locked or (u.status == 'FROZEN'),
                    "failed_attempts": u.failed_attempts,
                    "last_active": last_active,
                    "created_at": u.created_at.isoformat() + 'Z'
                })
            return jsonify({"success": True, "users": output}), 200
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/admin/api/users/<user_id>/toggle-lock", methods=["POST"])
    def toggle_user_lock(user_id):
        try:
            user = User.query.filter_by(user_id=user_id).first()
            if not user:
                return jsonify({"success": False, "message": "User not found"}), 404
            
            if user.status not in ('ACTIVE', 'FROZEN'):
                # A PENDING signup must never become ACTIVE through an admin toggle (skips OTP).
                return jsonify({"success": False,
                                "message": f"Only ACTIVE or FROZEN accounts can be locked/unlocked (status: {user.status})."}), 409

            data = request.get_json(silent=True) or {}
            raw = data.get("lock", not (user.is_locked or user.status == 'FROZEN'))
            lock_status = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("true", "1", "yes")

            user.is_locked = lock_status
            if not lock_status:
                # Clear every lockout counter, not just the legacy one, or the user stays locked out.
                user.failed_attempts = 0
                user.locked_until = None
                user.login_failed_attempts = 0
                user.login_locked_until = None
                user.payment_failed_attempts = 0
                user.payment_locked_until = None
                user.status = 'ACTIVE'
            else:
                user.status = 'FROZEN'

            db.session.commit()
            from audit_logger import log_audit_action
            log_audit_action(user.user_id, "ADMIN_UNLOCK" if not lock_status else "ADMIN_LOCK", 200)
            status_text = "locked" if lock_status else "unlocked"
            return jsonify({"success": True, "message": f"User account has been successfully {status_text}."}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    def _metrics_from_training_file():
        """Honest held-out metrics written by train_all_models.py (nothing writes ModelMetrics rows)."""
        import json
        path = os.path.join(current_dir, "models", "mlbfd_mega_metrics.json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        trained_at = str((raw.get("_metadata") or {}).get("timestamp") or "")
        out = []
        for i, (name, m) in enumerate(raw.items(), 1):
            if name.startswith("_") or not isinstance(m, dict):
                continue
            real = m.get("real_subset") or {}
            sim = m.get("simulator_subset") or {}
            out.append({
                "id": i,
                "model_name": name,
                "auc_score": float(m.get("roc_auc") or 0),
                "pr_auc": float(m.get("pr_auc") or 0),
                "recall": float(m.get("recall") or 0),
                "precision": float(m.get("precision") or 0),
                "f1_score": float(m.get("f1_score") or 0),
                "accuracy": float(m.get("accuracy") or 0),
                "recall_at_1pct_fpr": float(m.get("recall_at_1pct_fpr") or 0),
                "real_recall_at_1pct_fpr": float(real.get("recall_at_1pct_fpr") or 0),
                "simulator_recall_at_1pct_fpr": float(sim.get("recall_at_1pct_fpr") or 0),
                "trained_at": trained_at,
                "source": "training file",
            })
        return out

    @app.route("/admin/api/models/metrics", methods=["GET"])
    def get_model_metrics():
        try:
            file_metrics = _metrics_from_training_file()
            if file_metrics:
                return jsonify({"success": True, "metrics": file_metrics}), 200
            metrics = ModelMetrics.query.order_by(ModelMetrics.trained_at.desc()).all()
            output = []
            seen = set()
            for m in metrics:
                # Group by model name, show only the latest training run
                if m.model_name in seen:
                    continue
                seen.add(m.model_name)
                output.append({
                    "id": m.id,
                    "model_name": m.model_name,
                    "auc_score": float(m.auc_score or 0),
                    "recall": float(m.recall or 0),
                    "precision": float(m.precision or 0),
                    "f1_score": float(m.f1_score or 0),
                    "accuracy": float(m.accuracy or 0),
                    "trained_at": m.trained_at.isoformat() + 'Z'
                })
            return jsonify({"success": True, "metrics": output}), 200
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    _retrain_lock = threading.Lock()

    @app.route("/admin/api/models/retrain", methods=["POST"])
    def trigger_model_retrain():
        try:
            if not _retrain_lock.acquire(blocking=False):
                return jsonify({"success": False, "message": "Retraining is already running."}), 409

            def run_training():
                py_path = sys.executable
                train_script = os.path.join(current_dir, "train_all_models.py")
                app_log_dir = os.path.dirname(train_script)
                
                # Check for venv python first
                venv_python = os.path.join(current_dir, ".venv", "Scripts", "python.exe")
                if not os.path.exists(venv_python):
                    venv_python = os.path.join(current_dir, "venv311", "Scripts", "python.exe")
                if os.path.exists(venv_python):
                    py_path = venv_python
                
                print(f"🔄 Retraining models asynchronously with: {py_path}...")
                try:
                    subprocess.run([py_path, train_script], cwd=app_log_dir)
                    print("✅ Asynchronous model retraining complete!")
                finally:
                    _retrain_lock.release()

            thread = threading.Thread(target=run_training)
            thread.daemon = True
            thread.start()
            
            return jsonify({"success": True, "message": "Model retraining process successfully started in background."}), 202
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/admin/api/drift/metrics", methods=["GET"])
    def get_data_drift_metrics():
        try:
            # We fetch recent transactions (e.g. last 100) and compare metrics with user baselines
            recent_txns = Transaction.query.order_by(Transaction.created_at.desc()).limit(100).all()
            if not recent_txns:
                return jsonify({
                    "success": True,
                    "drift_detected": False,
                    "amount_drift_score": 0.0,
                    "location_drift_score": 0.0,
                    "time_drift_score": 0.0,
                    "message": "No transaction history to compute drift."
                }), 200
                
            recent_amounts = [float(t.amount) for t in recent_txns]
            recent_mean = sum(recent_amounts) / len(recent_amounts)
            
            # Baseline average amount across all users
            baselines = UserBehaviorBaseline.query.all()
            baseline_mean = sum(float(b.avg_amount) for b in baselines) / len(baselines) if baselines else 5000.0
            
            # Percentage change as a proxy for drift
            amount_drift = abs(recent_mean - baseline_mean) / baseline_mean if baseline_mean > 0 else 0.0
            
            # Check for sudden surge in block rates (velocity/concept drift)
            recent_blocked = sum(1 for t in recent_txns if t.status == "BLOCKED")
            blocked_ratio = recent_blocked / len(recent_txns)
            
            drift_detected = (amount_drift > 0.3) or (blocked_ratio > 0.15)
            
            return jsonify({
                "success": True,
                "drift_detected": bool(drift_detected),
                "amount_drift_score": float(round(amount_drift, 4)),
                "blocked_ratio": float(round(blocked_ratio, 4)),
                "baseline_mean": float(round(baseline_mean, 2)),
                "recent_mean": float(round(recent_mean, 2)),
                "metrics": {
                    "psi_score": float(round(amount_drift * 0.5, 4)),  # Mocked Population Stability Index
                    "ks_p_value": 0.045 if drift_detected else 0.420
                }
            }), 200
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/admin/api/compliance/npci-export", methods=["GET"])
    def export_npci_csv():
        try:
            txns = Transaction.query.order_by(Transaction.created_at.desc()).all()
            
            def mask_upi_str(upi):
                if '@' in upi:
                    parts = upi.split('@')
                    local = parts[0]
                    domain = parts[1]
                    masked = local[:2] + '*' * max(0, len(local) - 2) + '@' + domain
                    return masked
                return upi[:3] + '***' + upi[-3:] if len(upi) > 6 else '***'
            
            records = []
            for t in txns:
                decrypted_sender = decrypt_val(t.sender_upi)
                decrypted_receiver = decrypt_val(t.receiver_upi)
                records.append({
                    "NPCI_TXN_ID": t.txn_id,
                    "SENDER_UPI_MASKED": mask_upi_str(decrypted_sender),
                    "RECEIVER_UPI_MASKED": mask_upi_str(decrypted_receiver),
                    "AMOUNT": float(t.amount),
                    "RISK_VERDICT": t.status,
                    "RISK_SCORE": float(t.risk_score or 0),
                    "FRAUD_FLAG": 1 if t.is_fraud else 0,
                    "MCC": t.mcc_code,
                    "TIMESTAMP": t.created_at.strftime("%Y-%m-%d %H:%M:%S")
                })
            
            df = pd.DataFrame(records)
            export_path = os.path.join(current_dir, "npci_fraud_report.csv")
            df.to_csv(export_path, index=False)
            
            return send_file(
                export_path,
                mimetype="text/csv",
                as_attachment=True,
                download_name=f"npci_fraud_report_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
            )
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    return app

if __name__ == "__main__":
    # debug=True runs the Werkzeug reloader: this file executes in a parent watcher
    # process AND a serving child (WERKZEUG_RUN_MAIN=true). Only the child may poll
    # Telegram, otherwise both call getUpdates and Telegram answers HTTP 409.
    use_reloader = os.getenv("FLASK_USE_RELOADER", "true").lower() in ("true", "1", "yes")
    is_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    app = create_app(start_bot=(is_child or not use_reloader))
    if is_child or not use_reloader:
        import otp_service
        for w in otp_service.startup_banner_lines():
            print(f"!! OTP WARNING: {w}")
    # Read port from environment variable
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=use_reloader)
