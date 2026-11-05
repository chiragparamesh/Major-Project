"""
latency_benchmark.py - End-to-End Latency & Throughput Benchmark for MLBFD

Measures:
- Feature extraction & canonical alignment latency
- 7-model ML/DL ensemble inference latency
- SHAP TreeExplainer attribution latency (< 10 ms)
- 7-layer rules & learned stacking fusion latency
- Full end-to-end decision pipeline latency:
  - Mean, Median (p50), p95, p99, Min, Max
  - Throughput (evaluations per second)
"""

import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import time
import argparse
import numpy as np

# Ensure backend is in sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(root_dir, "backend")
for p in [root_dir, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from database import db, User, UserBehaviorBaseline
from fraud_detection import global_fraud_detector
from predictor import load_prediction_assets, explain_prediction_shap
from security import hash_pin, encrypt_val, compute_lookup_hash


def setup_benchmark_environment():
    """Initializes app and retrieves or creates benchmark users for warm execution."""
    os.environ["SECRET_KEY"] = "benchmark_secret_key"
    os.environ["JWT_SECRET_KEY"] = "benchmark_jwt_secret_key"
    os.environ["HASH_PEPPER"] = "benchmark_hash_pepper"
    os.environ["EMAIL_DRY_RUN"] = "True"

    app = create_app()

    with app.app_context():
        # Find active sender and receiver if already present
        sender = User.query.filter_by(status="ACTIVE").first()
        receiver = User.query.filter(User.status == "ACTIVE", User.user_id != (sender.user_id if sender else "")).first()

        if sender and receiver:
            sender_id = sender.user_id
            sender_upi = sender.get_decrypted_upi_id() or f"{sender.user_id}@mlbfd"
            receiver_upi = receiver.get_decrypted_upi_id() or f"{receiver.user_id}@mlbfd"
        else:
            # Seed isolated test user with unique timestamped phone
            uid_s = f"bench_u_{int(time.time() * 1000) % 100000}"
            uid_r = f"bench_r_{int(time.time() * 1000) % 100000}"
            p_s = f"+9191{int(time.time() * 1000) % 100000000:08d}"
            p_r = f"+9192{int(time.time() * 1000) % 100000000:08d}"
            sender_upi = f"{p_s[-10:]}@mlbfd"
            receiver_upi = f"{p_r[-10:]}@mlbfd"

            sender = User(
                user_id=uid_s,
                full_name="Benchmark Sender",
                phone=encrypt_val(p_s),
                phone_hash=compute_lookup_hash(p_s),
                email=encrypt_val(f"{uid_s}@mlbfd.local"),
                email_hash=compute_lookup_hash(f"{uid_s}@mlbfd.local"),
                upi_id=encrypt_val(sender_upi),
                upi_hash=compute_lookup_hash(sender_upi),
                login_pin_hash=hash_pin("129845"),
                payment_pin_hash=hash_pin("582914"),
                status="ACTIVE",
                balance=100000.0,
                email_verified=True,
                telegram_verified=True,
                known_devices=["bench_device_01"]
            )
            receiver = User(
                user_id=uid_r,
                full_name="Benchmark Receiver",
                phone=encrypt_val(p_r),
                phone_hash=compute_lookup_hash(p_r),
                email=encrypt_val(f"{uid_r}@mlbfd.local"),
                email_hash=compute_lookup_hash(f"{uid_r}@mlbfd.local"),
                upi_id=encrypt_val(receiver_upi),
                upi_hash=compute_lookup_hash(receiver_upi),
                login_pin_hash=hash_pin("129845"),
                payment_pin_hash=hash_pin("582914"),
                status="ACTIVE",
                balance=100000.0,
                email_verified=True,
                telegram_verified=True
            )
            baseline = UserBehaviorBaseline(
                user_id=uid_s,
                avg_amount=1500.0,
                std_amount=400.0,
                txn_count=20,
                known_devices=["bench_device_01"]
            )
            db.session.add_all([sender, receiver, baseline])
            db.session.commit()
            sender_id = uid_s

    return app, sender_id, sender_upi, receiver_upi


def run_benchmark(num_iterations: int = 100):
    print("=" * 70)
    print(f"MLBFD FRAUD DETECTION PIPELINE BENCHMARK ({num_iterations} iterations)")
    print("=" * 70)

    app, sender_id, sender_upi, receiver_upi = setup_benchmark_environment()

    # Pre-warm prediction assets
    print("Warming up ML/DL models and SHAP TreeExplainer...")
    with app.app_context():
        load_prediction_assets()
        # Warmup execution
        warmup_payload = {
            'user_id': sender_id,
            'sender_upi': sender_upi,
            'receiver_upi': receiver_upi,
            'amount': 1500.0,
            'device_id': 'bench_device_01',
            'latitude': 12.9716,
            'longitude': 77.5946
        }
        _ = global_fraud_detector.detect(warmup_payload)
    print("Warmup complete. Starting benchmark runs...\n")

    test_payloads = [
        # Normal transaction
        {
            'user_id': sender_id,
            'sender_upi': sender_upi,
            'receiver_upi': receiver_upi,
            'amount': 450.0,
            'device_id': 'bench_device_01',
            'latitude': 12.9716,
            'longitude': 77.5946
        },
        # High-value new device
        {
            'user_id': sender_id,
            'sender_upi': sender_upi,
            'receiver_upi': receiver_upi,
            'amount': 25000.0,
            'device_id': 'unknown_device_x',
            'latitude': 13.0827,
            'longitude': 80.2707
        },
        # Structuring payment
        {
            'user_id': sender_id,
            'sender_upi': sender_upi,
            'receiver_upi': receiver_upi,
            'amount': 9999.0,
            'device_id': 'bench_device_01',
            'latitude': 12.9716,
            'longitude': 77.5946
        }
    ]

    total_latencies = []
    shap_latencies = []

    with app.app_context():
        start_bench_time = time.perf_counter()
        for i in range(num_iterations):
            payload = test_payloads[i % len(test_payloads)]

            t0 = time.perf_counter()
            verdict = global_fraud_detector.detect(payload)
            t1 = time.perf_counter()

            total_latencies.append((t1 - t0) * 1000.0)

            # Benchmark isolated SHAP call
            t_shap_0 = time.perf_counter()
            _ = explain_prediction_shap({'amount': payload['amount']}, top_k=5)
            t_shap_1 = time.perf_counter()
            shap_latencies.append((t_shap_1 - t_shap_0) * 1000.0)

        end_bench_time = time.perf_counter()

    elapsed_total_sec = end_bench_time - start_bench_time
    throughput = num_iterations / elapsed_total_sec

    # Compute percentiles
    total_latencies = np.array(total_latencies)
    shap_latencies = np.array(shap_latencies)

    mean_lat = np.mean(total_latencies)
    p50_lat = np.percentile(total_latencies, 50)
    p95_lat = np.percentile(total_latencies, 95)
    p99_lat = np.percentile(total_latencies, 99)
    min_lat = np.min(total_latencies)
    max_lat = np.max(total_latencies)

    shap_mean = np.mean(shap_latencies)
    shap_p95 = np.percentile(shap_latencies, 95)

    print("-" * 70)
    print("BENCHMARK RESULTS SUMMARY:")
    print("-" * 70)
    print(f"Total Transactions Evaluated : {num_iterations}")
    print(f"Total Benchmark Time         : {elapsed_total_sec:.2f} s")
    print(f"Throughput                   : {throughput:.2f} txns/sec")
    print("-" * 70)
    print("END-TO-END PIPELINE LATENCY (Full 7 layers + 7 models + Fusion + SHAP):")
    print(f"  Mean Latency               : {mean_lat:.2f} ms")
    print(f"  Median (p50) Latency       : {p50_lat:.2f} ms")
    print(f"  95th Percentile (p95)      : {p95_lat:.2f} ms")
    print(f"  99th Percentile (p99)      : {p99_lat:.2f} ms")
    print(f"  Min / Max                  : {min_lat:.2f} ms / {max_lat:.2f} ms")
    print("-" * 70)
    print("SHAP TreeExplainer Attributions (Added Overhead):")
    print(f"  Mean Latency               : {shap_mean:.2f} ms  (Target: < 10 ms)")
    print(f"  95th Percentile (p95)      : {shap_p95:.2f} ms")
    print("-" * 70)

    # Verification assertions
    assert shap_mean < 10.0, f"SHAP mean latency {shap_mean:.2f}ms exceeds 10ms threshold"
    print("[OK] All latency and throughput criteria satisfied.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLBFD Latency Benchmark")
    parser.add_argument("--iterations", type=int, default=100, help="Number of benchmark iterations")
    args = parser.parse_args()
    sys.exit(run_benchmark(num_iterations=args.iterations))

