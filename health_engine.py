"""
health_engine.py — analytical functions + the Python interface for teammates.

Every public function returns a JSON-serializable dict (summary_report returns a str).
Every dict carries the disclaimer. Advice text comes ONLY from the `countermeasures` table.

Prototype for research/education only — not for clinical diagnosis.
"""
import functools
import json
import math
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from scipy import stats

import ai_health_model as aim
import resource_facts as rf

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = aim.APP_DB_PATH
AUTH_CONFIG_PATH = os.path.join(HERE, "config", "demo_credentials.json")
_BUNDLE = None
_AUTH_CFG = None
_PH = PasswordHasher(time_cost=2, memory_cost=4096, parallelism=2)
_SEVERITY = {"green": 0, "yellow": 1, "red": 2}
_ZONE_SKIP_Z = {"bone_health", "muscle_health", "cardio_session_min", "resistance_training_min"}
TASKS = {
    "cardio_session": {"done": "cardio_session_done", "minutes": "cardio_session_min"},
    "resistance_training": {"done": "resistance_training_done", "minutes": "resistance_training_min"},
    "daily_physical_activity": {"done": None, "minutes": "daily_physical_activity_min"},
}
SIMPLE_STATUS = {
    "Normal": "OK - no alert from the model.",
    "Stress_BP_Spike_No_Medical_Danger": "Stress spike - no medical danger flagged. A calming action is suggested.",
    "Health_Warning": "Health warning - please review the highlighted body zones.",
    "Medical_Danger_Alert": "MEDICAL DANGER ALERT - notify Earth doctors and the flight surgeon now.",
}
CLASS_AREA = {"Stress_BP_Spike_No_Medical_Danger": "Stress", "Health_Warning": "Health_Warning",
              "Medical_Danger_Alert": "Medical_Danger"}
EDITABLE_PROFILE_FIELDS =[f[0] for f in rf.PROFILE_FIELDS if f[0] != "astronaut_id"]


# ============================================================================= helpers
def _con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _auth_cfg():
    global _AUTH_CFG
    if _AUTH_CFG is None:
        with open(AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
            _AUTH_CFG = json.load(f)
    return _AUTH_CFG


def _now_utc(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        dt = datetime.fromisoformat(now)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    raise ValueError("Invalid timestamp for now")


def _verify_password_hash(password: str, stored_hash: str) -> bool:
    if not isinstance(password, str) or not password:
        return False
    if stored_hash.startswith("$argon2"):
        try:
            return _PH.verify(stored_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    return False


def astronaut_exists(astronaut_id: str) -> bool:
    con = _con()
    row = con.execute("SELECT 1 FROM astronaut_profile WHERE astronaut_id = ?", (str(astronaut_id).strip().upper(),)).fetchone()
    con.close()
    return row is not None


def _enforce_session(session_token, target_astronaut_id=None, now=None):
    if session_token is None:
        return None
    con = _con()
    row = con.execute("SELECT * FROM auth_sessions WHERE token = ?", (str(session_token),)).fetchone()
    con.close()
    if row is None or int(row["revoked"]) != 0:
        raise ValueError("Invalid or revoked session token.")
    cur_now = _now_utc(now)
    exp = _now_utc(row["expires_at"])
    if cur_now >= exp:
        raise ValueError("Session token has expired.")
    role = row["role"]
    uid = row["user_id"]
    if role == "astronaut":
        if target_astronaut_id is None:
            raise ValueError("Access denied: crew-wide view requires flight_surgeon role.")
        if str(target_astronaut_id).strip().upper() != uid:
            raise ValueError(f"Access denied: astronaut {uid} cannot view records of {target_astronaut_id}.")
    elif role != "flight_surgeon":
        raise ValueError(f"Unknown role: {role}")
    return {"user_id": uid, "role": role, "expires_at": row["expires_at"]}


def _bundle():
    global _BUNDLE
    if _BUNDLE is None:
        _BUNDLE = aim.load_model()
        try:
            _BUNDLE["pipeline"].named_steps["model"].n_jobs = 1   # single readings: avoid thread start-up cost
        except (KeyError, AttributeError):
            pass
    return _BUNDLE


def _clean(obj):
    """Make any nested structure JSON-serializable (NaN -> None, numpy -> python)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if obj is pd.NA:
        return None
    return obj


def _r(x, nd=2):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else round(f, nd)


def api(fn):
    """Public-function wrapper: JSON-safe output, disclaimer on every dict, errors as {'ok': False}."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            out = fn(*args, **kwargs)
        except (ValueError, FileNotFoundError) as e:
            msg = e.args[0] if e.args else str(e)
            return {
                "ok": False,
                "error": str(msg),
                "disclaimer": rf.DISCLAIMER,
                "synthetic_data_disclaimer": rf.SYNTHETIC_DATA_DISCLAIMER,
                "dashboard_footer": f"{rf.DISCLAIMER} {rf.SYNTHETIC_DATA_DISCLAIMER}",
            }
        if isinstance(out, dict):
            out.setdefault("ok", True)
            out["disclaimer"] = rf.DISCLAIMER
            out["synthetic_data_disclaimer"] = rf.SYNTHETIC_DATA_DISCLAIMER
            out["dashboard_footer"] = f"{rf.DISCLAIMER} {rf.SYNTHETIC_DATA_DISCLAIMER}"
            return _clean(out)
        return out
    return wrapper


def _profile(astronaut_id):
    con = _con()
    row = con.execute("SELECT * FROM astronaut_profile WHERE astronaut_id = ?", (str(astronaut_id),)).fetchone()
    con.close()
    if row is None:
        raise ValueError(f"Unknown astronaut_id: {astronaut_id!r}")
    return dict(row)


def _baseline_df(astronaut_id):
    con = _con()
    df = pd.read_sql_query("SELECT * FROM preflight_baseline WHERE astronaut_id = ?", con, params=(astronaut_id,))
    con.close()
    if df.empty:
        raise ValueError(f"No pre-flight baseline for astronaut_id: {astronaut_id!r}")
    return df


def _history(astronaut_id, upto_day=None):
    con = _con()
    q = "SELECT * FROM mission_telemetry WHERE astronaut_id = ?"
    params = [astronaut_id]
    if upto_day is not None:
        q += " AND mission_day <= ?"
        params.append(int(upto_day))
    df = pd.read_sql_query(q + " ORDER BY mission_day", con, params=params)
    con.close()
    if df.empty:
        raise ValueError(f"No telemetry for astronaut_id: {astronaut_id!r}")
    return df


def _countermeasures(problem_area, trigger=None, allow_fallback=True):
    con = _con()
    q = "SELECT * FROM countermeasures WHERE problem_area = ?"
    params = [problem_area]
    if trigger:
        q += " AND trigger_condition = ?"
        params.append(trigger)
    rows = [dict(r) for r in con.execute(q, params).fetchall()]
    con.close()
    if not rows and allow_fallback and trigger != "resource_context":
        is_danger = "danger" in str(problem_area).lower() or (trigger and "danger" in str(trigger).lower())
        fallback_text = (
            "Contact flight surgeon immediately. " + rf.SAFE_COUNTERMEASURE_FALLBACK
            if is_danger and not rf.SAFE_COUNTERMEASURE_FALLBACK.startswith("Contact flight surgeon immediately")
            else rf.SAFE_COUNTERMEASURE_FALLBACK
        )
        return [{
            "countermeasure_id": -1,
            "problem_area": problem_area,
            "trigger_condition": trigger or "fallback",
            "advice_text": fallback_text,
            "resource_name": "safe_fallback",
            "resource_location": "health_engine.py safe fallback (Phase 5 D1)",
            "source_status": "SAFE_FALLBACK",
            "reviewer_status": "",
            "reviewer_role": "",
            "review_date": "",
            "decision": "",
            "ui_badge": "NASA standard",
        }]
    return rows


@api
def get_countermeasures_for_category(problem_area, trigger_condition=None):
    """Return countermeasures for a problem_area (with safe fallback if category has no database row)."""
    rows = _countermeasures(problem_area, trigger=trigger_condition, allow_fallback=True)
    return {"problem_area": problem_area, "trigger_condition": trigger_condition, "countermeasures": rows}


@api
def get_threshold_badges():
    """Return Step 5 UI badges ('NASA standard' / 'Physician-reviewed' / 'Reference value' / 'Placeholder' / 'Unverified') for all indicators and alert thresholds."""
    with open(rf.SCHEMA_JSON_PATH, encoding="utf-8") as f:
        schema_doc = json.load(f)
    indicators_out = []
    thresholds_out = []
    for ind in schema_doc.get("indicators", []):
        v_stat = ind.get("verification_status", "UNVERIFIED")
        r_stat = ind.get("reviewer_status", "")
        badge = rf.compute_ui_badge(v_stat, r_stat)
        indicators_out.append({
            "indicator": ind["name"],
            "telemetry_column": ind.get("telemetry_column"),
            "display_name": ind.get("display_name", ind["name"]),
            "unit": ind.get("unit", ""),
            "verification_status": v_stat,
            "source_status": ind.get("source_status", v_stat),
            "reviewer_status": r_stat,
            "ui_badge": badge,
            "validated_instrument_mapping": ind.get("validated_instrument_mapping", ""),
        })
        for t_key, td in (ind.get("threshold_details") or {}).items():
            tv_stat = td.get("verification_status", v_stat)
            tr_stat = td.get("reviewer_status", r_stat)
            thresholds_out.append({
                "indicator": ind["name"],
                "threshold_name": t_key,
                "value_used": td.get("value_used"),
                "unit": ind.get("unit", ""),
                "verification_status": tv_stat,
                "source_status": td.get("source_status", tv_stat),
                "reviewer_status": tr_stat,
                "ui_badge": rf.compute_ui_badge(tv_stat, tr_stat),
                "source_document": td.get("source_document", ind.get("source_document", "")),
            })
    return {"indicators": indicators_out, "thresholds": thresholds_out}


def _provenance():
    con = _con()
    rows = con.execute("SELECT * FROM data_provenance").fetchall()
    con.close()
    return {r["column_name"]: {"data_type": r["data_type"], "resource_name": r["resource_name"],
                               "resource_location": r["resource_location"]} for r in rows}


def _trailing_rate(series, window=30):
    """Loss per 30 days of a declining series (7-day smoothed). None if there is too little history."""
    s = series.astype(float).rolling(7, min_periods=3).mean().reset_index(drop=True)
    if len(s) < 15:
        return None
    span = min(window, len(s) - 1)
    a, b = s.iloc[-1 - span], s.iloc[-1]
    if pd.isna(a) or pd.isna(b):
        return None
    return float((a - b) * 30.0 / span)


def _deviations(row, base_row, feat_row):
    out = {}
    for n in rf.INDICATOR_NAMES:
        ind = rf.IND[n]
        entry = {
            "value": _r(row.get(n), 2),
            "unit": ind["unit"],
            "baseline_mean": _r(base_row[n + "_mean"], 2),
            "baseline_std": _r(base_row[n + "_std"], 2),
            "verification_status": ind.get("verification_status", "PLACEHOLDER_SCALE"),
            "source_status": ind.get("source_status", ind.get("verification_status", "")),
            "reviewer_status": ind.get("reviewer_status", ""),
            "ui_badge": ind.get("ui_badge", "Placeholder"),
            "validated_instrument_mapping": ind.get("validated_instrument_mapping", ""),
        }
        if ind["kind"] != "flag":
            entry["z"] = _r(feat_row.get(f"{n}_z"), 2)
            entry["z_3day"] = _r(feat_row.get(f"{n}_z_r3"), 2)
            entry["z_7day"] = _r(feat_row.get(f"{n}_z_r7"), 2)
            entry["acute_change_vs_prev_week"] = _r(feat_row.get(f"{n}_z_acute"), 2)
        out[n] = entry
    return out


def _zones(hist, feat_row, devs, pred):
    """Body-zone colours (assumption A7).

    A zone lights up only when the MODEL raises an alert (class != Normal); it is then coloured by its
    largest personal deviation (>= 2 SD yellow, >= 3 SD red; any flagged zone is red on a
    Medical_Danger_Alert). If the model alerts but no zone reaches 2 SD, the zone with the largest
    7-day deviation is shown yellow. The bone-loss-rate flag (from resource R5) applies on its own.
    When the model says Normal, deviations >= 2 SD are listed under `watch` but the zone stays green.
    """
    zones = _zone_flags(hist, devs)
    alert = pred != "Normal"
    for zone, v in zones.items():
        stat_flags = [r for r in v["reasons"] if r["indicator"] != "bone_health" or r.get("z") is not None]
        bone_flags = [r for r in v["reasons"] if r not in stat_flags]
        if not alert:
            v["watch"], v["reasons"] = stat_flags, bone_flags
        else:
            v["watch"] = []
            if pred == "Medical_Danger_Alert":
                for r in stat_flags:
                    if r["level"] != "red":
                        r["level"] = "red"
                        r["rule"] += " - escalated to red because the model class is Medical_Danger_Alert"
        v["status"] = max([r["level"] for r in v["reasons"]], key=lambda s: _SEVERITY[s], default="green")
    if alert and all(v["status"] == "green" for v in zones.values()):
        best = None
        for zone, inds in rf.ZONES.items():
            for n in inds:
                z7 = devs[n].get("z_7day")
                if n in _ZONE_SKIP_Z or z7 is None:
                    continue
                adverse = rf.IND[n]["adverse"]
                score = z7 if adverse == "high" else (-z7 if adverse == "low" else abs(z7))
                if best is None or score > best[0]:
                    best = (score, zone, n)
        if best is not None:
            _, zone, n = best
            zones[zone]["status"] = "yellow"
            zones[zone]["reasons"].append({
                "indicator": n, "level": "yellow", "value": devs[n]["value"], "unit": devs[n]["unit"],
                "baseline_mean": devs[n]["baseline_mean"], "baseline_std": devs[n]["baseline_std"],
                "z": devs[n].get("z"), "z_7day": devs[n]["z_7day"],
                "rule": "model alert with no single-day flag: zone with the largest 7-day personal deviation"})
    return zones


def _zone_flags(hist, devs):
    zones = {}
    for zone, inds in rf.ZONES.items():
        status, reasons, info = "green", [], {}
        for n in inds:
            if n in _ZONE_SKIP_Z:
                continue
            z = devs[n].get("z")
            if z is None:
                continue
            # remove the in-flight shift everyone is expected to show (team file ranges), so that only the
            # astronaut's own extra deviation is flagged
            std = devs[n]["baseline_std"]
            if rf.IND[n]["flight_shift"] and std:
                z = round(z - rf.IND[n]["flight_shift"] / std, 2)
            adverse = rf.IND[n]["adverse"]
            score = z if adverse == "high" else (-z if adverse == "low" else abs(z))
            level = "red" if score >= rf.Z_RED else ("yellow" if score >= rf.Z_YELLOW else None)
            if level:
                reasons.append({"indicator": n, "level": level, "value": devs[n]["value"], "unit": devs[n]["unit"],
                                "baseline_mean": devs[n]["baseline_mean"], "baseline_std": devs[n]["baseline_std"],
                                "z": z, "rule": f"personal deviation flag: >= {rf.Z_RED if level == 'red' else rf.Z_YELLOW} SD "
                                                f"({adverse} direction, after removing the expected in-flight shift) "
                                                f"- statistical flag, not a clinical cut-off"})
                if _SEVERITY[level] > _SEVERITY[status]:
                    status = level
        if zone == "Bone_Muscle":
            rate = _trailing_rate(hist["bone_health"])
            info["bone_loss_pct_per_month_trailing_30d"] = _r(rate, 2)
            info["muscle_index_loss_trailing_30d"] = _r(_trailing_rate(hist["muscle_health"]), 2)
            last7 = hist.tail(rf.ADHERENCE_WINDOW_DAYS)
            info["sessions_last_7_days"] = {
                "cardio_done": int(last7["cardio_session_done"].sum()),
                "resistance_done": int(last7["resistance_training_done"].sum()),
                "days_counted": int(len(last7)),
                "note": "Reported for information; no adherence threshold exists in the challenge resources."}
            if rate is not None:
                level = "red" if rate >= rf.BONE_RATE_RED else ("yellow" if rate >= rf.BONE_RATE_YELLOW else None)
                if level:
                    reasons.append({"indicator": "bone_health", "level": level, "value": devs["bone_health"]["value"],
                                    "unit": devs["bone_health"]["unit"],
                                    "baseline_mean": devs["bone_health"]["baseline_mean"],
                                    "baseline_std": devs["bone_health"]["baseline_std"],
                                    "z": None, "loss_pct_per_month": _r(rate, 2),
                                    "rule": f"trailing 30-day bone loss >= "
                                            f"{rf.BONE_RATE_RED if level == 'red' else rf.BONE_RATE_YELLOW} %/month "
                                            f"(resource R5 states a maximum of {rf.BONE_LOSS_MAX_PCT_PER_MONTH} %/month; "
                                            f"used as a flag by assumption A7)"})
                    if _SEVERITY[level] > _SEVERITY[status]:
                        status = level
        zones[zone] = {"status": status, "title": rf.ZONE_TITLES[zone], "reasons": reasons, "info": info}
    return zones


def _action(pred, profile, zones):
    if pred == "Stress_BP_Spike_No_Medical_Danger":
        return {"calming_action": "play_song", "file": profile["song"],
                "alternative": {"calming_action": "show_family_photo", "file": profile["family_photo"]}}
    if pred == "Medical_Danger_Alert":
        return {"notify": ["earth_doctors", "flight_surgeon"], "contact": profile["contact_flight_surgeon"]}
    if pred == "Health_Warning":
        return {"review_zones": [z for z, v in zones.items() if v["status"] != "green"]}
    return {}


def _evaluate(astronaut_id, hist=None):
    """Evaluate the LAST row of `hist` (default: the astronaut's stored telemetry)."""
    profile = _profile(astronaut_id)
    base = _baseline_df(astronaut_id)
    if hist is None:
        hist = _history(astronaut_id)
    feats = aim.build_features(hist, base)
    feat_row = feats.iloc[-1]
    row = hist.iloc[-1]
    bundle = _bundle()
    labels, proba = aim.predict(bundle, feats.iloc[[-1]])
    probs = {c: round(float(p), 4) for c, p in zip(rf.CLASSES, proba[0])}
    pred = str(labels[0])
    devs = _deviations(row, base.iloc[0], feat_row)
    zones = _zones(hist, feat_row, devs, pred)
    return {"astronaut_id": astronaut_id, "record_id": int(row["record_id"]), "mission_day": int(row["mission_day"]),
            "timestamp": row["timestamp"], "reading": {n: _r(row.get(n), 2) for n in rf.INDICATOR_NAMES},
            "baseline_deviations": devs, "predicted_class": pred, "class_probabilities": probs,
            "zone_alerts": zones, "action": _action(pred, profile, zones), "model_version": bundle["model_version"],
            "_profile": profile, "_hist": hist}


def _public(ev):
    return {k: v for k, v in ev.items() if not k.startswith("_")}


def _validate_indicator_values(values):
    clean = {}
    for k, v in values.items():
        if k not in rf.IND:
            raise ValueError(f"Unknown indicator: {k!r}. Allowed: {rf.INDICATOR_NAMES}")
        if v is None:
            clean[k] = np.nan
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"Indicator {k!r} must be a number or null, got {v!r}")
        ind = rf.IND[k]
        if not (ind["lo"] <= float(v) <= ind["hi"]):
            raise ValueError(f"Indicator {k!r} = {v} is outside its scale [{ind['lo']}, {ind['hi']}] ({ind['unit']})")
        clean[k] = float(v)
    return clean


def _resolve_day(astronaut_id, mission_day=None):
    con = _con()
    if mission_day is None:
        row = con.execute("SELECT record_id, mission_day FROM mission_telemetry WHERE astronaut_id = ? "
                          "ORDER BY mission_day DESC LIMIT 1", (astronaut_id,)).fetchone()
    else:
        row = con.execute("SELECT record_id, mission_day FROM mission_telemetry WHERE astronaut_id = ? "
                          "AND mission_day = ?", (astronaut_id, int(mission_day))).fetchone()
    con.close()
    if row is None:
        raise ValueError(f"No telemetry row for astronaut {astronaut_id!r}, mission_day {mission_day!r}")
    return int(row["record_id"]), int(row["mission_day"])


def _refresh_prediction(astronaut_id, mission_day):
    """Re-score one stored record after a write-back so mission_replay stays consistent."""
    try:
        ev = _evaluate(astronaut_id, _history(astronaut_id, upto_day=mission_day))
    except FileNotFoundError:
        return
    con = _con()
    con.execute("INSERT OR REPLACE INTO model_predictions VALUES (?,?,?,?,?)",
                (ev["record_id"], ev["predicted_class"], json.dumps(ev["class_probabilities"]),
                 ev["model_version"], datetime.now(timezone.utc).isoformat(timespec="seconds")))
    con.commit()
    con.close()


def _calming(profile):
    return {"type": "calming", "calming_action": "play_song", "file": profile["song"],
            "alternative": {"calming_action": "show_family_photo", "file": profile["family_photo"]}}


def _todo(hist):
    row = hist.iloc[-1]
    items = []
    for task, cols in TASKS.items():
        minutes = _r(row[cols["minutes"]], 0)
        if cols["done"]:
            done = bool(row[cols["done"]] == 1)
        else:
            done = bool(minutes is not None and minutes > 0)
        items.append({"task": task, "done": done, "minutes": minutes})
    return {"mission_day": int(row["mission_day"]), "items": items}


def _linked_action(zone, ev):
    profile, hist = ev["_profile"], ev["_hist"]
    if zone == "Bone_Muscle":
        return {"type": "todo", "todo": _todo(hist), "open_page": "Home Page > To-Do list"}
    if zone == "Sleep_Brain":
        return {"type": "sleep_schedule",
                "your_baseline_sleep_hours": ev["baseline_deviations"]["sleep_hours"]["baseline_mean"],
                "last_7_days_mean_sleep_hours": _r(hist["sleep_hours"].tail(7).mean(), 1),
                "calming": _calming(profile)}
    if zone == "Stress" or (zone == "Cardiovascular" and ev["predicted_class"] == "Stress_BP_Spike_No_Medical_Danger"):
        return _calming(profile)
    if zone == "Health_Warning":
        return {"type": "todo_and_sleep_schedule", "todo": _todo(hist), "open_page": "Home Page > To-Do list",
                "your_baseline_sleep_hours": ev["baseline_deviations"]["sleep_hours"]["baseline_mean"],
                "last_7_days_mean_sleep_hours": _r(hist["sleep_hours"].tail(7).mean(), 1),
                "calming": _calming(profile)}
    return {"type": "contact_flight_surgeon", "contact": profile["contact_flight_surgeon"]}


def _fmt_dev(reason):
    if reason.get("loss_pct_per_month") is not None:
        return (f"{reason['indicator']}: {reason['value']} {reason['unit']} now vs. your pre-flight baseline "
                f"{reason['baseline_mean']}; trailing 30-day loss {reason.get('loss_pct_per_month')} %/month")
    dev = "missing today" if reason.get("z") is None else f"{reason['z']:+.2f} SD"
    if reason.get("z_7day") is not None:
        dev += f", 7-day mean {reason['z_7day']:+.2f} SD"
    return (f"{reason['indicator']}: {reason['value']} {reason['unit']} now vs. your pre-flight baseline "
            f"{reason['baseline_mean']} +/- {reason['baseline_std']} ({dev})")


def _explain_one(area, ev):
    """Build what / current_vs_baseline / why / how_to_fix for a zone or for a class-level alert."""
    pred, probs = ev["predicted_class"], ev["class_probabilities"]
    if area in rf.ZONES:
        z = ev["zone_alerts"][area]
        what = f"{z['title']} zone is {z['status'].upper()}: {len(z['reasons'])} indicator(s) flagged."
        cvb = [_fmt_dev(r) for r in z["reasons"]]
        structured = z["reasons"]
        triggers = "; ".join(r["rule"] for r in z["reasons"]) or "no indicator in this zone is flagged"
        cm_area, cm_trigger = area, "zone_alert"
    else:
        cm_area = CLASS_AREA[pred]
        cm_trigger = "class_" + pred
        what = f"The model classified today's reading as {pred} (probability {probs[pred]:.2f})."
        devs = ev["baseline_deviations"]
        top = sorted(((n, d["z"]) for n, d in devs.items() if d.get("z") is not None and n not in _ZONE_SKIP_Z),
                     key=lambda t: -abs(t[1]))[:4]
        cvb = [f"{n}: {devs[n]['value']} {devs[n]['unit']} now vs. your pre-flight baseline "
               f"{devs[n]['baseline_mean']} +/- {devs[n]['baseline_std']} ({zv:+.2f} SD)" for n, zv in top]
        structured = [{"indicator": n, "z": zv, "value": devs[n]["value"], "baseline_mean": devs[n]["baseline_mean"],
                       "baseline_std": devs[n]["baseline_std"], "unit": devs[n]["unit"]} for n, zv in top]
        triggers = "largest personal deviations today are listed above"
    context = _countermeasures(cm_area, "resource_context", allow_fallback=False)
    why = (f"Why the software raised this: {triggers}. Model output: {pred} (p={probs[pred]:.2f}). "
           + (context[0]["advice_text"] + " " if context else "")
           + "This describes why the alert fired on simulated data; it is not a diagnosis.")
    advice = _countermeasures(cm_area, cm_trigger, allow_fallback=True)
    adv = advice[0] if advice else {"advice_text": rf.SAFE_COUNTERMEASURE_FALLBACK, "resource_name": rf.NONE_NAME,
                                    "resource_location": "", "countermeasure_id": None,
                                    "source_status": "SAFE_FALLBACK", "reviewer_status": "", "ui_badge": "NASA standard"}
    cm_id = adv.get("countermeasure_id") if "countermeasure_id" in adv else adv.get("id")
    return {"area": area, "status": ev["zone_alerts"][area]["status"] if area in rf.ZONES else "class_alert",
            "what": what, "current_vs_baseline": cvb, "current_vs_baseline_data": structured, "why": why,
            "why_resource_context": [{"text": c["advice_text"], "resource_name": c["resource_name"],
                                      "resource_location": c["resource_location"]} for c in context],
            "how_to_fix": {"advice_text": adv["advice_text"], "countermeasure_id": cm_id,
                           "resource_name": adv["resource_name"], "resource_location": adv["resource_location"],
                           "source_status": adv.get("source_status", ""),
                           "reviewer_status": adv.get("reviewer_status", ""),
                           "ui_badge": adv.get("ui_badge", "NASA standard"),
                           "linked_action": _linked_action(cm_area, ev)}}


def _active_areas(ev):
    areas = [z for z, v in sorted(ev["zone_alerts"].items(), key=lambda kv: -_SEVERITY[kv[1]["status"]])
             if v["status"] != "green"]
    if ev["predicted_class"] != "Normal":
        areas.insert(0, "Model_Class")
    return areas


# ============================================================================= 5.7 analytical functions
@api
def evaluate_reading(astronaut_id, reading, session_token=None, *, now=None):
    """Score a NEW reading (not saved). Missing indicators are allowed (use null or omit)."""
    _enforce_session(session_token, astronaut_id, now=now)
    if not isinstance(reading, dict):
        raise ValueError("reading must be a dict of indicator -> number")
    meta = {k: reading[k] for k in ("timestamp", "mission_day") if k in reading}
    values = _validate_indicator_values({k: v for k, v in reading.items() if k not in meta})
    hist = _history(astronaut_id)
    last = hist.iloc[-1]
    new = {n: values.get(n, np.nan) for n in rf.INDICATOR_NAMES}
    new["record_id"] = -1
    new["astronaut_id"] = astronaut_id
    new["mission_day"] = int(meta.get("mission_day", int(last["mission_day"]) + 1))
    if new["mission_day"] <= int(last["mission_day"]):
        raise ValueError("mission_day of a new reading must be after the last stored day "
                         f"({int(last['mission_day'])}). Use mission_replay() for past days.")
    new["timestamp"] = meta.get("timestamp") or (datetime.fromisoformat(last["timestamp"]) + timedelta(days=1)).isoformat()
    hist2 = pd.concat([hist, pd.DataFrame([new])], ignore_index=True)
    out = _public(_evaluate(astronaut_id, hist2))
    out["saved"] = False
    out["note"] = "Reading scored against the personal pre-flight baseline; it was NOT written to the database."
    return out


@api
def body_zone_alerts(astronaut_id, reading=None, session_token=None, *, now=None):
    """green / yellow / red for Cardiovascular, Bone_Muscle, Immune, Sleep_Brain (latest stored day, or a new reading)."""
    _enforce_session(session_token, astronaut_id, now=now)
    if reading is not None:
        res = evaluate_reading(astronaut_id, reading, session_token=session_token, now=now)
        if not res.get("ok"):
            raise ValueError(res["error"])
        zones, day = res["zone_alerts"], res["mission_day"]
    else:
        ev = _evaluate(astronaut_id)
        zones, day = ev["zone_alerts"], ev["mission_day"]
    return {"astronaut_id": astronaut_id, "mission_day": day,
            "zones": {z: v["status"] for z, v in zones.items()}, "details": zones,
            "rule_note": "A zone lights up only when the model raises an alert; it is then coloured by personal "
                         "deviation (>= 2 SD yellow, >= 3 SD red). Statistical flags (assumption A7), not clinical cut-offs."}


@api
def astronaut_card(astronaut_id, session_token=None, *, now=None):
    """Simple view for the astronaut: status, active alerts, immediate advice."""
    _enforce_session(session_token, astronaut_id, now=now)
    ev = _evaluate(astronaut_id)
    alerts, advice = [], []
    for area in _active_areas(ev):
        ex = _explain_one(area, ev)
        alerts.append({"area": area, "status": ex["status"], "summary": ex["what"]})
        advice.append({"area": area, "advice_text": ex["how_to_fix"]["advice_text"],
                       "linked_action": ex["how_to_fix"]["linked_action"],
                       "source": "countermeasures.id=" + str(ex["how_to_fix"]["countermeasure_id"])})
    return {"astronaut_id": astronaut_id, "name": ev["_profile"]["name"], "mission_day": ev["mission_day"],
            "timestamp": ev["timestamp"], "status_class": ev["predicted_class"],
            "status": SIMPLE_STATUS[ev["predicted_class"]],
            "zones": {z: v["status"] for z, v in ev["zone_alerts"].items()},
            "active_alerts": alerts, "immediate_advice": advice, "action": ev["action"], "todo": _todo(ev["_hist"])}


@api
def earth_doctor_card(astronaut_id, last_n_days=14, session_token=None, *, now=None):
    """Full view for Earth doctors: telemetry, deviations, hormones, probabilities, breakdown, provenance."""
    _enforce_session(session_token, astronaut_id, now=now)
    ev = _evaluate(astronaut_id)
    hist, prov = ev["_hist"], _provenance()
    devs = ev["baseline_deviations"]
    for n, d in devs.items():
        d["provenance"] = prov.get("mission_telemetry." + n)
    breakdown = {}
    for zone, inds in rf.ZONES.items():
        breakdown[zone] = {"status": ev["zone_alerts"][zone]["status"], "info": ev["zone_alerts"][zone]["info"],
                           "indicators": [{"indicator": n, "adverse_direction": rf.IND[n]["adverse"],
                                           **{k: devs[n].get(k) for k in ("value", "unit", "baseline_mean", "baseline_std",
                                                                         "z", "z_3day", "z_7day",
                                                                         "acute_change_vs_prev_week")}}
                                          for n in inds]}
    con = _con()
    preds = [dict(r) for r in con.execute(
        "SELECT t.mission_day, p.predicted_class, p.class_probabilities FROM model_predictions p "
        "JOIN mission_telemetry t ON t.record_id = p.record_id WHERE t.astronaut_id = ? "
        "ORDER BY t.mission_day DESC LIMIT ?", (astronaut_id, int(last_n_days))).fetchall()]
    con.close()
    for p in preds:
        p["class_probabilities"] = json.loads(p["class_probabilities"])
    profile = ev["_profile"]
    return {"astronaut_id": astronaut_id, "profile": profile, "mission_day": ev["mission_day"],
            "timestamp": ev["timestamp"], "latest_reading": ev["reading"],
            "telemetry_last_n_days": hist.tail(int(last_n_days)).to_dict(orient="records"),
            "baseline_deviations": devs,
            "hormones": {**devs["hormones"], "last_7_days_mean": _r(hist["hormones"].tail(7).mean(), 2)},
            "predicted_class": ev["predicted_class"], "class_probabilities": ev["class_probabilities"],
            "diagnostic_breakdown": breakdown, "recent_predictions": preds[::-1],
            "action": ev["action"], "model_version": ev["model_version"],
            "data_note": "All values are simulated (see provenance on each indicator). No value is a real measurement."}


@api
def explain_alert(astronaut_id, zone=None, session_token=None, *, now=None):
    """what / current_vs_baseline / why / how_to_fix for one zone, or for the most severe active alert."""
    _enforce_session(session_token, astronaut_id, now=now)
    ev = _evaluate(astronaut_id)
    if zone is not None and zone not in rf.ZONES:
        raise ValueError(f"Unknown zone {zone!r}. Allowed: {list(rf.ZONES)}")
    active = _active_areas(ev)
    primary = zone or (active[0] if active else None)
    base = {"astronaut_id": astronaut_id, "mission_day": ev["mission_day"], "predicted_class": ev["predicted_class"],
            "class_probabilities": ev["class_probabilities"], "active_areas": active}
    if primary is None:
        base.update({"area": None, "what": "No active alert: all body zones are green and the model class is Normal.",
                     "current_vs_baseline": [], "why": "No indicator is flagged against your personal baseline.",
                     "how_to_fix": {"advice_text": "No action needed from the alert system.", "linked_action": {}}})
        return base
    base.update(_explain_one(primary, ev))
    base["other_alerts"] = [_explain_one(a, ev) for a in active if a != primary]
    return base


@api
def mission_replay(astronaut_id, timestamp, session_token=None, *, now=None):
    """Telemetry + stored prediction at (or nearest to) an ISO timestamp, e.g. '2030-03-01T12:00:00'."""
    _enforce_session(session_token, astronaut_id, now=now)
    try:
        target = datetime.fromisoformat(str(timestamp))
    except ValueError:
        raise ValueError(f"timestamp must be ISO format like '2030-03-01T12:00:00', got {timestamp!r}")
    hist = _history(astronaut_id)
    diffs = hist["timestamp"].map(lambda s: abs((datetime.fromisoformat(s) - target).total_seconds()))
    row = hist.loc[diffs.idxmin()]
    day = int(row["mission_day"])
    con = _con()
    p = con.execute("SELECT * FROM model_predictions WHERE record_id = ? ORDER BY created_at DESC LIMIT 1",
                    (int(row["record_id"]),)).fetchone()
    con.close()
    ev = _evaluate(astronaut_id, hist[hist["mission_day"] <= day])
    return {"astronaut_id": astronaut_id, "requested_timestamp": target.isoformat(),
            "matched_timestamp": row["timestamp"], "mission_day": day,
            "seconds_from_request": float(diffs.min()),
            "telemetry": {n: _r(row[n], 2) for n in rf.INDICATOR_NAMES},
            "stored_prediction": None if p is None else {
                "predicted_class": p["predicted_class"], "class_probabilities": json.loads(p["class_probabilities"]),
                "model_version": p["model_version"], "created_at": p["created_at"]},
            "zones_at_that_time": {z: v["status"] for z, v in ev["zone_alerts"].items()},
            "baseline_deviations": ev["baseline_deviations"]}


@api
def what_if(astronaut_id, changes, session_token=None, *, now=None):
    """Re-run the model on the latest reading with modified inputs.

    changes: {"sleep_hours": 1, "daily_training_hours": -0.5}  -> numbers are DELTAS added to the current value
             {"mood": {"set": 7}}                                 -> absolute value
    """
    _enforce_session(session_token, astronaut_id, now=now)
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a non-empty dict, e.g. {'sleep_hours': 1, 'daily_training_hours': -0.5}")
    hist = _history(astronaut_id)
    mod = hist.copy()
    idx = mod.index[-1]
    applied = {}
    for k, v in changes.items():
        if k not in rf.IND:
            raise ValueError(f"Unknown indicator: {k!r}. Allowed: {rf.INDICATOR_NAMES}")
        ind = rf.IND[k]
        old = mod.at[idx, k]
        if isinstance(v, dict) and "set" in v:
            new = float(v["set"])
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            if pd.isna(old):
                raise ValueError(f"{k!r} is missing in the latest reading; use {{'set': value}} instead of a delta")
            new = float(old) + float(v)
        else:
            raise ValueError(f"Change for {k!r} must be a number (delta) or {{'set': value}}")
        new = min(max(new, ind["lo"]), ind["hi"])
        mod.at[idx, k] = new
        applied[k] = {"before": _r(old, 2), "after": _r(new, 2), "unit": ind["unit"]}
    before, after = _evaluate(astronaut_id, hist), _evaluate(astronaut_id, mod)
    return {"astronaut_id": astronaut_id, "mission_day": before["mission_day"], "applied_changes": applied,
            "before": {"predicted_class": before["predicted_class"], "class_probabilities": before["class_probabilities"],
                       "zones": {z: v["status"] for z, v in before["zone_alerts"].items()}},
            "after": {"predicted_class": after["predicted_class"], "class_probabilities": after["class_probabilities"],
                      "zones": {z: v["status"] for z, v in after["zone_alerts"].items()}},
            "probability_change": {c: round(after["class_probabilities"][c] - before["class_probabilities"][c], 4)
                                   for c in before["class_probabilities"]},
            "note": "This is a MODEL SIMULATION on simulated data: it shows how the classifier's output moves when the "
                    "inputs move. It is not a medical prediction and not advice."}


# ============================================================================= 5.8 mood vs training (Phase 2 B5)
def _corr(x, y):
    ok = x.notna() & y.notna()
    x, y = x[ok].astype(float), y[ok].astype(float)
    n = int(len(x))
    if n < 3 or x.nunique() < 2 or y.nunique() < 2:
        return {"n": n, "pearson_r": None, "pearson_p": None, "ci_95_low": None, "ci_95_high": None,
                "spearman_rho": None, "spearman_p": None}
    pr, sr = stats.pearsonr(x, y), stats.spearmanr(x, y)
    r_val = float(pr[0])
    if n > 3 and abs(r_val) < 0.999999:
        z = math.atanh(r_val)
        se = 1.0 / math.sqrt(n - 3)
        ci_lo = round(math.tanh(z - 1.959964 * se), 4)
        ci_hi = round(math.tanh(z + 1.959964 * se), 4)
    else:
        ci_lo, ci_hi = None, None
    return {"n": n, "pearson_r": round(r_val, 4), "pearson_p": float(f"{float(pr[1]):.3g}"),
            "ci_95_low": ci_lo, "ci_95_high": ci_hi,
            "spearman_rho": round(float(sr[0]), 4), "spearman_p": float(f"{float(sr[1]):.3g}")}


def compute_rm_corr_and_mixed_effects(df: pd.DataFrame):
    """
    Compute within-astronaut repeated-measures correlation (Bakdash & Marusich 2017 / pingouin.rm_corr)
    and a random-intercept linear mixed-effects model:
        mood_it = beta_0 + u_i + beta_1 * daily_training_hours_it + e_it
    Returns exact r_rm, 95% CI, degrees of freedom, p-value, and mixed-effects fixed slope + 95% CI.
    """
    sub = df[["astronaut_id", "mood", "daily_training_hours"]].dropna().copy()
    if sub.empty:
        return {
            "method": "repeated_measures_correlation_and_mixed_effects",
            "n_observations": 0,
            "n_astronauts": 0,
            "df": 0,
            "rm_corr_r": None,
            "ci_95_low": None,
            "ci_95_high": None,
            "p_value": None,
            "mixed_effects_slope": None,
            "mixed_effects_slope_se": None,
            "mixed_effects_slope_ci_95": [None, None],
            "mixed_effects_p_value": None,
            "random_intercept_sd": None,
            "residual_sd": None,
        }

    # Filter astronauts with at least 3 valid paired observations
    counts = sub.groupby("astronaut_id").size()
    valid_aids = counts[counts >= 3].index
    sub = sub[sub["astronaut_id"].isin(valid_aids)].copy()
    n_obs = int(len(sub))
    k_astro = int(sub["astronaut_id"].nunique())
    df_rm = max(1, n_obs - k_astro - 1)

    # Within-astronaut centered residuals (ANCOVA / rm_corr)
    grp_means = sub.groupby("astronaut_id")[["daily_training_hours", "mood"]].transform("mean")
    x_res = (sub["daily_training_hours"] - grp_means["daily_training_hours"]).to_numpy(dtype=float)
    y_res = (sub["mood"] - grp_means["mood"]).to_numpy(dtype=float)

    ss_x = float(np.sum(x_res ** 2))
    ss_y = float(np.sum(y_res ** 2))
    sp_xy = float(np.sum(x_res * y_res))

    if ss_x <= 1e-12 or ss_y <= 1e-12:
        r_rm = 0.0
        beta_within = 0.0
    else:
        r_rm = float(np.clip(sp_xy / math.sqrt(ss_x * ss_y), -0.999999, 0.999999))
        beta_within = sp_xy / ss_x

    t_stat = r_rm * math.sqrt(df_rm / max(1e-12, 1.0 - r_rm ** 2))
    p_rm = float(2.0 * stats.t.sf(abs(t_stat), df_rm))

    if df_rm > 2:
        z = math.atanh(r_rm)
        se_z = 1.0 / math.sqrt(df_rm - 1)
        ci_low = round(math.tanh(z - 1.959964 * se_z), 4)
        ci_high = round(math.tanh(z + 1.959964 * se_z), 4)
    else:
        ci_low, ci_high = None, None

    # Random-intercept mixed-effects model (Swamy-Arora / Henderson Method 3 variance components + GLS)
    ss_err = max(0.0, ss_y - beta_within * sp_xy)
    sigma2_e = ss_err / df_rm if df_rm > 0 else 0.0
    se_beta = math.sqrt(sigma2_e / ss_x) if ss_x > 1e-12 else 0.0

    astro_means = sub.groupby("astronaut_id")[["daily_training_hours", "mood"]].mean()
    n_bar = n_obs / max(1, k_astro)
    between_resid = astro_means["mood"] - (astro_means["mood"].mean() + beta_within * (astro_means["daily_training_hours"] - astro_means["daily_training_hours"].mean()))
    var_between = float(between_resid.var(ddof=1)) if k_astro > 1 else 0.0
    sigma2_u = max(0.0, var_between - sigma2_e / max(1.0, n_bar))

    # GLS random-intercept weight theta
    theta = 1.0 - math.sqrt(sigma2_e / (sigma2_e + n_bar * sigma2_u)) if (sigma2_e + n_bar * sigma2_u) > 1e-12 else 0.0
    x_gls = sub["daily_training_hours"].to_numpy(dtype=float) - theta * grp_means["daily_training_hours"].to_numpy(dtype=float)
    y_gls = sub["mood"].to_numpy(dtype=float) - theta * grp_means["mood"].to_numpy(dtype=float)
    x_gls_c = x_gls - np.mean(x_gls)
    y_gls_c = y_gls - np.mean(y_gls)
    ss_x_gls = float(np.sum(x_gls_c ** 2))
    beta_gls = float(np.sum(x_gls_c * y_gls_c) / ss_x_gls) if ss_x_gls > 1e-12 else beta_within
    se_gls = math.sqrt(sigma2_e / ss_x_gls) if ss_x_gls > 1e-12 else se_beta
    t_gls = beta_gls / max(1e-12, se_gls)
    p_gls = float(2.0 * stats.t.sf(abs(t_gls), df_rm))

    return {
        "method": "repeated_measures_correlation_and_mixed_effects",
        "n_observations": n_obs,
        "n_astronauts": k_astro,
        "df": df_rm,
        "rm_corr_r": round(r_rm, 4),
        "ci_95_low": ci_low,
        "ci_95_high": ci_high,
        "p_value": float(f"{p_rm:.3g}"),
        "mixed_effects_slope": round(beta_gls, 4),
        "mixed_effects_slope_se": round(se_gls, 4),
        "mixed_effects_slope_ci_95": [
            round(beta_gls - 1.959964 * se_gls, 4),
            round(beta_gls + 1.959964 * se_gls, 4),
        ],
        "mixed_effects_p_value": float(f"{p_gls:.3g}"),
        "random_intercept_sd": round(math.sqrt(sigma2_u), 4),
        "residual_sd": round(math.sqrt(sigma2_e), 4),
        "simulator_coupling_enabled": rf.ENABLE_MOOD_TRAINING_COUPLING,
    }


@api
def mood_training_correlation(astronaut_id=None):
    """
    Within-astronaut correlation of mood vs daily_training_hours (Phase 2 B5):
    - Primary metric: Repeated-measures correlation (r_rm) and Random-Intercept Mixed-Effects Model with 95% CIs.
    - Replaces the invalid pooled Pearson correlation that ignored within-astronaut clustering.
    """
    con = _con()
    df = pd.read_sql_query("SELECT astronaut_id, mood, daily_training_hours FROM mission_telemetry", con)
    con.close()
    if astronaut_id is not None:
        _profile(astronaut_id)
        df_target = df[df["astronaut_id"] == astronaut_id]
    else:
        df_target = df

    within = []
    for aid, g in df_target.groupby("astronaut_id"):
        within.append({"astronaut_id": aid, **_corr(g["mood"], g["daily_training_hours"])})
    rs = [w["pearson_r"] for w in within if w["pearson_r"] is not None]
    sig = sum(1 for w in within if w["pearson_p"] is not None and w["pearson_p"] < 0.05)

    if len(rs) >= 2:
        mean_r = float(np.mean(rs))
        se_r = float(np.std(rs, ddof=1) / math.sqrt(len(rs)))
        mean_r_ci = [round(mean_r - 1.959964 * se_r, 4), round(mean_r + 1.959964 * se_r, 4)]
    elif len(rs) == 1:
        mean_r = float(rs[0])
        mean_r_ci = [within[0]["ci_95_low"], within[0]["ci_95_high"]]
    else:
        mean_r = None
        mean_r_ci = [None, None]

    rm_mixed = compute_rm_corr_and_mixed_effects(df_target)
    pooled_raw = _corr(df["mood"], df["daily_training_hours"])

    return {
        "repeated_measures_and_mixed_effects": rm_mixed,
        "within_astronaut": within,
        "within_summary": {
            "n_astronauts": len(within),
            "mean_pearson_r": _r(mean_r, 4),
            "mean_pearson_r_ci_95": mean_r_ci,
            "rm_corr_r": rm_mixed["rm_corr_r"],
            "rm_corr_ci_95": [rm_mixed["ci_95_low"], rm_mixed["ci_95_high"]],
            "rm_corr_p_value": rm_mixed["p_value"],
            "mixed_effects_slope": rm_mixed["mixed_effects_slope"],
            "mixed_effects_slope_ci_95": rm_mixed["mixed_effects_slope_ci_95"],
            "mixed_effects_p_value": rm_mixed["mixed_effects_p_value"],
            "n_with_p_below_0.05": sig,
        },
        "pooled_deprecated_do_not_use": {
            **pooled_raw,
            "invalid_pooling_reason": (
                "DEPRECATED (B5): Naive pooled Pearson correlation across 200 astronauts x 180 days "
                "violates observation independence due to between-astronaut random intercepts. Use "
                "repeated_measures_and_mixed_effects.rm_corr_r and mixed_effects_slope instead."
            ),
        },
        "note": (
            "Within-astronaut analysis using repeated-measures correlation (r_rm) and a random-intercept "
            "mixed-effects model properly accounts for repeated daily observations within each astronaut. "
            f"Simulator mood-training coupling flag (enable_mood_training_coupling) is currently "
            f"{rf.ENABLE_MOOD_TRAINING_COUPLING}."
        ),
    }


# ============================================================================= summary report
def summary_report(astronaut_id=None):
    """Plain-text report: indicators, alerts, mood-training correlation, recommendations."""
    lines = ["=" * 78, "ASTRONAUT HEALTH SUMMARY REPORT", rf.DISCLAIMER, "=" * 78]
    corr = mood_training_correlation(astronaut_id)
    if not corr.get("ok"):
        return "\n".join(lines + ["ERROR: " + corr["error"]])
    if astronaut_id is None:
        con = _con()
        ids = [r[0] for r in con.execute("SELECT astronaut_id FROM astronaut_profile ORDER BY astronaut_id")]
        con.close()
        counts, flagged = {c: 0 for c in rf.CLASSES}, []
        zone_counts = {z: {"green": 0, "yellow": 0, "red": 0} for z in rf.ZONES}
        for aid in ids:
            ev = _evaluate(aid)
            counts[ev["predicted_class"]] += 1
            for z, v in ev["zone_alerts"].items():
                zone_counts[z][v["status"]] += 1
            bad = [f"{z}={v['status']}" for z, v in ev["zone_alerts"].items() if v["status"] != "green"]
            if ev["predicted_class"] != "Normal" or bad:
                flagged.append(f"  {aid}  day {ev['mission_day']:>3}  model: {ev['predicted_class']:<34} zones: "
                               + (", ".join(bad) or "all green"))
        lines.append(f"CREW REPORT - {len(ids)} astronauts, latest stored day for each")
        lines.append("\nModel class on the latest day:")
        for c in rf.CLASSES:
            lines.append(f"  {c:<36} {counts[c]:>3}")
        lines.append("\nBody zones on the latest day (green / yellow / red):")
        for z, c in zone_counts.items():
            lines.append(f"  {rf.ZONE_TITLES[z]:<24} {c['green']:>3} / {c['yellow']:>3} / {c['red']:>3}")
        lines.append(f"\nAstronauts with an active alert ({len(flagged)}):")
        lines += flagged or ["  none"]
    else:
        ev = _evaluate(astronaut_id)
        p = ev["_profile"]
        lines.append(f"{p['name']} ({astronaut_id}) - mission day {ev['mission_day']} - {ev['timestamp']}")
        lines.append(f"\nSTATUS: {SIMPLE_STATUS[ev['predicted_class']]}")
        lines.append("Model class probabilities: " + ", ".join(f"{c}={v:.2f}" for c, v in ev["class_probabilities"].items()))
        lines.append("\nALL INDICATORS (current vs personal pre-flight baseline):")
        lines.append(f"  {'indicator':<30}{'value':>9}{'baseline':>10}{'std':>7}{'z':>8}   unit")
        for n, d in ev["baseline_deviations"].items():
            fmt = lambda v: "   n/a" if v is None else f"{v:.2f}"
            lines.append(f"  {n:<30}{fmt(d['value']):>9}{fmt(d['baseline_mean']):>10}{fmt(d['baseline_std']):>7}"
                         f"{fmt(d.get('z')):>8}   {d['unit']}")
        lines.append("\nBODY ZONES:")
        for z, v in ev["zone_alerts"].items():
            lines.append(f"  {v['title']:<24} {v['status'].upper()}")
            for r in v["reasons"]:
                lines.append("      - " + _fmt_dev(r))
        lines.append("\nALERTS AND RECOMMENDATIONS (advice text from the countermeasures table only):")
        areas = _active_areas(ev)
        if not areas:
            lines.append("  No active alert.")
        for a in areas:
            ex = _explain_one(a, ev)
            lines.append(f"  [{a}] {ex['what']}")
            lines.append(f"      Advice: {ex['how_to_fix']['advice_text']}")
            lines.append(f"      Linked action: {ex['how_to_fix']['linked_action'].get('type', 'calming')}")
        td = _todo(ev["_hist"])
        lines.append(f"\nTO-DO (mission day {td['mission_day']}):")
        for it in td["items"]:
            lines.append(f"  [{'x' if it['done'] else ' '}] {it['task']:<26} {it['minutes']} min")
    lines.append("\nMOOD vs DAILY TRAINING HOURS (Within-Astronaut Repeated-Measures & Mixed-Effects Analysis):")
    rm = corr["repeated_measures_and_mixed_effects"]
    lines.append(
        f"  Repeated-measures r_rm (n={rm['n_observations']}, df={rm['df']}): "
        f"r_rm={rm['rm_corr_r']} (95% CI [{rm['ci_95_low']}, {rm['ci_95_high']}], p={rm['p_value']})"
    )
    lines.append(
        f"  Mixed-effects random-intercept slope: beta={rm['mixed_effects_slope']} "
        f"(95% CI {rm['mixed_effects_slope_ci_95']}, p={rm['mixed_effects_p_value']})"
    )
    if astronaut_id is not None and corr["within_astronaut"]:
        w = corr["within_astronaut"][0]
        lines.append(
            f"  This astronaut (n={w['n']}): Pearson r={w['pearson_r']} "
            f"(95% CI [{w['ci_95_low']}, {w['ci_95_high']}], p={w['pearson_p']}), "
            f"Spearman rho={w['spearman_rho']} (p={w['spearman_p']})"
        )
    else:
        ws = corr["within_summary"]
        lines.append(
            f"  Per-astronaut distribution ({ws['n_astronauts']} astronauts): "
            f"mean r={ws['mean_pearson_r']} (95% CI {ws['mean_pearson_r_ci_95']}); "
            f"{ws['n_with_p_below_0.05']} have p<0.05 (~5% expected by chance)"
        )
    lines.append("  " + corr["note"])
    lines.append("\nSources: mission_telemetry, preflight_baseline, countermeasures, model " + rf.MODEL_VERSION)
    lines.append(rf.DISCLAIMER)
    lines.append(rf.SYNTHETIC_DATA_DISCLAIMER)
    return "\n".join(lines)


# ============================================================================= page-support interface
@api
def login(user_id, password=None, *, now=None):
    """Authenticate an astronaut or flight_surgeon with Argon2id/bcrypt password hash, 5-attempt lockout, and session token."""
    uid = str(user_id).strip().upper()
    if password is None or not str(password):
        raise ValueError("PIN or password is required to log in.")
    cfg = _auth_cfg()
    max_attempts = int(cfg.get("max_failed_attempts", 5))
    lockout_sec = int(cfg.get("lockout_duration_seconds", 900))
    ttl_sec = int(cfg.get("session_ttl_seconds", 3600))
    cur_now = _now_utc(now)

    con = _con()
    user = con.execute("SELECT * FROM auth_users WHERE user_id = ?", (uid,)).fetchone()
    if user is None:
        con.close()
        raise ValueError(f"Unknown user_id: {uid!r}")

    failed = int(user["failed_attempts"] or 0)
    locked_until = user["locked_until"]
    if locked_until:
        lock_dt = _now_utc(locked_until)
        if cur_now < lock_dt:
            con.close()
            raise ValueError(f"Account {uid} is locked until {locked_until} after {max_attempts} failed attempts.")
        # Lockout period has elapsed
        failed = 0
        locked_until = None

    if not _verify_password_hash(str(password), user["password_hash"]):
        failed += 1
        if failed >= max_attempts:
            locked_until = (cur_now + timedelta(seconds=lockout_sec)).isoformat(timespec="seconds")
        con.execute("UPDATE auth_users SET failed_attempts = ?, locked_until = ? WHERE user_id = ?",
                    (failed, locked_until, uid))
        con.commit()
        con.close()
        if locked_until:
            raise ValueError(f"Invalid credentials ({failed}/{max_attempts} failed attempts) — account locked until {locked_until}.")
        raise ValueError(f"Invalid credentials ({failed}/{max_attempts} failed attempts).")

    # Success: reset failed_attempts and issue session token
    con.execute("UPDATE auth_users SET failed_attempts = 0, locked_until = NULL WHERE user_id = ?", (uid,))
    token = secrets.token_urlsafe(32)
    created_iso = cur_now.isoformat(timespec="seconds")
    expires_iso = (cur_now + timedelta(seconds=ttl_sec)).isoformat(timespec="seconds")
    role = user["role"]
    con.execute("INSERT INTO auth_sessions VALUES (?,?,?,?,?,0)",
                (token, uid, role, created_iso, expires_iso))
    con.commit()
    con.close()

    if role == "astronaut":
        p = _profile(uid)
        return {"user_id": uid, "astronaut_id": uid, "name": p["name"], "role": role,
                "mission_role": p["mission_role"], "profile_photo": p["profile_photo"],
                "session_token": token, "expires_at": expires_iso}
    return {"user_id": uid, "name": user["display_name"], "role": role,
            "session_token": token, "expires_at": expires_iso}


@api
def verify_session(session_token, target_astronaut_id=None, *, now=None):
    """Validate a session token and optional target astronaut access."""
    if not session_token:
        raise ValueError("session_token is required.")
    return _enforce_session(session_token, target_astronaut_id=target_astronaut_id, now=now)


@api
def logout(session_token):
    """Revoke an active session token."""
    if not session_token:
        raise ValueError("session_token is required.")
    con = _con()
    cur = con.execute("UPDATE auth_sessions SET revoked = 1 WHERE token = ?", (str(session_token),))
    con.commit()
    con.close()
    if cur.rowcount == 0:
        raise ValueError("Unknown session token.")
    return {"revoked": True}


@api
def list_all_astronauts(session_token, *, now=None):
    """Flight surgeon endpoint: view summary status across all astronauts."""
    if not session_token:
        raise ValueError("session_token is required.")
    _enforce_session(session_token, target_astronaut_id=None, now=now)
    con = _con()
    rows = [dict(r) for r in con.execute("SELECT astronaut_id, name, mission_role, destination_for_flight FROM astronaut_profile ORDER BY astronaut_id").fetchall()]
    con.close()
    return {"n_astronauts": len(rows), "astronauts": rows}


@api
def get_profile(astronaut_id, session_token=None, *, now=None):
    _enforce_session(session_token, astronaut_id, now=now)
    return {"astronaut_id": astronaut_id, "profile": _profile(astronaut_id), "baseline": _baseline_df(astronaut_id).iloc[0].to_dict()}


@api
def update_profile(astronaut_id, changes, session_token=None, *, now=None):
    """About/Settings: edit profile fields. `changes` = {"field": value, ...}."""
    _enforce_session(session_token, astronaut_id, now=now)
    _profile(astronaut_id)
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a non-empty dict")
    bad = [k for k in changes if k not in EDITABLE_PROFILE_FIELDS]
    if bad:
        raise ValueError(f"Not editable / unknown profile field(s): {bad}. Editable: {EDITABLE_PROFILE_FIELDS}")
    con = _con()
    sets = ", ".join(f"{k} = ?" for k in changes)        # keys are validated against a fixed whitelist above
    con.execute(f"UPDATE astronaut_profile SET {sets} WHERE astronaut_id = ?", list(changes.values()) + [astronaut_id])
    con.commit()
    con.close()
    return {"astronaut_id": astronaut_id, "updated_fields": list(changes), "profile": _profile(astronaut_id)}


@api
def set_calming_media(astronaut_id, family_photo=None, song=None, session_token=None):
    """About/Settings: store the PATHS of the uploaded calming photo / song (files are saved by the frontend)."""
    changes = {k: v for k, v in (("family_photo", family_photo), ("song", song)) if v is not None}
    if not changes:
        raise ValueError("Give family_photo and/or song (a file path such as 'media/A01_family.jpg')")
    res = update_profile(astronaut_id, changes, session_token=session_token)
    if not res.get("ok"):
        raise ValueError(res["error"])
    return {"astronaut_id": astronaut_id, "family_photo": res["profile"]["family_photo"], "song": res["profile"]["song"]}


@api
def get_todo(astronaut_id, mission_day=None, session_token=None, *, now=None):
    """Home Page To-Do list for one day (default: latest stored day)."""
    _enforce_session(session_token, astronaut_id, now=now)
    _profile(astronaut_id)
    _, day = _resolve_day(astronaut_id, mission_day)
    return {"astronaut_id": astronaut_id, **_todo(_history(astronaut_id, upto_day=day))}


@api
def complete_task(astronaut_id, task, minutes, mission_day=None, session_token=None, *, now=None):
    """Write 'task completed' back to SQLite (mission_telemetry) and refresh that day's stored prediction."""
    _enforce_session(session_token, astronaut_id, now=now)
    _profile(astronaut_id)
    if task not in TASKS:
        raise ValueError(f"Unknown task {task!r}. Allowed: {list(TASKS)}")
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not (0 <= minutes <= rf.IND[TASKS[task]['minutes']]['hi']):
        raise ValueError("minutes must be a number >= 0")
    record_id, day = _resolve_day(astronaut_id, mission_day)
    cols = TASKS[task]
    con = _con()
    con.execute(f"UPDATE mission_telemetry SET {cols['minutes']} = ? WHERE record_id = ?", (float(minutes), record_id))
    if cols["done"]:
        con.execute(f"UPDATE mission_telemetry SET {cols['done']} = ? WHERE record_id = ?",
                    (1 if minutes > 0 else 0, record_id))
    con.commit()
    con.close()
    _refresh_prediction(astronaut_id, day)
    return {"astronaut_id": astronaut_id, "written": {"table": "mission_telemetry", "record_id": record_id,
                                                      "task": task, "minutes": float(minutes)},
            **_todo(_history(astronaut_id, upto_day=day))}


def _write_score(astronaut_id, column, score, mission_day, session_token=None, now=None):
    _enforce_session(session_token, astronaut_id, now=now)
    _profile(astronaut_id)
    values = _validate_indicator_values({column: score})
    if np.isnan(values[column]):
        raise ValueError("score must be a number")
    record_id, day = _resolve_day(astronaut_id, mission_day)
    con = _con()
    con.execute(f"UPDATE mission_telemetry SET {column} = ? WHERE record_id = ?", (values[column], record_id))
    con.commit()
    con.close()
    _refresh_prediction(astronaut_id, day)
    b = _baseline_df(astronaut_id).iloc[0]
    return {"astronaut_id": astronaut_id, "written": {"table": "mission_telemetry", "record_id": record_id,
                                                      "column": column, "value": values[column]},
            "mission_day": day, "baseline_mean": _r(b[column + "_mean"], 2), "baseline_std": _r(b[column + "_std"], 2)}


@api
def submit_mental_health_assessment(astronaut_id, score, mission_day=None, session_token=None):
    """Health Test Page: store a mental-health assessment score (0-100; questionnaire items are a team task)."""
    return _write_score(astronaut_id, "mental_health_assessment", score, mission_day, session_token=session_token)


@api
def submit_game_test_score(astronaut_id, score, mission_day=None, session_token=None):
    """Health Test Page: store a game-test score (0-100; scoring method is a team task)."""
    return _write_score(astronaut_id, "game_test_score", score, mission_day, session_token=session_token)


@api
def get_alerts(astronaut_id, session_token=None, *, now=None):
    """Home Page alerts: model class + non-green zones."""
    _enforce_session(session_token, astronaut_id, now=now)
    card = astronaut_card(astronaut_id)
    if not card.get("ok"):
        raise ValueError(card["error"])
    return {k: card[k] for k in ("astronaut_id", "mission_day", "status_class", "status", "zones",
                                 "active_alerts", "action")}


@api
def get_chart_data(astronaut_id, indicators=None, last_n_days=30, session_token=None, *, now=None):
    """Health Dashboard charts/tables: time-series + personal baseline band for the chosen indicators."""
    _enforce_session(session_token, astronaut_id, now=now)
    names = list(indicators) if indicators else rf.INDICATOR_NAMES
    bad = [n for n in names if n not in rf.IND]
    if bad:
        raise ValueError(f"Unknown indicator(s): {bad}")
    hist = _history(astronaut_id).tail(int(last_n_days))
    b = _baseline_df(astronaut_id).iloc[0]
    return {"astronaut_id": astronaut_id, "mission_day": hist["mission_day"].tolist(),
            "timestamp": hist["timestamp"].tolist(),
            "series": {n: [_r(v, 2) for v in hist[n]] for n in names},
            "baseline": {n: {"mean": _r(b[n + "_mean"], 2), "std": _r(b[n + "_std"], 2)} for n in names},
            "units": {n: rf.IND[n]["unit"] for n in names},
            "data_types": {n: rf.IND[n]["data_type"] for n in names}}


@api
def get_health_advice(astronaut_id, session_token=None, *, now=None):
    """Health Test Page advice: one explanation per active alert (advice text from countermeasures only)."""
    _enforce_session(session_token, astronaut_id, now=now)
    ev = _evaluate(astronaut_id)
    return {"astronaut_id": astronaut_id, "mission_day": ev["mission_day"], "predicted_class": ev["predicted_class"],
            "advice": [_explain_one(a, ev) for a in _active_areas(ev)]}


if __name__ == "__main__":
    print(summary_report())
