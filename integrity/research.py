"""Offline TwiBot-22 account classification. This module is never imported by detection."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform

FEATURES = (
    "followers", "following", "posts", "listed", "name_length", "description_length",
    "followers_per_following",
)
FEATURE_SCHEMA = "twibot22-profile-v1"
SEED = 42


def file_digest(path):
    with path.open("rb") as stream:
        return sha256_stream(stream)


def sha256_stream(stream):
    digest = sha256()
    while block := stream.read(1024 * 1024):
        digest.update(block)
    return digest.hexdigest()


def require_compatible(manifest, platform_name, feature_schema, columns):
    if (
        manifest.get("platform") != platform_name
        or manifest.get("feature_schema") != feature_schema
        or manifest.get("features") != list(columns)
        or manifest.get("evaluation_kind") != "labeled_research"
    ):
        raise ValueError("Model platform, feature schema, feature order, or evaluation provenance is incompatible")


def split_integrity(labels, splits):
    expected = {"train", "valid", "test"}
    if labels["id"].duplicated().any() or splits["id"].duplicated().any():
        raise ValueError("Duplicate IDs can leak accounts across splits")
    if set(splits["split"]) != expected or set(labels["label"]) != {"human", "bot"}:
        raise ValueError("Expected official train/valid/test splits and human/bot labels")
    if set(splits["id"]) != set(labels["id"]):
        raise ValueError("Split IDs and label IDs differ")
    return splits.merge(labels, on="id", validate="one_to_one")


def profile(user):
    metrics = user.get("public_metrics") or {}
    counts = {key: metrics.get(source) for key, source in {
        "followers": "followers_count", "following": "following_count", "posts": "tweet_count", "listed": "listed_count",
    }.items()}
    counts = {key: value if isinstance(value, int) and value >= 0 else None for key, value in counts.items()}
    follower, following = counts["followers"], counts["following"]
    return {
        **counts,
        "name_length": len(user["username"]) if isinstance(user.get("username"), str) else None,
        "description_length": len(user["description"]) if isinstance(user.get("description"), str) else None,
        "followers_per_following": follower / (following + 1) if follower is not None and following is not None else None,
    }


def load_twibot(directory):
    import ijson
    import pandas as pd

    paths = {name: directory / name for name in ("label.csv", "split.csv", "user.json")}
    if not all(path.is_file() for path in paths.values()):
        raise FileNotFoundError("Approved TwiBot-22 download must contain label.csv, split.csv, and user.json")
    labels = pd.read_csv(paths["label.csv"], dtype=str, keep_default_na=False)
    splits = pd.read_csv(paths["split.csv"], dtype=str, keep_default_na=False)
    index = split_integrity(labels, splits).set_index("id")
    records = {}
    with paths["user.json"].open("rb") as source:
        for user in ijson.items(source, "item"):
            uid = user.get("id")
            if uid not in index.index:
                continue
            if uid in records:
                raise ValueError("Duplicate account in user.json")
            records[uid] = profile(user)
    if len(records) != len(index):
        raise ValueError(f"Missing profiles for {len(index) - len(records)} labeled accounts")
    frame = index.join(pd.DataFrame.from_dict(records, orient="index"), validate="one_to_one")
    for name, partition in frame.groupby("split"):
        if set(partition["label"]) != {"human", "bot"}:
            raise ValueError(f"Split {name} does not contain both classes")
    train = frame.loc[frame.split == "train", list(FEATURES)]
    if train.isna().all().any():
        raise ValueError("At least one requested feature is absent in the entire training split")
    return frame, {name: file_digest(path) for name, path in paths.items()}


def classification_metrics(truth, scores, decision, calibrated_probability=False):
    from sklearn.metrics import average_precision_score, brier_score_loss, confusion_matrix, precision_recall_fscore_support

    p, r, f, _ = precision_recall_fscore_support(truth, decision, average="binary", zero_division=0)
    return {
        "n": len(truth), "positives": int(truth.sum()), "precision": float(p),
        "recall": float(r), "f1": float(f),
        "pr_auc": float(average_precision_score(truth, scores)) if len(set(truth)) == 2 else None,
        "confusion": confusion_matrix(truth, decision, labels=[0, 1]).tolist(),
        "brier": float(brier_score_loss(truth, scores)) if calibrated_probability else None,
    }


def train(directory, dataset_version, output, tracking_uri):
    import joblib
    import mlflow
    import numpy as np
    import sklearn
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import IsolationForest
    from sklearn.frozen import FrozenEstimator
    from sklearn.impute import SimpleImputer
    import shap
    import xgboost

    frame, dataset_hashes = load_twibot(directory)
    parts = {name: chunk for name, chunk in frame.groupby("split", sort=True)}
    data = {name: chunk.loc[:, list(FEATURES)].astype(float) for name, chunk in parts.items()}
    labels = {name: (chunk.label == "bot").astype(int) for name, chunk in parts.items()}
    imputer = SimpleImputer(strategy="median").fit(data["train"])
    x = {name: imputer.transform(chunk) for name, chunk in data.items()}
    options = {"n_estimators": 220, "max_depth": 4, "learning_rate": 0.06, "tree_method": "hist", "n_jobs": 2, "random_state": SEED}
    model = xgboost.XGBClassifier(**options).fit(x["train"], labels["train"])
    calibration = CalibratedClassifierCV(FrozenEstimator(model), method="sigmoid").fit(x["valid"], labels["valid"])
    anomaly = IsolationForest(n_estimators=120, contamination=0.1, n_jobs=2, random_state=SEED).fit(x["train"])
    scores = {
        "Rule baseline": ((x["test"][:, 1] >= 1000) & (x["test"][:, 6] < 0.1)).astype(float),
        "Isolation Forest": -anomaly.decision_function(x["test"]),
        "Calibrated XGBoost": calibration.predict_proba(x["test"])[:, 1],
    }
    masks = {
        "followers_missing": data["test"]["followers"].isna(),
        "followers_0_to_99": data["test"]["followers"] < 100,
        "followers_100_plus": data["test"]["followers"] >= 100,
    }
    experiments = {}
    for name, values in scores.items():
        is_calibrated = name == "Calibrated XGBoost"
        threshold = 0 if name == "Isolation Forest" else 0.5
        decision = values > 0 if name == "Isolation Forest" else values >= threshold
        experiments[name] = classification_metrics(labels["test"], values, decision, is_calibrated)
        experiments[name]["slices"] = {
            slice_name: classification_metrics(labels["test"][mask], values[mask], decision[mask], is_calibrated)
            for slice_name, mask in masks.items() if mask.any()
        }
    sample = np.random.default_rng(SEED).choice(len(x["test"]), min(256, len(x["test"])), replace=False)
    contributions = shap.TreeExplainer(model)(x["test"][sample]).values
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / "twibot22-xgboost.joblib"
    joblib.dump({"imputer": imputer, "model": calibration}, artifact)
    run_version = file_digest(artifact)
    report = {
        "dataset": "TwiBot-22", "dataset_version": dataset_version, "dataset_hashes": dataset_hashes,
        "version": run_version[:12], "platform": "twitter", "feature_schema": FEATURE_SCHEMA,
        "features": list(FEATURES), "evaluation_kind": "labeled_research",
        "split_sizes": {name: len(chunk) for name, chunk in parts.items()},
        "seed": SEED, "parameters": options,
        "runtime": {"python": platform.python_version(), "sklearn": sklearn.__version__, "xgboost": xgboost.__version__},
        "artifact_sha256": run_version,
        "experiments": experiments,
        "shap_mean_absolute": dict(zip(FEATURES, np.abs(contributions).mean(axis=0).tolist())),
        "shap_target": "Uncalibrated XGBoost log-odds on a deterministic test sample",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("twibot22-profile-research")
    with mlflow.start_run(run_name=report["version"]):
        mlflow.log_params({"dataset_version": dataset_version, "schema": FEATURE_SCHEMA, "seed": SEED, **options})
        mlflow.log_metrics({f"xgb_{key}": experiments["Calibrated XGBoost"][key] for key in ("precision", "recall", "f1", "pr_auc")})
        mlflow.log_artifacts(str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/twibot22"))
    parser.add_argument("--tracking-uri", default="sqlite:///artifacts/mlflow.db")
    parser.add_argument("--approved-access", action="store_true", help="Confirm you obtained the dataset under its applicable terms")
    args = parser.parse_args()
    if not args.approved_access:
        parser.error("Obtain authorized dataset access and pass --approved-access")
    train(args.directory, args.dataset_version, args.output, args.tracking_uri)


if __name__ == "__main__":
    main()
