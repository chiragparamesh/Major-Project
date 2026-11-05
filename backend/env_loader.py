"""
MLBFD .env loader.

One place that resolves and parses the repo-root .env so app.py, serve.py, the
test-suite and otp_doctor.py all see identical, cleaned values regardless of
the current working directory.

Rules:
- The path is resolved from this file's location (absolute), never from CWD.
- Values are cleaned: surrounding quotes, inline `# comments`, trailing spaces,
  CR characters and a UTF-8 BOM are removed.
- .env wins over pre-existing OS/user environment variables of the same name
  (override=True). Stale Windows user variables were silently masking .env.
- backend/.env is legacy; it only fills keys the root .env does not define.
- .env.example is never read.
"""
import os
import re
from typing import Dict, List, Tuple

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BACKEND_DIR)
ENV_PATH = os.path.join(REPO_ROOT, ".env")
LEGACY_ENV_PATH = os.path.join(BACKEND_DIR, ".env")

_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

# Names whose values must never contain internal whitespace.
NO_SPACE_KEYS = ("EMAIL_PASSWORD", "SMTP_PASS", "TELEGRAM_BOT_TOKEN", "GOOGLE_SAFE_BROWSING_API_KEY")

_loaded_once = False
_overridden: List[str] = []


def clean_value(raw: str) -> str:
    """Strip quotes, inline comments and whitespace from a raw .env value."""
    v = (raw or "").replace("\r", "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1].strip()
    # Unquoted: ` # comment` starts an inline comment.
    m = re.search(r"\s+#", v)
    if m:
        v = v[: m.start()]
    return v.strip()


def parse_env_file(path: str) -> List[Tuple[int, str, str, str]]:
    """Return [(line_no, key, raw_value, cleaned_value)] for every assignment."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8", errors="replace")
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        s = line.replace("\r", "")
        if not s.strip() or s.strip().startswith("#"):
            continue
        m = _LINE_RE.match(s)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        cleaned = clean_value(raw)
        if key in NO_SPACE_KEYS:
            cleaned = re.sub(r"\s+", "", cleaned)
        out.append((i, key, raw, cleaned))
    return out


def read_env_values(path: str = ENV_PATH) -> Dict[str, str]:
    """Last assignment wins, mirroring python-dotenv."""
    values: Dict[str, str] = {}
    for _, key, _, cleaned in parse_env_file(path):
        values[key] = cleaned
    return values


def load_env(force: bool = False) -> List[str]:
    """
    Load .env into os.environ with override=True.
    Returns the names of variables whose pre-existing OS value was replaced
    by a different .env value (names only, never values).
    """
    global _loaded_once, _overridden
    if _loaded_once and not force:
        return list(_overridden)
    overridden = []
    # The test-suite pins DATABASE_URL / dry-run flags before import; never clobber them.
    testing = os.environ.get("MLBFD_TESTING") == "1"
    root_values = read_env_values(ENV_PATH)
    for key, val in root_values.items():
        prev = os.environ.get(key)
        if prev is not None and testing:
            continue
        if prev is not None and prev != val:
            overridden.append(key)
        os.environ[key] = val
    for key, val in read_env_values(LEGACY_ENV_PATH).items():
        if key not in root_values and key not in os.environ:
            os.environ[key] = val
    _overridden = overridden
    _loaded_once = True
    return list(overridden)


def env_str(*names: str, default: str = "") -> str:
    """First non-empty value among canonical name and legacy aliases, cleaned."""
    for n in names:
        v = os.environ.get(n)
        if v is not None and clean_value(v) != "":
            v = clean_value(v)
            if n in NO_SPACE_KEYS:
                v = re.sub(r"\s+", "", v)
            return v
    return default


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or clean_value(v) == "":
        return default
    return clean_value(v).lower() in ("true", "1", "yes", "on")


def is_placeholder(value: str) -> bool:
    """Empty, MOCK, or an obvious template placeholder."""
    v = (value or "").strip()
    if not v:
        return True
    up = v.upper()
    return up in ("MOCK", "CHANGEME", "NONE", "NULL") or up.startswith("YOUR_") or "PASTE" in up or up.startswith("<")
