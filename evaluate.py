"""
src/evaluate.py
---------------
Comprehensive evaluation utilities:
  - quick_eval()      : one-liner metrics print during training
  - full_evaluation() : detailed classification report + confusion matrix
  - cross_val_report(): stratified k-fold cross-validation summary
  - plot_roc()        : ROC curve saved to reports/
  - plot_confusion_matrix()
  - plot_feature_importance()
  - calibration_plot()
  - generate_report() : writes a full Markdown evaluation report
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")        # headless / CI-safe backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
    average_precision_score,
    precision_recall_curve,
)
from sklearn.calibration import calibration_curve
from sklearn.model_selection import StratifiedKFold, cross_validate

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
import config

log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _ensure_reports():
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _predict(model, X: np.ndarray):
    """Returns (y_pred, y_prob) handling models without predict_proba."""
    y_pred = model.predict(X)
    try:
        y_prob = model.predict_proba(X)[:, 1]
    except AttributeError:
        y_prob = y_pred.astype(float)
    return y_pred, y_prob


# ────────────────────────────────────────────────────────────────────────────
# Core metrics
# ────────────────────────────────────────────────────────────────────────────

def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: Optional[np.ndarray] = None,
) -> Dict[str, float]:
    """Returns a flat dict of all relevant classification metrics."""
    metrics: Dict[str, float] = {
        "accuracy"  : round(accuracy_score(y_true, y_pred), 4),
        "precision" : round(precision_score(y_true, y_pred, zero_division=0), 4),
        "recall"    : round(recall_score(y_true, y_pred, zero_division=0), 4),
        "f1"        : round(f1_score(y_true, y_pred, zero_division=0), 4),
        "f1_macro"  : round(f1_score(y_true, y_pred, average="macro", zero_division=0), 4),
    }
    if y_prob is not None:
        metrics["roc_auc"]  = round(roc_auc_score(y_true, y_prob), 4)
        metrics["pr_auc"]   = round(average_precision_score(y_true, y_prob), 4)
    return metrics


def quick_eval(
    model,
    X    : np.ndarray,
    y    : np.ndarray,
    label: str = "Model",
) -> Dict[str, float]:
    """Lightweight one-liner print + return metrics dict."""
    y_pred, y_prob = _predict(model, X)
    m = compute_metrics(y, y_pred, y_prob)
    print(
        f"  [{label}]  "
        f"F1={m['f1']:.4f}  "
        f"ROC-AUC={m.get('roc_auc', 0):.4f}  "
        f"Precision={m['precision']:.4f}  "
        f"Recall={m['recall']:.4f}"
    )
    return m


def full_evaluation(
    model,
    X    : np.ndarray,
    y    : np.ndarray,
    label: str = "Model",
) -> Dict[str, Any]:
    """
    Detailed evaluation: classification report, confusion matrix, all metrics.
    """
    y_pred, y_prob = _predict(model, X)
    metrics = compute_metrics(y, y_pred, y_prob)

    cm = confusion_matrix(y, y_pred)
    tn, fp, fn, tp = cm.ravel()

    report = {
        "label"             : label,
        "metrics"           : metrics,
        "confusion_matrix"  : cm.tolist(),
        "TP"                : int(tp),
        "FP"                : int(fp),
        "TN"                : int(tn),
        "FN"                : int(fn),
        "false_positive_rate": round(fp / (fp + tn + 1e-9), 4),
        "false_negative_rate": round(fn / (fn + tp + 1e-9), 4),
    }

    print(f"\n{'═'*60}")
    print(f"  {label} — Full Evaluation")
    print(f"{'─'*60}")
    print(classification_report(y, y_pred, target_names=["Human", "Bot"]))
    print(f"  Confusion Matrix:\n{cm}")
    print(f"  ROC-AUC : {metrics.get('roc_auc', 'N/A')}")
    print(f"  PR-AUC  : {metrics.get('pr_auc',  'N/A')}")
    print(f"{'═'*60}\n")

    return report


# ────────────────────────────────────────────────────────────────────────────
# Cross-validation
# ────────────────────────────────────────────────────────────────────────────

def cross_val_report(
    model,
    X    : np.ndarray,
    y    : np.ndarray,
    label: str = "Model",
    n_folds: int = config.CV_FOLDS,
) -> Dict[str, float]:
    """Runs stratified k-fold CV and prints mean ± std for each metric."""
    log.info("Running %d-fold CV for %s …", n_folds, label)
    cv = StratifiedKFold(n_splits=n_folds, shuffle=True,
                         random_state=config.RANDOM_SEED)

    scoring = ["f1", "roc_auc", "precision", "recall", "accuracy"]
    results = cross_validate(model, X, y, cv=cv, scoring=scoring,
                             n_jobs=-1, return_train_score=False)

    summary = {}
    print(f"\n  {label} — {n_folds}-Fold Stratified CV")
    print(f"  {'Metric':<20} {'Mean':>8} {'Std':>8}")
    print(f"  {'─'*38}")
    for metric in scoring:
        key     = f"test_{metric}"
        mean_   = float(np.mean(results[key]))
        std_    = float(np.std(results[key]))
        summary[f"{metric}_mean"] = round(mean_, 4)
        summary[f"{metric}_std"]  = round(std_,  4)
        print(f"  {metric:<20} {mean_:>8.4f} ±{std_:>6.4f}")

    return summary


# ────────────────────────────────────────────────────────────────────────────
# Plots
# ────────────────────────────────────────────────────────────────────────────

PLOT_STYLE = {
    "figure.facecolor": "#0d1117",
    "axes.facecolor"  : "#161b22",
    "axes.edgecolor"  : "#30363d",
    "axes.labelcolor" : "#c9d1d9",
    "xtick.color"     : "#8b949e",
    "ytick.color"     : "#8b949e",
    "text.color"      : "#c9d1d9",
    "grid.color"      : "#21262d",
    "grid.linestyle"  : "--",
    "grid.alpha"      : 0.5,
    "font.family"     : "monospace",
}


def plot_roc(
    models_dict : Dict[str, Any],
    X           : np.ndarray,
    y           : np.ndarray,
    save        : bool = True,
) -> plt.Figure:
    """Overlays ROC curves for each model in models_dict."""
    _ensure_reports()
    plt.rcParams.update(PLOT_STYLE)
    fig, ax = plt.subplots(figsize=(7, 6))

    colors = ["#58a6ff", "#3fb950", "#f78166", "#d2a8ff", "#ffa657"]
    for (name, model), color in zip(models_dict.items(), colors):
        _, y_prob = _predict(model, X)
        fpr, tpr, _ = roc_curve(y, y_prob)
        auc = roc_auc_score(y, y_prob)
        ax.plot(fpr, tpr, color=color, lw=2,
                label=f"{name} (AUC = {auc:.4f})")

    ax.plot([0, 1], [0, 1], ":", color="#6e7681", lw=1)
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("ROC Curves — Bot Detection Ensemble")
    ax.legend(framealpha=0.15)
    ax.grid(True)

    if save:
        path = config.REPORTS_DIR / "roc_curves.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        log.info("Saved → %s", path)
    return fig


def plot_precision_recall(
    models_dict : Dict[str, Any],
    X           : np.ndarray,
    y           : np.ndarray,
    save        : bool = True,
) -> plt.Figure:
    """PR curves — more informative than ROC for imbalanced datasets."""
    _ensure_reports()
    plt.rcParams.update(PLOT_STYLE)
    fig, ax = plt.subplots(figsize=(7, 6))

    colors = ["#58a6ff", "#3fb950", "#f78166", "#d2a8ff", "#ffa657"]
    for (name, model), color in zip(models_dict.items(), colors):
        _, y_prob = _predict(model, X)
        prec, rec, _ = precision_recall_curve(y, y_prob)
        ap = average_precision_score(y, y_prob)
        ax.plot(rec, prec, color=color, lw=2,
                label=f"{name} (AP = {ap:.4f})")

    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-Recall Curves — Bot Detection Ensemble")
    ax.legend(framealpha=0.15)
    ax.grid(True)

    if save:
        path = config.REPORTS_DIR / "pr_curves.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        log.info("Saved → %s", path)
    return fig


def plot_confusion_matrix(
    model,
    X    : np.ndarray,
    y    : np.ndarray,
    label: str = "Ensemble",
    save : bool = True,
) -> plt.Figure:
    _ensure_reports()
    plt.rcParams.update(PLOT_STYLE)

    y_pred, _ = _predict(model, X)
    cm = confusion_matrix(y, y_pred)

    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(cm, cmap="Blues")
    plt.colorbar(im, ax=ax)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["Human", "Bot"])
    ax.set_yticks([0, 1]); ax.set_yticklabels(["Human", "Bot"])
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
    ax.set_title(f"Confusion Matrix — {label}")

    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{cm[i,j]:,}", ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "#c9d1d9",
                    fontsize=13, fontweight="bold")

    if save:
        path = config.REPORTS_DIR / f"confusion_matrix_{label.lower().replace(' ','_')}.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        log.info("Saved → %s", path)
    return fig


def plot_feature_importance(
    model,
    feature_names: List[str],
    top_n : int  = 20,
    label : str  = "Random Forest",
    save  : bool = True,
) -> plt.Figure:
    _ensure_reports()
    plt.rcParams.update(PLOT_STYLE)

    importances = model.feature_importances_
    indices     = np.argsort(importances)[::-1][:top_n]
    names       = [feature_names[i] for i in indices]
    vals        = importances[indices]

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.barh(range(top_n), vals[::-1],
                   color=["#58a6ff"] * top_n, alpha=0.85)
    ax.set_yticks(range(top_n))
    ax.set_yticklabels(names[::-1], fontsize=9)
    ax.set_xlabel("Mean Decrease in Impurity")
    ax.set_title(f"Top-{top_n} Feature Importances — {label}")
    ax.grid(axis="x")

    if save:
        path = config.REPORTS_DIR / "feature_importance.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        log.info("Saved → %s", path)
    return fig


def plot_calibration(
    models_dict : Dict[str, Any],
    X           : np.ndarray,
    y           : np.ndarray,
    save        : bool = True,
) -> plt.Figure:
    """Reliability diagram — checks if predicted probabilities are trustworthy."""
    _ensure_reports()
    plt.rcParams.update(PLOT_STYLE)
    fig, ax = plt.subplots(figsize=(6, 5))

    ax.plot([0, 1], [0, 1], ":", color="#6e7681", lw=1, label="Perfect")
    colors = ["#58a6ff", "#3fb950", "#f78166", "#d2a8ff"]
    for (name, model), color in zip(models_dict.items(), colors):
        _, y_prob = _predict(model, X)
        prob_true, prob_pred = calibration_curve(y, y_prob, n_bins=15)
        ax.plot(prob_pred, prob_true, "s-", color=color, lw=1.5,
                markersize=4, label=name)

    ax.set_xlabel("Mean Predicted Probability")
    ax.set_ylabel("Fraction of Positives")
    ax.set_title("Calibration Plot — Predicted vs Actual Bot Probability")
    ax.legend(framealpha=0.15)
    ax.grid(True)

    if save:
        path = config.REPORTS_DIR / "calibration.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        log.info("Saved → %s", path)
    return fig


# ────────────────────────────────────────────────────────────────────────────
# Markdown report
# ────────────────────────────────────────────────────────────────────────────

def generate_report(
    eval_results    : List[Dict],
    cv_results      : Optional[Dict] = None,
    feature_count   : int = 0,
    n_profiles      : int = 0,
) -> Path:
    """Writes a Markdown evaluation report to config.REPORTS_DIR."""
    _ensure_reports()
    path = config.REPORTS_DIR / "evaluation_report.md"

    lines = [
        "# Fake / Bot Profile Detection — Evaluation Report",
        "",
        f"**Dataset**: {n_profiles:,} Twitter profiles  "
        f"| **Features**: {feature_count}",
        "",
        "---",
        "",
        "## Model Comparison (Test Set)",
        "",
        "| Model | F1 | ROC-AUC | Precision | Recall | PR-AUC |",
        "|:------|---:|--------:|----------:|-------:|-------:|",
    ]

    for r in eval_results:
        m = r["metrics"]
        lines.append(
            f"| {r['label']} "
            f"| {m['f1']:.4f} "
            f"| {m.get('roc_auc','—')!s:>8} "
            f"| {m['precision']:.4f} "
            f"| {m['recall']:.4f} "
            f"| {m.get('pr_auc','—')!s:>7} |"
        )

    if cv_results:
        lines += [
            "",
            "---",
            "",
            "## Cross-Validation Summary (Ensemble, 5-Fold Stratified)",
            "",
            "| Metric | Mean | Std |",
            "|:-------|-----:|----:|",
        ]
        for metric in ["f1", "roc_auc", "precision", "recall", "accuracy"]:
            mean_ = cv_results.get(f"{metric}_mean", "—")
            std_  = cv_results.get(f"{metric}_std",  "—")
            lines.append(f"| {metric} | {mean_} | ±{std_} |")

    lines += [
        "",
        "---",
        "",
        "## Artefacts",
        "",
        "| File | Description |",
        "|:-----|:------------|",
        "| `reports/roc_curves.png` | ROC curves for all models |",
        "| `reports/pr_curves.png` | Precision-Recall curves |",
        "| `reports/feature_importance.png` | Top-20 feature importances |",
        "| `reports/calibration.png` | Reliability diagram |",
        "| `reports/confusion_matrix_*.png` | Per-model confusion matrices |",
        "",
    ]

    path.write_text("\n".join(lines))
    log.info("Evaluation report → %s", path)
    return path
