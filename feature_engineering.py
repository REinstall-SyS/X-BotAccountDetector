"""
src/feature_engineering.py
--------------------------
Documents and groups all 30+ engineered features used by the classifiers.

Although most raw features are already generated in generate_data.py,
this module:
  1. Provides a typed FeatureCatalog (documentation + grouping).
  2. Offers a `FeaturePipeline` sklearn-compatible transformer that can
     accept a raw DataFrame and output the final feature matrix,
     making the code reusable for inference on new data.
  3. Runs a quick variance / correlation audit to flag low-signal features.

Feature groups
--------------
  A. Account Metadata     (6 features)
  B. Activity & Volume    (5 features)
  C. Engagement           (3 features)
  D. Content Signals      (7 features)
  E. Temporal Signals     (2 features)
  F. Network Graph        (2 features)
  G. Derived Interactions (3 features)
  ─────────────────────────────────────
  Total                   28 features
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config

log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Feature Catalog
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class Feature:
    name        : str
    group       : str
    description : str
    dtype       : str = "float"
    is_raw      : bool = True   # False = derived in preprocessing


FEATURE_CATALOG: List[Feature] = [
    # ── A. Account Metadata ──────────────────────────────────────────────────
    Feature("account_age_days",          "metadata", "Days since account creation"),
    Feature("verified",                  "metadata", "Twitter-verified badge (binary)", dtype="int"),
    Feature("followers_to_following_ratio","metadata","Ratio of followers to following count; bots follow many, have few followers"),
    Feature("follower_growth_rate",      "metadata", "Followers gained per day (followers / account_age_days)"),
    Feature("profile_completeness",      "metadata", "Weighted score: bio, location, URL, profile pic, verification"),
    Feature("default_profile_pic",       "metadata", "1 if still using default avatar (strong bot signal)", dtype="int"),
    Feature("username_length",           "metadata", "Character length of the username"),
    Feature("username_digit_ratio",      "metadata", "Fraction of username characters that are digits"),

    # ── B. Activity & Volume ─────────────────────────────────────────────────
    Feature("total_tweets",              "activity", "Lifetime tweet count"),
    Feature("tweet_frequency",           "activity", "Tweets per day (total_tweets / account_age_days)"),
    Feature("avg_likes_per_tweet",       "activity", "Mean likes received across sampled tweets"),
    Feature("avg_retweets_per_tweet",    "activity", "Mean retweets received across sampled tweets"),
    Feature("engagement_velocity",       "activity", "Rate of engagement accumulation per active day; bots show near-zero values"),

    # ── C. Content Signals ───────────────────────────────────────────────────
    Feature("avg_tweet_length",          "content",  "Mean character length of tweets; bots post short templated messages"),
    Feature("hashtag_ratio",             "content",  "Proportion of tweets containing ≥1 hashtag"),
    Feature("url_ratio",                 "content",  "Proportion of tweets containing URLs (spam bots post links heavily)"),
    Feature("mention_ratio",             "content",  "Proportion of tweets with @mentions"),
    Feature("retweet_ratio",             "content",  "Fraction of activity that is retweets rather than original content"),
    Feature("duplicate_tweet_ratio",     "content",  "Fraction of tweets near-identical to another in the user's timeline"),
    Feature("content_similarity",        "content",  "Mean pairwise cosine similarity across sampled tweets; measures repetitiveness"),

    # ── D. Temporal Signals ──────────────────────────────────────────────────
    Feature("posting_time_entropy",      "temporal", "Shannon entropy of tweet-hour distribution; bots post uniformly → higher entropy"),
    Feature("night_tweet_ratio",         "temporal", "Fraction of tweets posted 00:00–06:00 UTC; automated accounts ignore sleep"),

    # ── E. Network Graph ─────────────────────────────────────────────────────
    Feature("network_clustering_coef",   "network",  "Local clustering coefficient in the follower graph; bots sit in star-shaped sub-graphs"),
    Feature("bot_neighbor_ratio",        "network",  "Fraction of first-degree graph neighbours also flagged as suspicious"),

    # ── F. Derived (interaction) ─────────────────────────────────────────────
    Feature("ff_ratio_x_engagement",         "derived", "followers_to_following_ratio × engagement_velocity", is_raw=False),
    Feature("tweet_freq_x_low_engagement",   "derived", "tweet_frequency / (engagement_velocity + ε)", is_raw=False),
    Feature("isolation_score",               "derived", "bot_neighbor_ratio × (1 − network_clustering_coef)", is_raw=False),
]

FEATURE_NAMES = [f.name for f in FEATURE_CATALOG]
FEATURE_GROUPS = {g: [f.name for f in FEATURE_CATALOG if f.group == g]
                  for g in {f.group for f in FEATURE_CATALOG}}


def print_catalog() -> None:
    """Pretty-prints the feature catalog grouped by type."""
    for group, features in sorted(FEATURE_GROUPS.items()):
        print(f"\n{'─'*60}")
        print(f"  {group.upper()}")
        print(f"{'─'*60}")
        for name in features:
            feat = next(f for f in FEATURE_CATALOG if f.name == name)
            print(f"  {name:<40} {feat.description}")
    print()


# ────────────────────────────────────────────────────────────────────────────
# sklearn-compatible FeaturePipeline
# ────────────────────────────────────────────────────────────────────────────

class FeaturePipeline(BaseEstimator, TransformerMixin):
    """
    Takes a raw profile DataFrame and outputs the final feature matrix
    as a numpy array.

    Usage
    -----
    >>> pipe = FeaturePipeline()
    >>> X = pipe.fit_transform(df_raw)
    """

    def __init__(self, feature_names: Optional[List[str]] = None):
        self.feature_names = feature_names or FEATURE_NAMES

    # ── sklearn interface ────────────────────────────────────────────────────
    def fit(self, X: pd.DataFrame, y=None):
        # Compute medians for imputation during inference
        self._medians = X[self.feature_names].median()
        return self

    def transform(self, X: pd.DataFrame, y=None) -> np.ndarray:
        df = X[self.feature_names].copy()

        # Impute with training-set medians
        df = df.fillna(self._medians)

        # Re-derive interaction features if they aren't already present
        if "ff_ratio_x_engagement" not in df.columns:
            df = self._add_interactions(df)

        return df.values

    # ── internal helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _add_interactions(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ff_ratio_x_engagement"] = (
            df.get("followers_to_following_ratio", 0)
            * df.get("engagement_velocity", 0)
        )
        df["tweet_freq_x_low_engagement"] = (
            df.get("tweet_frequency", 0)
            / (df.get("engagement_velocity", 0) + 1e-6)
        )
        df["isolation_score"] = (
            df.get("bot_neighbor_ratio", 0)
            * (1 - df.get("network_clustering_coef", 0))
        )
        return df

    def get_feature_names_out(self, input_features=None):
        return np.array(self.feature_names)


# ────────────────────────────────────────────────────────────────────────────
# Audit helpers (called from train.py)
# ────────────────────────────────────────────────────────────────────────────

def variance_audit(df: pd.DataFrame,
                   threshold: float = 0.001) -> List[str]:
    """Returns list of numeric features with near-zero variance."""
    low_var = []
    for col in FEATURE_NAMES:
        if col in df.columns:
            var = df[col].var()
            if var < threshold:
                low_var.append(col)
                log.warning("Low variance feature: %s (var=%.6f)", col, var)
    return low_var


def correlation_audit(df: pd.DataFrame,
                      threshold: float = 0.95) -> List[tuple]:
    """Returns pairs of features with Pearson |r| above threshold."""
    num_df = df[[c for c in FEATURE_NAMES if c in df.columns]]
    corr   = num_df.corr().abs()
    pairs  = []
    cols   = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            val = corr.iloc[i, j]
            if val >= threshold:
                pairs.append((cols[i], cols[j], round(val, 3)))
                log.warning("High correlation: %s ↔ %s (r=%.3f)", cols[i], cols[j], val)
    return pairs


if __name__ == "__main__":
    print_catalog()
    print(f"\nTotal features: {len(FEATURE_CATALOG)}")
    print(f"Groups        : {list(FEATURE_GROUPS.keys())}")
