import html
import os
import re
import smtplib
import ssl
import threading
import time
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any, List, Tuple

from config import Config
from security import mask_upi
from env_loader import env_str, clean_value, is_placeholder
import otp_delivery_log

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 10
# How long an OTP request waits for the background SMTP thread before answering "pending".
OTP_SEND_WAIT_SECONDS = 8

class EmailConfigError(Exception):
    """Raised when SMTP credentials are missing; never silently treated as success."""


# Exceptions that will not improve by switching port/mode (stop immediately).
_FATAL_SMTP = (smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused)


def provider_name(host: str) -> str:
    h = (host or "").lower()
    if "gmail" in h:
        return "gmail"
    if "brevo" in h or "sendinblue" in h:
        return "brevo"
    return "smtp"


def smtp_settings(config=None) -> Dict[str, Any]:
    """Cleaned SMTP settings: canonical EMAIL_* names, legacy SMTP_* aliases as fallback."""
    cfg = config or Config

    def pick(attr, *names, default=""):
        v = env_str(*names)
        if v:
            return v
        v = getattr(cfg, attr, None)
        return clean_value(str(v)) if v not in (None, "") else default

    # EMAIL_USER = the mailbox (Gmail: also the login). Relays such as Brevo log in with a
    # separate EMAIL_SMTP_LOGIN; it falls back to EMAIL_USER so Gmail setups are unchanged.
    inbox = pick("EMAIL_USER", "EMAIL_USER", "SMTP_USER")
    # Live environment only (Config caches import-time values); injected configs may set it.
    user = env_str("EMAIL_SMTP_LOGIN") or (
        clean_value(str(getattr(cfg, "EMAIL_SMTP_LOGIN", "") or "")) if cfg is not Config else "") or inbox
    if is_placeholder(user):
        user = ""  # e.g. PASTE_BREVO_SMTP_LOGIN_HERE -> treated as not configured
    password = re.sub(r"\s+", "", pick("EMAIL_PASSWORD", "EMAIL_PASSWORD", "SMTP_PASS"))
    port_raw = pick("EMAIL_PORT", "EMAIL_PORT", "SMTP_PORT", default="587")
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    mode = (env_str("EMAIL_SMTP_MODE") or "auto").lower()
    if mode not in ("auto", "starttls", "ssl"):
        mode = "auto"
    return {
        "host": pick("EMAIL_HOST", "EMAIL_HOST", "SMTP_HOST", default="smtp.gmail.com"),
        "port": port,
        "mode": mode,
        "user": user,
        "inbox": inbox,
        "provider": provider_name(pick("EMAIL_HOST", "EMAIL_HOST", "SMTP_HOST", default="smtp.gmail.com")),
        "password": password,
        "from_name": pick("EMAIL_FROM_NAME", "EMAIL_FROM_NAME", default="MLBFD"),
        "from_addr": pick("EMAIL_FROM", "EMAIL_FROM", "SMTP_FROM", default=inbox or user or "no-reply@mlbfd.local"),
        "timeout": SMTP_TIMEOUT_SECONDS,
    }


def _smtp_routes(settings: Dict[str, Any]) -> List[Tuple[str, int]]:
    """Ordered (mode, port) attempts. auto = configured port first, then the other one."""
    port, mode = settings["port"], settings["mode"]
    if mode == "ssl":
        return [("SSL", port if port != 587 else 465)]
    if mode == "starttls":
        return [("STARTTLS", port if port != 465 else 587)]
    first = ("SSL", 465) if port == 465 else ("STARTTLS", port)
    second = ("STARTTLS", 587) if first[0] == "SSL" else ("SSL", 465)
    return [first, second]


def send_via_smtp(settings, to_email, subject, plain_text, html_content=None, attempts_log=None):
    """
    Try each SMTP route until one accepts the message.
    Returns (ok, "MODE:port" used, last exception). Never logs the address or body.
    """
    from_addr = settings["from_addr"]
    # Gmail rejects/rewrites a From that is not the authenticated account.
    if "gmail" in settings["host"].lower() and from_addr.lower() != settings["user"].lower():
        logger.warning("EMAIL_FROM differs from EMAIL_USER; using EMAIL_USER as sender for Gmail")
        from_addr = settings["user"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings['from_name']} <{from_addr}>"
    msg["To"] = to_email
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    if html_content:
        msg.attach(MIMEText(html_content, "html", "utf-8"))

    last_exc = None
    for mode, port in _smtp_routes(settings):
        route = f"{mode}:{port}"
        server = None
        try:
            ctx = ssl.create_default_context()
            if mode == "SSL":
                server = smtplib.SMTP_SSL(settings["host"], port, timeout=settings["timeout"], context=ctx)
            else:
                server = smtplib.SMTP(settings["host"], port, timeout=settings["timeout"])
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
            _smtp_login(server, settings["user"], settings["password"])
            server.sendmail(from_addr, [to_email], msg.as_string())
            logger.info(f"SMTP accepted message via {route}")
            if attempts_log is not None:
                attempts_log.append({"mode": mode, "port": port, "ok": True})
            return True, route, None
        except Exception as e:  # class is logged; caller re-raises the last one
            last_exc = e
            logger.warning(f"SMTP route {route} failed: {type(e).__name__}")
            if attempts_log is not None:
                from otp_doctor import smtp_hint  # doctor-only hint table
                attempts_log.append({"mode": mode, "port": port, "ok": False, "error_class": type(e).__name__,
                                     "error": _redact(str(e), settings), "hint": smtp_hint(e)})
            if isinstance(e, _FATAL_SMTP):
                break
        finally:
            if server is not None:
                try:
                    server.quit()
                except (smtplib.SMTPException, OSError):
                    pass
    return False, "", last_exc


def _smtp_login(server, user: str, password: str):
    """
    Authenticate with ONE mechanism. smtplib.login() falls through to the next
    mechanism after a 535; Gmail then drops the socket and the real
    "535 5.7.8 BadCredentials" is reported as SMTPServerDisconnected.
    """
    server.ehlo_or_helo_if_needed()
    advertised = (server.esmtp_features.get("auth") or "").upper().split()
    server.user, server.password = user, password
    if "LOGIN" in advertised or not advertised:
        return server.auth("LOGIN", server.auth_login)
    return server.auth("PLAIN", server.auth_plain)


def probe_smtp_login(config=None) -> Tuple[bool, str]:
    """Log in (no email sent) on each SMTP route; returns (ok, secret-free detail)."""
    settings = smtp_settings(config)
    if not settings["user"] or not settings["password"]:
        return False, "EMAIL_USER / EMAIL_PASSWORD empty"
    last = None
    for mode, port in _smtp_routes(settings):
        server = None
        try:
            ctx = ssl.create_default_context()
            if mode == "SSL":
                server = smtplib.SMTP_SSL(settings["host"], port, timeout=settings["timeout"], context=ctx)
            else:
                server = smtplib.SMTP(settings["host"], port, timeout=settings["timeout"])
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
            _smtp_login(server, settings["user"], settings["password"])
            return True, f"SMTP login OK via {mode}:{port}"
        except Exception as e:
            last = e
            if isinstance(e, _FATAL_SMTP):
                break
        finally:
            if server is not None:
                try:
                    server.quit()
                except (smtplib.SMTPException, OSError):
                    pass
    return False, _public_smtp_detail(last) if last else "no SMTP route"


def _public_smtp_detail(e: Exception) -> str:
    """Short, secret-free explanation that may be shown to the user/admin."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return f"SMTP login rejected ({e.smtp_code}): server email credentials invalid"
    if isinstance(e, EmailConfigError):
        return "server email is not configured"
    if isinstance(e, (TimeoutError, OSError)) and not isinstance(e, smtplib.SMTPException):
        return "mail server unreachable (timeout or blocked port)"
    return f"mail server error ({type(e).__name__})"


def _redact(text: str, settings: Dict[str, Any]) -> str:
    for secret in (settings.get("password"), settings.get("user")):
        if secret:
            text = text.replace(secret, secret[:3] + "***")
    return text


class EmailSender:
    """
    MLBFD SMTP Email Dispatcher.
    Supports free SMTP providers (Gmail App Passwords, Brevo / Sendinblue).
    Sends dual-format HTML and plain-text emails.
    Dispatches in background thread with single retry and graceful failure handling.
    Includes EMAIL_DRY_RUN mode for testing.
    """
    def __init__(self, config=None, dry_run: Optional[bool] = None):
        self.config = config or Config
        self.sent_emails: List[Dict[str, Any]] = []
        self._dry_run = dry_run
        self.last_route = ""

    @property
    def is_dry_run(self) -> bool:
        if self._dry_run is not None:
            return self._dry_run
        env_val = os.getenv("EMAIL_DRY_RUN")
        if env_val is not None:
            return clean_value(env_val).lower() in ("true", "1", "yes")
        dry_run = getattr(self.config, "EMAIL_DRY_RUN", False)
        if isinstance(dry_run, bool):
            return dry_run
        return str(dry_run).strip().lower() in ("true", "1", "yes")

    @is_dry_run.setter
    def is_dry_run(self, val: bool):
        self._dry_run = val

    def format_email_content(
        self,
        code: str,
        purpose: str,
        amount: Optional[float] = None,
        receiver: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """
        Formats subject, plain text, and HTML body according to specification:
        'Your MLBFD code is 123456. Valid for 5 minutes. Purpose: <purpose>. Never share this code.'
        Transaction emails show amount and masked receiver.
        """
        purpose_str = str(purpose or "VERIFICATION").strip().upper()
        subject = f"[MLBFD] Your Verification Code - {purpose_str}"

        # Transaction details formatting
        txn_details_text = ""
        txn_details_html = ""
        if purpose_str == "TRANSACTION" and (amount is not None or receiver is not None):
            amt_formatted = f"Rs. {float(amount):,.2f}" if amount is not None else "N/A"
            rcv_masked = mask_upi(str(receiver)) if receiver else "N/A"
            txn_details_text = f"\nTransaction Details:\n- Amount: {amt_formatted}\n- Payee: {rcv_masked}\n"
            txn_details_html = f"""
            <div style="background-color: #f1f5f9; border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
                <p style="margin: 0 0 6px 0; font-weight: bold; color: #1e293b;">Transaction Information:</p>
                <p style="margin: 0; color: #334155;">Amount: <strong>{amt_formatted}</strong></p>
                <p style="margin: 4px 0 0 0; color: #334155;">Payee: <strong>{rcv_masked}</strong></p>
            </div>
            """

        plain_text = (
            f"Your MLBFD code is {code}. Valid for 5 minutes. Purpose: {purpose_str}. Never share this code."
            f"{txn_details_text}\n"
            f"If you did not request this code, please freeze your account immediately."
        )

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{subject}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1f2937; margin: 0; padding: 0; background-color: #f9fafb;">
    <table width="100%" cellpadding="0" cellspacing="0" style="padding: 24px 0;">
        <tr>
            <td align="center">
                <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 540px; background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                    <tr>
                        <td style="background-color: #1e3a8a; padding: 20px 24px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: 1px;">MLBFD SECURITY</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 28px 24px;">
                            <p style="margin: 0 0 16px 0; font-size: 15px; color: #374151;">Your MLBFD code is {code}. Valid for 5 minutes. Purpose: {purpose_str}. Never share this code.</p>
                            
                            <div style="text-align: center; margin: 24px 0;">
                                <div style="display: inline-block; font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #1e3a8a; background-color: #eff6ff; padding: 12px 24px; border-radius: 8px; border: 1px dashed #60a5fa;">
                                    {code}
                                </div>
                            </div>
                            
                            {txn_details_html}
                            
                            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0 16px 0;">
                            <p style="margin: 0; font-size: 12px; color: #6b7280; line-height: 1.5;">
                                This is an automated security notification from MLBFD Financial Fraud Detection. If you did not make this request, freeze your account immediately.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
        return subject, plain_text, html_content

    def _send_smtp_sync(self, to_email: str, subject: str, plain_text: str, html_content: str) -> bool:
        """
        Synchronous SMTP delivery helper.
        Returns True only when the SMTP server accepted the message (or in dry-run/testing,
        where the message is buffered). Raises the SMTP/socket exception on failure so the
        retry wrapper can log its class; never reports success for an undelivered email.
        """
        # Never hit a real SMTP server from the test-suite (flask test client sets TESTING).
        testing_mode = False
        try:
            from flask import current_app, has_app_context
            testing_mode = bool(has_app_context() and current_app.config.get("TESTING"))
        except (ImportError, RuntimeError):
            testing_mode = False

        if self.is_dry_run or testing_mode:
            self.sent_emails.append({
                "to": to_email,
                "subject": subject,
                "plain_text": plain_text,
                "html": html_content,
                "timestamp": time.time()
            })
            label = "TESTING" if testing_mode and not self.is_dry_run else "EMAIL DRY RUN"
            logger.info(f"[{label}] email buffered (Subject: {subject})")
            return True

        settings = smtp_settings(self.config)
        if not settings["user"] or not settings["password"]:
            raise EmailConfigError("EMAIL_USER / EMAIL_PASSWORD not configured in .env")

        ok, route, last_exc = send_via_smtp(settings, to_email, subject, plain_text, html_content)
        self.last_route = route
        if ok:
            return True
        raise last_exc or EmailConfigError("SMTP delivery failed")

    def send_email(
        self,
        to_email: str,
        code: str,
        purpose: str = "VERIFICATION",
        amount: Optional[float] = None,
        receiver: Optional[str] = None,
        background: bool = True
    ) -> Tuple[bool, str]:
        """
        Sends verification email with code and purpose (1 retry).
        background=True returns immediately; failures are still written to logs/otp_delivery.log.
        """
        res = self.send_email_status(to_email, code, purpose, amount=amount, receiver=receiver,
                                     wait=None if background else -1)
        if res["status"] == "pending":
            return True, "Email dispatch initiated."
        if res["status"] in ("sent", "dry_run"):
            return True, "Email delivered successfully."
        return False, "Failed to send email notification."

    def send_email_status(
        self,
        to_email: str,
        code: str,
        purpose: str = "VERIFICATION",
        amount: Optional[float] = None,
        receiver: Optional[str] = None,
        user_id: Optional[str] = None,
        wait: Optional[float] = OTP_SEND_WAIT_SECONDS,
    ) -> Dict[str, str]:
        """
        Delivery runs in a background thread with one retry. The caller waits up to
        `wait` seconds for the outcome (None = do not wait, -1 = run inline) and gets
        {"status": sent|failed|pending|dry_run, "detail", "error_class"}.
        """
        if not to_email:
            return {"status": "failed", "detail": "no email address on file", "error_class": "NoRecipient"}

        subject, plain_text, html_content = self.format_email_content(
            code=code, purpose=purpose, amount=amount, receiver=receiver
        )
        outcome: Dict[str, str] = {"status": "pending", "detail": "", "error_class": ""}
        dry = self.is_dry_run

        def _worker_with_retry():
            # Send with 1 retry (maximum 2 attempts); an auth/sender rejection is not retried.
            for attempt in range(2):
                try:
                    if self._send_smtp_sync(to_email, subject, plain_text, html_content):
                        outcome.update(status="dry_run" if dry else "sent",
                                       detail=self.last_route or ("buffered" if dry else "accepted"))
                        otp_delivery_log.record("EMAIL", purpose, user_id, True, outcome["detail"],
                                                route=self.last_route)
                        return
                except Exception as e:
                    outcome.update(status="failed", error_class=type(e).__name__,
                                   detail=_public_smtp_detail(e))
                    logger.warning(f"email_sender: attempt {attempt + 1}/2 failed: {type(e).__name__}")
                    otp_delivery_log.record("EMAIL", purpose, user_id, False, f"attempt {attempt + 1}/2",
                                            error_class=type(e).__name__)
                    if isinstance(e, _FATAL_SMTP + (EmailConfigError,)):
                        break
                    if attempt == 0:
                        time.sleep(1.0)
            outcome["status"] = "failed"
            logger.error("email_sender: email NOT delivered after retries")

        if wait == -1 or dry:
            _worker_with_retry()
            return outcome
        thread = threading.Thread(target=_worker_with_retry, daemon=True, name="EmailSend")
        thread.start()
        if wait == 0:
            # Caller overlaps other work (Telegram) and joins later via _join(timeout).
            def _join(timeout):
                thread.join(timeout=max(0.0, timeout))
                return dict(outcome)
            return dict(outcome, _join=_join)
        if wait:
            thread.join(timeout=wait)
        return dict(outcome)

    def send_security_alert(
        self,
        to_email: str,
        amount: float,
        receiver: str,
        timestamp: str,
        location: str,
        reason_summary: str,
        freeze_link: str,
        background: bool = True
    ) -> Tuple[bool, str]:
        """
        Sends "Was this you?" security alert email with signed freeze link.
        """
        if not to_email:
            return False, "Recipient email address is required."

        subject = "🚨 [MLBFD Security Alert] Suspicious Transaction Flagged - Action Required"

        plain_text = (
            f"MLBFD SECURITY ALERT: WAS THIS YOU?\n\n"
            f"A suspicious transaction was detected on your account:\n"
            f"- Amount: Rs. {amount:,.2f}\n"
            f"- Payee: {receiver}\n"
            f"- Time: {timestamp}\n"
            f"- Location: {location}\n"
            f"- Reason: {reason_summary}\n\n"
            f"If this was NOT you, immediately freeze your account using this secure link (valid for 24 hours):\n"
            f"{freeze_link}\n\n"
            f"Once frozen, unfreeze is only permitted via identity verification or administrator review.\n"
            f"- The MLBFD Security Team"
        )

        esc = lambda v: html.escape(str(v), quote=True)  # payee/location/reason are user-influenced
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; padding: 24px; color: #1e293b;">
            <div style="max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden;">
                <div style="background-color: #ef4444; color: white; padding: 16px 20px;">
                    <h2 style="margin: 0; font-size: 20px;">🚨 MLBFD Security Alert</h2>
                </div>
                <div style="padding: 24px;">
                    <p style="font-size: 16px; font-weight: 600; margin-top: 0;">Was this you?</p>
                    <p style="color: #475569; font-size: 14px;">A suspicious transaction was flagged on your MLBFD account.</p>
                    <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; padding: 14px; margin: 16px 0; border-radius: 4px;">
                        <p style="margin: 0 0 6px 0;"><strong>Amount:</strong> ₹{amount:,.2f}</p>
                        <p style="margin: 0 0 6px 0;"><strong>Payee:</strong> {esc(receiver)}</p>
                        <p style="margin: 0 0 6px 0;"><strong>Time:</strong> {esc(timestamp)}</p>
                        <p style="margin: 0 0 6px 0;"><strong>Location:</strong> {esc(location)}</p>
                        <p style="margin: 0;"><strong>Alert Reason:</strong> {esc(reason_summary)}</p>
                    </div>
                    <p style="font-size: 14px; color: #334155;">If you did not authorize this activity, freeze your account immediately to prevent further unauthorized transactions:</p>
                    <div style="text-align: center; margin: 24px 0;">
                        <a href="{esc(freeze_link)}" style="background-color: #ef4444; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Freeze My Account Now</a>
                    </div>
                    <p style="font-size: 12px; color: #94a3b8;">This single-use link will expire in 24 hours. Unfreeze is only permitted via forgot-PIN verification or by an admin.</p>
                </div>
            </div>
        </body>
        </html>
        """

        if self.is_dry_run:
            logger.info(f"[Email DRY RUN Alert] buffered (Subject={subject})")
            self.sent_emails.append({
                "to": to_email,
                "subject": subject,
                "plain_text": plain_text,
                "html": html_content,
                "freeze_link": freeze_link,
                "timestamp": time.time()
            })
            return True, "Security alert email sent (dry-run)."

        def _worker_alert():
            for attempt in range(2):
                try:
                    if self._send_smtp_sync(to_email, subject, plain_text, html_content):
                        otp_delivery_log.record("EMAIL", "SECURITY_ALERT", None, True, self.last_route)
                        return True
                except Exception as e:
                    logger.warning(f"Security alert email attempt {attempt + 1}/2 failed: {type(e).__name__}")
                    otp_delivery_log.record("EMAIL", "SECURITY_ALERT", None, False, f"attempt {attempt + 1}/2",
                                            error_class=type(e).__name__)
                    if isinstance(e, _FATAL_SMTP + (EmailConfigError,)):
                        break
                    time.sleep(1.0)
            return False

        if background:
            threading.Thread(target=_worker_alert, daemon=True).start()
            return True, "Security alert email initiated."
        else:
            ok = _worker_alert()
            return ok, "Dispatched" if ok else "Failed"



# ---------------------------------------------------------------------------
# OTP Service Sender Adapter
# ---------------------------------------------------------------------------
class EmailOtpSender:
    """Adapter implementing the BaseOtpSender interface for otp_service integration."""
    def __init__(self, email_sender: Optional[EmailSender] = None):
        self.email_sender = email_sender or EmailSender()

    def send(self, user: Any, channel: str, message: str, **kwargs) -> Dict[str, str]:
        """Returns {"status": sent|failed|pending|dry_run, "detail", "error_class"}."""
        if str(channel).strip().upper() != "EMAIL":
            logger.warning(f"EmailOtpSender.send called with channel={channel}; ignoring")
            return {"status": "failed", "detail": "wrong channel", "error_class": "ChannelMismatch"}

        # Resolve destination email address
        to_email = None
        user_id = getattr(user, "user_id", None) or str(user)
        if hasattr(user, "get_decrypted_email"):
            to_email = user.get_decrypted_email()
        elif hasattr(user, "email"):
            from security import decrypt_val
            to_email = decrypt_val(user.email) if user.email else None
        elif isinstance(user, str) and "@" in user:
            to_email = user.strip()
        else:
            from user_manager import find_user_by_upi_or_phone
            u = find_user_by_upi_or_phone(str(user))
            if u:
                to_email = u.get_decrypted_email()
        if not to_email and self.email_sender.is_dry_run:
            # Dry-run/test identifiers such as "alice@mlbfd" have no mailbox; buffer anyway.
            to_email = f"{str(user_id).split('@')[0]}@mlbfd.local"

        # Parse code and purpose from message
        code_match = re.search(r"\b(\d{6})\b", message)
        code = code_match.group(1) if code_match else ""
        purpose_match = re.search(r'Purpose:\s*(?:<b>)?([A-Za-z0-9_]+)', message, re.IGNORECASE)
        purpose = purpose_match.group(1) if purpose_match else "VERIFICATION"
        if not to_email:
            otp_delivery_log.record("EMAIL", purpose, user_id, False, "no email on file", error_class="NoRecipient")
            return {"status": "failed", "detail": "no email address on file", "error_class": "NoRecipient"}

        return self.email_sender.send_email_status(
            to_email=to_email,
            code=code,
            purpose=purpose,
            amount=kwargs.get('amount'),
            receiver=kwargs.get('receiver'),
            user_id=user_id,
            wait=kwargs.get('wait', OTP_SEND_WAIT_SECONDS),
        )


# Global default email sender instance
default_email_sender = EmailSender()
default_email_otp_sender = EmailOtpSender(default_email_sender)

def register_as_email_sender():
    """Registers default_email_otp_sender in otp_service for the EMAIL channel."""
    from otp_service import register_channel_sender
    register_channel_sender("EMAIL", default_email_otp_sender)
    logger.info("✅ EmailOtpSender successfully registered with otp_service for EMAIL channel.")
