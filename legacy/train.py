"""
train.py
--------
Orchestrates the full training pipeline:

  1. Generate synthetic data (if not already present)
  2. Preprocess & engineer features
  3. Run variance / correlation audits
  4. Train RF, HGB, ExtraTrees, and the soft-voting Ensemble
  5. Evaluate on held-out test set
  6. Run 5-fold cross-validation on the ensemble
  7. Report fixed-threshold results
  8. Save all models + artefacts + Markdown report

Usage
-----
    python train.py               # full run
    python train.py --no-plots    # skip matplotlib (CI / headless)
    python train.py --cv-only     # only re-run CV (assumes models exist)
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

# ── project imports ─────────────────────────────────────────────────────────
import config
from src.utils              import setup_logging, set_seed, timer, save_json
from src.data_preprocessing import load_and_preprocess
from src.feature_engineering import (
    variance_audit, correlation_audit, print_catalog, FEATURE_CATALOG
)
from src.models import (
    build_random_forest, build_ensemble,
    train_all, save_all, feature_importance_df
)
from src.evaluate import (
    full_evaluation, cross_val_report, generate_report,
    plot_roc, plot_precision_recall,
    plot_confusion_matrix, plot_feature_importance, plot_calibration,
    quick_eval,
)

# ── silence noisy sub-loggers ────────────────────────────────────────────────
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)


def parse_args():
    p = argparse.ArgumentParser(description="Train bot detection models")
    p.add_argument("--no-plots",  action="store_true", help="Skip all matplotlib plots")
    p.add_argument("--cv-only",   action="store_true", help="Only run cross-validation")
    p.add_argument("--no-cv",     action="store_true", help="Skip cross-validation (faster)")
    return p.parse_args()


# ────────────────────────────────────────────────────────────────────────────
# Step 1: data
# ────────────────────────────────────────────────────────────────────────────

def ensure_data() -> None:
    raw_path = config.RAW_DIR / "profiles.csv"
    if not raw_path.exists():
        log.info("Raw data not found — generating …")
        from data.generate_data import generate_profiles
        df = generate_profiles()
        df.to_csv(raw_path, index=False)
        log.info("Generated %d profiles → %s", len(df), raw_path)
    else:
        log.info("Raw data found → %s", raw_path)


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    log = setup_logging()
    set_seed(config.RANDOM_SEED)

    print("\n" + "═"*65)
    print("  Legacy synthetic benchmark — generated profiles only")
    print("═"*65 + "\n")

    # ── 1. Generate or locate data ───────────────────────────────────────────
    with timer("Data generation / check"):
        ensure_data()

    # ── 2. Preprocess ────────────────────────────────────────────────────────
    with timer("Preprocessing"):
        data = load_and_preprocess()

    X_train = data["X_train"]
    X_val   = data["X_val"]
    X_test  = data["X_test"]
    y_train = data["y_train"]
    y_val   = data["y_val"]
    y_test  = data["y_test"]
    feat_names = data["feature_names"]
    df_clean   = data["df_clean"]

    print(f"\n  Profiles  : {len(y_train)+len(y_val)+len(y_test):,}")
    print(f"  Features  : {len(feat_names)}")
    print(f"  Bot ratio : {(y_train.mean()):.1%} (train)")
    print()

    # ── 3. Feature catalog & audits ─────────────────────────────────────────
    print_catalog()
    low_var = variance_audit(df_clean)
    hi_cor  = correlation_audit(df_clean)
    if low_var:
        print(f"  ⚠  Low-variance features: {low_var}")
    if hi_cor:
        print(f"  ⚠  High-correlation pairs: {[p[:2] for p in hi_cor]}")

    if args.cv_only:
        from src.models import load_model
        log.info("--cv-only flag: loading saved ensemble …")
        ensemble = load_model("ensemble")
        X_all = np.vstack([X_train, X_val])
        y_all = np.concatenate([y_train, y_val])
        cv_res = cross_val_report(
            build_ensemble(calibrate=False), X_all, y_all, "Ensemble (CV)"
        )
        save_json(cv_res, config.REPORTS_DIR / "cv_results.json")
        return

    # ── 4. Train ─────────────────────────────────────────────────────────────
    print("\n" + "─"*65)
    print("  Training base learners & ensemble …")
    print("─"*65)
    with timer("Model training"):
        models = train_all(X_train, y_train, X_val, y_val, feat_names)

    # ── 5. Test-set evaluation ───────────────────────────────────────────────
    print("\n" + "─"*65)
    print("  Test-Set Evaluation")
    print("─"*65)
    eval_results = []
    for name, model in models.items():
        label = name.replace("_", " ").title()
        result = full_evaluation(model, X_test, y_test, label=label)
        eval_results.append(result)

    # ── 6. Fixed decision threshold ───────────────────────────────────────────
    ensemble = models["ensemble"]
    print("\n  Evaluation uses the fixed classifier threshold (0.50).")

    # ── 7. Cross-validation ──────────────────────────────────────────────────
    cv_res = None
    if not args.no_cv:
        print("\n" + "─"*65)
        print("  5-Fold Cross-Validation (Ensemble, no calibration wrapper)")
        print("─"*65)
        X_all = np.vstack([X_train, X_val])
        y_all = np.concatenate([y_train, y_val])
        # use uncalibrated ensemble for speed in CV
        cv_model = build_ensemble(calibrate=False)
        with timer("Cross-validation"):
            cv_res = cross_val_report(cv_model, X_all, y_all, "Ensemble")
        save_json(cv_res, config.REPORTS_DIR / "cv_results.json")

    # ── 8. Feature importance ────────────────────────────────────────────────
    fi_df = feature_importance_df(models["random_forest"], feat_names)
    fi_path = config.REPORTS_DIR / "feature_importance.csv"
    fi_df.to_csv(fi_path, index=False)
    print("\n  Top-10 Feature Importances (Random Forest):")
    print(fi_df.head(10).to_string(index=False))

    # ── 9. Save models ───────────────────────────────────────────────────────
    save_all(models)
    save_json(
        {name: r["metrics"] for name, r in zip(models.keys(), eval_results)},
        config.REPORTS_DIR / "test_metrics.json",
    )

    # ── 10. Plots ─────────────────────────────────────────────────────────────
    if not args.no_plots:
        print("\n  Generating plots …")
        try:
            plot_roc(models, X_test, y_test)
            plot_precision_recall(models, X_test, y_test)
            plot_confusion_matrix(ensemble, X_test, y_test, label="Ensemble")
            plot_feature_importance(
                models["random_forest"], feat_names,
                top_n=20, label="Random Forest"
            )
            plot_calibration(models, X_test, y_test)
            print("  Plots saved → reports/")
        except Exception as e:
            log.warning("Plot generation failed: %s", e)

    # ── 11. Markdown report ───────────────────────────────────────────────────
    report_path = generate_report(
        eval_results,
        cv_results      = cv_res,
        feature_count   = len(feat_names),
        n_profiles      = len(y_train) + len(y_val) + len(y_test),
    )
    print(f"\n  Report → {report_path}")

    # ── Summary banner ────────────────────────────────────────────────────────
    ens_metrics = eval_results[-1]["metrics"]   # ensemble is last
    print("\n" + "═"*65)
    print("  ✅  Training complete!")
    print(f"  Synthetic ensemble F1: {ens_metrics['f1']:.4f}")
    print(f"  Ensemble ROC-AUC   : {ens_metrics.get('roc_auc','—')}")
    print(f"  Ensemble PR-AUC    : {ens_metrics.get('pr_auc', '—')}")
    print("  Results describe only the synthetic generator.")
    print("═"*65 + "\n")


if __name__ == "__main__":
    log = logging.getLogger(__name__)
    main()
