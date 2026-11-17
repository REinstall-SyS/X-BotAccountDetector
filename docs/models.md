# Research datasets and model artifacts

| Source | Intended evaluation | Current status |
| --- | --- | --- |
| Legacy generated X-style profiles | Synthetic profile classification | Reproducible from the preserved generator |
| Deterministic Signal Desk scenario | Integration and detector behavior | Included |
| Public Bluesky Jetstream | Unsupervised investigation and coverage monitoring | Supported live |
| Reviewer decisions | Group-level alert evaluation | Available by watchlist source |
| TwiBot-22 | Historical Twitter account classification | Adapter and training command ready for approved data |

The TwiBot-22 maintainers require a dataset access request from an institutional email, with affiliation and intended use. Follow their terms and do not redistribute the underlying records. Point the command at the downloaded directory containing `label.csv`, `split.csv`, and the top-level array `user.json`. The adapter preserves the official train, validation and test partitions, checks uniqueness and coverage of account IDs, and validates both classes in each split. Features use the documented Twitter public profile metrics. Retain file hashes and the release identifier when writing an experiment report. [Official TwiBot-22 repository](https://github.com/LuoUndergradXJTU/TwiBot-22)

```sh
python -m pip install -r requirements-ml.txt
python -m integrity.research /path/to/twibot22 --dataset-version maintainer-release-id --approved-access
```

Only training data determine imputation and base model parameters. The validation partition fits sigmoid calibration for XGBoost. The held-out test partition reports precision, recall, F1, average precision (PR-AUC summary), confusion matrix, and follower-count slices. The simple rule and Isolation Forest share the same held-out evaluation. The Isolation Forest anomaly scores are uncalibrated. TreeSHAP summarizes contributions to the uncalibrated XGBoost margin on a seeded test subset. The joblib artifact is for trusted local research use. Its report contains the dataset hashes, feature schema and ordering, training configuration, runtime versions, and artifact digest. Use a unique `--output` directory to preserve each run. MLflow logs the run configuration, XGBoost metrics and associated artifacts. The Model Lab reads `artifacts/twibot22/report.json` by default or the path set by `INTEGRITY_MODEL_REPORT`.

The historical classifier uses features unavailable from Jetstream and several features driven directly by the synthetic label. Its preprocessing also computes clipping and imputation statistics before splitting. Preserve those limitations when interpreting the legacy results. The legacy model and the live coordination detector answer different tasks and cannot share a performance leaderboard with the TwiBot account classifiers.

The Bluesky path uses `coordination-v1` and never loads a supervised Twitter model. Research compatibility checks require matching data platform, feature schema, feature ordering, and labeled provenance. Supervised use on Bluesky would require valid Bluesky labels and domain-specific calibration. The optional sentence encoder measures semantic similarity and does not classify accounts.
