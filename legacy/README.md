# Legacy synthetic profile benchmark

The historical classifier here predicts labels produced by its synthetic account generator. The generator assigns many feature distributions using the label, including network and content signals. Metrics describe that synthetic benchmark only. Signal Desk and its Bluesky investigations have no dependency on this code.

From this directory, run `python -m pip install -r requirements.txt` and `python train.py --no-cv --no-plots`. Training regenerates the original seeded data if the CSV is absent. Historical files remain in Git history.

A machine learning project for classifying fake or automated social media profiles using account, activity, content, temporal, and network-related features.

## Features

- Generates synthetic profile data for training and testing
- Cleans and preprocesses profile-level data
- Engineers features for bot detection
- Trains multiple tree-based classification models
- Evaluates model performance using common classification metrics
- Supports prediction on new profile data

## Project Structure

```bash
fake_bot_detection/
├── config.py
├── train.py
├── predict.py
├── requirements.txt
├── data/
│   ├── generate_data.py
│   ├── raw/
│   └── processed/
├── src/
│   ├── data_preprocessing.py
│   ├── feature_engineering.py
│   ├── models.py
│   ├── evaluate.py
│   └── utils.py
├── models/
├── reports/
└── logs/
```

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Train the models

```bash
python train.py
```

### Predict on a CSV file

```bash
python predict.py --input data/raw/profiles.csv --output results.csv
```

### Predict a single profile

```bash
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

## Models Used

- Random Forest
- HistGradientBoosting
- Extra Trees
- Voting Ensemble

## Feature Groups

The project includes features from several categories:

- **Account metadata**
- **Activity and posting behavior**
- **Content-based signals**
- **Temporal patterns**
- **Network-related features**
- **Derived interaction features**

Examples include:

- `followers_to_following_ratio`
- `tweet_frequency`
- `engagement_velocity`
- `duplicate_tweet_ratio`
- `posting_time_entropy`
- `bot_neighbor_ratio`

## Evaluation

The training pipeline evaluates models using:

- F1 Score
- Precision
- Recall
- ROC-AUC
- Cross-validation

Generated evaluation plots and reports are saved in the `reports/` directory.

## Tech Stack

- Python
- Pandas
- NumPy
- Scikit-learn
- Matplotlib / Seaborn
- NetworkX
- Joblib

## Notes

- This project uses **synthetic data** generated locally.
- It is designed as a machine learning pipeline project and can be extended to real-world social media datasets.

## License

MIT
