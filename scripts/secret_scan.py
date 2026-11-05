"""
MLBFD secret scanner. Reports FILE and COMMIT only, never a value.

Scans tracked files and the full git history (`git log -p --all`) for:
- Telegram bot tokens            [0-9]{8,10}:[A-Za-z0-9_-]{30,}
- Google API keys                AIza[0-9A-Za-z_-]{35}
- long hex strings               [0-9a-f]{32,}
- literal password=/secret=/token=/key= assignments
and flags any hit that EQUALS a current .env value as a REAL leak.

Usage: python scripts/secret_scan.py [--history]
"""
import os
import re
import subprocess
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "backend"))
from env_loader import read_env_values, ENV_PATH  # noqa: E402

PATTERNS = {
    "telegram_token": re.compile(r"\b[0-9]{8,10}:[A-Za-z0-9_-]{30,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "long_hex": re.compile(r"\b[0-9a-fA-F]{32,}\b"),
    "literal_assignment": re.compile(
        r"""(?i)\b[A-Z0-9_]*(password|passwd|secret|token|api_key|pepper)[A-Z0-9_]*\s*[=:]\s*["']?([^\s"'#,)]{8,})"""),
}
PLACEHOLDER = re.compile(r"(?i)(your_|paste|change|example|placeholder|xxx|mock|dummy|test|pytest|fake|<|\{|\$|getenv|environ|os\.|config\.|none|null|true|false|self\.|request|data\.get)")
SKIP_DIRS = ("Datasets/", "models/", "paper_assets/", "flutter_app/sender_app/build", "flutter_app/receiver_app/build")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".pdf", ".pkl", ".parquet", ".keras", ".h5", ".ico", ".zip", ".csv", ".lock")


def secret_values():
    vals = {}
    for k, v in read_env_values(ENV_PATH).items():
        if re.search(r"(KEY|TOKEN|PASSWORD|PASS|PEPPER|SECRET)", k) and len(v) >= 8:
            vals[v] = k
    return vals


def classify(line, real):
    hits = []
    for name, pat in PATTERNS.items():
        for m in pat.finditer(line):
            val = m.group(2) if name == "literal_assignment" else m.group(0)
            if name == "long_hex" and len(set(val.lower())) < 6:
                continue
            leaked = real.get(val)
            if not leaked and name == "literal_assignment" and PLACEHOLDER.search(val):
                continue
            hits.append((name, leaked))
    for val, key in real.items():
        if val in line and not any(h[1] == key for h in hits):
            hits.append(("env_value", key))
    return hits


def scan_tree(real):
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.splitlines()
    report = defaultdict(set)
    for f in files:
        if f.startswith(SKIP_DIRS) or f.lower().endswith(SKIP_EXT):
            continue
        try:
            text = open(os.path.join(REPO, f), encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for line in text.splitlines():
            for name, leaked in classify(line, real):
                report[f].add(f"{name}{' REAL:' + leaked if leaked else ''}")
    return report


def scan_history(real):
    out = subprocess.run(["git", "log", "-p", "--all", "--no-color", "--format=COMMIT %h"],
                         cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout
    commit, path = "?", "?"
    report = defaultdict(set)
    for line in out.splitlines():
        if line.startswith("COMMIT "):
            commit = line.split()[1]
            continue
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if path.startswith(SKIP_DIRS) or path.lower().endswith(SKIP_EXT):
            continue
        for name, leaked in classify(line[1:], real):
            if leaked or name in ("telegram_token", "google_api_key"):
                report[(commit, path)].add(f"{name}{' REAL:' + leaked if leaked else ''}")
    return report


def main():
    real = secret_values()
    print(f"Loaded {len(real)} secret-like .env values for comparison (values not shown).")
    tree = scan_tree(real)
    print("\n== Working tree (tracked files) ==")
    for f, kinds in sorted(tree.items()):
        print(f"  {f}: {', '.join(sorted(kinds))}")
    if "--history" in sys.argv:
        hist = scan_history(real)
        print("\n== Git history (added lines; token/key patterns and REAL .env values) ==")
        for (c, f), kinds in sorted(hist.items(), key=lambda x: x[0][1]):
            print(f"  {c} {f}: {', '.join(sorted(kinds))}")
        leaked = sorted({k.split("REAL:")[1] for kinds in hist.values() for k in kinds if "REAL:" in k})
        print(f"\nREAL .env secrets found in history: {leaked or 'none'}")
    leaked_tree = sorted({k.split("REAL:")[1] for kinds in tree.values() for k in kinds if "REAL:" in k})
    print(f"REAL .env secrets in tracked files: {leaked_tree or 'none'}")


if __name__ == "__main__":
    main()
