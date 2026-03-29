"""
data/generate_data.py
---------------------
Generates a realistic synthetic dataset of 50,000+ Twitter-style profiles,
including:
  - Profile metadata   (followers, bio, verification, account age …)
  - Activity logs      (per-user tweet timestamps, content samples)
  - Network features   (follower-graph clustering coefficients)

Bot profiles are seeded with statistical fingerprints that mirror
real-world bot behaviour patterns documented in the literature.

Run directly:
    python data/generate_data.py
"""

import sys
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import entropy as scipy_entropy
from sklearn.preprocessing import MinMaxScaler

# ── allow imports from project root ────────────────────────────────────────
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config

logging.basicConfig(level=config.LOG_LEVEL,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ────────────────────────────────────────────────────────────────────────────

rng = np.random.default_rng(config.RANDOM_SEED)


def _human_tweet_times(n_tweets: int) -> list[int]:
    """Returns list of posting hours (0-23) following a human circadian rhythm."""
    # Humans tweet mostly 08-23 with a peak around 12-14 and 20-22
    weights = np.zeros(24)
    weights[8:23] = [1, 2, 3, 4, 5, 5, 4, 3, 3, 2, 3, 4, 4, 3, 2]
    weights /= weights.sum()
    return rng.choice(24, size=n_tweets, p=weights).tolist()


def _bot_tweet_times(n_tweets: int) -> list[int]:
    """Returns list of posting hours for a bot — nearly uniform with burst spikes."""
    weights = np.ones(24)
    # Random burst hour
    burst = rng.integers(0, 24)
    weights[burst] += rng.uniform(3, 10)
    weights /= weights.sum()
    return rng.choice(24, size=n_tweets, p=weights).tolist()


def _content_similarity(is_bot: bool, n_samples: int) -> float:
    """
    Simulates average pairwise cosine similarity across a user's tweets.
    Bots tend to post repetitive or templated content → higher similarity.
    """
    if is_bot:
        return float(np.clip(rng.beta(6, 2), 0.55, 0.99))
    return float(np.clip(rng.beta(2, 6), 0.01, 0.55))


def _posting_time_entropy(hours: list[int]) -> float:
    """Shannon entropy of posting-hour distribution (higher = more uniform)."""
    if not hours:
        return 0.0
    counts = np.bincount(hours, minlength=24).astype(float)
    counts += 1e-9                        # Laplace smoothing
    return float(scipy_entropy(counts / counts.sum()))


def _network_clustering(is_bot: bool) -> float:
    """
    Approximates a node's clustering coefficient from the follower graph.
    Bots typically sit in sparse, star-shaped sub-graphs → low coefficient.
    """
    if is_bot:
        return float(np.clip(rng.beta(1.5, 5), 0.0, 0.4))
    return float(np.clip(rng.beta(4, 3), 0.1, 1.0))


def _bot_neighbor_ratio(is_bot: bool) -> float:
    """Fraction of first-degree neighbours flagged as bots in graph analysis."""
    if is_bot:
        return float(np.clip(rng.beta(5, 2), 0.4, 1.0))
    return float(np.clip(rng.beta(1.5, 6), 0.0, 0.35))


# ────────────────────────────────────────────────────────────────────────────
# Main generator
# ────────────────────────────────────────────────────────────────────────────

def generate_profiles(n: int = config.N_PROFILES,
                      bot_ratio: float = config.BOT_RATIO) -> pd.DataFrame:
    """
    Build the full synthetic profile dataset.

    Returns
    -------
    pd.DataFrame with one row per profile and columns covering:
      metadata, activity statistics, content features, network features,
      and the binary label `is_bot`.
    """
    n_bots   = int(n * bot_ratio)
    n_humans = n - n_bots
    log.info("Generating %d profiles (%d bots / %d humans) …", n, n_bots, n_humans)

    records = []

    for label, count in [(1, n_bots), (0, n_humans)]:
        is_bot = bool(label)

        for _ in range(count):
            # ── Account age (days since creation) ──────────────────────────
            if is_bot:
                age_days = int(rng.integers(1, 365))           # young accounts
            else:
                age_days = int(rng.integers(90, 3650))         # established

            # ── Follower / following counts ─────────────────────────────────
            if is_bot:
                followers = int(rng.integers(0, 500))
                following = int(rng.integers(500, 8000))        # follow-spam
            else:
                followers = int(rng.integers(10, 25000))
                following = int(rng.integers(10, 2000))

            # ── Tweet volume ────────────────────────────────────────────────
            if is_bot:
                total_tweets = int(rng.integers(500, 30000))
            else:
                total_tweets = int(rng.integers(5, 5000))

            tweet_freq = round(total_tweets / max(age_days, 1), 4)   # tweets/day

            # ── Engagement ─────────────────────────────────────────────────
            if is_bot:
                avg_likes      = float(np.clip(rng.exponential(0.5), 0, 5))
                avg_retweets   = float(np.clip(rng.exponential(0.3), 0, 3))
            else:
                avg_likes      = float(np.clip(rng.exponential(15), 0, 500))
                avg_retweets   = float(np.clip(rng.exponential(5),  0, 200))

            # engagement velocity = (likes + retweets) per day active
            engagement_velocity = round(
                (avg_likes + avg_retweets) * tweet_freq, 4
            )

            # ── Profile completeness ────────────────────────────────────────
            has_bio         = bool(rng.choice([True, False], p=[0.3, 0.7] if is_bot else [0.85, 0.15]))
            has_location    = bool(rng.choice([True, False], p=[0.2, 0.8] if is_bot else [0.7, 0.3]))
            has_url         = bool(rng.choice([True, False], p=[0.15, 0.85] if is_bot else [0.4, 0.6]))
            has_profile_pic = bool(rng.choice([True, False], p=[0.4, 0.6] if is_bot else [0.95, 0.05]))
            default_pic     = bool(rng.choice([True, False], p=[0.6, 0.4] if is_bot else [0.05, 0.95]))
            verified        = bool(rng.choice([True, False], p=[0.01, 0.99] if is_bot else [0.08, 0.92]))

            profile_completeness = round(
                (has_bio + has_location + has_url + has_profile_pic + verified) / 5, 2
            )

            # ── Username signals ────────────────────────────────────────────
            username_length     = int(rng.integers(12, 16) if is_bot else rng.integers(4, 14))
            # bots often have trailing digits (e.g. user1234567)
            username_digit_ratio = round(
                rng.uniform(0.4, 0.8) if is_bot else rng.uniform(0.0, 0.2), 3
            )

            # ── Tweet content signals ────────────────────────────────────────
            avg_tweet_length    = float(np.clip(
                rng.normal(60, 20) if is_bot else rng.normal(110, 35), 10, 280
            ))
            hashtag_ratio       = round(rng.beta(5, 2) if is_bot else rng.beta(2, 5), 3)
            url_ratio           = round(rng.beta(6, 2) if is_bot else rng.beta(2, 5), 3)
            mention_ratio       = round(rng.beta(4, 3) if is_bot else rng.beta(2, 5), 3)
            retweet_ratio       = round(rng.beta(7, 2) if is_bot else rng.beta(2, 6), 3)
            duplicate_tweet_ratio = round(rng.beta(5, 2) if is_bot else rng.beta(1, 8), 3)

            # ── Content similarity ───────────────────────────────────────────
            content_similarity  = _content_similarity(is_bot, config.SIMILARITY_SAMPLE)

            # ── Temporal signals ─────────────────────────────────────────────
            n_sample_tweets     = min(total_tweets, 200)
            hours               = (_bot_tweet_times if is_bot else _human_tweet_times)(n_sample_tweets)
            posting_time_entropy= round(_posting_time_entropy(hours), 4)

            # bots post at night more uniformly
            night_tweet_ratio   = round(
                sum(1 for h in hours if 0 <= h < 6) / max(len(hours), 1), 3
            )

            # ── Network signals ──────────────────────────────────────────────
            network_clustering  = round(_network_clustering(is_bot), 4)
            bot_neighbor_ratio  = round(_bot_neighbor_ratio(is_bot), 4)

            # ── Follower growth rate (followers / age) ────────────────────────
            follower_growth_rate = round(followers / max(age_days, 1), 4)

            records.append({
                # identifiers
                "user_id"               : rng.integers(10**9, 10**12),
                "is_bot"                : label,
                # metadata
                "account_age_days"      : age_days,
                "verified"              : int(verified),
                "followers_count"       : followers,
                "following_count"       : following,
                "followers_to_following_ratio": round(followers / max(following, 1), 4),
                "follower_growth_rate"  : follower_growth_rate,
                "has_bio"               : int(has_bio),
                "has_location"          : int(has_location),
                "has_url"               : int(has_url),
                "has_profile_pic"       : int(has_profile_pic),
                "default_profile_pic"   : int(default_pic),
                "profile_completeness"  : profile_completeness,
                "username_length"       : username_length,
                "username_digit_ratio"  : username_digit_ratio,
                # activity
                "total_tweets"          : total_tweets,
                "tweet_frequency"       : tweet_freq,
                "engagement_velocity"   : engagement_velocity,
                "avg_likes_per_tweet"   : round(avg_likes, 2),
                "avg_retweets_per_tweet": round(avg_retweets, 2),
                # content
                "avg_tweet_length"      : round(avg_tweet_length, 2),
                "hashtag_ratio"         : hashtag_ratio,
                "url_ratio"             : url_ratio,
                "mention_ratio"         : mention_ratio,
                "retweet_ratio"         : retweet_ratio,
                "duplicate_tweet_ratio" : duplicate_tweet_ratio,
                "content_similarity"    : content_similarity,
                # temporal
                "posting_time_entropy"  : posting_time_entropy,
                "night_tweet_ratio"     : night_tweet_ratio,
                # network
                "network_clustering_coef": network_clustering,
                "bot_neighbor_ratio"    : bot_neighbor_ratio,
            })

    df = pd.DataFrame(records)
    df = df.sample(frac=1, random_state=config.RANDOM_SEED).reset_index(drop=True)
    log.info("Dataset shape: %s", df.shape)
    return df


# ────────────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = generate_profiles()

    profiles_path = config.RAW_DIR / "profiles.csv"
    df.to_csv(profiles_path, index=False)
    log.info("Saved → %s", profiles_path)

    # Quick sanity check
    print("\n── Dataset summary ──────────────────────────────")
    print(df.head())
    print(f"\nShape      : {df.shape}")
    print(f"Bot ratio  : {df['is_bot'].mean():.2%}")
    print(f"Features   : {df.shape[1] - 2}")   # minus user_id, is_bot
    print(f"Null cells : {df.isnull().sum().sum()}")
