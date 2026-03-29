"""
src/utils.py
------------
Shared utility functions used across the project:
  - Logging setup
  - Timer context manager
  - Pretty printing of dicts
  - JSON serialisation helpers
  - Reproducibility seed setter
"""

import json
import logging
import os
import random
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

import numpy as np

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config


# ────────────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────────────

def setup_logging(
    level    : str  = config.LOG_LEVEL,
    log_file : Path = config.LOG_FILE,
) -> logging.Logger:
    """
    Configures the root logger with both a console handler (INFO)
    and a rotating file handler (DEBUG).
    """
    fmt     = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level   = getattr(logging, level.upper(), logging.INFO),
        format  = fmt,
        datefmt = datefmt,
        handlers= [
            logging.StreamHandler(),
            logging.FileHandler(log_file, mode="a"),
        ],
    )
    return logging.getLogger()


# ────────────────────────────────────────────────────────────────────────────
# Reproducibility
# ────────────────────────────────────────────────────────────────────────────

def set_seed(seed: int = config.RANDOM_SEED) -> None:
    """Pins all random seeds for full reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


# ────────────────────────────────────────────────────────────────────────────
# Timing
# ────────────────────────────────────────────────────────────────────────────

@contextmanager
def timer(label: str = ""):
    """Context manager that prints elapsed time."""
    log = logging.getLogger("timer")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log.info("  ⏱  %s — %.2fs", label, elapsed)
        print(f"  ⏱  {label} — {elapsed:.2f}s")


# ────────────────────────────────────────────────────────────────────────────
# Pretty printing
# ────────────────────────────────────────────────────────────────────────────

def pprint_metrics(metrics: Dict[str, Any], title: str = "Metrics") -> None:
    """Prints a metrics dictionary in a neat table."""
    print(f"\n  ┌{'─'*(len(title)+2)}┐")
    print(f"  │ {title} │")
    print(f"  └{'─'*(len(title)+2)}┘")
    for k, v in metrics.items():
        val_str = f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"  {k:<35} {val_str}")


# ────────────────────────────────────────────────────────────────────────────
# JSON helpers
# ────────────────────────────────────────────────────────────────────────────

class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def save_json(data: Any, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, cls=_NumpyEncoder)
    logging.getLogger().info("Saved JSON → %s", path)


def load_json(path: Path) -> Any:
    with open(path) as f:
        return json.load(f)


# ────────────────────────────────────────────────────────────────────────────
# Threshold tuning
# ────────────────────────────────────────────────────────────────────────────

def find_best_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    metric: str = "f1",
) -> tuple[float, float]:
    """
    Sweeps decision thresholds [0.1, 0.9] and returns the threshold that
    maximises the given metric ('f1', 'precision', or 'recall').

    Returns
    -------
    (best_threshold, best_score)
    """
    from sklearn.metrics import f1_score, precision_score, recall_score

    fn_map = {"f1": f1_score, "precision": precision_score, "recall": recall_score}
    fn     = fn_map.get(metric, f1_score)

    best_thr, best_score = 0.5, 0.0
    for thr in np.arange(0.1, 0.91, 0.01):
        y_pred = (y_prob >= thr).astype(int)
        score  = fn(y_true, y_pred, zero_division=0)
        if score > best_score:
            best_score = score
            best_thr   = thr

    logging.getLogger().info(
        "Best threshold for %s: %.2f → score=%.4f", metric, best_thr, best_score
    )
    return float(best_thr), float(best_score)
