"""
config.py
---------
Centralised configuration for the Fake/Bot Profile Detection project.
All hyper-parameters, paths, and toggles live here so nothing is
hard-coded elsewhere.
"""

from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT_DIR        = Path(__file__).resolve().parent
DATA_DIR        = ROOT_DIR / "data"
RAW_DIR         = DATA_DIR / "raw"
PROCESSED_DIR   = DATA_DIR / "processed"
MODELS_DIR      = ROOT_DIR / "models"
REPORTS_DIR     = ROOT_DIR / "reports"
LOGS_DIR        = ROOT_DIR / "logs"

for _dir in [RAW_DIR, PROCESSED_DIR, MODELS_DIR, REPORTS_DIR, LOGS_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# ── Data Generation ────────────────────────────────────────────────────────
N_PROFILES          = 50_000          # total synthetic profiles
BOT_RATIO           = 0.35            # 35 % bots, 65 % humans
RANDOM_SEED         = 42

# ── Feature Engineering ────────────────────────────────────────────────────
SIMILARITY_SAMPLE   = 10             # tweets sampled per user for content-sim
ENTROPY_BINS        = 24             # hourly bins for posting-time entropy

# ── Model Training ─────────────────────────────────────────────────────────
TEST_SIZE           = 0.20
VAL_SIZE            = 0.10           # fraction of train split used for val
CV_FOLDS            = 5

# Random Forest
RF_PARAMS = {
    "n_estimators"  : 500,
    "max_depth"     : None,
    "min_samples_leaf": 2,
    "max_features"  : "sqrt",
    "class_weight"  : "balanced",
    "n_jobs"        : 2,
    "random_state"  : RANDOM_SEED,
}

# Gradient Boosting (XGBoost-style via HistGradientBoosting)
HGB_PARAMS = {
    "max_iter"          : 400,
    "max_depth"         : 6,
    "learning_rate"     : 0.05,
    "min_samples_leaf"  : 20,
    "l2_regularization" : 0.1,
    "random_state"      : RANDOM_SEED,
}

# Extra Trees
ET_PARAMS = {
    "n_estimators"  : 400,
    "max_depth"     : None,
    "min_samples_leaf": 2,
    "max_features"  : "sqrt",
    "class_weight"  : "balanced",
    "n_jobs"        : 2,
    "random_state"  : RANDOM_SEED,
}

# Voting Ensemble weights  (RF, HGB, ET)
ENSEMBLE_WEIGHTS    = [2, 3, 1]

# ── Evaluation ─────────────────────────────────────────────────────────────
POSITIVE_LABEL      = 1              # 1 = bot

# ── Logging ────────────────────────────────────────────────────────────────
LOG_LEVEL           = "INFO"
LOG_FILE            = LOGS_DIR / "training.log"
