"""
MLBFD OTP doctor: proves what the running app sees and whether OTP channels deliver.

Never prints a secret value or an OTP code. Values are reported by NAME and
status only (set / empty / MOCK / looks-valid); where a hint needs a value it
is masked to the first 3 characters plus "***".

Usage (from any working directory):
    python backend/otp_doctor.py                    # env, names, flags, live process checks
    python backend/otp_doctor.py --email-test       # one real email to EMAIL_USER
    python backend/otp_doctor.py --telegram-test    # getMe, username, webhook, 409
    python backend/otp_doctor.py --link-telegram    # t.me link + 90 s long-poll + test message
    python backend/otp_doctor.py --safebrowsing-test
"""
import argparse
import json
import os
import re
import secrets
import smtplib
import socket
import ssl
import subprocess
import sys
import time

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Snapshot the inherited process environment BEFORE anything loads .env.
_PRE_ENV = dict(os.environ)

import env_loader  # noqa: E402

REPO_ROOT = env_loader.REPO_ROOT
LOG_DIR = os.path.join(REPO_ROOT, "logs")
DOCTOR_TG_FILE = os.path.join(LOG_DIR, ".doctor_telegram.json")

EMAIL_KEYS = ["EMAIL_HOST", "EMAIL_PORT", "EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_FROM",
              "EMAIL_FROM_NAME", "EMAIL_DRY_RUN", "EMAIL_SMTP_MODE"]
TELEGRAM_KEYS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME", "TELEGRAM_POLLING_ENABLED", "TELEGRAM_DRY_RUN"]
LEGACY_ALIASES = {"SMTP_HOST": "EMAIL_HOST", "SMTP_PORT": "EMAIL_PORT", "SMTP_USER": "EMAIL_USER",
                  "SMTP_PASS": "EMAIL_PASSWORD", "SMTP_FROM": "EMAIL_FROM"}
SECRET_NAME_RE = re.compile(r"(KEY|TOKEN|PASSWORD|PASS|PEPPER|SECRET)", re.I)

_results = []


def mask(v: str) -> str:
    v = v or ""
    return (v[:3] + "***") if v else "(empty)"


def report(name: str, ok: bool, reason: str, hint: str = ""):
    tag = "PASS" if ok else "FAIL"
    _results.append((tag, name))
    print(f"[{tag}] {name}: {reason}")
    if hint and not ok:
        print(f"       hint: {hint}")


def info(msg: str):
    print(f"[INFO] {msg}")


def status_of(name: str, value: str) -> str:
    if value is None:
        return "missing"
    if value == "":
        return "empty"
    if env_loader.is_placeholder(value):
        return "MOCK/placeholder"
    return "set"


# --------------------------------------------------------------------------
# 1a. Env loading
# --------------------------------------------------------------------------
def check_env_file():
    path = env_loader.ENV_PATH
    print("\n== 1a. .env loading ==")
    info(f".env path resolved from file location: {path}")
    if not os.path.exists(path):
        report("env.file", False, ".env missing", "copy .env.example to .env at the repo root and fill it in")
        return
    report("env.file", True, ".env exists")
    raw = open(path, "rb").read()
    report("env.bom", not raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM present" if raw.startswith(b"\xef\xbb\xbf") else "no BOM",
           "re-save .env as UTF-8 without BOM (loader strips it anyway)")
    crlf = b"\r\n" in raw
    info(f"line endings: {'CRLF (handled by loader)' if crlf else 'LF'}")

    entries = env_loader.parse_env_file(path)
    seen = {}
    problems = 0
    for line_no, key, rawv, cleaned in entries:
        rv = rawv.replace("\r", "")
        issues = []
        if re.search(r"^\s*\S+\s+=|=\s+\S", f"{key}={rv}") or rv.startswith(" "):
            issues.append("space after '='")
        s = rv.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
            issues.append("quoted value")
        elif re.search(r"\s+#", s):
            issues.append("inline # comment")
        if rv != rv.rstrip():
            issues.append("trailing spaces")
        if key in ("EMAIL_PASSWORD", "SMTP_PASS") and re.search(r"\s", clean_inner(rv)):
            issues.append("app password contains spaces (Gmail shows it in 4 groups; remove spaces)")
        if issues:
            problems += 1
            info(f"L{line_no} {key}: " + ", ".join(issues) + " -> cleaned by env_loader")
        seen.setdefault(key, []).append(cleaned)
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    for k, vals in dups.items():
        conflict = len(set(vals)) > 1
        report(f"env.duplicate.{k}", not conflict,
               f"defined {len(vals)}x, values {'CONFLICT (last one wins)' if conflict else 'identical'}",
               f"keep a single {k}= line in .env")
    if not dups:
        report("env.duplicates", True, "no duplicate keys")
    info(f"{len(entries)} assignments, {problems} lines needed cleaning")

    # Legacy backend/.env
    legacy = env_loader.read_env_values(env_loader.LEGACY_ENV_PATH)
    if legacy:
        root = env_loader.read_env_values(path)
        only_legacy = sorted(k for k in legacy if k not in root)
        differ = sorted(k for k in legacy if k in root and legacy[k] != root[k])
        info(f"legacy backend/.env present with {len(legacy)} keys; root .env wins. "
             f"Only in legacy: {only_legacy or 'none'}; differing (ignored): {differ or 'none'}")

    # Pre-existing OS environment variables that python-dotenv would NOT override.
    root_values = env_loader.read_env_values(path)
    shadow = []
    for k, v in root_values.items():
        if k in _PRE_ENV and _PRE_ENV[k] != v:
            shadow.append(k)
    reg_shadow = windows_registry_env_names(set(root_values))
    if shadow:
        report("env.os_override", False,
               f"process env already defines {shadow} with different values; old load_dotenv() kept the OS value",
               "fixed: env_loader.load_env() now uses override=True; also delete these from Windows "
               "System Properties > Environment Variables")
    else:
        report("env.os_override", True, "no inherited env var shadows .env")
    if reg_shadow:
        info(f"Windows registry (user/system) also defines: {sorted(reg_shadow)} (shells started later inherit them)")


def clean_inner(rawv: str) -> str:
    s = rawv.replace("\r", "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1].strip()
    m = re.search(r"\s+#", s)
    return (s[: m.start()] if m else s).strip()


def windows_registry_env_names(names):
    found = set()
    if os.name != "nt":
        return found
    try:
        import winreg
        for hive, sub in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    i = 0
                    while True:
                        try:
                            n, _, _ = winreg.EnumValue(k, i)
                        except OSError:
                            break
                        if n.upper() in {x.upper() for x in names}:
                            found.add(n)
                        i += 1
            except OSError:
                pass
    except Exception:
        pass
    return found


# --------------------------------------------------------------------------
# 1b. Variable names
# --------------------------------------------------------------------------
def check_variable_names():
    print("\n== 1b. variable names: code vs .env ==")
    code_names = set()
    pat = re.compile(r"""(?:getenv|environ\.get|environ\[|env_str|env_bool)\(?\s*\(?["']([A-Z][A-Z0-9_]+)["']""")
    pat_multi = re.compile(r"""env_str\(([^)]*)\)""")
    for folder in (BACKEND_DIR, REPO_ROOT):
        for fn in os.listdir(folder):
            if not fn.endswith(".py") or fn == "otp_doctor.py":
                continue
            try:
                src = open(os.path.join(folder, fn), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            code_names.update(pat.findall(src))
            for args in pat_multi.findall(src):
                code_names.update(re.findall(r"""["']([A-Z][A-Z0-9_]+)["']""", args))
    relevant = re.compile(r"^(EMAIL_|SMTP_|TELEGRAM_|GOOGLE_SAFE|OPENPHISH|OTP_|NOMINATIM)")
    code_rel = {n for n in code_names if relevant.match(n)}
    env_names = set(env_loader.read_env_values(env_loader.ENV_PATH))
    env_rel = {n for n in env_names if relevant.match(n)}
    required = {"EMAIL_USER", "EMAIL_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME"}
    missing_required = sorted(required - env_names)
    report("names.required", not missing_required,
           f"required names missing from .env: {missing_required}" if missing_required else "all required names defined",
           "add them to .env (see OTP_SETUP.md)")
    code_only = sorted(n for n in code_rel - env_rel if n not in LEGACY_ALIASES)
    env_only = sorted(env_rel - code_rel)
    info(f"read by code but not in .env (defaults apply): {code_only or 'none'}")
    if env_only:
        report("names.unused", False, f".env defines names no code reads: {env_only}",
               "rename them to the canonical EMAIL_*/TELEGRAM_* names")
    else:
        report("names.unused", True, "every relevant .env name is read by code")
    aliases_in_env = sorted(n for n in env_names if n in LEGACY_ALIASES)
    if aliases_in_env:
        info(f"legacy alias names in .env: {aliases_in_env} -> read as fallback for "
             f"{[LEGACY_ALIASES[a] for a in aliases_in_env]}")


# --------------------------------------------------------------------------
# 1c. Flags
# --------------------------------------------------------------------------
def check_flags():
    print("\n== 1c. flags and credential status (values hidden) ==")
    env_loader.load_env(force=True)
    for k in ("EMAIL_DRY_RUN", "TELEGRAM_DRY_RUN", "TELEGRAM_POLLING_ENABLED"):
        v = os.environ.get(k)
        info(f"{k} = {v if v is not None else '(unset)'}")
    report("flag.EMAIL_DRY_RUN", not env_loader.env_bool("EMAIL_DRY_RUN"),
           "true: emails are only buffered" if env_loader.env_bool("EMAIL_DRY_RUN") else "false (real send)",
           "set EMAIL_DRY_RUN=false in .env")
    report("flag.TELEGRAM_DRY_RUN", not env_loader.env_bool("TELEGRAM_DRY_RUN"),
           "true: Telegram messages are only buffered" if env_loader.env_bool("TELEGRAM_DRY_RUN") else "false (real send)",
           "set TELEGRAM_DRY_RUN=false in .env")
    report("flag.TELEGRAM_POLLING_ENABLED", env_loader.env_bool("TELEGRAM_POLLING_ENABLED", True),
           "polling on" if env_loader.env_bool("TELEGRAM_POLLING_ENABLED", True) else "polling OFF: /start and contacts never processed",
           "set TELEGRAM_POLLING_ENABLED=true")
    email_host = env_loader.env_str("EMAIL_HOST", "SMTP_HOST", default="smtp.gmail.com").lower()
    is_brevo = "brevo" in email_host or "sendinblue" in email_host
    cred_keys = ["EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_FROM"] + (["EMAIL_SMTP_LOGIN"] if is_brevo else []) + [
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME", "GOOGLE_SAFE_BROWSING_API_KEY"]
    info(f"email provider: {'brevo' if is_brevo else ('gmail' if 'gmail' in email_host else 'smtp')}")
    for k in cred_keys:
        names = [k] + [a for a, c in LEGACY_ALIASES.items() if c == k]
        v = env_loader.env_str(*names, default=None)
        st = status_of(k, v)
        extra = ""
        if k == "EMAIL_PASSWORD" and v and is_brevo:
            extra = ", format " + ("Brevo SMTP key" if v.startswith(("xsmtpsib-", "bsk")) else
                                   ("API key (xkeysib-) - WRONG, use an SMTP key" if v.startswith("xkeysib-") else "unusual"))
        elif k == "EMAIL_PASSWORD" and v:
            extra = f", length {len(v)}" + (" (Gmail app passwords are 16)" if len(v) != 16 else " (Gmail app-password length)")
        if k == "EMAIL_SMTP_LOGIN" and v and st == "set":
            extra = ", format " + ("looks-valid" if v.endswith("@smtp-brevo.com") or "@" in v else "unusual")
        if k == "TELEGRAM_BOT_TOKEN" and v:
            extra = ", format " + ("looks-valid" if re.match(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$", v) else "INVALID")
        if k == "GOOGLE_SAFE_BROWSING_API_KEY" and v and st == "set":
            extra = ", format " + ("looks-valid" if re.match(r"^AIza[0-9A-Za-z_-]{35}$", v) else "unusual")
        hint = "paste the SMTP login from Brevo > SMTP & API > SMTP" if k == "EMAIL_SMTP_LOGIN" else ""
        report(f"cred.{k}", st == "set" or k == "GOOGLE_SAFE_BROWSING_API_KEY", f"{st}{extra}", hint)
    user = env_loader.env_str("EMAIL_USER", "SMTP_USER")
    frm = env_loader.env_str("EMAIL_FROM", "SMTP_FROM", default=user)
    host = env_loader.env_str("EMAIL_HOST", "SMTP_HOST", default="smtp.gmail.com")
    if "gmail" in host.lower():
        report("gmail.from_equals_user", (frm or "").lower() == (user or "").lower(),
               "EMAIL_FROM equals EMAIL_USER" if (frm or "").lower() == (user or "").lower()
               else "EMAIL_FROM differs from EMAIL_USER; Gmail rewrites or rejects it",
               "set EMAIL_FROM to the same address as EMAIL_USER (or leave EMAIL_FROM empty)")

    info("code branches that skip real sending (static scan):")
    for fn in ("email_sender.py", "telegram_bot.py", "otp_service.py"):
        path = os.path.join(BACKEND_DIR, fn)
        if not os.path.exists(path):
            continue
        for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            s = line.strip()
            if re.search(r"is_dry_run|== \"MOCK\"|testing_mode|except Exception:\s*$|except:\s*$|\bpass\b$", s):
                print(f"       {fn}:{i}: {s[:110]}")


# --------------------------------------------------------------------------
# 1d. Live processes
# --------------------------------------------------------------------------
def check_live_process(port: int = 5000):
    print(f"\n== 1d. live processes on port {port} ==")
    pids = set()
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
                pids.add(parts[4])
    except Exception as e:
        info(f"netstat unavailable ({type(e).__name__})")
    if not pids:
        report("process.port", True, f"nothing listening on {port}")
        return []
    procs = []
    for pid in sorted(pids):
        cmd = ""
        try:
            ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                                capture_output=True, text=True, timeout=15).stdout.strip()
            cmd = ps
        except Exception:
            pass
        ours = "MLBFD" in cmd or "serve.py" in cmd or "app.py" in cmd
        procs.append((pid, ours))
        short = re.sub(r"\s+", " ", cmd)[:120]
        report(f"process.{pid}", False, f"PID {pid} listening ({'this project' if ours else 'other'}): {short}",
               "stop it and restart AFTER editing .env: a server started earlier keeps the old values "
               f"(Stop-Process -Id {pid})")
    return procs


# --------------------------------------------------------------------------
# Phase 2: email
# --------------------------------------------------------------------------
SMTP_HINTS = [
    (r"Unauthorized IP|525", "Brevo blocks unknown IPs: Brevo > Security > Authorized IPs > add this "
     "machine's public IP (or turn off 'Block unknown IP addresses'); home IPs change, so turning it off is simpler"),
    (r"535|BadCredentials|Username and Password not accepted|Authentication failed",
     "535 bad credentials. Gmail: EMAIL_USER must be the exact account that created the app password "
     "(new app password, no spaces). Brevo: EMAIL_SMTP_LOGIN = the SMTP login shown under SMTP & API "
     "(xxxx@smtp-brevo.com) and EMAIL_PASSWORD = an SMTP key (bsk... or xsmtpsib-...), not the API key (xkeysib-...)"),
    (r"534|5\.7\.9|Application-specific password required", "534/5.7.9: Gmail requires an app password; turn on 2-Step "
     "Verification and create one"),
    (r"5\.7\.0|Authentication Required|530", "530 auth required: STARTTLS did not complete before login"),
    (r"553|550|Sender address rejected|5\.7\.1|not a valid sender|sender .* not",
     "sender rejected. Gmail: EMAIL_FROM must equal EMAIL_USER. Brevo: EMAIL_FROM must be a sender verified "
     "under Senders, Domains & Dedicated IPs"),
]


def smtp_hint(exc: Exception) -> str:
    txt = f"{type(exc).__name__} {exc}"
    for pat, hint in SMTP_HINTS:
        if re.search(pat, txt, re.I):
            return hint
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout: port blocked by antivirus/firewall/ISP; try the other port (587 STARTTLS / 465 SSL)"
    if isinstance(exc, ssl.SSLError):
        return "TLS error: antivirus HTTPS/mail scanning often intercepts TLS; disable mail shield or use port 465"
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return ("server closed connection: typical for wrong/revoked app password on Gmail, or a mail shield "
                "proxying port 587; regenerate the app password and retry")
    if isinstance(exc, (ConnectionRefusedError, OSError)):
        return "connection failed: no network, DNS failure, or port blocked"
    return "see exception class"


def email_test():
    print("\n== Phase 2: --email-test ==")
    env_loader.load_env(force=True)
    from email_sender import smtp_settings, send_via_smtp  # shared with the app
    s = smtp_settings()
    if not s["user"] or not s["password"]:
        what = "EMAIL_SMTP_LOGIN" if s["provider"] == "brevo" else "EMAIL_USER"
        report("email.creds", False, f"{what} or EMAIL_PASSWORD empty/placeholder",
               "Brevo: SMTP & API > SMTP shows the login and lets you create an SMTP key" if s["provider"] == "brevo"
               else "fill them in .env")
        return False
    to_addr = s["inbox"] or s["from_addr"]
    info(f"provider={s['provider']} host={s['host']} login={mask(s['user'])} from={mask(s['from_addr'])} "
         f"to={mask(to_addr)} password=set(len {len(s['password'])}) mode={s['mode']} port={s['port']}")
    if "gmail" in s["host"].lower() and s["from_addr"].lower() != s["user"].lower():
        report("email.from", False, "EMAIL_FROM != EMAIL_USER", "set EMAIL_FROM equal to EMAIL_USER")
    subject = "MLBFD test email (otp_doctor)"
    body = "This is an MLBFD otp_doctor delivery test. No code is included."
    attempts = []
    ok, used, err = send_via_smtp(s, to_addr, subject, body, None, attempts_log=attempts)
    for a in attempts:
        if a["ok"]:
            report(f"email.{a['mode']}:{a['port']}", True, "login + send accepted by server")
        else:
            report(f"email.{a['mode']}:{a['port']}", False, f"{a['error_class']}: {a['error'][:160]}", a["hint"])
    if ok:
        report("email.delivery", True, f"test email accepted via {used}; check the inbox (and Spam) of {mask(to_addr)}")
    else:
        report("email.delivery", False, "no SMTP mode worked", attempts[-1]["hint"] if attempts else "")
    return ok


# --------------------------------------------------------------------------
# Phase 3: telegram
# --------------------------------------------------------------------------
def _tg(method, token, http="get", **kw):
    import requests
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        r = requests.post(url, json=kw, timeout=40) if http == "post" else requests.get(url, params=kw, timeout=40)
        try:
            body = r.json()
        except ValueError:
            body = {}
        return r.status_code, body
    except Exception as e:
        return None, {"error_class": type(e).__name__}


def telegram_test():
    print("\n== Phase 3: --telegram-test ==")
    env_loader.load_env(force=True)
    token = env_loader.env_str("TELEGRAM_BOT_TOKEN")
    want = env_loader.env_str("TELEGRAM_BOT_USERNAME").lstrip("@")
    if env_loader.is_placeholder(token):
        report("tg.token", False, "TELEGRAM_BOT_TOKEN empty/MOCK", "paste the BotFather token into .env")
        return None
    if not re.match(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$", token):
        report("tg.token_format", False, "token not in <digits>:<secret> format", "copy the full token from BotFather")
        return None
    code, body = _tg("getMe", token)
    if code is None:
        report("tg.getMe", False, f"network error {body.get('error_class')}", "api.telegram.org blocked? check network/proxy")
        return None
    if code == 401 or code == 404:
        report("tg.getMe", False, f"HTTP {code}: token rejected (bad or revoked)", "BotFather /token or /revoke, update .env")
        return None
    actual = (body.get("result") or {}).get("username", "")
    report("tg.getMe", code == 200, f"HTTP {code}, bot username @{actual}")
    report("tg.username", actual.lower() == want.lower(),
           f".env TELEGRAM_BOT_USERNAME={'@' + want if want else '(empty)'} vs real @{actual}",
           f"set TELEGRAM_BOT_USERNAME={actual} in .env (t.me links use this name)")
    code, body = _tg("getWebhookInfo", token)
    hook = (body.get("result") or {}).get("url", "")
    if hook:
        dc, _ = _tg("deleteWebhook", token, http="post", drop_pending_updates=False)
        report("tg.webhook", dc == 200, f"a webhook was set (blocks getUpdates); deleteWebhook HTTP {dc}")
    else:
        report("tg.webhook", True, "no webhook set")
    code, body = _tg("getUpdates", token, timeout=0, limit=1)
    if code == 409:
        report("tg.poller", False, "HTTP 409: another getUpdates poller is running (server already up, or a 2nd instance)",
               "stop duplicate servers; only one process may poll")
    else:
        report("tg.poller", code == 200, f"getUpdates HTTP {code} (no competing poller)")
    return actual


def link_telegram(wait_seconds: int = 90):
    print("\n== Phase 3: --link-telegram ==")
    actual = telegram_test()
    if not actual:
        return False
    token = env_loader.env_str("TELEGRAM_BOT_TOKEN")
    payload = "doctor_" + secrets.token_urlsafe(9)
    print(f"\n  Open on your phone: https://t.me/{actual}?start={payload}")
    print(f"  Press START, then tap 'Share contact'. Waiting up to {wait_seconds}s ...\n")
    # Skip stale updates.
    _, body = _tg("getUpdates", token, timeout=0, offset=-1)
    res = body.get("result") or []
    offset = (res[-1]["update_id"] + 1) if res else 0
    deadline = time.time() + wait_seconds
    chat_id = None
    from_id = None
    while time.time() < deadline:
        code, body = _tg("getUpdates", token, timeout=min(25, max(1, int(deadline - time.time()))), offset=offset)
        if code == 409:
            report("tg.link", False, "HTTP 409: the MLBFD server is polling; stop it first", "Stop the server, rerun")
            return False
        for u in body.get("result") or []:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            text = (msg.get("text") or "").strip()
            if text == f"/start {payload}":
                chat_id = msg["chat"]["id"]
                from_id = (msg.get("from") or {}).get("id")
                report("tg.start", True, "received /start with doctor token")
                _tg("sendMessage", token, http="post", chat_id=chat_id,
                    text="MLBFD doctor: please share your contact to finish the test.",
                    reply_markup={"keyboard": [[{"text": "Share contact", "request_contact": True}]],
                                  "resize_keyboard": True, "one_time_keyboard": True})
            contact = msg.get("contact")
            if contact and chat_id and msg["chat"]["id"] == chat_id:
                same = contact.get("user_id") == (msg.get("from") or {}).get("id") == from_id
                report("tg.contact", same, "contact.user_id == from.id" if same else "contact is not the sender's own")
                if same:
                    digits = re.sub(r"\D", "", contact.get("phone_number", ""))
                    has_phone = 8 <= len(digits) <= 15
                    report("tg.contact_phone", has_phone, "phone normalized to E.164" if has_phone else "phone unparsable")
                os.makedirs(LOG_DIR, exist_ok=True)
                with open(DOCTOR_TG_FILE, "w", encoding="utf-8") as fh:
                    json.dump({"chat_id": chat_id, "linked_at": int(time.time())}, fh)
                c, _ = _tg("sendMessage", token, http="post", chat_id=chat_id, text="MLBFD test",
                           reply_markup={"remove_keyboard": True})
                report("tg.delivery", c == 200, f"sendMessage 'MLBFD test' HTTP {c}",
                       "403 = you blocked the bot; unblock and press Start")
                return c == 200
    report("tg.link", False, f"no /start received within {wait_seconds}s",
           "NEEDS USER ACTION: run --link-telegram while holding the phone")
    return False


# --------------------------------------------------------------------------
# Phase 7: Safe Browsing
# --------------------------------------------------------------------------
def safebrowsing_test():
    print("\n== Phase 7: --safebrowsing-test ==")
    env_loader.load_env(force=True)
    key = env_loader.env_str("GOOGLE_SAFE_BROWSING_API_KEY")
    if env_loader.is_placeholder(key):
        report("sb.key", False, "GOOGLE_SAFE_BROWSING_API_KEY empty/MOCK", "create a free key in Google Cloud Console")
        return False
    import requests
    test_url = "http://testsafebrowsing.appspot.com/s/malware.html"
    body = {"client": {"clientId": "mlbfd", "clientVersion": "1.0"},
            "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                                           "POTENTIALLY_HARMFUL_APPLICATION"],
                           "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
                           "threatEntries": [{"url": test_url}]}}
    try:
        r = requests.post("https://safebrowsing.googleapis.com/v4/threatMatches:find",
                          params={"key": key}, json=body, timeout=5)
    except Exception as e:
        report("sb.call", False, f"{type(e).__name__}", "network blocked or timeout")
        return False
    if r.status_code != 200:
        reason = ""
        try:
            reason = (r.json().get("error") or {}).get("status", "")
        except ValueError:
            pass
        report("sb.call", False, f"HTTP {r.status_code} {reason}",
               "403: enable 'Safe Browsing API' for the project and check key restrictions; 400: key invalid")
        return False
    matches = r.json().get("matches") or []
    report("sb.match", bool(matches), f"known test URL flagged as {[m.get('threatType') for m in matches]}"
           if matches else "known malware test URL NOT flagged")
    return bool(matches)


def main():
    ap = argparse.ArgumentParser(description="MLBFD OTP doctor (never prints secrets)")
    ap.add_argument("--email-test", action="store_true")
    ap.add_argument("--telegram-test", action="store_true")
    ap.add_argument("--link-telegram", action="store_true")
    ap.add_argument("--safebrowsing-test", action="store_true")
    ap.add_argument("--wait", type=int, default=90)
    a = ap.parse_args()
    if a.email_test:
        email_test()
    elif a.telegram_test:
        telegram_test()
    elif a.link_telegram:
        link_telegram(a.wait)
    elif a.safebrowsing_test:
        safebrowsing_test()
    else:
        check_env_file()
        check_variable_names()
        check_flags()
        check_live_process()
    fails = [n for t, n in _results if t == "FAIL"]
    print(f"\nSUMMARY: {len(_results) - len(fails)} PASS, {len(fails)} FAIL" + (f" -> {fails}" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
