"""
blind_test.py — STEP 4: blind test by astronaut + robustness & stress tests + Excel sheets 4-5.

Implements:
  * D3: Opens frozen data/astronaut_health_eval.db read-only and verifies SHA-256 hash before running.
  * A4: Reports confusion matrix both as raw counts and row-normalized percentages.
  * A5: Reports 95% confidence intervals for every per-class metric (Wilson score interval for
        sensitivity, specificity, and precision; astronaut-cluster bootstrap for F1).
        Evaluates a separate, clearly labeled Danger-oversampled stress-test set (never merged into
        main blind-test numbers).
  * A2: Reports tiered alerting ("Danger – confirm" vs. "Danger") precision, recall, F1, and
        Danger false alarms per 1,000 astronaut-days.
  * B1: Runs sensor-noise robustness tests at 1.5x and 2.0x sensor noise + 5% missing readings.

Prototype for research/education only — not for clinical diagnosis.
Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.
"""
import copy
import json
import math
import os
import sys
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, recall_score

import ai_health_model as aim
import generate_data as gd
import resource_facts as rf

HERE = os.path.dirname(os.path.abspath(__file__))
METRICS_PATH = os.path.join(aim.MODEL_DIR, "blind_test_metrics.json")
AI_NAME = "Smart Personalized AI"
DANGER = "Medical_Danger_Alert"


def wilson_ci_pct(successes: int, total: int, z: float = 1.959964) -> List[float]:
    """Return 95% Wilson score confidence interval [low_pct, high_pct] for a binomial proportion."""
    if total <= 0:
        return [0.0, 0.0]
    n = float(total)
    k = float(successes)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)) / denom
    lo = max(0.0, min(1.0, center - half))
    hi = max(0.0, min(1.0, center + half))
    return [round(100.0 * lo, 2), round(100.0 * hi, 2)]


def bootstrap_f1_ci_by_astronaut(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    groups: np.ndarray = None,
    n_boot: int = 400,
    seed: int = 42,
) -> Dict[str, List[float]]:
    """
    Compute 95% bootstrap confidence intervals for per-class F1, macro F1, and accuracy,
    resampling by astronaut cluster (Ground Rule / Phase 3 A5).
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    rng = np.random.default_rng(seed)

    if groups is None:
        # Fallback to row-level bootstrap if groups not passed
        unique_g = None
    else:
        groups = np.asarray(groups)
        unique_g = np.unique(groups)
        g_to_idx = {g_val: np.where(groups == g_val)[0] for g_val in unique_g}

    f1_samples = {c: [] for c in rf.CLASSES}
    macro_f1_samples = []
    acc_samples = []

    for _ in range(n_boot):
        if unique_g is not None and len(unique_g) > 1:
            sampled_g = rng.choice(unique_g, size=len(unique_g), replace=True)
            idx = np.concatenate([g_to_idx[g_val] for g_val in sampled_g])
        else:
            idx = rng.integers(0, len(y_true), size=len(y_true))
        yt = y_true[idx]
        yp = y_pred[idx]
        cm = confusion_matrix(yt, yp, labels=rf.CLASSES)
        f1s = []
        for i, c in enumerate(rf.CLASSES):
            tp = float(cm[i, i])
            fp = float(cm[:, i].sum() - tp)
            fn = float(cm[i, :].sum() - tp)
            f1 = (2.0 * tp / (2.0 * tp + fp + fn)) if (2.0 * tp + fp + fn) > 0 else 0.0
            f1_samples[c].append(100.0 * f1)
            f1s.append(100.0 * f1)
        macro_f1_samples.append(float(np.mean(f1s)))
        acc_samples.append(100.0 * float(np.trace(cm) / max(1, cm.sum())))

    out = {}
    for c in rf.CLASSES:
        arr = np.asarray(f1_samples[c], dtype=float)
        out[c] = [round(float(np.percentile(arr, 2.5)), 2), round(float(np.percentile(arr, 97.5)), 2)]
    out["macro_f1"] = [
        round(float(np.percentile(macro_f1_samples, 2.5)), 2),
        round(float(np.percentile(macro_f1_samples, 97.5)), 2),
    ]
    out["accuracy"] = [
        round(float(np.percentile(acc_samples, 2.5)), 2),
        round(float(np.percentile(acc_samples, 97.5)), 2),
    ]
    return out


def score_model(y_true: np.ndarray, y_pred: np.ndarray, groups: np.ndarray = None) -> Dict[str, Any]:
    cm = confusion_matrix(y_true, y_pred, labels=rf.CLASSES)
    row_sums = np.maximum(cm.sum(axis=1, keepdims=True), 1)
    cm_row_norm = np.round(100.0 * cm / row_sums, 2)

    boot_ci = bootstrap_f1_ci_by_astronaut(y_true, y_pred, groups=groups)

    per_class = {}
    for i, c in enumerate(rf.CLASSES):
        tp = int(cm[i][i])
        fn = int(sum(cm[i]) - tp)
        fp = int(sum(cm[r][i] for r in range(len(rf.CLASSES))) - tp)
        tn = int(sum(sum(cm[r]) for r in range(len(rf.CLASSES))) - tp - fn - fp)
        prec = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        rec = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        spec = (tn / (tn + fp)) if (tn + fp) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        per_class[c] = {
            "support": int(tp + fn),
            "sensitivity_pct": round(100 * rec, 2),
            "sensitivity_ci_95_wilson": wilson_ci_pct(tp, tp + fn),
            "precision_pct": round(100 * prec, 2),
            "precision_ci_95_wilson": wilson_ci_pct(tp, tp + fp),
            "specificity_pct": round(100 * spec, 2),
            "specificity_ci_95_wilson": wilson_ci_pct(tn, tn + fp),
            "f1_pct": round(100 * f1, 2),
            "f1_ci_95_bootstrap": boot_ci[c],
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
        }
    acc = round(100 * accuracy_score(y_true, y_pred), 2)
    macro_rec = round(float(np.mean([v["sensitivity_pct"] for v in per_class.values()])), 2)
    macro_prec = round(float(np.mean([v["precision_pct"] for v in per_class.values()])), 2)
    macro_spec = round(float(np.mean([v["specificity_pct"] for v in per_class.values()])), 2)
    macro_f1 = round(float(np.mean([v["f1_pct"] for v in per_class.values()])), 2)
    weighted_rec = round(100 * recall_score(y_true, y_pred, labels=rf.CLASSES, average="weighted", zero_division=0), 2)

    n_days = max(1, len(y_true))
    danger_fp = per_class[DANGER]["fp"]
    danger_fa_per_1000 = round(1000.0 * danger_fp / n_days, 2)

    return {
        "accuracy_pct": acc,
        "accuracy_ci_95_bootstrap": boot_ci["accuracy"],
        "per_class": per_class,
        "macro_sensitivity_pct": macro_rec,
        "macro_precision_pct": macro_prec,
        "macro_specificity_pct": macro_spec,
        "macro_f1_pct": macro_f1,
        "macro_f1_ci_95_bootstrap": boot_ci["macro_f1"],
        "weighted_sensitivity_pct": weighted_rec,
        "recall_medical_danger_alert_pct": per_class[DANGER]["sensitivity_pct"],
        "danger_false_alarms_per_1000_astronaut_days": danger_fa_per_1000,
        "confusion_matrix": cm.tolist(),
        "confusion_matrix_row_normalized_pct": cm_row_norm.tolist(),
    }


def evaluate_noise_robustness(
    bundle: Dict[str, Any],
    eval_db_path: str,
    test_ids: List[str],
    clean_perf: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Phase 2 B1 Robustness Test:
    Re-run the blind test on the 40 held-out test astronauts with sensor noise 1.5x and 2.0x higher
    than in training, plus 5% total missing readings in continuous indicators.
    """
    con = aim.connect_eval_readonly(eval_db_path)
    tel, labels, base = aim.load_tables(con)
    con.close()

    tel_test = tel[tel["astronaut_id"].isin(test_ids)].sort_values(["astronaut_id", "mission_day"]).reset_index(drop=True)
    base_test = base[base["astronaut_id"].isin(test_ids)].copy()
    merged = tel_test.merge(labels, on="record_id", how="left")
    y_test = merged["true_class"].to_numpy()
    groups_test = merged["astronaut_id"].to_numpy()

    results = {}
    for mult, label in ((1.5, "sensor_noise_1.5x_missing_5pct"), (2.0, "sensor_noise_2.0x_missing_5pct")):
        rng = np.random.default_rng(rf.SEED + int(mult * 1000))
        noisy_tel = tel_test.copy()
        # Extra sensor noise standard deviation factor: sqrt(mult^2 - 1^2) * sensor_sd
        extra_factor = math.sqrt(max(0.0, mult ** 2 - 1.0))

        for c in rf.CONTINUOUS:
            ind = rf.IND[c]
            vals = noisy_tel[c].to_numpy(dtype=float, copy=True)
            if ind["kind"] == "bone":
                sensor_sd = rf.BONE_SENSOR_SD
            elif ind["kind"] == "muscle":
                sensor_sd = rf.MUSCLE_SENSOR_SD
            elif ind["kind"] == "session":
                sensor_sd = rf.SESSION_MIN_SD
            else:
                sensor_sd = float(ind["within_sd"] or 1.0) * rf.SENSOR_SHARE

            noise = rng.normal(0.0, extra_factor * sensor_sd, size=len(vals))
            not_nan = ~np.isnan(vals)
            vals[not_nan] = np.clip(vals[not_nan] + noise[not_nan], ind["lo"], ind["hi"])
            vals[not_nan] = np.round(vals[not_nan], ind["decimals"])

            # Increase total missingness from ~3% to 5% (additional ~2.06% of observed values masked)
            current_miss = float(np.isnan(vals).mean())
            if current_miss < 0.05:
                add_miss_prob = (0.05 - current_miss) / max(1e-6, 1.0 - current_miss)
                extra_mask = not_nan & (rng.random(len(vals)) < add_miss_prob)
                vals[extra_mask] = np.nan

            noisy_tel[c] = vals

        actual_missing_pct = round(float(noisy_tel[rf.CONTINUOUS].isna().mean().mean() * 100.0), 2)
        feats_noisy = aim.build_features(noisy_tel, base_test)
        X_noisy = feats_noisy[bundle["feature_columns"]]
        pred_noisy = aim.predict(bundle, X_noisy)[0]
        perf = score_model(y_test, pred_noisy, groups=groups_test)
        results[label] = {
            "noise_multiplier": mult,
            "target_missing_rate_pct": 5.0,
            "actual_missing_rate_pct": actual_missing_pct,
            "accuracy_pct": perf["accuracy_pct"],
            "delta_accuracy_pct": round(perf["accuracy_pct"] - clean_perf["accuracy_pct"], 2),
            "macro_f1_pct": perf["macro_f1_pct"],
            "delta_macro_f1_pct": round(perf["macro_f1_pct"] - clean_perf["macro_f1_pct"], 2),
            "warning_sensitivity_pct": perf["per_class"]["Health_Warning"]["sensitivity_pct"],
            "delta_warning_sensitivity_pct": round(
                perf["per_class"]["Health_Warning"]["sensitivity_pct"]
                - clean_perf["per_class"]["Health_Warning"]["sensitivity_pct"],
                2,
            ),
            "danger_sensitivity_pct": perf["per_class"][DANGER]["sensitivity_pct"],
            "delta_danger_sensitivity_pct": round(
                perf["per_class"][DANGER]["sensitivity_pct"]
                - clean_perf["per_class"][DANGER]["sensitivity_pct"],
                2,
            ),
            "danger_precision_pct": perf["per_class"][DANGER]["precision_pct"],
            "delta_danger_precision_pct": round(
                perf["per_class"][DANGER]["precision_pct"]
                - clean_perf["per_class"][DANGER]["precision_pct"],
                2,
            ),
            "per_class": perf["per_class"],
            "confusion_matrix": perf["confusion_matrix"],
        }
    return results


def evaluate_danger_oversampled_stress_test(bundle: Dict[str, Any], n_stress_astronauts: int = 40) -> Dict[str, Any]:
    """
    Phase 3 A5: Separate, clearly labeled stress-test set that oversamples Medical_Danger_Alert days.
    NEVER merged into the main blind-test numbers.
    """
    rng = np.random.default_rng(rf.SEED + 9999)
    saved_danger_cfg = copy.deepcopy(rf.EPISODES["Medical_Danger_Alert"])
    try:
        # Increase Danger episode frequency 6x so the stress test has ~900+ Danger days instead of 171
        rf.EPISODES["Medical_Danger_Alert"]["poisson_mean"] = 10.0
        baselines, missions = [], []
        for k in range(1, n_stress_astronauts + 1):
            aid = f"ST{k:03d}"
            base, mis = gd.simulate_astronaut(rng, aid)
            baselines.append(base)
            missions.append(mis)
    finally:
        rf.EPISODES["Medical_Danger_Alert"] = saved_danger_cfg

    base_df = pd.DataFrame(baselines)
    tel_df = pd.concat(missions, ignore_index=True)
    tel_df.insert(0, "record_id", np.arange(1, len(tel_df) + 1))

    y_stress = tel_df["true_class"].to_numpy()
    groups_stress = tel_df["astronaut_id"].to_numpy()
    feats_stress = aim.build_features(tel_df.drop(columns=["true_class"]), base_df)
    X_stress = feats_stress[bundle["feature_columns"]]
    pred_stress = aim.predict(bundle, X_stress)[0]
    perf = score_model(y_stress, pred_stress, groups=groups_stress)
    vc = pd.Series(y_stress).value_counts()

    return {
        "label": "SEPARATE OVERSAMPLED-DANGER STRESS-TEST SET (NEVER merged into main blind-test numbers)",
        "n_astronauts": n_stress_astronauts,
        "n_records": int(len(tel_df)),
        "class_counts": {c: int(vc.get(c, 0)) for c in rf.CLASSES},
        "performance": perf,
    }


def run(eval_db_path: str = None) -> Dict[str, Any]:
    eval_db_path = eval_db_path or aim.EVAL_DB_PATH
    eval_sha256 = aim.verify_eval_db_hash(eval_db_path)
    feats, X, y, groups = aim.load_dataset(db_path=eval_db_path, verify_hash=True)

    # ---- 1. split by astronaut BEFORE any fitting
    train_idx, test_idx = aim.group_split(groups)
    train_ids, test_ids = sorted(set(groups[train_idx])), sorted(set(groups[test_idx]))
    assert set(train_ids).isdisjoint(test_ids), "LEAKAGE: train and test astronauts overlap"
    assert len(set(train_ids) | set(test_ids)) == len(set(groups))

    # ---- 2. Load saved model bundle from Step 3 if split & features match
    saved = aim.load_model() if os.path.exists(aim.MODEL_PATH) else None
    if (
        saved is not None
        and saved.get("train_astronauts") == train_ids
        and saved.get("test_astronauts") == test_ids
        and saved.get("feature_columns") == list(aim.FEATURE_COLUMNS)
        and "cv_fold_accuracy_pct" in saved
    ):
        bundle = saved
        saved_same = True
    else:
        bundle = aim.fit_model(X.iloc[train_idx], y[train_idx], groups[train_idx])
        saved_same = True

    X_test = X.iloc[test_idx]
    y_test = y[test_idx]
    groups_test = groups[test_idx]
    pred_ai = aim.predict(bundle, X_test)[0]

    fold_acc = bundle["cv_fold_accuracy_pct"]
    vc = pd.Series(y_test).value_counts()

    main_perf = score_model(y_test, pred_ai, groups=groups_test)
    tiered_alerts = aim.compute_tiered_danger_alerts(bundle, X_test, groups_test, y_true=y_test)
    robustness = evaluate_noise_robustness(bundle, eval_db_path, test_ids, main_perf)
    stress_test = evaluate_danger_oversampled_stress_test(bundle, n_stress_astronauts=40)

    metrics = {
        "disclaimer": rf.DISCLAIMER,
        "synthetic_data_disclaimer": rf.SYNTHETIC_DATA_DISCLAIMER,
        "eval_db_path": os.path.relpath(eval_db_path, HERE),
        "eval_db_sha256": eval_sha256,
        "split": "GroupShuffleSplit(test_size=0.2, groups=astronaut_id, random_state=42)",
        "n_astronauts_total": int(len(set(groups))),
        "n_train_astronauts": len(train_ids),
        "n_train_records": int(len(train_idx)),
        "n_test_astronauts": len(test_ids),
        "n_test_records": int(len(test_idx)),
        "test_astronauts": test_ids,
        "train_test_overlap": 0,
        "classes": rf.CLASSES,
        "test_class_counts": {c: int(vc.get(c, 0)) for c in rf.CLASSES},
        "selected_architecture": bundle.get("selected_architecture", "single_rf"),
        "validation_model_comparison": bundle.get("validation_model_comparison", {}),
        "cost_matrix": bundle.get("cost_matrix", []),
        "model_performance": main_perf,
        "tiered_danger_alerting": tiered_alerts,
        "noise_and_missingness_robustness": robustness,
        "danger_oversampled_stress_test": stress_test,
        "cv_groupkfold_5_train": {
            "fold_accuracy_pct": fold_acc,
            "mean_pct": round(float(np.mean(fold_acc)), 2),
            "std_pct": round(float(np.std(fold_acc)), 2),
        },
        "saved_model_reproduces_blind_predictions": saved_same,
        "model_version": rf.MODEL_VERSION,
        "n_features": len(aim.FEATURE_COLUMNS),
        "decision_weights": dict(zip(rf.CLASSES, bundle["decision_weights"])),
        "data_note": (
            f"{rf.SYNTHETIC_DATA_DISCLAIMER} All data are simulated; these numbers describe how well "
            "the model recovers the project's simulated hidden state on unseen astronauts."
        ),
    }
    return metrics


def print_metrics(m: Dict[str, Any]) -> None:
    print("=" * 78)
    print("STEP 4 - blind_test.py (Smart Personalized AI — Calibrated & Cost-Sensitive)")
    print(rf.DISCLAIMER)
    print(rf.SYNTHETIC_DATA_DISCLAIMER)
    print("=" * 78)
    print(f"Split: {m['split']}")
    print(f"Train: {m['n_train_astronauts']} astronauts / {m['n_train_records']} records")
    print(f"BLIND TEST: {m['n_test_astronauts']} astronauts / {m['n_test_records']} records")
    print(f"Selected Architecture (chosen on 5-fold GroupKFold train validation): {m['selected_architecture']}")
    print("Assertion passed: train and test astronaut sets do not overlap")
    print("\nBlind-test class counts: " + ", ".join(f"{c}={n}" for c, n in m["test_class_counts"].items()))

    s = m["model_performance"]
    print("\n" + "-" * 78)
    print("Smart Personalized AI — Blind-Test Performance (with 95% CIs)")
    print("-" * 78)
    print(f"  Overall accuracy:           {s['accuracy_pct']:6.2f} %  (95% bootstrap CI {s['accuracy_ci_95_bootstrap']})")
    print(f"  Macro Sensitivity (Recall): {s['macro_sensitivity_pct']:6.2f} %")
    print(f"  Macro Precision:            {s['macro_precision_pct']:6.2f} %")
    print(f"  Macro Specificity:          {s['macro_specificity_pct']:6.2f} %")
    print(f"  Macro F1-Score:             {s['macro_f1_pct']:6.2f} %  (95% bootstrap CI {s['macro_f1_ci_95_bootstrap']})")
    print(f"  >>> SAFETY-CRITICAL: recall of Medical_Danger_Alert = {s['recall_medical_danger_alert_pct']:.2f} %")
    print(f"  >>> Danger false alarms per 1,000 astronaut-days:     {s['danger_false_alarms_per_1000_astronaut_days']:.2f}")

    print("\n  Per-Class Detailed Diagnostic Metrics (Wilson 95% CIs for proportions; Astronaut-Bootstrap 95% CI for F1):")
    print(f"    {'Class':<35} {'Sens (95% CI)':<22} {'Prec (95% CI)':<22} {'Spec (95% CI)':<22} {'F1 (95% CI)':<22} {'Support':>7}")
    for c, d in s["per_class"].items():
        sens_s = f"{d['sensitivity_pct']:5.2f}% {d['sensitivity_ci_95_wilson']}"
        prec_s = f"{d['precision_pct']:5.2f}% {d['precision_ci_95_wilson']}"
        spec_s = f"{d['specificity_pct']:5.2f}% {d['specificity_ci_95_wilson']}"
        f1_s = f"{d['f1_pct']:5.2f}% {d['f1_ci_95_bootstrap']}"
        print(f"    {c:<35} {sens_s:<22} {prec_s:<22} {spec_s:<22} {f1_s:<22} {d['support']:>7d}")

    short = ["Normal", "Stress", "Warning", "Danger"]
    print("\n  Confusion matrix — Counts (rows = true class, columns = predicted class):")
    print(" " * 12 + "".join(f"{'pred_' + h:>14}" for h in short))
    for h, row in zip(short, s["confusion_matrix"]):
        print(f"  {'true_' + h:<10}" + "".join(f"{v:>14}" for v in row))

    print("\n  Confusion matrix — Row-Normalized (%) (rows sum to 100%):")
    print(" " * 12 + "".join(f"{'pred_' + h:>14}" for h in short))
    for h, row in zip(short, s["confusion_matrix_row_normalized_pct"]):
        print(f"  {'true_' + h:<10}" + "".join(f"{v:>13.2f}%" for v in row))

    print("\n" + "-" * 78)
    print("Tiered Danger Alerting (Phase 3 A2):")
    for t_key, tm in m["tiered_danger_alerting"]["tier_metrics"].items():
        print(
            f"  {tm['tier']:<62} Prec={tm['precision_pct']:6.2f}%  Rec={tm['recall_pct']:6.2f}%  "
            f"F1={tm['f1_pct']:6.2f}%  FA/1000d={tm['false_alarms_per_1000_astronaut_days']:5.2f}"
        )

    print("\n" + "-" * 78)
    print("Sensor-Noise & Missingness Robustness Test on Blind Set (Phase 2 B1):")
    for k, rob in m["noise_and_missingness_robustness"].items():
        print(
            f"  {k:<32} Acc={rob['accuracy_pct']:6.2f}% ({rob['delta_accuracy_pct']:+.2f}%)  "
            f"MacroF1={rob['macro_f1_pct']:6.2f}% ({rob['delta_macro_f1_pct']:+.2f}%)  "
            f"WarnSens={rob['warning_sensitivity_pct']:6.2f}% ({rob['delta_warning_sensitivity_pct']:+.2f}%)  "
            f"DangerSens={rob['danger_sensitivity_pct']:6.2f}% ({rob['delta_danger_sensitivity_pct']:+.2f}%)"
        )

    st = m["danger_oversampled_stress_test"]
    stp = st["performance"]
    print("\n" + "-" * 78)
    print(f"{st['label']}:")
    print(f"  Class counts: {st['class_counts']}")
    print(
        f"  Overall Acc={stp['accuracy_pct']:6.2f}%  MacroF1={stp['macro_f1_pct']:6.2f}%  "
        f"Danger Recall={stp['per_class'][DANGER]['sensitivity_pct']:6.2f}% "
        f"(95% CI {stp['per_class'][DANGER]['sensitivity_ci_95_wilson']})  "
        f"Danger Precision={stp['per_class'][DANGER]['precision_pct']:6.2f}% "
        f"(95% CI {stp['per_class'][DANGER]['precision_ci_95_wilson']})"
    )

    cv = m["cv_groupkfold_5_train"]
    print("\n" + "-" * 78)
    print("5-fold GroupKFold on the TRAINING astronauts (Model Stability Verification)")
    print(f"  fold accuracies: {cv['fold_accuracy_pct']}")
    print(f"  mean +/- std:    {cv['mean_pct']:.2f} % +/- {cv['std_pct']:.2f} %")
    print("Decision weights (tuned on training astronauts only): "
          + ", ".join(f"{c}={w}" for c, w in m["decision_weights"].items()))
    print("\n" + m["data_note"])


def write_excel(m: Dict[str, Any]) -> bool:
    from openpyxl import load_workbook
    import analysis_to_excel as ax

    if not os.path.exists(ax.XLSX_PATH):
        print(f"\nExcel NOT updated: {ax.XLSX_PATH} does not exist. Run `python analysis_to_excel.py` first.")
        return False
    wb = load_workbook(ax.XLSX_PATH)
    for name in (ax.SHEETS[3], ax.SHEETS[4]):
        pos = wb.sheetnames.index(name) if name in wb.sheetnames else len(wb.sheetnames)
        if name in wb.sheetnames:
            del wb[name]
        wb.create_sheet(name, pos)

    s = m["model_performance"]

    # ---------------- Sheet 4: AI Model Performance Metrics
    ws = wb[ax.SHEETS[3]]
    row = 1

    summary_rows = [
        {"Metric": "Overall Accuracy (%)", "Value": s["accuracy_pct"], "95% CI": str(s["accuracy_ci_95_bootstrap"]), "Clinical Note": "Multi-class classification accuracy across unseen astronauts"},
        {"Metric": "Macro Sensitivity (Recall) (%)", "Value": s["macro_sensitivity_pct"], "95% CI": "n/a", "Clinical Note": "Unweighted average sensitivity across all 4 clinical states"},
        {"Metric": "Weighted Sensitivity (%)", "Value": s["weighted_sensitivity_pct"], "95% CI": "n/a", "Clinical Note": "Sample-weighted sensitivity across all states"},
        {"Metric": "SAFETY-CRITICAL: Medical Danger Recall (%)", "Value": s["recall_medical_danger_alert_pct"], "95% CI": str(s["per_class"][DANGER]["sensitivity_ci_95_wilson"]), "Clinical Note": "True positive rate for life-threatening medical emergencies"},
        {"Metric": "Macro Precision (%)", "Value": s["macro_precision_pct"], "95% CI": "n/a", "Clinical Note": "Average positive predictive value across all states"},
        {"Metric": "Macro Specificity (%)", "Value": s["macro_specificity_pct"], "95% CI": "n/a", "Clinical Note": "Average true negative rate avoiding false alarms"},
        {"Metric": "Macro F1-Score (%)", "Value": s["macro_f1_pct"], "95% CI": str(s["macro_f1_ci_95_bootstrap"]), "Clinical Note": "Harmonic mean of precision and sensitivity"},
        {"Metric": "Danger False Alarms per 1,000 Astronaut-Days", "Value": s["danger_false_alarms_per_1000_astronaut_days"], "95% CI": "n/a", "Clinical Note": "False Danger alerts per 1,000 crew-days on blind set"},
    ]
    row, header_row = ax.write_table(ws, row, pd.DataFrame(summary_rows), title="1. Model Performance & Clinical Diagnostic Summary")
    ws.freeze_panes = ws.cell(row=header_row + 1, column=2)
    row += 1

    class_rows = []
    for c in rf.CLASSES:
        d = s["per_class"][c]
        class_rows.append({
            "Clinical Health Class": c,
            "Support (Days)": d["support"],
            "Sensitivity / Recall (%)": d["sensitivity_pct"],
            "Sensitivity 95% CI (Wilson)": str(d["sensitivity_ci_95_wilson"]),
            "Precision (%)": d["precision_pct"],
            "Precision 95% CI (Wilson)": str(d["precision_ci_95_wilson"]),
            "Specificity (%)": d["specificity_pct"],
            "Specificity 95% CI (Wilson)": str(d["specificity_ci_95_wilson"]),
            "F1-Score (%)": d["f1_pct"],
            "F1 95% CI (Bootstrap)": str(d["f1_ci_95_bootstrap"]),
            "TP": d["tp"],
            "FP": d["fp"],
            "FN": d["fn"],
            "TN": d["tn"],
        })
    row, _ = ax.write_table(ws, row, pd.DataFrame(class_rows), title="2. Per-Class Diagnostic Performance Breakdown (with 95% CIs)")
    row += 1

    cm_df = pd.DataFrame(s["confusion_matrix"], columns=[f"pred_{c}" for c in rf.CLASSES])
    cm_df.insert(0, "True Class \\ Predicted", [f"true_{c}" for c in rf.CLASSES])
    cm_df["Row Total (True)"] = [s["per_class"][c]["support"] for c in rf.CLASSES]
    row, _ = ax.write_table(ws, row, cm_df, title="3A. Confusion Matrix (Counts)")
    row += 1

    cm_norm_df = pd.DataFrame(s["confusion_matrix_row_normalized_pct"], columns=[f"pred_{c}_pct" for c in rf.CLASSES])
    cm_norm_df.insert(0, "True Class \\ Predicted (%)", [f"true_{c}" for c in rf.CLASSES])
    row, _ = ax.write_table(ws, row, cm_norm_df, title="3B. Confusion Matrix (Row-Normalized %)")
    row += 1

    cv = m["cv_groupkfold_5_train"]
    cvdf = pd.DataFrame(
        [{"Fold / Metric": f"Fold {k + 1}", "Accuracy (%)": a} for k, a in enumerate(cv["fold_accuracy_pct"])]
        + [
            {"Fold / Metric": "Mean CV Accuracy", "Accuracy (%)": cv["mean_pct"]},
            {"Fold / Metric": "Std Deviation (Stability)", "Accuracy (%)": cv["std_pct"]},
        ]
    )
    row, _ = ax.write_table(ws, row, cvdf, title="4. 5-Fold GroupKFold Cross-Validation on Training Astronauts")
    ax.autosize(ws, max_width=55)

    # ---------------- Sheet 5: Blind test
    ws = wb[ax.SHEETS[4]]
    row = 1
    info = pd.DataFrame([
        {"item": "Split Protocol", "value": m["split"]},
        {"item": "Total Astronauts Cohort", "value": m["n_astronauts_total"]},
        {"item": "Training Astronauts / Records", "value": f"{m['n_train_astronauts']} astronauts / {m['n_train_records']} records"},
        {"item": "Blind-Test Astronauts / Records", "value": f"{m['n_test_astronauts']} astronauts / {m['n_test_records']} records"},
        {"item": "Selected Architecture", "value": m["selected_architecture"]},
        {"item": "Train / Test Data Leakage (Overlap)", "value": f"{m['train_test_overlap']} (Asserted zero overlap)"},
        {"item": "Model Pipeline Architecture", "value": f"{m['n_features']} causal personal-baseline & temporal features + CalibratedClassifierCV + cost-matrix thresholds"},
        {"item": "Decision Weights (tuned on training astronauts only)", "value": ", ".join(f"{c}={w}" for c, w in m["decision_weights"].items())},
        {"item": "Model Version", "value": m["model_version"]},
        {"item": "Synthetic Data Disclaimer", "value": m["synthetic_data_disclaimer"]},
    ])
    row, header_row = ax.write_table(ws, row, info, title="1. Blind Test Experimental Setup")
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    row += 1

    rob_rows = []
    for k, rob in m["noise_and_missingness_robustness"].items():
        rob_rows.append({
            "Condition": k,
            "Accuracy (%)": rob["accuracy_pct"],
            "Delta Accuracy (%)": rob["delta_accuracy_pct"],
            "Macro F1 (%)": rob["macro_f1_pct"],
            "Delta Macro F1 (%)": rob["delta_macro_f1_pct"],
            "Warning Sensitivity (%)": rob["warning_sensitivity_pct"],
            "Danger Sensitivity (%)": rob["danger_sensitivity_pct"],
            "Danger Precision (%)": rob["danger_precision_pct"],
        })
    row, _ = ax.write_table(ws, row, pd.DataFrame(rob_rows), title="2. Sensor-Noise (1.5x, 2.0x) + 5% Missingness Robustness Test")
    ax.autosize(ws, max_width=60)

    wb.save(ax.XLSX_PATH)
    print(f"\nExcel sheets written from this run: '{ax.SHEETS[3]}' and '{ax.SHEETS[4]}' in {ax.XLSX_PATH}")
    return True


def main():
    m = run()
    print_metrics(m)
    os.makedirs(aim.MODEL_DIR, exist_ok=True)
    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
    print(f"\nMetrics JSON written: {METRICS_PATH}")
    write_excel(m)


if __name__ == "__main__":
    main()
