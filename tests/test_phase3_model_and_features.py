"""
Phase 3 Unit Tests — Causal Temporal Features (Zero Look-Ahead), Stress-vs-Danger Features,
Cost-Matrix Thresholds, Tiered Alerting, and Statistical Confidence Intervals
==========================================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ai_health_model as ahm
import blind_test as bt
import resource_facts as rf


def _load_single_astronaut(aid: str = "A001"):
    con = ahm.connect_eval_readonly()
    tel = pd.read_sql_query(
        "SELECT * FROM mission_telemetry WHERE astronaut_id = ? ORDER BY mission_day",
        con,
        params=(aid,),
    )
    base = pd.read_sql_query(
        "SELECT * FROM preflight_baseline WHERE astronaut_id = ?",
        con,
        params=(aid,),
    )
    con.close()
    return tel, base


def test_temporal_features_strictly_causal_no_lookahead():
    """
    A1 Ground Rule: Prove that temporal features at mission day t depend ONLY on
    days <= t and never leak information from future days > t.
    """
    tel, base = _load_single_astronaut("A001")
    full_features = ahm.build_features(tel, base)

    numeric_cols = [ind["name"] for ind in rf.INDICATORS if ind["kind"] != "flag"]

    for cutoff_idx in [7, 25, 60, 120]:
        # 1. Compute features when future rows do not even exist
        prefix_tel = tel.iloc[:cutoff_idx].copy()
        prefix_feat = ahm.build_features(prefix_tel, base)

        # 2. Compute features when future rows (>= cutoff_idx) are wildly corrupted
        corrupted_tel = tel.copy()
        for col in numeric_cols:
            if col in corrupted_tel.columns:
                corrupted_tel.loc[corrupted_tel.index >= cutoff_idx, col] = 99999.0
        corrupted_feat = ahm.build_features(corrupted_tel, base)

        # Every feature column up to cutoff_idx must match identically
        for col in ahm.FEATURE_COLUMNS:
            v_full = full_features.iloc[:cutoff_idx][col].to_numpy(dtype=float)
            v_pref = prefix_feat[col].to_numpy(dtype=float)
            v_corr = corrupted_feat.iloc[:cutoff_idx][col].to_numpy(dtype=float)

            assert np.allclose(v_full, v_pref, atol=1e-12, equal_nan=True), (
                f"Look-ahead leak detected in {col} at cutoff={cutoff_idx} (prefix vs full)"
            )
            assert np.allclose(v_full, v_corr, atol=1e-12, equal_nan=True), (
                f"Look-ahead leak detected in {col} at cutoff={cutoff_idx} (corrupted future vs full)"
            )


def test_required_temporal_and_discriminant_features_exist():
    """Verify A1 temporal features and A3 Stress-vs-Danger discriminant features are present."""
    required = [
        # A1 rolling means, SDs, slopes, baseline z-scores, cumulative bone/muscle change
        "sleep_hours_z_r3", "sleep_hours_z_r7", "sleep_hours_z_r14",
        "sleep_hours_z_sd3", "sleep_hours_z_sd7", "sleep_hours_z_sd14",
        "sleep_hours_z_slope7", "sleep_hours_z_slope14",
        "sleep_hours_z_vs_first7",
        "bone_health_cum_chg", "muscle_health_cum_chg",
        # A3 Stress vs Danger discriminants
        "spo2_deficit_below_94", "glucose_excursion_above_125", "glucose_hypo_below_70",
        "spike_streak_days", "vital_recovery_delta_1d", "vital_recovery_ratio_3d",
        "n_abnormal_systems_20sd", "danger_vs_stress_discriminant",
    ]
    for col in required:
        assert col in ahm.FEATURE_COLUMNS, f"Missing required feature: {col}"


def test_cost_matrix_and_tiered_danger_alerting():
    """Verify A2 cost matrix loading and two-tier Danger alerting with persistence promotion."""
    cm = ahm.load_cost_matrix()
    assert cm.shape == (4, 4)
    # Missed Danger -> Normal must cost much more than a false alarm
    assert cm[3, 0] >= 5.0 * cm[0, 3]

    # Create a mock bundle with fixed probabilities for 4 consecutive days of A001:
    # Day 1: low danger prob (0.05) -> No_Danger_Alert
    # Day 2: moderate danger prob (0.30) -> Danger – confirm
    # Day 3: consecutive moderate danger prob (0.31) -> promoted to Danger via persistence!
    # Day 4: high danger prob (0.75) -> Danger immediately
    class _MockEstimator:
        classes_ = np.array(rf.CLASSES, dtype=object)

        def predict_proba(self, X):
            return np.array([
                [0.90, 0.03, 0.02, 0.05],
                [0.45, 0.15, 0.10, 0.30],
                [0.44, 0.15, 0.10, 0.31],
                [0.10, 0.10, 0.05, 0.75],
            ])

    mock_bundle = {
        "pipeline": _MockEstimator(),
        "calibrated_pipeline": _MockEstimator(),
        "decision_weights": [1.0, 1.0, 1.0, 1.0],
        "feature_columns": ["f1"],
        "tiered_alerting_thresholds": {
            "danger_confirm_prob_threshold": 0.22,
            "danger_high_prob_threshold": 0.45,
            "danger_confirm_persistence_days": 2,
        },
    }
    X_dummy = pd.DataFrame({"f1": [0.0, 0.0, 0.0, 0.0]})
    groups = np.array(["A001", "A001", "A001", "A001"])
    y_true = np.array(["Normal", "Medical_Danger_Alert", "Medical_Danger_Alert", "Medical_Danger_Alert"])

    res = ahm.compute_tiered_danger_alerts(mock_bundle, X_dummy, groups, y_true=y_true)
    assert res["tier_labels"] == [
        "No_Danger_Alert",
        "Danger \u2013 confirm",
        "Danger",
        "Danger",
    ]
    assert "Danger" in res["tier_metrics"]
    assert "Danger_confirm_inclusive" in res["tier_metrics"]


def test_wilson_and_bootstrap_confidence_intervals():
    """Verify A5 Wilson 95% CI and astronaut-cluster bootstrap F1 CI behave properly."""
    lo, hi = bt.wilson_ci_pct(156, 171)
    point = 100.0 * 156 / 171
    assert 0.0 <= lo < point < hi <= 100.0
    assert (hi - lo) < 15.0

    y_true = np.array(["Normal"] * 30 + ["Medical_Danger_Alert"] * 10)
    y_pred = np.array(["Normal"] * 29 + ["Health_Warning"] * 1 + ["Medical_Danger_Alert"] * 9 + ["Normal"] * 1)
    groups = np.array(["A001"] * 10 + ["A002"] * 10 + ["A003"] * 10 + ["A004"] * 10)
    boot = bt.bootstrap_f1_ci_by_astronaut(y_true, y_pred, groups=groups, n_boot=100, seed=42)
    assert len(boot["Medical_Danger_Alert"]) == 2
    assert 0.0 <= boot["Medical_Danger_Alert"][0] <= boot["Medical_Danger_Alert"][1] <= 100.0
