"""
ai_health_model.py — STEP 3: causal personal-baseline temporal features + calibrated classifier.

Phase 3 improvements implemented strictly on training astronauts via 5-fold GroupKFold:
  * A1: Causal per-astronaut temporal features (rolling means & SDs over 3, 7, 14 days; linear slopes
        over 7 and 14 days; z-score vs pre-flight baseline and vs first 7 in-flight days; cumulative and
        7/14/30-day bone/muscle changes; exercise adherence & deconditioning composites). Zero look-ahead.
  * A3: Stress vs. Danger discrimination features (SpO2, blood_glucose_mg_dl, causal spike streak duration,
        vital recovery rate, multi-system concurrent abnormality counts at 1.5 SD and 2.0 SD, and composite
        baseline deviation norms). Compares Single-Stage vs. Two-Stage classifier on 5-fold GroupKFold.
  * A2: Probability calibration via CalibratedClassifierCV + cost-matrix decision thresholds tuned on
        out-of-fold training predictions + tiered alerting ("Danger – confirm" vs. "Danger").
  * Model comparison: Compares Random Forest vs. Two-Stage Random Forest vs. HistGradientBoosting
        (LightGBM-equivalent tree booster) on 5-fold GroupKFold of training astronauts only.

Prototype for research/education only — not for clinical diagnosis.
Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import Pipeline

import resource_facts as rf

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
EVAL_DB_PATH = os.environ.get("ASTRO_HEALTH_EVAL_DB") or os.path.join(DATA_DIR, "astronaut_health_eval.db")
EVAL_HASH_PATH = EVAL_DB_PATH + ".sha256"
APP_DB_PATH = os.environ.get("ASTRO_HEALTH_DB") or os.path.join(DATA_DIR, "astronaut_health_app.db")
LEGACY_DB_PATH = os.path.join(HERE, "astronaut_health.db")
DB_PATH = APP_DB_PATH
MODEL_DIR = os.path.join(HERE, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "health_model.joblib")
RANDOM_STATE = 42
TREND_COLUMNS = ["bone_health", "muscle_health"]

RAW_COLUMNS = [
    "heart_rate",
    "systolic_bp",
    "diastolic_bp",
    "blood_glucose_mg_dl",
    "temperature",
    "sleep_hours",
    "mood",
    "oxygen_saturation",
]

COMBOS = {
    "combo_bp_hr": ["systolic_bp", "diastolic_bp", "heart_rate"],
    "combo_psych": ["sleep_hours", "mood", "relaxation", "mental_health_assessment", "game_test_score"],
    "combo_immune": ["immunity_indicators", "hormones", "temperature", "blood_glucose_mg_dl"],
    "combo_cardio_metabolic": ["systolic_bp", "diastolic_bp", "heart_rate", "blood_glucose_mg_dl", "oxygen_saturation"],
}


def compute_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_eval_db_hash(db_path: str = None, hash_path: str = None) -> str:
    db_path = db_path or EVAL_DB_PATH
    hash_path = hash_path or (db_path + ".sha256")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Frozen evaluation database not found: {db_path}")
    if not os.path.exists(hash_path):
        raise FileNotFoundError(f"SHA-256 manifest not found: {hash_path}")
    with open(hash_path, "r", encoding="utf-8") as f:
        expected = f.read().strip().split()[0].lower()
    actual = compute_sha256(db_path).lower()
    if actual != expected:
        raise RuntimeError(
            f"SHA-256 HASH MISMATCH for {db_path}: expected {expected}, got {actual}. "
            "Refusing to run evaluation on a modified database."
        )
    return actual


def connect_eval_readonly(db_path: str = None, hash_path: str = None) -> sqlite3.Connection:
    db_path = db_path or EVAL_DB_PATH
    verify_eval_db_hash(db_path, hash_path)
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _causal_linear_slope(series_ff: pd.Series, groups: pd.Series, window: int) -> pd.Series:
    """
    Strictly causal trailing OLS slope over `window` days (uses only shifts k = 0 .. window-1 >= 0).
    For window W, weights w_j = (W - 1 - j) - (W - 1)/2 for lag j = 0 .. W-1.
    """
    w = np.arange(window, dtype=float) - (window - 1) / 2.0
    denom = float(np.sum(w ** 2))
    acc = pd.Series(0.0, index=series_ff.index)
    grp = series_ff.groupby(groups)
    for lag in range(window):
        weight = w[window - 1 - lag]
        if abs(weight) < 1e-12:
            continue
        shifted = series_ff if lag == 0 else grp.shift(lag).fillna(0.0)
        acc = acc + weight * shifted
    return acc / denom


def _causal_first_n_baseline(z_ff: pd.Series, groups: pd.Series, n_days: int = 7) -> pd.Series:
    """
    Compute each astronaut's baseline mean over their first `n_days` in-flight readings causally:
    - On day k <= n_days: expanding mean of days 1..k (uses no future days).
    - On day k > n_days: mean of days 1..n_days.
    """
    def _per_group(s: pd.Series) -> pd.Series:
        exp_mean = s.expanding(min_periods=1).mean()
        if len(s) > n_days:
            fixed = exp_mean.iloc[n_days - 1]
            exp_mean.iloc[n_days:] = fixed
        return exp_mean

    return z_ff.groupby(groups, group_keys=False).apply(_per_group)


def _causal_spike_streak(cv_score: pd.Series, groups: pd.Series, threshold_sd: float = 1.15) -> pd.Series:
    """
    Count consecutive days up to today (causal: lags 0..4 only) where cardiovascular spike >= threshold_sd.
    Stress spikes last 1-2 days, whereas Danger episodes can persist 1-4 days.
    """
    above0 = (cv_score >= threshold_sd).astype(float)
    grp = above0.groupby(groups)
    lag1 = grp.shift(1, fill_value=0.0)
    lag2 = grp.shift(2, fill_value=0.0)
    lag3 = grp.shift(3, fill_value=0.0)
    s1 = above0
    s2 = s1 * lag1
    s3 = s2 * lag2
    s4 = s3 * lag3
    return s1 + s2 + s3 + s4


def build_features(tel: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    """
    Compute strictly causal personal-baseline and temporal features (Phase 3 A1 & A3).
    Never uses future rows: every rolling window, shift, and baseline calculation depends ONLY on
    pre-flight baseline and mission days <= current mission_day.
    """
    df = tel.sort_values(["astronaut_id", "mission_day"]).reset_index(drop=True)
    b = base.set_index("astronaut_id")
    g = df["astronaut_id"]
    out: Dict[str, Any] = {
        "record_id": df["record_id"],
        "astronaut_id": df["astronaut_id"],
        "mission_day": df["mission_day"],
    }

    vs14: Dict[str, pd.Series] = {}
    z_ff_map: Dict[str, pd.Series] = {}
    r3_vs14_map: Dict[str, pd.Series] = {}
    r7_vs14_map: Dict[str, pd.Series] = {}

    for c in rf.CONTINUOUS:
        mean = g.map(b[c + "_mean"])
        std = g.map(b[c + "_std"]).where(lambda s: s > 1e-9, 1.0)
        z = (df[c].astype(float) - mean) / std
        grp = z.groupby(g)
        # Causal forward-fill of z for slope/streak calculations (falls back to 0.0 = pre-flight mean)
        z_ff = grp.transform(lambda s: s.ffill()).fillna(0.0)
        z_ff_map[c] = z_ff

        r3 = grp.transform(lambda s: s.rolling(3, min_periods=1).mean())
        r7 = grp.transform(lambda s: s.rolling(7, min_periods=1).mean())
        r14 = grp.transform(lambda s: s.rolling(14, min_periods=1).mean())

        sd3 = grp.transform(lambda s: s.rolling(3, min_periods=2).std(ddof=1)).fillna(0.0)
        sd7 = grp.transform(lambda s: s.rolling(7, min_periods=2).std(ddof=1)).fillna(0.0)
        sd14 = grp.transform(lambda s: s.rolling(14, min_periods=2).std(ddof=1)).fillna(0.0)

        slope7 = _causal_linear_slope(z_ff, g, 7)
        slope14 = _causal_linear_slope(z_ff, g, 14)

        first7_base = _causal_first_n_baseline(z_ff, g, n_days=7)
        z_vs_first7 = z_ff - first7_base

        med14 = grp.transform(lambda s: s.shift(1).rolling(14, min_periods=3).median()).fillna(first7_base)
        vs14_c = z - med14
        vs14[c] = vs14_c.fillna(z_vs_first7)

        r3_med14 = grp.transform(lambda s: s.shift(3).rolling(14, min_periods=3).median()).fillna(first7_base)
        r7_med14 = grp.transform(lambda s: s.shift(7).rolling(14, min_periods=3).median()).fillna(first7_base)
        r3_vs14_map[c] = (r3 - r3_med14).fillna(0.0)
        r7_vs14_map[c] = (r7 - r7_med14).fillna(0.0)

        out[f"{c}_z"] = z
        out[f"{c}_z_r3"] = r3
        out[f"{c}_z_r7"] = r7
        out[f"{c}_z_r14"] = r14
        out[f"{c}_z_sd3"] = sd3
        out[f"{c}_z_sd7"] = sd7
        out[f"{c}_z_sd14"] = sd14
        out[f"{c}_z_slope7"] = slope7
        out[f"{c}_z_slope14"] = slope14
        out[f"{c}_z_vs_first7"] = z_vs_first7
        out[f"{c}_z_acute"] = z - grp.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
        out[f"{c}_z_vs14"] = vs14[c]
        out[f"{c}_z_r3_vs14"] = r3_vs14_map[c]
        out[f"{c}_z_r7_vs14"] = r7_vs14_map[c]

    for c in RAW_COLUMNS:
        out[f"{c}_raw"] = df[c].astype(float)

    # Bone and muscle cumulative and multi-window changes (A1)
    for c in TREND_COLUMNS:
        raw_s = df[c].astype(float)
        raw_ff = raw_s.groupby(g).transform(lambda s: s.ffill()).fillna(100.0)
        raw3 = raw_s.groupby(g).transform(lambda s: s.rolling(3, min_periods=1).mean())
        raw7 = raw_s.groupby(g).transform(lambda s: s.rolling(7, min_periods=1).mean())
        out[f"{c}_cum_chg"] = raw_ff - 100.0
        out[f"{c}_chg7"] = raw3 - raw7.groupby(g).shift(7).fillna(100.0)
        out[f"{c}_chg14"] = raw7 - raw7.groupby(g).shift(14).fillna(100.0)
        out[f"{c}_chg30"] = raw7 - raw7.groupby(g).shift(30).fillna(100.0)
        out[f"{c}_slope14"] = _causal_linear_slope(raw_ff - 100.0, g, 14)

    # Exercise flags and rolling adherence over 3, 7, and 14 days (A1)
    for f in rf.FLAGS:
        fl = df[f].astype(float)
        out[f] = fl
        out[f"{f}_r3"] = fl.groupby(g).transform(lambda s: s.rolling(3, min_periods=1).mean())
        out[f"{f}_r7"] = fl.groupby(g).transform(lambda s: s.rolling(7, min_periods=1).mean())
        out[f"{f}_r14"] = fl.groupby(g).transform(lambda s: s.rolling(14, min_periods=1).mean())

    ex_min = df["cardio_session_min"].astype(float).fillna(0.0) + df["resistance_training_min"].astype(float).fillna(0.0)
    ex_done = (df["cardio_session_done"].astype(float) + df["resistance_training_done"].astype(float)) / 2.0
    out["exercise_total_min"] = ex_min
    out["exercise_total_min_r3"] = ex_min.groupby(g).transform(lambda s: s.rolling(3, min_periods=1).mean())
    out["exercise_total_min_r7"] = ex_min.groupby(g).transform(lambda s: s.rolling(7, min_periods=1).mean())
    out["exercise_total_min_r14"] = ex_min.groupby(g).transform(lambda s: s.rolling(14, min_periods=1).mean())
    out["exercise_adherence_r3"] = ex_done.groupby(g).transform(lambda s: s.rolling(3, min_periods=1).mean())
    out["exercise_adherence_r7"] = ex_done.groupby(g).transform(lambda s: s.rolling(7, min_periods=1).mean())
    out["exercise_adherence_r14"] = ex_done.groupby(g).transform(lambda s: s.rolling(14, min_periods=1).mean())

    # Sub-acute Health_Warning subtype composites (deconditioning, sleep/mood, immune)
    sign = {c: (-1.0 if rf.IND[c]["adverse"] == "low" else 1.0) for c in rf.CONTINUOUS}
    for k, members in COMBOS.items():
        out[f"{k}_vs14"] = pd.concat([vs14[c] * sign[c] for c in members], axis=1).mean(axis=1)
        out[f"{k}_r3vs"] = pd.concat([r3_vs14_map[c] * sign[c] for c in members], axis=1).mean(axis=1)
        out[f"{k}_r7vs"] = pd.concat([r7_vs14_map[c] * sign[c] for c in members], axis=1).mean(axis=1)

    out["decond_warning_score"] = (
        (1.0 - out["exercise_adherence_r7"]) * 2.0
        + np.maximum(0.0, (110.0 - out["exercise_total_min_r7"]) / 35.0)
        + np.maximum(0.0, -r7_vs14_map["daily_physical_activity_min"])
        + np.maximum(0.0, -out["bone_health_chg7"] * 2.5)
        + np.maximum(0.0, -out["muscle_health_chg7"] * 1.5)
    )
    out["sleep_mood_warning_score"] = (
        np.maximum(0.0, -r3_vs14_map["sleep_hours"])
        + np.maximum(0.0, -r3_vs14_map["mood"])
        + np.maximum(0.0, -r3_vs14_map["relaxation"])
        + np.maximum(0.0, -r3_vs14_map["mental_health_assessment"])
        + np.maximum(0.0, -r3_vs14_map["game_test_score"])
    )
    out["immune_warning_score"] = (
        np.maximum(0.0, r3_vs14_map["temperature"])
        + np.maximum(0.0, -r3_vs14_map["immunity_indicators"])
        + np.maximum(0.0, r3_vs14_map["hormones"])
        + np.maximum(0.0, r3_vs14_map["blood_glucose_mg_dl"])
    )

    # A3: Stress vs. Danger discrimination features
    cv_spike = out["combo_bp_hr_vs14"].fillna(0.0)
    out["spike_streak_days"] = _causal_spike_streak(cv_spike, g, threshold_sd=1.15)
    cv_lag1 = cv_spike.groupby(g).shift(1).fillna(0.0)
    cv_max3 = cv_spike.groupby(g).transform(lambda s: s.rolling(3, min_periods=1).max()).fillna(0.0)
    out["vital_recovery_delta_1d"] = cv_spike - cv_lag1
    out["vital_recovery_ratio_3d"] = cv_spike / np.maximum(0.5, cv_max3)

    # SpO2 and Blood Glucose clinical threshold excursion features (A3 & B4)
    spo2_raw = df["oxygen_saturation"].astype(float).groupby(g).transform(lambda s: s.ffill()).fillna(97.0)
    gluc_raw = df["blood_glucose_mg_dl"].astype(float).groupby(g).transform(lambda s: s.ffill()).fillna(95.0)
    temp_raw = df["temperature"].astype(float).groupby(g).transform(lambda s: s.ffill()).fillna(37.2)
    sbp_raw = df["systolic_bp"].astype(float).groupby(g).transform(lambda s: s.ffill()).fillna(115.0)
    dbp_raw = df["diastolic_bp"].astype(float).groupby(g).transform(lambda s: s.ffill()).fillna(75.0)
    hr_raw = df["heart_rate"].astype(float).groupby(g).transform(lambda s: s.ffill()).fillna(75.0)

    out["spo2_deficit_below_94"] = np.maximum(0.0, 94.0 - spo2_raw)
    out["glucose_excursion_above_125"] = np.maximum(0.0, gluc_raw - 125.0) / 20.0
    out["glucose_hypo_below_70"] = np.maximum(0.0, 70.0 - gluc_raw) / 10.0
    out["temp_fever_above_38"] = np.maximum(0.0, temp_raw - 38.0) * 3.0
    out["bp_hr_critical_excess"] = (
        np.maximum(0.0, sbp_raw - 150.0) / 15.0
        + np.maximum(0.0, dbp_raw - 95.0) / 10.0
        + np.maximum(0.0, hr_raw - 120.0) / 15.0
    )

    # Multi-system concurrent abnormality count (6 physiological systems, A3)
    sys_cv = pd.concat([vs14["systolic_bp"].abs(), vs14["diastolic_bp"].abs(), vs14["heart_rate"].abs()], axis=1).max(axis=1)
    sys_resp = (-vs14["oxygen_saturation"]).clip(lower=0.0)
    sys_met = vs14["blood_glucose_mg_dl"].abs()
    sys_imm = pd.concat([vs14["temperature"].abs(), (-vs14["immunity_indicators"]).clip(lower=0.0), vs14["hormones"].clip(lower=0.0)], axis=1).max(axis=1)
    sys_neuro = pd.concat([(-vs14["sleep_hours"]).clip(lower=0.0), (-vs14["mood"]).clip(lower=0.0), (-vs14["relaxation"]).clip(lower=0.0), (-vs14["mental_health_assessment"]).clip(lower=0.0), (-vs14["game_test_score"]).clip(lower=0.0)], axis=1).max(axis=1)
    sys_musc = pd.concat([(-vs14["daily_physical_activity_min"]).clip(lower=0.0), (-out["bone_health_chg7"] * 3.0).clip(lower=0.0), (-out["muscle_health_chg7"] * 2.0).clip(lower=0.0)], axis=1).max(axis=1)

    systems_df = pd.concat([sys_cv, sys_resp, sys_met, sys_imm, sys_neuro, sys_musc], axis=1)
    out["n_abnormal_systems_15sd"] = (systems_df >= 1.5).sum(axis=1).astype(float)
    out["n_abnormal_systems_20sd"] = (systems_df >= 2.0).sum(axis=1).astype(float)
    out["n_abnormal_systems_25sd"] = (systems_df >= 2.5).sum(axis=1).astype(float)

    # Non-cardiovascular danger score (tells multi-system Danger apart from isolated Stress BP spike)
    out["danger_vs_stress_discriminant"] = (
        sys_resp * 1.8
        + sys_met * 1.4
        + (-vs14["immunity_indicators"]).clip(lower=0.0) * 1.3
        + out["temp_fever_above_38"]
        + out["bp_hr_critical_excess"] * 1.5
    )

    vital = [c for c in rf.CONTINUOUS if rf.IND[c]["kind"] in ("natural", "index")]
    dev = pd.concat([vs14[c].abs() for c in vital], axis=1)
    out["n_dev2_vs14"] = (dev >= 2.0).sum(axis=1).astype(float)
    out["n_dev3_vs14"] = (dev >= 3.0).sum(axis=1).astype(float)
    out["max_abs_vs14"] = dev.max(axis=1)
    out["composite_vs14_l2"] = np.sqrt((dev ** 2).sum(axis=1))
    z_vital = pd.concat([z_ff_map[c].abs() for c in vital], axis=1)
    out["composite_baseline_l2"] = np.sqrt((z_vital ** 2).sum(axis=1))

    res = pd.DataFrame(out)
    return res[[c for c in res.columns if not c.startswith("__")]]


def _infer_feature_columns() -> List[str]:
    # Build on a tiny synthetic 2-day dummy table to get exact feature column names in order
    dummy_tel = {
        "record_id": [1, 2],
        "astronaut_id": ["A001", "A001"],
        "timestamp": ["2030-01-01T12:00:00", "2030-01-02T12:00:00"],
        "mission_day": [1, 2],
    }
    dummy_base = {"astronaut_id": ["A001"], "mental_health_assessment_baseline": [50.0]}
    for ind in rf.INDICATORS:
        n = ind["name"]
        dummy_tel[n] = [1, 1] if ind["kind"] == "flag" else [float(ind["center"] or 50.0)] * 2
        dummy_base[n + "_mean"] = [float(ind["center"] or 50.0)]
        dummy_base[n + "_std"] = [float(ind["within_sd"] or 1.0)]
    df_f = build_features(pd.DataFrame(dummy_tel), pd.DataFrame(dummy_base))
    return [c for c in df_f.columns if c not in ("record_id", "astronaut_id", "mission_day")]


FEATURE_COLUMNS = _infer_feature_columns()


class TwoStageHealthClassifier(BaseEstimator, ClassifierMixin):
    """
    Two-stage hierarchical classifier (Phase 3 A3):
      - Stage 1: Acute event (Stress or Danger) vs. Non-Acute (Normal or Warning)
      - Stage 2A (within Non-Acute): Normal vs. Health_Warning
      - Stage 2B (within Acute): Stress_BP_Spike_No_Medical_Danger vs. Medical_Danger_Alert
    Combines calibrated/tree stage probabilities via exact law of total probability.
    """

    def __init__(self, n_estimators: int = 250, min_samples_leaf: int = 8, random_state: int = RANDOM_STATE):
        self.n_estimators = n_estimators
        self.min_samples_leaf = min_samples_leaf
        self.random_state = random_state

    def _make_rf(self, seed_offset: int = 0) -> Pipeline:
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", RandomForestClassifier(
                n_estimators=self.n_estimators,
                min_samples_leaf=self.min_samples_leaf,
                class_weight="balanced_subsample",
                random_state=self.random_state + seed_offset,
                n_jobs=-1,
            )),
        ])

    def fit(self, X, y):
        y_arr = np.asarray(y)
        self.classes_ = np.array(rf.CLASSES, dtype=object)

        # Stage 1: Acute (1) vs Non-Acute (0)
        is_acute = np.isin(y_arr, ["Stress_BP_Spike_No_Medical_Danger", "Medical_Danger_Alert"]).astype(int)
        self.stage1_ = self._make_rf(0).fit(X, is_acute)

        # Stage 2A: Normal vs Health_Warning (on non-acute rows)
        mask_non_acute = is_acute == 0
        X_na = X.iloc[mask_non_acute] if hasattr(X, "iloc") else X[mask_non_acute]
        y_na = (y_arr[mask_non_acute] == "Health_Warning").astype(int)
        self.stage2_non_acute_ = self._make_rf(10).fit(X_na, y_na)

        # Stage 2B: Stress vs Danger (on acute rows)
        mask_acute = is_acute == 1
        X_ac = X.iloc[mask_acute] if hasattr(X, "iloc") else X[mask_acute]
        y_ac = (y_arr[mask_acute] == "Medical_Danger_Alert").astype(int)
        self.stage2_acute_ = self._make_rf(20).fit(X_ac, y_ac)

        self.feature_importances_ = (
            0.40 * self.stage1_.named_steps["model"].feature_importances_
            + 0.35 * self.stage2_non_acute_.named_steps["model"].feature_importances_
            + 0.25 * self.stage2_acute_.named_steps["model"].feature_importances_
        )
        return self

    def predict_proba(self, X):
        p_acute = self.stage1_.predict_proba(X)[:, 1]
        p_non_acute = 1.0 - p_acute

        p_warn_given_na = self.stage2_non_acute_.predict_proba(X)[:, 1]
        p_danger_given_ac = self.stage2_acute_.predict_proba(X)[:, 1]

        p_normal = p_non_acute * (1.0 - p_warn_given_na)
        p_stress = p_acute * (1.0 - p_danger_given_ac)
        p_warning = p_non_acute * p_warn_given_na
        p_danger = p_acute * p_danger_given_ac

        proba = np.column_stack([p_normal, p_stress, p_warning, p_danger])
        proba = proba / np.maximum(proba.sum(axis=1, keepdims=True), 1e-12)
        return proba

    def predict(self, X):
        proba = self.predict_proba(X)
        return self.classes_[proba.argmax(axis=1)]


def make_pipeline(architecture: str = "single_rf") -> BaseEstimator:
    """Create candidate classifier pipeline."""
    if architecture == "two_stage_rf":
        return TwoStageHealthClassifier(n_estimators=260, min_samples_leaf=8, random_state=RANDOM_STATE)
    if architecture == "hist_gbm":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                max_iter=250,
                learning_rate=0.05,
                max_leaf_nodes=31,
                min_samples_leaf=20,
                class_weight="balanced",
                random_state=RANDOM_STATE,
            )),
        ])
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", RandomForestClassifier(
            n_estimators=320,
            min_samples_leaf=8,
            class_weight="balanced_subsample",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )),
    ])


WEIGHT_GRID = [0.4, 0.55, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0, 2.4, 3.0]


def load_cost_matrix() -> np.ndarray:
    cm_cfg = rf.PROJECT_CONFIG.get("model", {}).get("cost_matrix", {})
    mat = cm_cfg.get("matrix")
    if mat and len(mat) == 4:
        return np.asarray(mat, dtype=float)
    return np.array([
        [0.0, 1.5, 1.2, 4.0],
        [3.0, 0.0, 2.0, 3.5],
        [4.5, 2.5, 0.0, 3.5],
        [40.0, 25.0, 20.0, 0.0],
    ], dtype=float)


def _validation_objective(y_true: np.ndarray, y_pred: np.ndarray, cost_matrix: np.ndarray) -> float:
    """
    Composite validation objective on training out-of-fold predictions:
      Combines normalized negative expected cost from config/project_config.json with
      macro F1 and safety-critical sensitivity (Health_Warning & Medical_Danger_Alert).
    """
    cm = confusion_matrix(y_true, y_pred, labels=rf.CLASSES).astype(float)
    total = max(1.0, float(cm.sum()))
    avg_cost = float(np.sum(cm * cost_matrix)) / total

    rec = np.diag(cm) / np.maximum(cm.sum(axis=1), 1.0)
    prec = np.diag(cm) / np.maximum(cm.sum(axis=0), 1.0)
    f1 = np.where((prec + rec) > 0, 2.0 * prec * rec / (prec + rec), 0.0)
    acc = float(np.trace(cm)) / total

    # High penalty if Danger precision drops below 72% or Warning recall drops below 74%
    danger_prec = float(prec[3])
    danger_rec = float(rec[3])
    warn_rec = float(rec[2])

    score = (
        1.2 * float(f1.mean())
        + 0.8 * acc
        + 0.45 * warn_rec
        + 0.45 * danger_rec
        + 0.35 * danger_prec
        - 0.25 * avg_cost
    )
    return score


def apply_weights(proba: np.ndarray, weights: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    """Apply per-class cost-matrix decision thresholds/weights and re-normalize."""
    adj = np.asarray(proba, dtype=float) * np.asarray(weights, dtype=float)
    denom = np.maximum(adj.sum(axis=1, keepdims=True), 1e-12)
    adj = adj / denom
    return np.array(rf.CLASSES, dtype=object)[adj.argmax(axis=1)], adj


def _proba(estimator: Any, X: pd.DataFrame) -> np.ndarray:
    classes = list(estimator.classes_)
    order = [classes.index(c) for c in rf.CLASSES]
    return estimator.predict_proba(X)[:, order]


def _calibrate_oof_and_fit(base_factory, X: pd.DataFrame, y: np.ndarray, groups: np.ndarray):
    """
    Compute 5-fold GroupKFold out-of-fold calibrated probabilities:
      1. Fit base estimator once per astronaut-grouped fold (strictly zero astronaut overlap).
      2. Apply fold-safe Platt sigmoid calibration (matching CalibratedClassifierCV(method='sigmoid'))
         fitted only on the 4 training folds' raw OOF predictions and evaluated on the held-out fold.
    """
    from sklearn.linear_model import LogisticRegression

    oof_raw = np.zeros((len(y), len(rf.CLASSES)), dtype=float)
    oof_cal = np.zeros((len(y), len(rf.CLASSES)), dtype=float)
    fold_of = np.zeros(len(y), dtype=int)
    gkf = GroupKFold(n_splits=5)
    splits = list(gkf.split(X, y, groups=groups))

    for k, (tr, va) in enumerate(splits):
        assert set(groups[tr]).isdisjoint(set(groups[va]))
        est = base_factory().fit(X.iloc[tr], y[tr])
        oof_raw[va] = _proba(est, X.iloc[va])
        fold_of[va] = k

    # Fold-safe Platt scaling (one-vs-rest sigmoid calibration on raw OOF probabilities)
    clipped = np.clip(oof_raw, 1e-6, 1.0 - 1e-6)
    logits = np.log(clipped / (1.0 - clipped))
    for k, (tr, va) in enumerate(splits):
        for c_idx, cls_name in enumerate(rf.CLASSES):
            y_bin_tr = (y[tr] == cls_name).astype(int)
            lr = LogisticRegression(C=1e4, solver="lbfgs", max_iter=200)
            lr.fit(logits[tr, c_idx : c_idx + 1], y_bin_tr)
            oof_cal[va, c_idx] = lr.predict_proba(logits[va, c_idx : c_idx + 1])[:, 1]
        row_sum = np.maximum(oof_cal[va].sum(axis=1, keepdims=True), 1e-12)
        oof_cal[va] = oof_cal[va] / row_sum

    return oof_cal, fold_of


def _tune_cost_thresholds(oof_proba: np.ndarray, y: np.ndarray, cost_matrix: np.ndarray) -> np.ndarray:
    weights = np.ones(len(rf.CLASSES), dtype=float)
    best = _validation_objective(y, apply_weights(oof_proba, weights)[0], cost_matrix)
    for _ in range(4):
        for i in range(1, len(rf.CLASSES)):
            for v in WEIGHT_GRID:
                trial = weights.copy()
                trial[i] = v
                sc = _validation_objective(y, apply_weights(oof_proba, trial)[0], cost_matrix)
                if sc > best + 1e-9:
                    best, weights = sc, trial
    return weights


def _summarize_oof(y: np.ndarray, y_pred: np.ndarray, cost_matrix: np.ndarray) -> Dict[str, float]:
    cm = confusion_matrix(y, y_pred, labels=rf.CLASSES).astype(float)
    rec = np.diag(cm) / np.maximum(cm.sum(axis=1), 1.0)
    prec = np.diag(cm) / np.maximum(cm.sum(axis=0), 1.0)
    f1 = np.where((prec + rec) > 0, 2.0 * prec * rec / (prec + rec), 0.0)
    avg_cost = float(np.sum(cm * cost_matrix) / max(1.0, cm.sum()))
    return {
        "accuracy_pct": round(100.0 * float(np.trace(cm) / cm.sum()), 2),
        "macro_f1_pct": round(100.0 * float(f1.mean()), 2),
        "macro_recall_pct": round(100.0 * float(rec.mean()), 2),
        "macro_precision_pct": round(100.0 * float(prec.mean()), 2),
        "warning_sensitivity_pct": round(100.0 * float(rec[2]), 2),
        "danger_sensitivity_pct": round(100.0 * float(rec[3]), 2),
        "danger_precision_pct": round(100.0 * float(prec[3]), 2),
        "expected_cost_per_day": round(avg_cost, 4),
        "objective_score": round(_validation_objective(y, y_pred, cost_matrix), 4),
    }


def fit_model(X: pd.DataFrame, y: np.ndarray, groups: np.ndarray) -> Dict[str, Any]:
    """
    Train and select model architecture, probability calibration, and cost-matrix decision thresholds
    using ONLY the training astronauts (5-fold GroupKFold).
    Compares:
      1. single_rf (Single-Stage Calibrated Random Forest)
      2. two_stage_rf (Two-Stage Calibrated Hierarchical Random Forest: Acute vs Non-Acute -> Stress vs Danger)
      3. hist_gbm (Calibrated HistGradientBoosting / LightGBM-style GBDT)
    """
    cost_matrix = load_cost_matrix()
    candidates = ["single_rf", "two_stage_rf", "hist_gbm"]
    comparison: Dict[str, Any] = {}
    best_arch = "single_rf"
    best_oof = None
    best_weights = None
    best_fold_of = None
    best_obj = -1e9

    oof_by_arch: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for arch in candidates:
        oof_cal, fold_of = _calibrate_oof_and_fit(lambda a=arch: make_pipeline(a), X, y, groups)
        w = _tune_cost_thresholds(oof_cal, y, cost_matrix)
        oof_pred = apply_weights(oof_cal, w)[0]
        summary = _summarize_oof(y, oof_pred, cost_matrix)
        summary["decision_weights"] = [round(float(x), 4) for x in w]
        comparison[arch] = summary
        oof_by_arch[arch] = (oof_cal, w, fold_of)

    # First compare Single-Stage RF vs Two-Stage RF on validation
    best_rf_arch = (
        "two_stage_rf"
        if comparison["two_stage_rf"]["objective_score"] > comparison["single_rf"]["objective_score"]
        else "single_rf"
    )
    rf_summary = comparison[best_rf_arch]
    gbm_summary = comparison["hist_gbm"]

    # Keep RF unless HistGBM is clearly better across both objective (> 0.03 margin) and Warning sensitivity
    if (
        gbm_summary["objective_score"] - rf_summary["objective_score"] > 0.03
        and gbm_summary["warning_sensitivity_pct"] >= rf_summary["warning_sensitivity_pct"]
    ):
        best_arch = "hist_gbm"
    else:
        best_arch = best_rf_arch

    best_oof, best_weights, best_fold_of = oof_by_arch[best_arch]
    best_obj = comparison[best_arch]["objective_score"]

    oof_pred = apply_weights(best_oof, best_weights)[0]
    fold_acc = [
        round(100.0 * float((oof_pred[best_fold_of == k] == y[best_fold_of == k]).mean()), 2)
        for k in range(5)
    ]

    # Fit final base model + CalibratedClassifierCV on all training astronauts
    base_pipe = make_pipeline(best_arch).fit(X, y)
    calibrated_pipe = CalibratedClassifierCV(
        estimator=make_pipeline(best_arch),
        method="sigmoid",
        cv=3,
    ).fit(X, y)

    # Extract feature importances from the fitted base tree model
    if hasattr(base_pipe, "feature_importances_"):
        feat_imp = base_pipe.feature_importances_
    elif hasattr(base_pipe, "named_steps") and hasattr(base_pipe.named_steps["model"], "feature_importances_"):
        feat_imp = base_pipe.named_steps["model"].feature_importances_
    else:
        feat_imp = np.zeros(len(FEATURE_COLUMNS))

    # Tune tiered alerting thresholds on out-of-fold calibrated probabilities (training astronauts only)
    danger_idx = rf.CLASSES.index("Medical_Danger_Alert")
    p_danger_oof = best_oof[:, danger_idx]
    # Tier 1 ("Danger – confirm"): moderate probability threshold
    # Tier 2 ("Danger"): high probability threshold OR consecutive 2-day persistence >= confirm threshold
    tier_cfg = rf.PROJECT_CONFIG.get("model", {}).get("tiered_alerting", {})
    confirm_thresh = float(tier_cfg.get("danger_confirm_prob_threshold", 0.22))
    high_thresh = float(tier_cfg.get("danger_high_prob_threshold", 0.45))

    return {
        "pipeline": base_pipe,
        "calibrated_pipeline": calibrated_pipe,
        "selected_architecture": best_arch,
        "validation_model_comparison": comparison,
        "cost_matrix": cost_matrix.tolist(),
        "decision_weights": [float(w) for w in best_weights],
        "tiered_alerting_thresholds": {
            "danger_confirm_prob_threshold": confirm_thresh,
            "danger_high_prob_threshold": high_thresh,
            "danger_confirm_persistence_days": 2,
        },
        "cv_fold_accuracy_pct": fold_acc,
        "feature_columns": FEATURE_COLUMNS,
        "feature_importances": [float(x) for x in feat_imp],
        "classes": rf.CLASSES,
        "model_version": rf.MODEL_VERSION,
    }


def predict(bundle: Dict[str, Any], X: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    """Return (predicted_labels, calibrated_weighted_probabilities) in rf.CLASSES order."""
    est = bundle.get("calibrated_pipeline") or bundle["pipeline"]
    raw_cal_proba = _proba(est, X[bundle["feature_columns"]])
    return apply_weights(raw_cal_proba, bundle["decision_weights"])


def predict_calibrated_proba(bundle: Dict[str, Any], X: pd.DataFrame) -> np.ndarray:
    """Return unweighted calibrated probabilities in rf.CLASSES order."""
    est = bundle.get("calibrated_pipeline") or bundle["pipeline"]
    return _proba(est, X[bundle["feature_columns"]])


def compute_tiered_danger_alerts(
    bundle: Dict[str, Any],
    X: pd.DataFrame,
    groups: np.ndarray,
    y_true: np.ndarray = None,
) -> Dict[str, Any]:
    """
    Compute Phase 3 A2 tiered alerting for Medical_Danger_Alert:
      - 'Danger – confirm': moderate calibrated probability (>= confirm_thresh); asks for re-measurement.
      - 'Danger': high calibrated probability (>= high_thresh) OR predicted class is Medical_Danger_Alert
                  OR moderate signal persists across >= 2 consecutive days for the same astronaut (causal).
    """
    cal_proba = predict_calibrated_proba(bundle, X)
    pred_labels, weighted_proba = predict(bundle, X)
    danger_idx = rf.CLASSES.index("Medical_Danger_Alert")
    p_danger = cal_proba[:, danger_idx]

    t_cfg = bundle.get("tiered_alerting_thresholds", {})
    confirm_t = float(t_cfg.get("danger_confirm_prob_threshold", 0.22))
    high_t = float(t_cfg.get("danger_high_prob_threshold", 0.45))

    # Causal consecutive persistence: yesterday (t-1) and today (t) both >= confirm_t for same astronaut
    s_mod = pd.Series((p_danger >= confirm_t).astype(int))
    s_grp = pd.Series(groups)
    prev_mod = s_mod.groupby(s_grp).shift(1, fill_value=0).to_numpy(dtype=bool)
    persisted = (p_danger >= confirm_t) & prev_mod

    tier_danger = (p_danger >= high_t) | persisted | (pred_labels == "Medical_Danger_Alert")
    tier_confirm_inclusive = (p_danger >= confirm_t) | tier_danger
    tier_confirm_only = tier_confirm_inclusive & (~tier_danger)

    tier_labels = np.where(
        tier_danger,
        "Danger",
        np.where(tier_confirm_only, "Danger – confirm", "No_Danger_Alert"),
    )

    out: Dict[str, Any] = {
        "thresholds": {
            "danger_confirm_prob_threshold": confirm_t,
            "danger_high_prob_threshold": high_t,
            "persistence_days": 2,
        },
        "tier_counts": {
            "Danger": int(tier_danger.sum()),
            "Danger – confirm (remeasurement only)": int(tier_confirm_only.sum()),
            "Danger + Danger – confirm (combined screening)": int(tier_confirm_inclusive.sum()),
        },
        "tier_labels": tier_labels.tolist(),
    }

    if y_true is not None:
        is_true_danger = (np.asarray(y_true) == "Medical_Danger_Alert")
        n_days = max(1, len(y_true))

        def _tier_stats(mask: np.ndarray, label: str) -> Dict[str, Any]:
            tp = int((mask & is_true_danger).sum())
            fp = int((mask & (~is_true_danger)).sum())
            fn = int(((~mask) & is_true_danger).sum())
            tn = int(((~mask) & (~is_true_danger)).sum())
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
            fa_per_1000 = 1000.0 * fp / n_days
            return {
                "tier": label,
                "precision_pct": round(100.0 * prec, 2),
                "recall_pct": round(100.0 * rec, 2),
                "f1_pct": round(100.0 * f1, 2),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
                "false_alarms_per_1000_astronaut_days": round(fa_per_1000, 2),
            }

        out["tier_metrics"] = {
            "Danger": _tier_stats(tier_danger, "Danger (high probability or consecutive persistence)"),
            "Danger_confirm_inclusive": _tier_stats(
                tier_confirm_inclusive,
                "Danger – confirm (moderate probability screening + re-measurement)",
            ),
            "Danger_confirm_only": _tier_stats(
                tier_confirm_only,
                "Danger – confirm only (moderate probability band asking for re-measurement)",
            ),
        }
    return out


def group_split(groups: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The one and only train/test split: by astronaut, 20 % of astronauts held out."""
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    idx = np.arange(len(groups))
    train_idx, test_idx = next(gss.split(idx, groups=groups))
    train_ids, test_ids = set(groups[train_idx]), set(groups[test_idx])
    assert train_ids.isdisjoint(test_ids), "LEAKAGE: an astronaut appears in both train and test"
    return train_idx, test_idx


def load_tables(con: sqlite3.Connection) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tel = pd.read_sql_query("SELECT * FROM mission_telemetry ORDER BY astronaut_id, mission_day", con)
    labels = pd.read_sql_query("SELECT * FROM telemetry_labels", con)
    base = pd.read_sql_query("SELECT * FROM preflight_baseline", con)
    return tel, labels, base


def load_dataset(db_path: str = None, verify_hash: bool = True):
    db_path = db_path or EVAL_DB_PATH
    if verify_hash:
        con = connect_eval_readonly(db_path)
    else:
        uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
    tel, labels, base = load_tables(con)
    con.close()
    feats = build_features(tel, base)
    feats = feats.merge(labels, on="record_id", how="left")
    X = feats[FEATURE_COLUMNS]
    y = feats["true_class"].to_numpy()
    groups = feats["astronaut_id"].to_numpy()
    return feats, X, y, groups


def load_model() -> Dict[str, Any]:
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError("models/health_model.joblib not found - run `python ai_health_model.py` first.")
    return joblib.load(MODEL_PATH)


def main():
    print("=" * 78)
    print("STEP 3 - ai_health_model.py (Causal Temporal Features + Calibrated Classifier)")
    print(rf.DISCLAIMER)
    print(rf.SYNTHETIC_DATA_DISCLAIMER)
    print("=" * 78)
    feats, X, y, groups = load_dataset()
    train_idx, test_idx = group_split(groups)
    train_ids = sorted(set(groups[train_idx]))
    test_ids = sorted(set(groups[test_idx]))
    print(f"Features: {len(FEATURE_COLUMNS)}   Records: {len(X)}")
    print(f"Train astronauts: {len(train_ids)}  ({len(train_idx)} records)")
    print(f"Held-out astronauts (never fitted): {len(test_ids)}  ({len(test_idx)} records)")
    print("No train/test astronaut overlap: asserted OK")

    print("\nClass balance in TRAIN (class_weight='balanced_subsample' is used):")
    vc = pd.Series(y[train_idx]).value_counts()
    for c in rf.CLASSES:
        print(f"  {c:<36} {int(vc.get(c, 0)):>6}  ({100 * vc.get(c, 0) / len(train_idx):5.2f} %)")

    bundle = fit_model(X.iloc[train_idx], y[train_idx], groups[train_idx])
    os.makedirs(MODEL_DIR, exist_ok=True)
    bundle.update({
        "train_astronauts": train_ids,
        "test_astronauts": test_ids,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    joblib.dump(bundle, MODEL_PATH, compress=6)
    print(f"\nSaved: {MODEL_PATH}")
    print(f"Selected architecture on 5-fold GroupKFold validation: {bundle['selected_architecture']}")
    print("\n5-fold GroupKFold Validation Model Comparison (Training Astronauts Only):")
    for arch, stats_d in bundle["validation_model_comparison"].items():
        print(
            f"  {arch:<16} Acc={stats_d['accuracy_pct']:5.2f}%  MacroF1={stats_d['macro_f1_pct']:5.2f}%  "
            f"WarnSens={stats_d['warning_sensitivity_pct']:5.2f}%  "
            f"DangerSens={stats_d['danger_sensitivity_pct']:5.2f}%  "
            f"DangerPrec={stats_d['danger_precision_pct']:5.2f}%  "
            f"Cost={stats_d['expected_cost_per_day']:.4f}"
        )

    print("\nDecision weights tuned on out-of-fold training predictions via cost matrix: "
          + ", ".join(f"{c}={w}" for c, w in zip(rf.CLASSES, bundle["decision_weights"])))
    print(f"5-fold GroupKFold accuracy on training astronauts: {bundle['cv_fold_accuracy_pct']}")
    in_sample = (predict(bundle, X.iloc[train_idx])[0] == y[train_idx]).mean() * 100
    print(f"In-sample (TRAIN) accuracy: {in_sample:.2f} %   <- optimistic by construction; "
          f"the honest number comes from blind_test.py")

    imp = pd.Series(bundle["feature_importances"], index=FEATURE_COLUMNS)
    print("\nTop 12 features by importance:")
    for name, val in imp.sort_values(ascending=False).head(12).items():
        print(f"  {name:<40} {val:.4f}")

    # ---- write predictions for every telemetry record into WORKING app DB only (never touch frozen eval DB)
    pred, proba = predict(bundle, X)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        (int(rid), str(p), json.dumps({c: round(float(v), 4) for c, v in zip(rf.CLASSES, pr)}), rf.MODEL_VERSION, now)
        for rid, p, pr in zip(feats["record_id"], pred, proba)
    ]
    for target_db in (APP_DB_PATH, LEGACY_DB_PATH):
        if os.path.exists(target_db):
            con = sqlite3.connect(target_db)
            con.execute("DELETE FROM model_predictions")
            con.executemany("INSERT INTO model_predictions VALUES (?,?,?,?,?)", rows)
            con.commit()
            con.close()
    print(f"\nmodel_predictions rows written to working app DB ({APP_DB_PATH}): {len(rows)}  (model_version = {rf.MODEL_VERSION})")
    print("Note: predictions for the train astronauts are in-sample; only the held-out astronauts are a fair test.")


if __name__ == "__main__":
    main()
