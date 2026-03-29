"""
src/models.py
-------------
Defines, trains, calibrates, and saves the three base classifiers
and the final soft-voting ensemble used for bot detection.

Architecture
─────────────
  Base learners
  ├── RandomForestClassifier     (RF)   – robust, good with mixed features
  ├── HistGradientBoostingClassifier (HGB) – fastest, handles scale well
  └── ExtraTreesClassifier       (ET)   – high variance reduction via random splits

  Ensemble
  └── VotingClassifier (soft, weighted 2:3:1)
        └── CalibratedClassifierCV wraps each base learner
              (Platt scaling to get well-calibrated probabilities)

Persistence: models are saved as joblib files under config.MODELS_DIR.
"""

import logging
import pickle
from pathlib import Path
from typing import Dict, Tuple, Any

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    RandomForestClassifier,
    ExtraTreesClassifier,
    VotingClassifier,
    HistGradientBoostingClassifier,
)
from sklearn.pipeline import Pipeline

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config

log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# Builder functions
# ────────────────────────────────────────────────────────────────────────────

def build_random_forest() -> RandomForestClassifier:
    """500-tree Random Forest with balanced class weights."""
    return RandomForestClassifier(**config.RF_PARAMS)


def build_hist_gradient_boosting() -> HistGradientBoostingClassifier:
    """Histogram-based GBM — fast and memory-efficient on 50k rows."""
    return HistGradientBoostingClassifier(**config.HGB_PARAMS)


def build_extra_trees() -> ExtraTreesClassifier:
    """Extra-Trees for additional diversity in the ensemble."""
    return ExtraTreesClassifier(**config.ET_PARAMS)


def build_ensemble(
    calibrate: bool = True,
    cv_folds : int  = 3,
) -> VotingClassifier:
    """
    Build the weighted soft-voting ensemble.

    Parameters
    ----------
    calibrate : wrap each base learner with CalibratedClassifierCV
                for well-calibrated probability estimates.
    cv_folds  : number of cross-val folds used for Platt calibration.
    """
    rf  = build_random_forest()
    hgb = build_hist_gradient_boosting()
    et  = build_extra_trees()

    if calibrate:
        rf  = CalibratedClassifierCV(rf,  method="isotonic", cv=cv_folds)
        hgb = CalibratedClassifierCV(hgb, method="sigmoid",  cv=cv_folds)
        et  = CalibratedClassifierCV(et,  method="isotonic", cv=cv_folds)

    ensemble = VotingClassifier(
        estimators=[("rf", rf), ("hgb", hgb), ("et", et)],
        voting="soft",
        weights=config.ENSEMBLE_WEIGHTS,
        n_jobs=-1,
    )
    return ensemble


# ────────────────────────────────────────────────────────────────────────────
# Training
# ────────────────────────────────────────────────────────────────────────────

def train_all(
    X_train : np.ndarray,
    y_train : np.ndarray,
    X_val   : np.ndarray,
    y_val   : np.ndarray,
    feature_names: list[str],
) -> Dict[str, Any]:
    """
    Trains four models: RF, HGB, ET (individually calibrated) and the
    combined soft-voting ensemble.

    Returns
    -------
    dict mapping model name → fitted estimator
    """
    from src.evaluate import quick_eval   # avoid circular import at module level

    models: Dict[str, Any] = {}

    # ── Individual base learners (uncalibrated, for feature importance) ──────
    log.info("Training Random Forest …")
    rf  = build_random_forest()
    rf.fit(X_train, y_train)
    models["random_forest"] = rf
    quick_eval(rf, X_val, y_val, label="Random Forest  (val)")

    log.info("Training HistGradientBoosting …")
    hgb = build_hist_gradient_boosting()
    hgb.fit(X_train, y_train)
    models["hist_gradient_boosting"] = hgb
    quick_eval(hgb, X_val, y_val, label="HistGradBoost  (val)")

    log.info("Training Extra Trees …")
    et  = build_extra_trees()
    et.fit(X_train, y_train)
    models["extra_trees"] = et
    quick_eval(et, X_val, y_val, label="Extra Trees    (val)")

    # ── Ensemble ─────────────────────────────────────────────────────────────
    log.info("Training Voting Ensemble (with Platt/isotonic calibration) …")
    ensemble = build_ensemble(calibrate=True)
    # Ensemble is trained on combined train+val to maximise data usage
    X_all = np.vstack([X_train, X_val])
    y_all = np.concatenate([y_train, y_val])
    ensemble.fit(X_all, y_all)
    models["ensemble"] = ensemble
    log.info("Ensemble training complete.")

    return models


# ────────────────────────────────────────────────────────────────────────────
# Feature importance
# ────────────────────────────────────────────────────────────────────────────

def feature_importance_df(
    model       : RandomForestClassifier | ExtraTreesClassifier,
    feature_names: list[str],
    top_n       : int = 20,
) -> "pd.DataFrame":
    """Returns a sorted DataFrame of impurity-based feature importances."""
    import pandas as pd
    importances = model.feature_importances_
    df = pd.DataFrame({
        "feature"   : feature_names,
        "importance": importances,
    }).sort_values("importance", ascending=False)
    return df.head(top_n).reset_index(drop=True)


# ────────────────────────────────────────────────────────────────────────────
# Persistence
# ────────────────────────────────────────────────────────────────────────────

def save_model(model, name: str, directory: Path = config.MODELS_DIR) -> Path:
    path = directory / f"{name}.joblib"
    joblib.dump(model, path)
    log.info("Saved model → %s", path)
    return path


def load_model(name: str, directory: Path = config.MODELS_DIR):
    path = directory / f"{name}.joblib"
    if not path.exists():
        raise FileNotFoundError(f"No saved model at {path}.")
    model = joblib.load(path)
    log.info("Loaded model ← %s", path)
    return model


def save_all(models: dict, directory: Path = config.MODELS_DIR) -> None:
    for name, model in models.items():
        save_model(model, name, directory)
