"""
predict.py
----------
Production-ready inference script.

Loads the saved ensemble model and scores new profile records.
Accepts either:
  (a) a CSV file path  →  predict.py --input profiles.csv --output results.csv
  (b) a JSON dict      →  predict.py --json '{"followers_count": 12, ...}'

Output adds two columns to the input CSV:
  - bot_probability   : calibrated probability (0–1) that the account is a bot
  - predicted_label   : 1 = bot, 0 = human (using optimal threshold)

Usage
-----
    python predict.py --input new_profiles.csv
    python predict.py --input new_profiles.csv --threshold 0.48
    python predict.py --json '{"followers_count":10, "following_count":9000, ...}'
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import config
from src.utils              import setup_logging, load_json
from src.data_preprocessing import clean, engineer_interaction_features
from src.models             import load_model

log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def load_feature_names() -> list[str]:
    """Loads the ordered feature name list saved during training."""
    path = config.REPORTS_DIR / "feature_names.json"
    if path.exists():
        return load_json(path)
    # fallback: derive from feature engineering catalog
    from src.feature_engineering import FEATURE_NAMES
    return FEATURE_NAMES


def preprocess_for_inference(df: pd.DataFrame, feature_names: list[str]) -> np.ndarray:
    """
    Applies the same cleaning & interaction-feature steps as training,
    then selects and orders columns to match the trained model's input.
    """
    df = df.copy()

    # Add any missing columns with 0 (safe fallback)
    for col in feature_names:
        if col not in df.columns:
            log.warning("Missing feature '%s' — filling with 0.", col)
            df[col] = 0

    # Re-derive interaction features
    df = engineer_interaction_features(df)

    # Clip negatives
    for col in ["account_age_days", "followers_count", "following_count",
                "total_tweets", "tweet_frequency", "engagement_velocity"]:
        if col in df.columns:
            df[col] = df[col].clip(lower=0)

    # Median impute any remaining nulls
    for col in feature_names:
        if df[col].isnull().any():
            df[col] = df[col].fillna(df[col].median())

    return df[feature_names].values


# ────────────────────────────────────────────────────────────────────────────
# Core predict function
# ────────────────────────────────────────────────────────────────────────────

def predict(
    df          : pd.DataFrame,
    model       = None,
    threshold   : float = 0.50,
    feature_names: list[str] | None = None,
) -> pd.DataFrame:
    """
    Scores a DataFrame of profiles.

    Parameters
    ----------
    df            : raw profile DataFrame (must include feature columns)
    model         : fitted ensemble (loaded if None)
    threshold     : decision boundary for binary label
    feature_names : ordered feature list from training

    Returns
    -------
    Input DataFrame with 'bot_probability' and 'predicted_label' appended.
    """
    if model is None:
        model = load_model("ensemble")

    if feature_names is None:
        feature_names = load_feature_names()

    X = preprocess_for_inference(df, feature_names)
    probs  = model.predict_proba(X)[:, 1]
    labels = (probs >= threshold).astype(int)

    df = df.copy()
    df["bot_probability"] = np.round(probs, 4)
    df["predicted_label"] = labels
    return df


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Score profiles for bot probability")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=str, help="Path to input CSV")
    group.add_argument("--json",  type=str, help="Single profile as JSON string")
    p.add_argument("--output",    type=str, default=None,
                   help="Output CSV path (default: input_scored.csv)")
    p.add_argument("--threshold", type=float, default=0.50,
                   help="Decision threshold (default 0.50)")
    p.add_argument("--model",     type=str, default="ensemble",
                   help="Model name to load (default: ensemble)")
    return p.parse_args()


def main():
    setup_logging()
    args = parse_args()

    model = load_model(args.model)
    feature_names = load_feature_names()

    if args.json:
        # Single profile from JSON
        record = json.loads(args.json)
        df_in  = pd.DataFrame([record])
    else:
        df_in = pd.read_csv(args.input)
        log.info("Loaded %d profiles from %s", len(df_in), args.input)

    df_out = predict(df_in, model=model,
                     threshold=args.threshold,
                     feature_names=feature_names)

    # Summary stats
    n_bots = df_out["predicted_label"].sum()
    print(f"\n  Profiles scored  : {len(df_out):,}")
    print(f"  Predicted bots   : {n_bots:,} ({n_bots/len(df_out):.1%})")
    print(f"  Mean bot prob    : {df_out['bot_probability'].mean():.4f}")
    print(f"  Decision threshold: {args.threshold}")

    if args.json:
        # Pretty-print for single-profile mode
        row = df_out.iloc[0]
        status = "🤖 BOT" if row["predicted_label"] == 1 else "✅ Human"
        print(f"\n  Result: {status}  (probability: {row['bot_probability']:.4f})")
    else:
        out_path = args.output or args.input.replace(".csv", "_scored.csv")
        df_out.to_csv(out_path, index=False)
        print(f"\n  Scored CSV → {out_path}")


if __name__ == "__main__":
    main()
