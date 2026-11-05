"""
Boot `python serve.py`, wait until it answers (TensorFlow import is slow), keep it up for
--seconds, print the banner + health summary, then kill the WHOLE process tree
(the venv launcher spawns a child interpreter that Stop-Process alone leaves running).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args()
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    log_path = os.path.join(REPO, "logs", "serve_boot.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, "serve.py"], cwd=REPO, stdout=log, stderr=subprocess.STDOUT, env=env)
        t0 = time.time()
        health = None
        try:
            while time.time() - t0 < a.timeout:
                if proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen("http://127.0.0.1:5000/api/health/otp", timeout=3) as r:
                        health = json.loads(r.read().decode())
                        break
                except Exception:
                    time.sleep(1)
            ready_after = time.time() - t0
            if health is not None:
                time.sleep(a.seconds)
            alive = proc.poll() is None
        finally:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    banner = open(log_path, encoding="utf-8", errors="replace").read().splitlines()
    keep = [l for l in banner if any(k in l for k in ("MLBFD", "Local Portal", "Waitress", "OTP", "!!", "READY",
                                                       "ERROR", "polling", "Serving on", "Port"))]
    print("\n".join(keep[:30]))
    if health is None:
        print(f"[FAIL] server did not answer within {a.timeout}s (exit code {proc.returncode})")
        return 1
    print(f"[PASS] answered after {ready_after:.1f}s, stayed up {a.seconds}s: {'alive' if alive else 'DIED'}")
    print(f"       otp_ready={health.get('otp_ready')} email.ready={health['channels']['email']['ready']} "
          f"telegram.ready={health['channels']['telegram']['ready']}")
    return 0 if alive else 1


if __name__ == "__main__":
    sys.exit(main())
