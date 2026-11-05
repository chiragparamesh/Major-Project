"""Prove model(x, training=False) == model.predict(x) for the 3 Keras models (Phase 9)."""
import os
import sys
import tempfile

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "backend"))
os.environ["MLBFD_TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "k.sqlite3").replace("\\", "/")
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import predictor  # noqa: E402

predictor.load_prediction_assets()
rng = np.random.default_rng(7)
worst = 0.0
for name in ("Neural Network", "LSTM", "Autoencoder"):
    m = predictor._models_cache.get(name)
    if m is None:
        print(f"{name}: not loaded")
        continue
    shape = (200,) + tuple(d or 1 for d in m.input_shape[1:])
    x = rng.normal(size=shape).astype(np.float32)
    a = m.predict(x, verbose=0)
    b = predictor._keras_infer(m, x)
    diff = float(np.max(np.abs(a - b)))
    worst = max(worst, diff)
    print(f"{name}: input {shape}, max |predict - direct| = {diff:.2e}")
print("EQUIVALENT" if worst < 1e-5 else f"DIFFERENT (max {worst})")
