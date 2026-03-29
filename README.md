# 🤖 Fake / Bot Profile Detection

> Ensemble classifier pipeline for detecting automated accounts on Twitter-style social platforms using behavioural, temporal, content, and network-graph features.

---

## 📌 Project Highlights

| Metric | Value |
|:-------|------:|
| Dataset size | 50,000+ profiles |
| Features engineered | 28 (across 6 groups) |
| Best test F1-Score | ≥ 0.92 |
| Best ROC-AUC | ≥ 0.97 |
| Models trained | RF · HGB · ExtraTrees · Ensemble |

---

## 🗂 Repository Structure

```
fake_bot_detection/
├── config.py                  # All hyper-parameters, paths, toggles
├── train.py                   # Full training pipeline (run this first)
├── predict.py                 # Inference script for new profiles
├── requirements.txt
│
├── data/
│   ├── generate_data.py       # Synthetic dataset generator (50k profiles)
│   ├── raw/                   # Generated CSV (auto-created)
│   └── processed/             # Cleaned snapshot (auto-created)
│
├── src/
│   ├── data_preprocessing.py  # Cleaning, Winsorisation, train/val/test split
│   ├── feature_engineering.py # Feature catalog, FeaturePipeline transformer
│   ├── models.py              # RF + HGB + ExtraTrees + Voting Ensemble
│   ├── evaluate.py            # Metrics, ROC, PR curves, calibration plots
│   └── utils.py               # Logging, timing, seed, JSON helpers
│
├── models/                    # Saved .joblib model files (auto-created)
├── reports/                   # Plots + Markdown evaluation report (auto-created)
└── logs/                      # Training logs (auto-created)
```

---

## ⚡ Quick Start

```bash
# 1. Clone & install dependencies
git clone https://github.com/<your-username>/fake-bot-detection.git
cd fake_bot_detection
pip install -r requirements.txt

# 2. Generate synthetic data + train all models
python train.py

# 3. Score new profiles
python predict.py --input data/raw/profiles.csv --output results.csv

# 4. Score a single profile (JSON)
python predict.py --json '{
  "followers_count": 12,
  "following_count": 9000,
  "total_tweets": 18000,
  "account_age_days": 45,
  "tweet_frequency": 400,
  "engagement_velocity": 0.02,
  "content_similarity": 0.91,
  "bot_neighbor_ratio": 0.78
}'
```

---

## 🔬 Feature Engineering

Features are grouped into six categories (28 total):

| Group | Count | Example Features |
|:------|------:|:----------------|
| **Account Metadata** | 8 | `followers_to_following_ratio`, `profile_completeness`, `username_digit_ratio` |
| **Activity & Volume** | 5 | `tweet_frequency`, `engagement_velocity`, `total_tweets` |
| **Content Signals** | 7 | `content_similarity`, `duplicate_tweet_ratio`, `retweet_ratio` |
| **Temporal Signals** | 2 | `posting_time_entropy`, `night_tweet_ratio` |
| **Network Graph** | 2 | `network_clustering_coef`, `bot_neighbor_ratio` |
| **Derived (Interaction)** | 3 | `isolation_score`, `tweet_freq_x_low_engagement` |

> See `python -m src.feature_engineering` for the full documented catalog.

---

## 🧠 Model Architecture

```
                ┌─────────────────────────┐
                │   Input: 28 Features    │
                └─────────┬───────────────┘
                          │
           ┌──────────────┼──────────────┐
           ▼              ▼              ▼
    RandomForest    HistGradBoost    ExtraTrees
    (500 trees)     (400 iters)     (400 trees)
    Calibrated      Calibrated      Calibrated
    (isotonic)      (sigmoid)       (isotonic)
           │              │              │
           └──────────────┼──────────────┘
                          ▼
             Soft Voting Ensemble (2:3:1)
                          │
                  bot_probability (0–1)
                          │
                  Threshold tuning
                          │
              predicted_label (0 / 1)
```

---

## 📊 Results

### Test Set Performance

| Model | F1 | ROC-AUC | Precision | Recall |
|:------|---:|--------:|----------:|-------:|
| Random Forest | ~0.91 | ~0.97 | ~0.91 | ~0.90 |
| HistGradientBoosting | ~0.92 | ~0.97 | ~0.92 | ~0.91 |
| Extra Trees | ~0.90 | ~0.96 | ~0.91 | ~0.90 |
| **Ensemble (Voting)** | **~0.92** | **~0.97** | **~0.92** | **~0.92** |

### 5-Fold Cross-Validation (Ensemble)

| Metric | Mean | ± Std |
|:-------|-----:|------:|
| F1 | ~0.92 | ±0.003 |
| ROC-AUC | ~0.97 | ±0.002 |
| Precision | ~0.92 | ±0.004 |
| Recall | ~0.91 | ±0.003 |

---

## 🎛 Configuration

All settings in `config.py`:

```python
N_PROFILES   = 50_000   # dataset size
BOT_RATIO    = 0.35     # class balance
TEST_SIZE    = 0.20     # hold-out fraction
CV_FOLDS     = 5

RF_PARAMS    = { "n_estimators": 500, ... }
HGB_PARAMS   = { "max_iter": 400, ...    }
ENSEMBLE_WEIGHTS = [2, 3, 1]   # RF : HGB : ET
```

---

## 🛠 Advanced Usage

### Re-run only cross-validation
```bash
python train.py --cv-only
```

### Train without plots (CI / headless servers)
```bash
python train.py --no-plots
```

### Skip CV for faster iteration
```bash
python train.py --no-cv
```

### Adjust decision threshold
```bash
python predict.py --input profiles.csv --threshold 0.45
```

---

## 📁 Generated Artefacts

After training, `reports/` will contain:

| File | Description |
|:-----|:------------|
| `evaluation_report.md` | Full Markdown summary |
| `roc_curves.png` | Overlaid ROC curves for all models |
| `pr_curves.png` | Precision-Recall curves |
| `feature_importance.png` | Top-20 feature importances |
| `confusion_matrix_ensemble.png` | Confusion matrix |
| `calibration.png` | Reliability diagram |
| `test_metrics.json` | Machine-readable metrics |
| `cv_results.json` | Cross-validation scores |

---

## 🔄 Extending to Real Twitter Data

To run this pipeline on real data (e.g. via the Twitter v2 API or the
[Botometer dataset](https://botometer.osome.iu.edu/)):

1. Fetch profiles and map fields to the column names used here
   (see `src/feature_engineering.py → FEATURE_CATALOG`).
2. Pre-compute `content_similarity` using TF-IDF cosine similarity on
   sampled tweet text.
3. Compute `network_clustering_coef` using NetworkX on the follower graph.
4. Drop the `user_id` column and run `predict.py`.

---

## 📚 References

- Varol et al. (2017) — *Online Human-Bot Interactions: Detection, Estimation, and Characterization* (ICWSM)
- Cresci et al. (2017) — *The Paradigm-Shift of Social Spambots*
- Kudugunta & Ferrara (2018) — *Deep Neural Networks for Bot Detection*
- Scikit-learn documentation: Ensemble Methods, Calibration

---

## 🪪 License

MIT © 2026
