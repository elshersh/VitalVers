"""Startup-loaded AI model service backed by models/health_model.joblib and 07_health_indicators_schema.json."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

import numpy as np
import pandas as pd

import ai_health_model as aim
import health_engine as he
import resource_facts as rf
from backend.config import MODEL_PATH, SCHEMA_PATH

UI_STATUS_BY_CLASS = {
    "Normal": "normal",
    "Stress_BP_Spike_No_Medical_Danger": "watch",
    "Health_Warning": "watch",
    "Medical_Danger_Alert": "alert",
}

DISPLAY_LABEL_BY_CLASS = {
    "Normal": "Normal",
    "Stress_BP_Spike_No_Medical_Danger": "Stress Spike",
    "Health_Warning": "Health Warning",
    "Medical_Danger_Alert": "Medical Danger Alert",
}


class ModelService:
    """Loads models/health_model.joblib once at startup and serves 180-day inference."""

    def __init__(self) -> None:
        if not MODEL_PATH.is_file():
            raise FileNotFoundError(f"Missing model artifact: {MODEL_PATH}")
        aim.MODEL_PATH = str(MODEL_PATH)
        self.bundle = aim.load_model()
        # Single-astronaut requests should avoid joblib/OpenMP worker pool startup cost.
        for key in ("pipeline", "calibrated_pipeline"):
            pipe = self.bundle.get(key)
            if pipe is not None and hasattr(pipe, "named_steps") and "model" in pipe.named_steps:
                est = pipe.named_steps["model"]
                if hasattr(est, "n_jobs"):
                    est.n_jobs = 1
        he._BUNDLE = self.bundle
        self.schema_badges = self._load_schema_badges()

    @staticmethod
    def _load_schema_badges() -> dict[str, dict[str, Any]]:
        if not SCHEMA_PATH.is_file():
            return {}
        doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        badges: dict[str, dict[str, Any]] = {}
        for item in doc.get("indicators", []):
            col = item.get("telemetry_column") or item.get("name")
            if not col:
                continue
            badges[col] = {
                "display_name": item.get("display_name", col),
                "unit": item.get("unit", ""),
                "ui_badge": item.get("ui_badge", "Placeholder"),
                "verification_status": item.get("verification_status", "UNVERIFIED"),
                "alert_thresholds": item.get("alert_thresholds") or {},
            }
        return badges

    def predict_astronaut_timeline(
        self,
        con: sqlite3.Connection,
        astronaut_id: str,
        max_day: int | None = None,
    ) -> dict[str, Any]:
        """Run startup-loaded health_model.joblib inference across an astronaut's mission days."""
        aid = str(astronaut_id).strip().upper()
        base_df = pd.read_sql_query("SELECT * FROM preflight_baseline WHERE astronaut_id = ?", con, params=(aid,))
        if base_df.empty:
            raise ValueError(f"Unknown astronaut baseline: {aid}")

        query = "SELECT * FROM mission_telemetry WHERE astronaut_id = ?"
        params: list[Any] = [aid]
        if max_day is not None:
            query += " AND mission_day <= ?"
            params.append(int(max_day))
        query += " ORDER BY mission_day ASC"

        tel_df = pd.read_sql_query(query, con, params=params)
        if tel_df.empty:
            return {
                "astronaut_id": aid,
                "model_version": self.bundle.get("model_version", rf.MODEL_VERSION),
                "selected_architecture": self.bundle.get("selected_architecture", "unknown"),
                "total_days": 0,
                "latest": None,
                "predictions": [],
            }

        feats = aim.build_features(tel_df, base_df)
        pred_labels, weighted_proba = aim.predict(self.bundle, feats)
        groups = feats["astronaut_id"].to_numpy()
        tiered = aim.compute_tiered_danger_alerts(self.bundle, feats, groups)
        tier_labels = tiered["tier_labels"]

        rows: list[dict[str, Any]] = []
        classes = list(rf.CLASSES)
        for idx, row in enumerate(tel_df.itertuples(index=False)):
            cls_name = str(pred_labels[idx])
            probs = {c: round(float(weighted_proba[idx][ci]), 4) for ci, c in enumerate(classes)}
            tier = str(tier_labels[idx])
            rows.append(
                {
                    "record_id": int(row.record_id),
                    "mission_day": int(row.mission_day),
                    "recorded_at": str(row.timestamp),
                    "predicted_class": cls_name,
                    "status_label": DISPLAY_LABEL_BY_CLASS.get(cls_name, cls_name),
                    "ui_status": UI_STATUS_BY_CLASS.get(cls_name, "watch"),
                    "confidence": round(float(max(weighted_proba[idx])), 4),
                    "class_probabilities": probs,
                    "danger_tier": tier,
                }
            )

        latest = rows[-1]
        return {
            "astronaut_id": aid,
            "model_version": self.bundle.get("model_version", rf.MODEL_VERSION),
            "selected_architecture": self.bundle.get("selected_architecture", "single_rf"),
            "total_days": len(rows),
            "latest": latest,
            "predictions": rows,
        }
