"""
src/data_preprocessing.py
--------------------------
Handles all data ingestion, cleaning, validation, and train/val/test
splitting.  The main entry-point is `load_and_preprocess()`.

Design notes
------------
- Keeps raw data untouched; all transforms are applied to copies.
- Reproducible splits using stratified sampling (preserves class ratio).
- Outlier capping via IQR fence (Winsorisation) to protect tree models
  from extreme synthetic artefacts.
- Returns sklearn-compatible numpy arrays ready for the pipeline.
"""

import logging
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import RobustScaler

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config

log = logging.getLogger(__name__)

# Columns that are NOT features (drop before modelling)
NON_FEATURE_COLS = ["user_id", "is_bot"]

# Columns that should never be negative (guard against generation drift)
NON_NEGATIVE_COLS = [
    "account_age_days", "followers_count", "following_count",
    "total_tweets", "tweet_frequency", "engagement_velocity",
    "avg_likes_per_tweet", "avg_retweets_per_tweet",
    "follower_growth_rate",
]

# Binary / already-bounded columns — skip Winsorisation
SKIP_WINSOR_COLS = [
    "verified", "has_bio", "has_location", "has_url",
    "has_profile_pic", "default_profile_pic",
]


def load_raw(path: Path | None = None) -> pd.DataFrame:
    """Load the raw CSV produced by generate_data.py."""
    path = path or config.RAW_DIR / "profiles.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Raw data not found at {path}.\n"
            "Run `python data/generate_data.py` first."
        )
    df = pd.read_csv(path)
    log.info("Loaded raw data: %s rows, %s cols", *df.shape)
    return df


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Basic data-quality checks.  Raises ValueError on critical failures,
    warns on minor ones.
    """
    # Check label column exists and is binary
    assert "is_bot" in df.columns, "Target column 'is_bot' missing."
    assert set(df["is_bot"].unique()).issubset({0, 1}), "Labels must be 0/1."

    n_null = df.isnull().sum().sum()
    if n_null > 0:
        log.warning("Found %d null values — will be filled with column median.", n_null)

    bot_pct = df["is_bot"].mean()
    if not 0.05 < bot_pct < 0.95:
        log.warning("Extreme class imbalance detected: %.1f%% bots.", bot_pct * 100)

    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """
    Impute missing values, fix negatives, and Winsorise heavy-tail columns.
    """
    df = df.copy()

    # Median imputation (safe for skewed distributions)
    for col in df.select_dtypes(include=np.number).columns:
        if df[col].isnull().any():
            df[col].fillna(df[col].median(), inplace=True)

    # Clip negatives
    for col in NON_NEGATIVE_COLS:
        if col in df.columns:
            df[col] = df[col].clip(lower=0)

    # Winsorise numeric features (1st / 99th percentile)
    numeric_cols = [
        c for c in df.select_dtypes(include=np.number).columns
        if c not in NON_FEATURE_COLS + SKIP_WINSOR_COLS
    ]
    for col in numeric_cols:
        lo, hi = df[col].quantile([0.01, 0.99])
        df[col] = df[col].clip(lower=lo, upper=hi)

    log.info("Cleaned dataset: %s rows, %s cols", *df.shape)
    return df


def engineer_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds a small set of derived ratio / interaction features that
    commonly carry signal for bot detection.
    """
    df = df.copy()

    # High follower-to-following ratio + low engagement → suspicious
    df["ff_ratio_x_engagement"] = (
        df["followers_to_following_ratio"] * df["engagement_velocity"]
    ).round(4)

    # Prolific tweeter but no real engagement
    df["tweet_freq_x_low_engagement"] = (
        df["tweet_frequency"] / (df["engagement_velocity"] + 1e-6)
    ).round(4)

    # Bot-neighbourhood amplified by low clustering
    df["isolation_score"] = (
        df["bot_neighbor_ratio"] * (1 - df["network_clustering_coef"])
    ).round(4)

    log.debug("Added 3 interaction features.")
    return df


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in NON_FEATURE_COLS]


def split(
    df: pd.DataFrame,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray, np.ndarray,
           list[str]]:
    """
    Stratified train / validation / test split.

    Returns
    -------
    X_train, X_val, X_test  : feature arrays
    y_train, y_val, y_test  : label vectors
    feature_names           : column name list (for SHAP / importance plots)
    """
    feature_cols = get_feature_columns(df)
    X = df[feature_cols].values
    y = df["is_bot"].values

    # First cut: (train+val) vs test
    X_tv, X_test, y_tv, y_test = train_test_split(
        X, y,
        test_size=config.TEST_SIZE,
        stratify=y,
        random_state=config.RANDOM_SEED,
    )

    # Second cut: train vs val
    val_frac = config.VAL_SIZE / (1 - config.TEST_SIZE)
    X_train, X_val, y_train, y_val = train_test_split(
        X_tv, y_tv,
        test_size=val_frac,
        stratify=y_tv,
        random_state=config.RANDOM_SEED,
    )

    log.info(
        "Split sizes → train: %d | val: %d | test: %d",
        len(y_train), len(y_val), len(y_test),
    )
    return X_train, X_val, X_test, y_train, y_val, y_test, feature_cols


def scale(
    X_train: np.ndarray,
    X_val:   np.ndarray,
    X_test:  np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, RobustScaler]:
    """
    Fit a RobustScaler on train, apply to val/test.
    Note: tree-based ensembles don't strictly need scaling, but it helps
    the calibration step and any linear meta-learner in a stacking ensemble.
    """
    scaler = RobustScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s   = scaler.transform(X_val)
    X_test_s  = scaler.transform(X_test)
    return X_train_s, X_val_s, X_test_s, scaler


def load_and_preprocess(
    path: Path | None = None,
    scale_features: bool = False,
) -> dict:
    """
    Full preprocessing pipeline.

    Parameters
    ----------
    path            : CSV path (default: config.RAW_DIR / profiles.csv)
    scale_features  : if True, apply RobustScaler (optional for trees)

    Returns
    -------
    dict with keys:
        X_train, X_val, X_test,
        y_train, y_val, y_test,
        feature_names, scaler (None if scale_features=False),
        df_clean (full cleaned DataFrame)
    """
    df = load_raw(path)
    df = validate(df)
    df = clean(df)
    df = engineer_interaction_features(df)

    # Save processed snapshot
    proc_path = config.PROCESSED_DIR / "profiles_clean.csv"
    df.to_csv(proc_path, index=False)
    log.info("Saved processed data → %s", proc_path)

    X_train, X_val, X_test, y_train, y_val, y_test, feat_cols = split(df)

    scaler = None
    if scale_features:
        X_train, X_val, X_test, scaler = scale(X_train, X_val, X_test)

    return {
        "X_train"       : X_train,
        "X_val"         : X_val,
        "X_test"        : X_test,
        "y_train"       : y_train,
        "y_val"         : y_val,
        "y_test"        : y_test,
        "feature_names" : feat_cols,
        "scaler"        : scaler,
        "df_clean"      : df,
    }
