"""
generate_data.py — STEP 1: build astronaut_health.db

No allowed resource contains per-astronaut measurements, so NO column is `real`.
* bone_health and estimated_time_for_flight_days are `synthetic_from_resource` (CSA resource R5).
* blood pressure, heart rate, SpO2, temperature, sleep, mood and exercise minutes are
  `synthetic_from_team_file_unverified` (ranges from the team-supplied files; see resource_facts.py).
* everything else is `placeholder_not_from_resources`.

Labels come from a simulated hidden daily state; features are generated FROM that state plus
personal variation, drift, sensor noise, missing values and deliberately overlapping cases.

Prototype for research/education only — not for clinical diagnosis.
"""
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from argon2 import PasswordHasher

import resource_facts as rf

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
EVAL_DB_PATH = os.environ.get("ASTRO_HEALTH_EVAL_DB") or os.path.join(DATA_DIR, "astronaut_health_eval.db")
EVAL_HASH_PATH = EVAL_DB_PATH + ".sha256"
APP_DB_PATH = os.environ.get("ASTRO_HEALTH_APP_DB") or os.path.join(DATA_DIR, "astronaut_health_app.db")
DB_PATH = os.path.join(HERE, "astronaut_health.db")
AUTH_CONFIG_PATH = os.path.join(HERE, "config", "demo_credentials.json")

WARNING_TYPES = ["decond", "sleep_mood", "immune"]
DANGER_GROUPS = list(rf.EFFECTS_SD["danger_optional"].keys())


def compute_sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------- schema
def create_schema(con):
    cur = con.cursor()
    cur.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE astronaut_profile (
        astronaut_id TEXT PRIMARY KEY,
        name TEXT, mission_role TEXT, nationality TEXT, profile_photo TEXT,
        contact_flight_surgeon TEXT, previous_flight INTEGER,
        age INTEGER, gender TEXT, weight_kg REAL, height_cm REAL, blood_type TEXT, allergies TEXT,
        previous_surgeries TEXT, previous_injuries TEXT, immunization_history TEXT, family_medical_history TEXT,
        family_photo TEXT, song TEXT,
        type_of_aircraft TEXT, estimated_time_for_flight_days INTEGER, destination_for_flight TEXT
    );
    CREATE TABLE auth_users (
        user_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT
    );
    CREATE TABLE auth_sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES auth_users(user_id),
        role TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE countermeasures (
        countermeasure_id INTEGER PRIMARY KEY AUTOINCREMENT,
        problem_area TEXT, trigger_condition TEXT, advice_text TEXT,
        resource_name TEXT, resource_location TEXT,
        source_status TEXT, reviewer_status TEXT,
        reviewer_role TEXT, review_date TEXT, decision TEXT,
        ui_badge TEXT
    );
    CREATE TABLE data_provenance (
        column_name TEXT, data_type TEXT, resource_name TEXT, resource_location TEXT
    );
    CREATE TABLE data_dictionary (
        column_name TEXT PRIMARY KEY, problem_area TEXT, unit TEXT, scale TEXT,
        adverse_direction TEXT, data_type TEXT, notes TEXT,
        source_status TEXT, reviewer_status TEXT, ui_badge TEXT,
        validated_instrument_mapping TEXT
    );
    """)
    base_cols = ",\n        ".join(f"{n}_mean REAL, {n}_std REAL" for n in rf.INDICATOR_NAMES)
    cur.execute(f"""
    CREATE TABLE preflight_baseline (
        astronaut_id TEXT PRIMARY KEY REFERENCES astronaut_profile(astronaut_id),
        {base_cols},
        mental_health_assessment_baseline REAL
    )""")
    tel_cols = ",\n        ".join(
        f"{n} {'INTEGER' if rf.IND[n]['kind'] == 'flag' else 'REAL'}" for n in rf.INDICATOR_NAMES)
    cur.execute(f"""
    CREATE TABLE mission_telemetry (
        record_id INTEGER PRIMARY KEY,
        astronaut_id TEXT NOT NULL REFERENCES astronaut_profile(astronaut_id),
        timestamp TEXT NOT NULL,
        mission_day INTEGER NOT NULL,
        {tel_cols}
    )""")
    cur.executescript("""
    CREATE INDEX idx_tel_astro_day ON mission_telemetry(astronaut_id, mission_day);
    CREATE TABLE telemetry_labels (
        record_id INTEGER PRIMARY KEY REFERENCES mission_telemetry(record_id),
        true_class TEXT NOT NULL
    );
    CREATE TABLE model_predictions (
        record_id INTEGER NOT NULL REFERENCES mission_telemetry(record_id),
        predicted_class TEXT, class_probabilities TEXT, model_version TEXT, created_at TEXT,
        PRIMARY KEY (record_id, model_version)
    );
    """)
    con.commit()


# ----------------------------------------------------------------------------- profiles
def make_profiles(rng):
    rows = []
    blood = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
    craft = ["Spacecraft (placeholder)", "Space station (placeholder)"]
    dest = ["International Space Station", "Moon", "Mars"]
    for k in range(1, rf.N_ASTRONAUTS + 1):
        aid = f"A{k:03d}"
        rows.append({
            "astronaut_id": aid,
            "name": f"Astronaut {aid}",
            "mission_role": f"Crew Role {int(rng.integers(1, 5))} (placeholder)",
            "nationality": f"Placeholder Nation {'ABCDE'[int(rng.integers(0, 5))]}",
            "profile_photo": f"media/{aid}_profile.jpg",
            "contact_flight_surgeon": f"Flight Surgeon Desk {int(rng.integers(1, 4))} (fictional) - console channel FS-{k:03d}",
            "previous_flight": int(rng.integers(0, 4)),
            "age": int(rng.integers(30, 51)),
            "gender": str(rng.choice(["F", "M"])),
            "weight_kg": round(float(rng.uniform(55, 90)), 1),
            "height_cm": round(float(rng.uniform(155, 190)), 1),
            "blood_type": str(rng.choice(blood)),
            "allergies": "None recorded (placeholder)",
            "previous_surgeries": "None recorded (placeholder)",
            "previous_injuries": "None recorded (placeholder)",
            "immunization_history": "Not recorded (placeholder)",
            "family_medical_history": "Not recorded (placeholder)",
            "family_photo": f"media/{aid}_family.jpg",
            "song": f"media/{aid}_song.mp3",
            "type_of_aircraft": str(rng.choice(craft)),
            "estimated_time_for_flight_days": rf.MISSION_DAYS,
            "destination_for_flight": str(rng.choice(dest)),
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- hidden state
def simulate_hidden_state(rng, D):
    """Return per-day hidden state for one astronaut. Label priority: Danger > Stress > Warning > Normal."""
    w_type = np.array([""] * D, dtype=object)
    w_int = np.zeros(D)
    s_int = np.zeros(D)
    s_temp = np.zeros(D, dtype=bool)
    d_int = np.zeros(D)
    d_groups = [None] * D

    cfg = rf.EPISODES["Health_Warning"]
    for _ in range(rng.poisson(cfg["poisson_mean"])):
        dur = int(rng.integers(cfg["duration_days"][0], cfg["duration_days"][1] + 1))
        start = int(rng.integers(0, D))
        typ = str(rng.choice(WARNING_TYPES))
        g = float(rng.uniform(*cfg["intensity"]))
        for k, d in enumerate(range(start, min(D, start + dur))):
            eff = g * min(1.0, (k + 1) / cfg["ramp_days"])
            if eff > w_int[d]:
                w_type[d], w_int[d] = typ, eff

    cfg = rf.EPISODES["Stress_BP_Spike_No_Medical_Danger"]
    for _ in range(rng.poisson(cfg["poisson_mean"])):
        dur = int(rng.integers(cfg["duration_days"][0], cfg["duration_days"][1] + 1))
        start = int(rng.integers(0, D))
        g = float(rng.uniform(*cfg["intensity"]))
        conf = bool(rng.random() < rf.STRESS_TEMP_CONFOUNDER_PROB)
        for d in range(start, min(D, start + dur)):
            s_int[d] = max(s_int[d], g)
            s_temp[d] = s_temp[d] or conf

    cfg = rf.EPISODES["Medical_Danger_Alert"]
    for _ in range(rng.poisson(cfg["poisson_mean"])):
        dur = int(rng.integers(cfg["duration_days"][0], cfg["duration_days"][1] + 1))
        start = int(rng.integers(0, D))
        g = float(rng.uniform(*cfg["intensity"]))
        groups = [grp for grp in DANGER_GROUPS if rng.random() < rf.DANGER_SIGNAL_PROB]
        if not groups:                      # at least one signal; a BP-only danger looks like stress (overlap)
            groups = ["bp"]
        for d in range(start, min(D, start + dur)):
            d_int[d] = max(d_int[d], g)
            d_groups[d] = groups

    label = np.array(["Normal"] * D, dtype=object)
    label[w_int > 0] = "Health_Warning"
    label[s_int > 0] = "Stress_BP_Spike_No_Medical_Danger"
    label[d_int > 0] = "Medical_Danger_Alert"
    # on danger days the stress effect is not added on top (danger has its own signature)
    s_int = np.where(d_int > 0, 0.0, s_int)
    return {"label": label, "w_type": w_type, "w_int": w_int, "s_int": s_int, "s_temp": s_temp,
            "d_int": d_int, "d_groups": d_groups}


def effect_matrix(rng, hs, D):
    """Sum of state effects per indicator per day: (personal-SD units, real units)."""
    eff_sd = {n: np.zeros(D) for n in rf.CONTINUOUS}
    eff_abs = {n: np.zeros(D) for n in rf.CONTINUOUS}

    def add(key, weight, sub=None):
        for src, dst in ((rf.EFFECTS_SD, eff_sd), (rf.EFFECTS_ABS, eff_abs)):
            table = src.get(key, {})
            if sub is not None:
                table = table.get(sub, {})
            for name, size in table.items():
                dst[name] += size * weight

    add("stress", hs["s_int"])
    add("stress_temp_confounder", hs["s_int"] * hs["s_temp"])
    add("danger_always", hs["d_int"])
    for grp in DANGER_GROUPS:
        on = np.array([1.0 if (g is not None and grp in g) else 0.0 for g in hs["d_groups"]])
        add("danger_optional", hs["d_int"] * on, sub=grp)
    for typ in WARNING_TYPES:
        add("warning_" + typ, hs["w_int"] * (hs["w_type"] == typ))
    benign = (hs["label"] == "Normal") & (rng.random(D) < rf.BENIGN_EXERTION_PROB)
    add("benign_exertion", benign.astype(float))
    return eff_sd, eff_abs


# ----------------------------------------------------------------------------- one astronaut
def simulate_astronaut(rng, aid):
    P, D = rf.PREFLIGHT_DAYS, rf.MISSION_DAYS
    T = P + D
    hs = simulate_hidden_state(rng, D)
    eff, eff_abs = effect_matrix(rng, hs, D)
    decond = (hs["w_type"] == "decond") & (hs["w_int"] > 0)
    in_flight = np.arange(T) >= P
    day = np.arange(1, D + 1)
    out = {}

    for ind in rf.INDICATORS:
        name, kind = ind["name"], ind["kind"]
        if kind in ("index", "natural"):
            mu = rng.normal(ind["center"], ind["between_sd"])
            sigma = ind["within_sd"] * rng.uniform(0.7, 1.3)
            latent = np.zeros(T)
            latent[0] = rng.normal()
            for t in range(1, T):
                latent[t] = rf.AR_PHI * latent[t - 1] + np.sqrt(1 - rf.AR_PHI ** 2) * rng.normal()
            vals = mu + sigma * (rf.LATENT_SHARE * latent + rf.SENSOR_SHARE * rng.normal(size=T))
            step = rng.normal(0, rf.LAUNCH_STEP_SD)
            slope = rng.normal(0, rf.DRIFT_SD_END_OF_MISSION) / D
            vals[P:] += ind["flight_shift"] + sigma * (step + slope * day + eff[name]) + eff_abs[name]
            out[name] = vals
        elif kind == "bone":
            rate_n = rng.uniform(*rf.BONE_RATE_WITH_EXERCISE)
            rate_d = rng.uniform(*rf.BONE_LOSS_UNMITIGATED)
            daily = np.where(decond, rate_d, rate_n) / rf.DAYS_PER_MONTH
            true = np.concatenate([np.full(P, 100.0), 100.0 - np.cumsum(daily)])
            out[name] = true + rng.normal(0, rf.BONE_SENSOR_SD, size=T)
        elif kind == "muscle":
            rate_n = rng.uniform(*rf.MUSCLE_RATE_NORMAL)
            rate_d = rng.uniform(*rf.MUSCLE_RATE_DECOND)
            daily = np.where(decond, rate_d, rate_n) / rf.DAYS_PER_MONTH
            true = np.concatenate([np.full(P, 100.0), 100.0 - np.cumsum(daily)])
            out[name] = true + rng.normal(0, rf.MUSCLE_SENSOR_SD, size=T)

    for sess in ("cardio_session", "resistance_training"):
        p = rng.uniform(*rf.ADHERENCE_NORMAL)
        p_day = np.full(T, p)
        p_day[P:] = np.where(decond, p * rf.ADHERENCE_DECOND_FACTOR, p)
        done = (rng.random(T) < p_day).astype(int)
        ind = rf.IND[sess + "_min"]
        minutes = rng.normal(ind["center"], ind["within_sd"], size=T)
        minutes[P:] = np.where(decond, minutes[P:] * rf.SESSION_MIN_DECOND_FACTOR, minutes[P:])
        out[sess + "_done"] = done
        out[sess + "_min"] = np.where(done == 1, minutes, 0.0)

    if rf.ENABLE_MOOD_TRAINING_COUPLING:
        train_dev = (
            (out["daily_training_hours"] - rf.IND["daily_training_hours"]["center"])
            / max(rf.IND["daily_training_hours"]["within_sd"], 1e-6)
        )
        out["mood"] = out["mood"] + rf.MOOD_TRAINING_COUPLING_BETA * rf.IND["mood"]["within_sd"] * train_dev

    # clip + round + missing values
    for ind in rf.INDICATORS:
        name = ind["name"]
        v = np.clip(out[name].astype(float), ind["lo"], ind["hi"])
        v = np.round(v, ind["decimals"])
        if ind["kind"] != "flag":
            v[rng.random(T) < rf.MISSING_RATE] = np.nan
        out[name] = v

    df = pd.DataFrame(out)[rf.INDICATOR_NAMES]
    pre, mis = df.iloc[:P].copy(), df.iloc[P:].copy().reset_index(drop=True)

    base = {"astronaut_id": aid}
    for n in rf.INDICATOR_NAMES:
        base[n + "_mean"] = round(float(pre[n].mean()), 4)
        base[n + "_std"] = round(float(pre[n].std(ddof=1)), 4)
    base["mental_health_assessment_baseline"] = base["mental_health_assessment_mean"]

    start = datetime.fromisoformat(rf.MISSION_START)
    mis.insert(0, "mission_day", day)
    mis.insert(0, "timestamp", [(start + timedelta(days=int(d - 1))).isoformat() for d in day])
    mis.insert(0, "astronaut_id", aid)
    mis["true_class"] = hs["label"]
    return base, mis


# ----------------------------------------------------------------------------- reference tables
def reference_rows():
    prov = []
    for f in rf.PROFILE_FIELDS:
        prov.append(("astronaut_profile." + f[0], f[2], f[3], f[4]))
    for c, note in (("record_id", "running row number"), ("astronaut_id", "fictional ID"),
                    ("timestamp", "fictional mission calendar (assumption A4)"),
                    ("mission_day", "1..180; mission length from R5 'six months' x 30 days")):
        dtype = rf.SYN if c == "mission_day" else rf.PH
        rname = rf.R5_NAME if c == "mission_day" else rf.NONE_NAME
        rloc = rf.R5_PAGE if c == "mission_day" else note
        prov.append(("mission_telemetry." + c, dtype, rname, rloc))
    for i in rf.INDICATORS:
        prov.append(("mission_telemetry." + i["name"], i["data_type"], i["resource_name"], i["resource_location"]))
    for i in rf.INDICATORS:
        for suffix in ("_mean", "_std"):
            prov.append(("preflight_baseline." + i["name"] + suffix, i["data_type"], i["resource_name"],
                         "computed from 30 simulated pre-flight days of " + i["name"] + "; " + i["resource_location"]))
    prov.append(("preflight_baseline.mental_health_assessment_baseline", rf.PH, rf.NONE_NAME,
                 "copy of mental_health_assessment_mean; " + rf.NOT_IN))
    prov.append(("telemetry_labels.true_class", rf.PH, rf.NONE_NAME,
                 "simulated hidden state (assumption A6); " + rf.NOT_IN))

    ddict = []
    for i in rf.INDICATORS:
        ddict.append((
            i["name"], " + ".join(i["problems"]), i["unit"], i["scale"],
            i["adverse"] or "n/a", i["data_type"], i["note"],
            i.get("source_status", i.get("verification_status", "")),
            i.get("reviewer_status", ""),
            i.get("ui_badge", "Placeholder"),
            i.get("validated_instrument_mapping", ""),
        ))
    cm = [(
        c["problem_area"], c["trigger_condition"], c["advice_text"],
        c["resource_name"], c["resource_location"],
        c.get("source_status", c.get("verification_status", "")),
        c.get("reviewer_status", ""),
        c.get("reviewer_role", ""),
        c.get("review_date", ""),
        c.get("decision", ""),
        c.get("ui_badge", "NASA standard"),
    ) for c in rf.COUNTERMEASURES]
    return prov, ddict, cm


def seed_auth_users(con, profiles):
    with open(AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    ap = cfg.get("argon2_params", {})
    ph = PasswordHasher(
        time_cost=ap.get("time_cost", 2),
        memory_cost=ap.get("memory_cost", 4096),
        parallelism=ap.get("parallelism", 2),
        hash_len=ap.get("hash_len", 32),
        salt_len=ap.get("salt_len", 16),
    )
    auth_rng = np.random.default_rng(rf.SEED + 1000)
    rule = cfg["astronaut_credential_rule"]
    fmt = rule["format"]
    overrides = rule.get("overrides", {})
    rows = []
    for _, prof in profiles.iterrows():
        aid = prof["astronaut_id"]
        cred = overrides.get(aid, fmt.format(astronaut_id=aid))
        salt = auth_rng.bytes(16)
        rows.append((aid, prof["name"], "astronaut", ph.hash(cred, salt=salt), 0, None))
    for fs in cfg.get("flight_surgeons", []):
        salt = auth_rng.bytes(16)
        rows.append((fs["user_id"], fs["name"], fs["role"], ph.hash(fs["credential"], salt=salt), 0, None))
    con.executemany("INSERT INTO auth_users VALUES (?,?,?,?,?,?)", rows)


# ----------------------------------------------------------------------------- main
def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    for p in (EVAL_DB_PATH, APP_DB_PATH, DB_PATH):
        if os.path.exists(p):
            os.remove(p)
    rng = np.random.default_rng(rf.SEED)
    con = sqlite3.connect(EVAL_DB_PATH)
    create_schema(con)

    profiles = make_profiles(rng)
    profiles.to_sql("astronaut_profile", con, if_exists="append", index=False)
    seed_auth_users(con, profiles)

    baselines, missions = [], []
    for aid in profiles["astronaut_id"]:
        base, mis = simulate_astronaut(rng, aid)
        baselines.append(base)
        missions.append(mis)
    base_df = pd.DataFrame(baselines)
    tel = pd.concat(missions, ignore_index=True)
    tel.insert(0, "record_id", np.arange(1, len(tel) + 1))

    base_df.to_sql("preflight_baseline", con, if_exists="append", index=False)
    tel.drop(columns=["true_class"]).to_sql("mission_telemetry", con, if_exists="append", index=False)
    tel[["record_id", "true_class"]].to_sql("telemetry_labels", con, if_exists="append", index=False)

    prov, ddict, cm = reference_rows()
    con.executemany("INSERT INTO data_provenance VALUES (?,?,?,?)", prov)
    con.executemany("INSERT INTO data_dictionary VALUES (?,?,?,?,?,?,?,?,?,?,?)", ddict)
    con.executemany(
        "INSERT INTO countermeasures (problem_area, trigger_condition, advice_text, resource_name, "
        "resource_location, source_status, reviewer_status, reviewer_role, review_date, decision, ui_badge) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        cm,
    )
    con.commit()

    # ---- report (real numbers from this run)
    print("=" * 78)
    print("STEP 1 - generate_data.py")
    print(rf.DISCLAIMER)
    print("=" * 78)
    print(f"Frozen Eval Database written: {EVAL_DB_PATH}")
    for t in ("astronaut_profile", "auth_users", "preflight_baseline", "mission_telemetry", "telemetry_labels",
              "countermeasures", "data_provenance", "data_dictionary", "model_predictions"):
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<22} {n:>7} rows")
    con.close()

    eval_sha = compute_sha256(EVAL_DB_PATH)
    with open(EVAL_HASH_PATH, "w", encoding="utf-8") as f:
        f.write(f"{eval_sha}  astronaut_health_eval.db\n")
    shutil.copy2(EVAL_DB_PATH, APP_DB_PATH)
    shutil.copy2(EVAL_DB_PATH, DB_PATH)
    print(f"Frozen Eval SHA-256:          {eval_sha}")
    print(f"Hash manifest written:        {EVAL_HASH_PATH}")
    print(f"Working App Database copied:  {APP_DB_PATH}")

    print("\nClass balance (simulated hidden state):")
    vc = tel["true_class"].value_counts()
    for c in rf.CLASSES:
        print(f"  {c:<36} {int(vc.get(c, 0)):>6}  ({100 * vc.get(c, 0) / len(tel):5.2f} %)")
    miss = tel[rf.CONTINUOUS].isna().mean().mean() * 100
    print(f"\nMissing values in continuous indicators: {miss:.2f} %")
    dt = pd.Series([p[1] for p in prov]).value_counts()
    print("\nColumn provenance counts:")
    for k in rf.DATA_TYPES:
        print(f"  {k:<38} {int(dt.get(k, 0)):>4}")
    print("\nIn-flight means of team-file indicators (real units, unverified source):")
    for n in rf.SCHEMA_MAP:
        print(f"  {n:<20} {tel[n].mean():8.2f} {rf.IND[n]['unit']}")
    final_bone = tel[tel["mission_day"] == rf.MISSION_DAYS]["bone_health"]
    worst = 100 - final_bone.min()
    print(f"\nSanity check vs resource R5 (max 1.5 %/month x 6 months = 9.0 % loss):")
    print(f"  largest simulated bone loss at day {rf.MISSION_DAYS}: {worst:.2f} % of pre-flight (incl. sensor noise)")


if __name__ == "__main__":
    main()
