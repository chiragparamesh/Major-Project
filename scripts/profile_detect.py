"""Profile fraud_detection.detect() on a throw-away DB: python scripts/profile_detect.py [N]"""
import cProfile
import os
import pstats
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "backend"))
sys.path.insert(0, REPO)
os.environ["MLBFD_TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "p.sqlite3").replace("\\", "/")
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import latency_benchmark as lb  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
app = lb.setup_benchmark_environment() if hasattr(lb, "setup_benchmark_environment") else None
from app import create_app  # noqa: E402
from fraud_detection import global_fraud_detector  # noqa: E402

app = app if hasattr(app, "app_context") else create_app(start_bot=False)
with app.app_context():
    payload = {"user_id": "bench_user_01", "sender_upi": "9876500001@mlbfd", "receiver_upi": "9876500002@mlbfd",
               "amount": 1250.0, "device_id": "bench-device", "latitude": 12.97, "longitude": 77.59}
    for _ in range(3):
        global_fraud_detector.detect(dict(payload))
    pr = cProfile.Profile()
    pr.enable()
    for i in range(n):
        p = dict(payload)
        p["amount"] = 500.0 + i
        global_fraud_detector.detect(p)
    pr.disable()
    st = pstats.Stats(pr).sort_stats("cumulative")
    st.print_stats(28)
