"""
resource_facts.py — single source of truth for everything the project is allowed to "know".

Every number, indicator, threshold, and countermeasure used anywhere in the project is defined
HERE with its full Phase 2 (B2/B3/B4) and Phase 5 (D1/D4) verification metadata:
  * VERIFIED_AGAINST_PUBLISHED_STANDARD - verified against NASA-STD-3001, NASA OCHMO, NASA HRP, CSA, or peer-reviewed spaceflight medicine
  * ADJUSTED_TO_PUBLISHED_STANDARD      - adjusted from prior team-file value to match published standard (old_value recorded)
  * TERRESTRIAL_REFERENCE               - verified against standard terrestrial clinical reference (AHA, ADA, RCP NEWS2, AASM) where no spaceflight-specific value is published
  * PLACEHOLDER_SCALE                   - synthetic 0-100 or 1-10 prototype scale, mapped to a validated psychometric/physiological instrument (PSS-10, PHQ-9, Borg RPE, PVT)
  * UNVERIFIED                          - no source available (never guessed)

Prototype for research/education only — not for clinical diagnosis.
Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

DISCLAIMER = "Prototype for research/education only — not for clinical diagnosis."
SYNTHETIC_DATA_DISCLAIMER = (
    "Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy."
)
REFUSAL_TEXT = (
    "I can only answer using your health records, the model's results, and the verified "
    "challenge-resource database. I don't have that information — please contact your flight surgeon."
)
NO_GUIDANCE_TEXT = "No verified guidance in challenge resources — contact flight surgeon."
SAFE_COUNTERMEASURE_FALLBACK = (
    "Contact flight surgeon immediately if experiencing acute symptoms; otherwise re-verify sensor "
    "readings, maintain scheduled rest and hydration, and log the anomaly for medical review."
)

REAL = "real"
SYN = "synthetic_from_resource"
TEAM = "synthetic_from_team_file_unverified"
PH = "placeholder_not_from_resources"
DATA_TYPES = [REAL, SYN, TEAM, PH]

VERIFICATION_STATUSES = [
    "VERIFIED_AGAINST_PUBLISHED_STANDARD",
    "ADJUSTED_TO_PUBLISHED_STANDARD",
    "TERRESTRIAL_REFERENCE",
    "PLACEHOLDER_SCALE",
    "UNVERIFIED",
]

MODEL_VERSION = "personal_baseline_v4"

# Load project config
PROJECT_CONFIG_PATH = os.path.join(HERE, "config", "project_config.json")
if os.path.exists(PROJECT_CONFIG_PATH):
    with open(PROJECT_CONFIG_PATH, encoding="utf-8") as _cf:
        PROJECT_CONFIG = json.load(_cf)
else:
    PROJECT_CONFIG = {"simulation": {"enable_mood_training_coupling": False, "mood_training_coupling_beta": 0.35}}

ENABLE_MOOD_TRAINING_COUPLING = bool(
    PROJECT_CONFIG.get("simulation", {}).get("enable_mood_training_coupling", False)
)
MOOD_TRAINING_COUPLING_BETA = float(
    PROJECT_CONFIG.get("simulation", {}).get("mood_training_coupling_beta", 0.35)
)


def compute_ui_badge(verification_status: str, reviewer_status: str = "") -> str:
    """Return the Step 5 UI badge for a given verification_status and reviewer_status."""
    if reviewer_status and reviewer_status.strip():
        return "Physician-reviewed"
    if verification_status in ("VERIFIED_AGAINST_PUBLISHED_STANDARD", "ADJUSTED_TO_PUBLISHED_STANDARD"):
        return "NASA standard"
    if verification_status == "TERRESTRIAL_REFERENCE":
        return "Reference value"
    if verification_status == "PLACEHOLDER_SCALE":
        return "Placeholder"
    return "Unverified"


# --------------------------------------------------------------------------------------
# 1. ALLOWED RESOURCES & EXTERNAL REFERENCE DOCUMENTS
# --------------------------------------------------------------------------------------
_NASA_STATUS = "Verified against published NASA-STD-3001 / OCHMO / HRP / peer-reviewed references in references/: "
ALLOWED_RESOURCES = [
    {"id": "R0", "name": "Challenge page: Create Health Monitoring Software for Astronauts on Space Missions",
     "url": "https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/",
     "status": "READ directly", "local_file": "references/allowed_csa_and_spaceapps_verbatim.txt"},
    {"id": "R1", "name": "NASA HRP: 5 Hazards of Human Spaceflight",
     "url": "https://www.nasa.gov/hrp/hazards/",
     "status": _NASA_STATUS + "references/nasa_hrp_hazards_and_analogs.txt",
     "local_file": "references/nasa_hrp_hazards_and_analogs.txt"},
    {"id": "R2", "name": "NASA HRP: Risks of Human Spaceflight & OCHMO Technical Briefs",
     "url": "https://www.nasa.gov/ochmo/health-and-medical-policy/nasa-std-3001-technical-briefs/",
     "status": _NASA_STATUS + "references/nasa_ochmo_technical_briefs.txt",
     "local_file": "references/nasa_ochmo_technical_briefs.txt"},
    {"id": "R3", "name": "NASA HRP: Ongoing HRP Research in Space (CIPHER, Standard Measures, Analogs)",
     "url": "https://www.nasa.gov/hrp/ongoing-hrp-research/",
     "status": _NASA_STATUS + "references/nasa_hrp_hazards_and_analogs.txt",
     "local_file": "references/nasa_hrp_hazards_and_analogs.txt"},
    {"id": "R4", "name": "CSA: Monitoring Radiation for Astronaut Health",
     "url": "https://www.asc-csa.gc.ca/eng/news/articles/2026/2026-02-26-monitoring-radiation-astronaut-health.asp",
     "status": "READ directly", "local_file": "references/allowed_csa_and_spaceapps_verbatim.txt"},
    {"id": "R5", "name": "CSA: Why Do We Conduct Science Experiments in Space?",
     "url": "https://www.asc-csa.gc.ca/eng/iss/science/why-do-we-conduct-science-experiments-in-space.asp",
     "status": "READ directly (page + embedded infographic text version + embedded video transcript)",
     "local_file": "references/allowed_csa_and_spaceapps_verbatim.txt"},
    {"id": "T7", "name": "Expanded Schema: 07_health_indicators_schema.json (source-verified ranges and thresholds)",
     "url": "references/OUTSIDE_ALLOWED_RESOURCES.md",
     "status": "Cross-checked and expanded in Phase 2 against NASA-STD-3001, OCHMO, HRP, peer-reviewed papers, and terrestrial clinical standards.",
     "local_file": "data_raw/team_supplied/07_health_indicators_schema.json"},
]

R0_NAME = ALLOWED_RESOURCES[0]["name"]
R1_NAME = ALLOWED_RESOURCES[1]["name"]
R5_NAME = ALLOWED_RESOURCES[5]["name"]
T7_NAME = ALLOWED_RESOURCES[6]["name"]
R0_BACKGROUND = "references/allowed_csa_and_spaceapps_verbatim.txt - section R0"
R0_SUMMARY = "references/allowed_csa_and_spaceapps_verbatim.txt - section R0"
R0_CONSIDER = "data_raw/spaceapps_challenge_details.txt - section POTENTIAL CONSIDERATIONS"
R1_FILE = "data_raw/team_supplied/02_nasa_5_hazards_of_human_spaceflight.md"
R5_INFOGRAPHIC = "references/allowed_csa_and_spaceapps_verbatim.txt - section R5"
R5_PAGE = "references/allowed_csa_and_spaceapps_verbatim.txt - section R5"
T7_FILE = "data_raw/team_supplied/07_health_indicators_schema.json"
NASA_GRAVITY_NAME = "NASA HRP: Hazard - Gravity Fields (sub-page of R1)"
NASA_ENV_NAME = "NASA HRP: Hazard - Hostile/Closed Environments (sub-page of R1)"
NASA_ISO_NAME = "NASA HRP: Hazard - Isolation and Confinement (sub-page of R1)"
NASA_NOTES = "references/nasa_hrp_hazards_and_analogs.txt"
NONE_NAME = "none"
NOT_IN = "NOT IN RESOURCES (placeholder simulation parameter)"

# --------------------------------------------------------------------------------------
# 2. NUMBERS FROM RESOURCES / TEAM FILES
# --------------------------------------------------------------------------------------
BONE_LOSS_MAX_PCT_PER_MONTH = 1.5   # R5 infographic 'Bones': "up to 1.5% of their bone mass each month"
BONE_LOSS_UNMITIGATED = (1.0, 1.5)  # NASA OCHMO-TB-030 & Gravity Fields page: 1% to 1.5% per month
MISSION_MONTHS = 6                  # R5 page: "Studying the human body in space for six months"
EXERCISE_HOURS_PER_DAY = (2.0, 2.5) # NASA OCHMO-TB-031: "2.0 to 2.5 hours per day for combined resistive and aerobic exercise"
DAYS_PER_MONTH = 30                 # assumption A4
MISSION_DAYS = MISSION_MONTHS * DAYS_PER_MONTH

SCHEMA_JSON_PATH = os.path.join(HERE, "data_raw", "team_supplied", "07_health_indicators_schema.json")
with open(SCHEMA_JSON_PATH, encoding="utf-8") as _f:
    _RAW_SCHEMA_DOC = json.load(_f)
    TEAM_SCHEMA = {i["name"]: i for i in _RAW_SCHEMA_DOC["indicators"]}
    SUMMARY_CLAIMS = _RAW_SCHEMA_DOC.get("summary_02_04_verified_claims", [])

# project telemetry indicator -> name in 07_health_indicators_schema.json
SCHEMA_MAP = {
    "heart_rate": "heart_rate",
    "systolic_bp": "blood_pressure_systolic",
    "diastolic_bp": "blood_pressure_diastolic",
    "blood_glucose_mg_dl": "blood_sugar",
    "temperature": "body_temperature",
    "sleep_hours": "sleep_hours",
    "mood": "mood_score",
    "oxygen_saturation": "oxygen_saturation_spo2",
    "bone_health": "bone_health",
    "muscle_health": "muscle_health",
    "immunity_indicators": "immunity_indicators",
    "hormones": "hormones",
    "relaxation": "relaxation",
    "mental_health_assessment": "mental_health_assessment",
    "game_test_score": "game_test_score",
    "daily_training_hours": "exercise_and_exertion",
    "cardio_session_min": "exercise_and_exertion",
    "resistance_training_min": "exercise_and_exertion",
    "cardio_session_done": "exercise_and_exertion",
    "resistance_training_done": "exercise_and_exertion",
    "daily_physical_activity_min": "exercise_and_exertion",
}


def _mid(r):
    return (r["min"] + r["max"]) / 2.0


def _schema(name):
    s = TEAM_SCHEMA[SCHEMA_MAP[name]]
    flight = next((v for k, v in s.items() if k.startswith("spaceflight_expected")), s["normal_earth_baseline"])
    return s, s["normal_earth_baseline"], flight


def flight_mid(name):
    return _mid(_schema(name)[2])


def threshold(name, key):
    return _schema(name)[0]["alert_thresholds"][key]


# --------------------------------------------------------------------------------------
# 3. SIMULATION SETTINGS (all assumptions - NOT from resources)
# --------------------------------------------------------------------------------------
SEED = 42
N_ASTRONAUTS = 200
PREFLIGHT_DAYS = 30
MISSION_START = "2030-01-01T12:00:00"   # fictional date, one reading per day
MISSING_RATE = 0.03                      # user spec: ~2-5 % missing values
AR_PHI = 0.5                             # day-to-day autocorrelation of each signal
LATENT_SHARE = 0.8                       # share of personal SD that is slow day-to-day variation
SENSOR_SHARE = 0.6                       # share of personal SD that is sensor noise (0.8^2+0.6^2=1)
DRIFT_SD_END_OF_MISSION = 0.6            # random personal in-flight drift reached by last day (personal SDs)
LAUNCH_STEP_SD = 0.5                     # random personal step change at launch (personal SDs)
BETWEEN_SD_RANGE_FRACTION = 1 / 6        # between-astronaut SD = this x width of the Earth "normal" range
WITHIN_SD_RANGE_FRACTION = 1 / 5         # day-to-day SD      = this x width of the Earth "normal" range
BONE_SENSOR_SD = 0.15                    # %-points
BONE_RATE_WITH_EXERCISE = (0.0, BONE_LOSS_UNMITIGATED[0])
MUSCLE_SENSOR_SD = 0.5                   # index points
MUSCLE_RATE_NORMAL = (0.0, 0.5)          # index points per month (arbitrary placeholder)
MUSCLE_RATE_DECOND = (0.5, 1.0)          # index points per month (arbitrary placeholder)
ADHERENCE_NORMAL = (0.80, 0.95)          # probability an exercise session is done on a normal day
ADHERENCE_DECOND_FACTOR = 0.5            # multiplies adherence during deconditioning episodes
SESSION_MIN_DECOND_FACTOR = 0.7          # multiplies session minutes during deconditioning episodes
SESSION_MIN_SD = 6                       # minutes

# Hidden-state episode process (per astronaut, over the mission)
EPISODES = {
    "Health_Warning": {"poisson_mean": 2.2, "duration_days": (6, 20), "intensity": (0.3, 1.2), "ramp_days": 3},
    "Stress_BP_Spike_No_Medical_Danger": {"poisson_mean": 9.0, "duration_days": (1, 2), "intensity": (0.3, 1.2)},
    "Medical_Danger_Alert": {"poisson_mean": 1.6, "duration_days": (1, 4), "intensity": (0.3, 1.3)},
}
BENIGN_EXERTION_PROB = 0.03              # Normal-labelled days that still show a heart-rate / BP bump
STRESS_TEMP_CONFOUNDER_PROB = 0.15       # stress episodes that also show a temperature bump
DANGER_SIGNAL_PROB = 0.6                 # chance each danger signal is expressed in a given episode

# Effect sizes at intensity 1.0 (including blood_glucose_mg_dl for B4)
EFFECTS_ABS = {
    "stress": {
        "systolic_bp": threshold("systolic_bp", "high_warning") - flight_mid("systolic_bp"),
        "diastolic_bp": threshold("diastolic_bp", "high_warning") - flight_mid("diastolic_bp"),
        "heart_rate": threshold("heart_rate", "high_warning") - flight_mid("heart_rate"),
        "blood_glucose_mg_dl": round((threshold("blood_glucose_mg_dl", "hyperglycemia_warning") - flight_mid("blood_glucose_mg_dl")) * 0.55, 2),
    },
    "danger_optional": {
        "bp": {
            "systolic_bp": threshold("systolic_bp", "high_critical") - flight_mid("systolic_bp"),
            "diastolic_bp": threshold("diastolic_bp", "high_critical") - flight_mid("diastolic_bp"),
            "blood_glucose_mg_dl": round((threshold("blood_glucose_mg_dl", "hyperglycemia_critical") - flight_mid("blood_glucose_mg_dl")) * 0.65, 2),
        },
        "hr": {
            "heart_rate": threshold("heart_rate", "high_critical") - flight_mid("heart_rate"),
            "blood_glucose_mg_dl": round((threshold("blood_glucose_mg_dl", "hyperglycemia_critical") - flight_mid("blood_glucose_mg_dl")) * 0.55, 2),
        },
        "spo2": {
            "oxygen_saturation": threshold("oxygen_saturation", "hypoxia_critical") - flight_mid("oxygen_saturation"),
            "blood_glucose_mg_dl": round((threshold("blood_glucose_mg_dl", "hyperglycemia_warning") - flight_mid("blood_glucose_mg_dl")) * 0.9, 2),
        },
        "temp": {
            "temperature": threshold("temperature", "pyrexia_critical") - flight_mid("temperature"),
            "blood_glucose_mg_dl": round((threshold("blood_glucose_mg_dl", "hyperglycemia_critical") - flight_mid("blood_glucose_mg_dl")) * 0.6, 2),
        },
        "immune": {
            "blood_glucose_mg_dl": round((threshold("blood_glucose_mg_dl", "hyperglycemia_warning") - flight_mid("blood_glucose_mg_dl")) * 1.1, 2),
        },
    },
    "warning_sleep_mood": {
        "sleep_hours": threshold("sleep_hours", "deficit_warning") - flight_mid("sleep_hours"),
        "mood": threshold("mood", "low_warning") - flight_mid("mood"),
    },
    "warning_immune": {
        "temperature": threshold("temperature", "pyrexia_warning") - flight_mid("temperature"),
        "blood_glucose_mg_dl": round((threshold("blood_glucose_mg_dl", "hyperglycemia_warning") - flight_mid("blood_glucose_mg_dl")) * 0.85, 2),
    },
}
EFFECTS_SD = {
    "stress": {"hormones": 1.5, "relaxation": -1.5, "mood": -0.8, "sleep_hours": -0.5, "temperature": 0.2},
    "stress_temp_confounder": {"temperature": 1.0},
    "danger_always": {"hormones": 1.2, "relaxation": -0.8, "mood": -0.8, "blood_glucose_mg_dl": 1.4},
    "danger_optional": {"bp": {}, "hr": {}, "spo2": {}, "temp": {}, "immune": {"immunity_indicators": -1.2}},
    "warning_decond": {"daily_physical_activity_min": -1.2},
    "warning_sleep_mood": {"relaxation": -0.8, "mental_health_assessment": -1.0, "game_test_score": -0.7},
    "warning_immune": {"immunity_indicators": -1.3, "hormones": 0.8},
    "benign_exertion": {"heart_rate": 1.5, "systolic_bp": 1.0},
}

CLASSES = ["Normal", "Stress_BP_Spike_No_Medical_Danger", "Health_Warning", "Medical_Danger_Alert"]

# --------------------------------------------------------------------------------------
# 4. INDICATORS (data dictionary + generator parameters + B2/B3/B4 provenance)
# --------------------------------------------------------------------------------------
PU = "PU (placeholder units, 0-100 scale; NOT a clinical unit)"
_PH_NOTE = "Value range is an arbitrary neutral placeholder; mapped to validated instrument where applicable."


def _attach_b2_metadata(entry_dict, schema_name):
    """Attach Phase 2 B2/B3/D4/Step 5 fields from 07_health_indicators_schema.json."""
    if schema_name and schema_name in TEAM_SCHEMA:
        s = TEAM_SCHEMA[schema_name]
        v_status = s.get("verification_status", "UNVERIFIED")
        r_status = s.get("reviewer_status", "")
        if "old_value" in s:
            entry_dict["old_value"] = s["old_value"]
        entry_dict.update({
            "value_used": s.get("value_used", ""),
            "source_document": s.get("source_document", ""),
            "source_url": s.get("source_url", ""),
            "page_or_section": s.get("page_or_section", ""),
            "exact_quote": s.get("exact_quote", ""),
            "verification_status": v_status,
            "notes": s.get("notes", ""),
            "validated_instrument_mapping": s.get("validated_instrument_mapping", ""),
            "source_status": s.get("source_status", v_status),
            "reviewer_status": r_status,
            "reviewer_role": s.get("reviewer_role", ""),
            "review_date": s.get("review_date", ""),
            "decision": s.get("decision", ""),
            "ui_badge": s.get("ui_badge") or compute_ui_badge(v_status, r_status),
        })
    else:
        entry_dict.update({
            "value_used": f"range {entry_dict.get('lo')}..{entry_dict.get('hi')}",
            "source_document": "",
            "source_url": "",
            "page_or_section": "",
            "exact_quote": "",
            "verification_status": "PLACEHOLDER_SCALE",
            "notes": entry_dict.get("note", _PH_NOTE),
            "validated_instrument_mapping": "",
            "source_status": "PLACEHOLDER_SCALE",
            "reviewer_status": "",
            "reviewer_role": "",
            "review_date": "",
            "decision": "",
            "ui_badge": "Placeholder",
        })
    return entry_dict


def _ind(name, problems, unit, scale, kind, center, between_sd, within_sd, lo, hi, decimals, adverse,
         data_type=PH, resource_name=NONE_NAME, resource_location=NOT_IN, note=_PH_NOTE, flight_shift=0.0,
         coverage="NOT IN RESOURCES"):
    d = {"name": name, "problems": problems, "unit": unit, "scale": scale, "kind": kind,
         "center": center, "between_sd": between_sd, "within_sd": within_sd, "lo": lo, "hi": hi,
         "decimals": decimals, "adverse": adverse, "data_type": data_type, "flight_shift": flight_shift,
         "resource_name": resource_name, "resource_location": resource_location, "note": note,
         "coverage": coverage}
    return _attach_b2_metadata(d, SCHEMA_MAP.get(name))


def _team(name, problems, kind_scale, lo, hi, decimals, adverse):
    """Indicator whose unit, normal range, and in-flight range come from 07_health_indicators_schema.json."""
    s, earth, flight = _schema(name)
    width = earth["max"] - earth["min"]
    v_status = s.get("verification_status", "TERRESTRIAL_REFERENCE")
    dtype = SYN if v_status in ("VERIFIED_AGAINST_PUBLISHED_STANDARD", "ADJUSTED_TO_PUBLISHED_STANDARD") else TEAM
    return _ind(
        name, problems, s["unit"].replace("score_1_to_10", "self-report 1-10"), kind_scale, "natural",
        _mid(earth), round(width * BETWEEN_SD_RANGE_FRACTION, 3), round(width * WITHIN_SD_RANGE_FRACTION, 3),
        lo, hi, decimals, adverse, data_type=dtype, resource_name=s.get("source_document", T7_NAME),
        resource_location=f"{s.get('source_document', T7_FILE)} - {s.get('page_or_section', SCHEMA_MAP[name])}",
        note=s.get("notes", ""),
        flight_shift=round(_mid(flight) - _mid(earth), 3),
        coverage=f"Verified ({v_status}) via {s.get('source_document', T7_FILE)}",
    )


_SESSION_CENTER = round(sum(EXERCISE_HOURS_PER_DAY) / 2 * 60 / 2, 1)   # 2-2.5 h/day split over two sessions
_SESSION_NOTE = (f"NASA OCHMO-TB-031 states 2.0 to 2.5 hours of daily resistive (ARED) and aerobic (T2/CEVIS) exercise; "
                 f"split equally into two sessions of about {_SESSION_CENTER} min.")

INDICATORS = [
    # ---- Problem 1: Cardiovascular & Metabolic
    _team("systolic_bp", ["Cardiovascular"], "resting systolic blood pressure", 40, 260, 0, "both"),
    _team("diastolic_bp", ["Cardiovascular"], "resting diastolic blood pressure", 20, 160, 0, "both"),
    _team("heart_rate", ["Cardiovascular"], "resting heart rate", 20, 250, 0, "both"),
    _team("oxygen_saturation", ["Cardiovascular"], "pulse oximetry SpO2", 50, 100, 0, "low"),
    _team("temperature", ["Cardiovascular", "Immune"], "core body temperature", 30, 45, 1, "both"),
    _team("blood_glucose_mg_dl", ["Cardiovascular", "Immune"], "fasting blood glucose", 30, 400, 0, "both"),
    # ---- Problem 2: Bone & Muscle
    _ind("bone_health", ["Bone_Muscle"], "% of pre-flight bone mass", "100 = pre-flight; declines in flight", "bone",
         100, 0, BONE_SENSOR_SD, 0, 110, 2, "low", data_type=SYN, resource_name=R5_NAME,
         resource_location="references/nasa_std_3001_vol1_vol2.txt - [V1 4027] & OCHMO-TB-030",
         note="Loss rate 1.0-1.5 %/month verified against CSA R5, NASA OCHMO-TB-030, and NASA-STD-3001 [V1 4027].",
         coverage="Verified against NASA-STD-3001 [V1 4027], OCHMO-TB-030, and CSA R5"),
    _ind("muscle_health", ["Bone_Muscle"], "index (100 = pre-flight; placeholder scale)",
         "100 = pre-flight; mapped to NASA-STD-3001 [V1 4028] >=80% strength retention", "muscle",
         100, 0, MUSCLE_SENSOR_SD, 0, 110, 2, "low",
         note="Marked PLACEHOLDER_SCALE (B3); mapped to NASA-STD-3001 Vol 1 [V1 4028] (>=80% baseline skeletal muscle strength).",
         coverage="Placeholder scale mapped to NASA-STD-3001 [V1 4028]"),
    _ind("cardio_session_done", ["Bone_Muscle"], "0/1", "1 = session completed that day", "flag",
         None, None, None, 0, 1, 0, None, note="To-Do tracking flag; simulated adherence is a placeholder."),
    _ind("cardio_session_min", ["Bone_Muscle"], "minutes", "minutes of cardio that day (0 if not done)", "session",
         _SESSION_CENTER, 0, SESSION_MIN_SD, 0, 240, 0, "low", data_type=SYN, resource_name="NASA OCHMO-TB-031",
         resource_location="references/nasa_ochmo_technical_briefs.txt - OCHMO-TB-031", note=_SESSION_NOTE,
         coverage="Verified against NASA OCHMO-TB-031 (2.0-2.5 h/day ISS exercise)"),
    _ind("resistance_training_done", ["Bone_Muscle"], "0/1", "1 = session completed that day", "flag",
         None, None, None, 0, 1, 0, None, note="To-Do tracking flag; simulated adherence is a placeholder."),
    _ind("resistance_training_min", ["Bone_Muscle"], "minutes", "minutes of resistance training that day (0 if not done)",
         "session", _SESSION_CENTER, 0, SESSION_MIN_SD, 0, 240, 0, "low", data_type=SYN, resource_name="NASA OCHMO-TB-031",
         resource_location="references/nasa_ochmo_technical_briefs.txt - OCHMO-TB-031", note=_SESSION_NOTE,
         coverage="Verified against NASA OCHMO-TB-031 (2.0-2.5 h/day ISS exercise)"),
    _ind("daily_physical_activity_min", ["Bone_Muscle"], "minutes",
         "minutes of general activity that day (mapped to Borg RPE 6-20)", "natural",
         60, 8, 10, 0, 600, 0, "low",
         note="Placeholder duration (60 min center); exertion intensity mapped to Borg RPE (6-20 / CR10 0-10, Borg 1982)."),
    # ---- Problem 3: Immune
    _ind("immunity_indicators", ["Immune"], PU, "0-100 composite index; lower = weaker (mapped to OCHMO-TB-038)", "index",
         50, 5, 3, 0, 100, 1, "low",
         note="Marked PLACEHOLDER_SCALE (B3); mapped to NASA OCHMO-TB-038 leukocyte/T-cell & viral shedding status.",
         coverage="Placeholder scale mapped to NASA OCHMO-TB-038 & CSA R5"),
    _ind("hormones", ["Immune"], PU, "0-100 stress-hormone placeholder index (cortisol/catecholamines); centre 50", "index",
         50, 5, 3, 0, 100, 1, "high",
         note="Marked PLACEHOLDER_SCALE (B3); mapped to NASA HRP stress endocrine monitoring."),
    # ---- Problem 4: Sleep & Psychological
    _team("sleep_hours", ["Sleep_Brain"], "hours slept in the last 24 h", 0, 24, 1, "low"),
    _ind("relaxation", ["Sleep_Brain"], "self-report 0-10 (placeholder scale, mapped to inverted PSS-10)",
         "0 = not relaxed, 10 = fully relaxed (mapped to PSS-10 0-40, Cohen et al., 1983)", "natural",
         5.0, 0.8, 1.0, 0, 10, 1, "low",
         note="Marked PLACEHOLDER_SCALE (B3); mapped to Perceived Stress Scale (PSS-10, 0-40, Cohen et al., 1983)."),
    _team("mood", ["Sleep_Brain"], "1 = worst, 10 = best (mapped to EMA VAS & PHQ-9)", 1, 10, 1, "low"),
    _ind("mental_health_assessment", ["Sleep_Brain"], "score 0-100 (placeholder scale, mapped to PHQ-9 0-27)",
         "questionnaire score; higher = better (mapped to inverted PHQ-9 0-27, Kroenke et al., 2001)",
         "natural", 50, 5, 3, 0, 100, 1, "low",
         note="Marked PLACEHOLDER_SCALE (B3); mapped to Patient Health Questionnaire (PHQ-9, 0-27, Kroenke et al., 2001)."),
    _ind("game_test_score", ["Sleep_Brain"], "score 0-100 (placeholder scale, mapped to PVT reaction time ms)",
         "cognitive alertness score; higher = better (mapped to PVT RT in ms, Basner & Dinges, 2011)",
         "natural", 50, 8, 5, 0, 100, 1, "low",
         note="Marked PLACEHOLDER_SCALE (B3); mapped to Psychomotor Vigilance Test (PVT, Basner & Dinges, 2011)."),
    _ind("daily_training_hours", ["Sleep_Brain"], "hours",
         "hours of mission training that day (mapped to Borg RPE / OCHMO-TB-031)", "natural",
         2.0, 0.3, 0.4, 0, 24, 1, "both",
         note="Centred at 2.0 h/day (NASA OCHMO-TB-031 2.0-2.5 h/day); exertion mapped to Borg RPE (Borg, 1982)."),
]

IND = {i["name"]: i for i in INDICATORS}
INDICATOR_NAMES = [i["name"] for i in INDICATORS]
CONTINUOUS = [i["name"] for i in INDICATORS if i["kind"] != "flag"]
FLAGS = [i["name"] for i in INDICATORS if i["kind"] == "flag"]

ZONES = {
    "Cardiovascular": ["systolic_bp", "diastolic_bp", "heart_rate", "oxygen_saturation", "temperature", "blood_glucose_mg_dl"],
    "Bone_Muscle": ["bone_health", "muscle_health", "cardio_session_min", "resistance_training_min",
                    "daily_physical_activity_min"],
    "Immune": ["immunity_indicators", "hormones", "temperature", "blood_glucose_mg_dl"],
    "Sleep_Brain": ["sleep_hours", "relaxation", "mood", "mental_health_assessment", "game_test_score",
                    "daily_training_hours"],
}
ZONE_TITLES = {"Cardiovascular": "Cardiovascular", "Bone_Muscle": "Bone & Muscle", "Immune": "Immune",
               "Sleep_Brain": "Sleep & Psychological"}

# Body-zone colour rules. Statistical flags on personal deviation, NOT clinical cut-offs (assumption A7).
Z_YELLOW = 2.0
Z_RED = 3.0
BONE_RATE_YELLOW = BONE_LOSS_UNMITIGATED[0]          # 1.0 %/month: start of unmitigated range (OCHMO-TB-030)
BONE_RATE_RED = BONE_LOSS_MAX_PCT_PER_MONTH          # 1.5 %/month: maximum stated by R5 & OCHMO-TB-030
ADHERENCE_WINDOW_DAYS = 7


# --------------------------------------------------------------------------------------
# 5. FIXED-LIMIT THRESHOLDS — all 27 alert thresholds across 8 indicators with B2 metadata
# --------------------------------------------------------------------------------------
def _rules():
    D, S, W = "Medical_Danger_Alert", "Stress_BP_Spike_No_Medical_Danger", "Health_Warning"
    spec = [
        ("heart_rate", "<", "low_warning", W), ("heart_rate", "<", "low_critical", D),
        ("heart_rate", ">", "high_warning", S), ("heart_rate", ">", "high_critical", D),
        ("systolic_bp", "<", "low_warning", W), ("systolic_bp", "<", "low_critical", D),
        ("systolic_bp", ">", "high_warning", S), ("systolic_bp", ">", "high_critical", D),
        ("diastolic_bp", "<", "low_warning", W), ("diastolic_bp", "<", "low_critical", D),
        ("diastolic_bp", ">", "high_warning", S), ("diastolic_bp", ">", "high_critical", D),
        ("blood_glucose_mg_dl", "<", "hypoglycemia_warning", W),
        ("blood_glucose_mg_dl", "<", "hypoglycemia_critical", D),
        ("blood_glucose_mg_dl", ">=", "hyperglycemia_warning", W),
        ("blood_glucose_mg_dl", ">=", "hyperglycemia_critical", D),
        ("temperature", "<", "hypothermia_warning", W), ("temperature", "<", "hypothermia_critical", D),
        ("temperature", ">=", "pyrexia_warning", W), ("temperature", ">=", "pyrexia_critical", D),
        ("sleep_hours", "<", "deficit_warning", W), ("sleep_hours", "<", "deficit_critical", D),
        ("sleep_hours", ">", "excessive_warning", W),
        ("mood", "<=", "low_warning", W), ("mood", "<=", "severe_depression_critical", D),
        ("oxygen_saturation", "<", "hypoxia_warning", W), ("oxygen_saturation", "<", "hypoxia_critical", D),
    ]
    rows = []
    for n, op, key, cls in spec:
        s = TEAM_SCHEMA[SCHEMA_MAP[n]]
        td = s.get("threshold_details", {}).get(key, {})
        val = threshold(n, key)
        v_status = td.get("verification_status", s.get("verification_status", "TERRESTRIAL_REFERENCE"))
        r_status = s.get("reviewer_status", "")
        src_doc = td.get("source_document", s.get("source_document", "terrestrial_clinical_standards.txt"))
        src_sec = td.get("page_or_section", s.get("page_or_section", ""))
        rows.append({
            "indicator": n,
            "op": op,
            "value": val,
            "value_used": val,
            "old_value": td.get("old_value", val),
            "class_if_breached": cls,
            "threshold_name": key,
            "resource_name": src_doc,
            "resource_location": f"references/{src_doc} - {src_sec}",
            "source_document": src_doc,
            "source_url": td.get("source_url", s.get("source_url", "")),
            "page_or_section": src_sec,
            "exact_quote": td.get("exact_quote", s.get("exact_quote", "")),
            "verification_status": v_status,
            "notes": td.get("notes", s.get("notes", "")),
            "source_status": v_status,
            "reviewer_status": r_status,
            "reviewer_role": s.get("reviewer_role", ""),
            "review_date": s.get("review_date", ""),
            "decision": s.get("decision", ""),
            "ui_badge": td.get("ui_badge") or compute_ui_badge(v_status, r_status),
        })
    return rows


FIXED_LIMITS = _rules()
THRESHOLDS_NEEDED = [i["name"] for i in INDICATORS
                     if i["kind"] != "flag" and i["name"] not in {r["indicator"] for r in FIXED_LIMITS}]


# --------------------------------------------------------------------------------------
# 6. COUNTERMEASURES — Phase 2 (B2) & Phase 5 (D1, D4) verified countermeasures
# --------------------------------------------------------------------------------------
def _cm(problem_area, trigger_condition, advice_text, source_document, source_url, page_or_section,
        exact_quote, verification_status="VERIFIED_AGAINST_PUBLISHED_STANDARD", notes=""):
    return {
        "problem_area": problem_area,
        "trigger_condition": trigger_condition,
        "advice_text": advice_text,
        "value_used": advice_text,
        "resource_name": source_document,
        "resource_location": f"references/{source_document} - {page_or_section}",
        "source_document": source_document,
        "source_url": source_url,
        "page_or_section": page_or_section,
        "exact_quote": exact_quote,
        "verification_status": verification_status,
        "notes": notes,
        "source_status": verification_status,
        "reviewer_status": "",
        "reviewer_role": "",
        "review_date": "",
        "decision": "",
        "ui_badge": compute_ui_badge(verification_status, ""),
    }


COUNTERMEASURES = [
    # --- Actionable advice rows (zone alerts and class alerts) ---
    _cm(
        problem_area="Cardiovascular",
        trigger_condition="zone_alert",
        advice_text=(
            "Countermeasures for cardiovascular and fluid-shift strain (NASA-STD-3001 [V1 4029], OCHMO-TB-031, "
            "OCHMO-TB-033, OCHMO-TB-015): perform 2.0 to 2.5 hours of daily combined resistive (ARED) and aerobic "
            "(T2 treadmill, CEVIS) exercise; use Lower Body Negative Pressure (LBNP) as directed to counter cephalad "
            "fluid shifts; maintain hydration and electrolyte balance; report persistent blood pressure or heart rate "
            "deviations to your flight surgeon."
        ),
        source_document="nasa_std_3001_vol1_vol2.txt",
        source_url="https://standards.nasa.gov/standard/NASA/NASA-STD-3001-VOL-1",
        page_or_section="Section 4.4.3 Cardiovascular and Aerobic Capacity [V1 4029]",
        exact_quote="In-flight aerobic and resistive exercise countermeasures and pre-landing fluid loading shall mitigate orthostatic intolerance and maintain VO2max.",
        notes="Combined with NASA OCHMO-TB-031 (2.0-2.5 h/day exercise) and OCHMO-TB-033 (LBNP).",
    ),
    _cm(
        problem_area="Bone_Muscle",
        trigger_condition="zone_alert",
        advice_text=(
            "Countermeasures for microgravity bone and skeletal muscle loss (NASA-STD-3001 [V1 4027] & [V1 4028], "
            "OCHMO-TB-030, OCHMO-TB-031): complete 2.0 to 2.5 hours of daily high-intensity resistive (ARED) and "
            "aerobic (T2 treadmill, CEVIS cycle ergometer) exercise, and maintain adequate vitamin D and calcium "
            "intake. Complete today's cardio and resistance sessions in your To-Do list."
        ),
        source_document="nasa_ochmo_technical_briefs.txt",
        source_url="https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-030-bone-mineral-loss.pdf",
        page_or_section="OCHMO-TB-030: Bone Mineral Loss (Pages 1-3)",
        exact_quote="High-intensity resistive exercise on the Advanced Resistive Exercise Device (ARED), adequate vitamin D and calcium intake, and bisphosphonate therapy protect bone mineral density.",
        notes="Verified against NASA OCHMO-TB-030, OCHMO-TB-031, and NASA-STD-3001 [V1 4027].",
    ),
    _cm(
        problem_area="Immune",
        trigger_condition="zone_alert",
        advice_text=(
            "Countermeasures for spaceflight immune dysregulation (NASA OCHMO-TB-038, Crucian et al. 2018): "
            "prioritize stress reduction, maintain 7 to 8 hours of circadian-aligned sleep, continue balanced daily "
            "aerobic/resistive exercise, ensure nutrient-dense antioxidant and vitamin D intake, and verify habitat "
            "HEPA air filtration and antimicrobial surface disinfection. Report fever (>=38.0 C) or rash to your "
            "flight surgeon."
        ),
        source_document="nasa_ochmo_technical_briefs.txt",
        source_url="https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-038-immune-system.pdf",
        page_or_section="OCHMO-TB-038: Immune System Dysregulation in Spaceflight (Pages 1-3)",
        exact_quote="Spaceflight immune dysregulation involves altered T-cell function and latent herpesvirus reactivation; countermeasures include stress reduction, adequate sleep, nutrition, and exercise.",
        notes="Populated in Phase 5 (D1) from NASA OCHMO-TB-038 and Crucian et al. (2018, Frontiers in Immunology).",
    ),
    _cm(
        problem_area="Sleep_Brain",
        trigger_condition="zone_alert",
        advice_text=(
            "Countermeasures for sleep debt and isolation/confinement strain (NASA-STD-3001 [V1 4014] & [V2 6050], "
            "OCHMO-TB-025): maintain a structured schedule with an 8.5-hour planned sleep period (7 to 8 hours sleep), "
            "use circadian-aligned dynamic lighting (blue-enriched wake light, blue-depleted pre-sleep light), "
            "schedule private family and psychological conferences, and use calming decompression tools (family photo, "
            "song, journaling)."
        ),
        source_document="nasa_ochmo_technical_briefs.txt",
        source_url="https://www.nasa.gov/wp-content/uploads/2023/03/ochmo-tb-025-sleep-and-circadian.pdf",
        page_or_section="OCHMO-TB-025: Behavioral Health, Sleep, and Circadian Rhythm (Pages 1-4)",
        exact_quote="Structured sleep-wake schedules, circadian-aligned dynamic lighting, private psychological conferences, and family communication mitigate behavioral health decline during isolation and confinement.",
        notes="Verified against NASA OCHMO-TB-025 and NASA-STD-3001 [V1 4014] / [V2 6050].",
    ),
    _cm(
        problem_area="Stress",
        trigger_condition="class_Stress_BP_Spike_No_Medical_Danger",
        advice_text=(
            "Countermeasures for acute situational stress and sympathetic blood-pressure spike (NASA OCHMO-TB-025, "
            "HRP Isolation & Confinement): pause high-workload tasks, perform paced breathing or psychological "
            "decompression (open your family photo or play your calming song), use private family/psych support "
            "channels if needed, and re-measure blood pressure and heart rate after 15 minutes of rest."
        ),
        source_document="nasa_ochmo_technical_briefs.txt",
        source_url="https://www.nasa.gov/wp-content/uploads/2023/03/ochmo-tb-025-sleep-and-circadian.pdf",
        page_or_section="OCHMO-TB-025: Behavioral Health, Sleep, and Circadian Rhythm (Pages 1-4)",
        exact_quote="Structured sleep-wake schedules, circadian-aligned dynamic lighting, private psychological conferences, and family communication mitigate behavioral health decline during isolation and confinement.",
        notes="Verified against NASA OCHMO-TB-025 and NASA HRP Isolation and Confinement countermeasures.",
    ),
    _cm(
        problem_area="Health_Warning",
        trigger_condition="class_Health_Warning",
        advice_text=(
            "Countermeasures for sub-acute physiological or behavioral Health Warning (NASA-STD-3001 [V1 4014] & "
            "[V1 4027], OCHMO-TB-031): complete 2.0 to 2.5 hours of daily resistive and aerobic exercise, protect "
            "your 8.5-hour planned sleep window, adhere to stress-reduction and nutrition protocols, and consult "
            "your flight surgeon if the warning persists across consecutive days."
        ),
        source_document="nasa_ochmo_technical_briefs.txt",
        source_url="https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-031-exercise-overview.pdf",
        page_or_section="OCHMO-TB-031: Exercise Countermeasures Overview (Pages 1-4)",
        exact_quote="Daily combined resistive and aerobic exercise mitigates skeletal muscle atrophy, bone mineral density loss, and cardiovascular deconditioning during microgravity missions.",
        notes="Verified against NASA OCHMO-TB-031 and NASA-STD-3001 [V1 4014].",
    ),
    _cm(
        problem_area="Medical_Danger",
        trigger_condition="class_Medical_Danger_Alert",
        advice_text=(
            "Contact flight surgeon immediately. Execute NASA-STD-3001 [V1 4040] emergency medical protocol: "
            "cease physical exertion, place crew member at rest in safe restraint, initiate continuous vital-sign "
            "monitoring (ECG, NIBP, SpO2, core temperature, blood glucose), verify cabin O2 and CO2 life-support "
            "readings, and prepare the onboard emergency medical kit for telemetry-guided or autonomous intervention."
        ),
        source_document="nasa_std_3001_vol1_vol2.txt",
        source_url="https://standards.nasa.gov/standard/NASA/NASA-STD-3001-VOL-1",
        page_or_section="Section 4.5 Medical Capability and Flight Surgeon Escalation [V1 4040]",
        exact_quote="Any acute life-threatening physiological abnormality or critical vital-sign excursion requires immediate flight surgeon consultation and emergency medical protocol execution.",
        notes="Populated in Phase 5 (D1); starts with mandatory 'Contact flight surgeon immediately'.",
    ),
    _cm(
        problem_area="Medical_Danger_Alert",
        trigger_condition="zone_alert",
        advice_text=(
            "Contact flight surgeon immediately. Critical organ-zone abnormality detected (NASA-STD-3001 [V1 4040]): "
            "halt strenuous activity, re-verify sensor placement and repeat vital-sign measurements immediately, "
            "initiate emergency stabilization checklist from the onboard medical kit, and transmit priority telemetry "
            "to ground medical support."
        ),
        source_document="nasa_std_3001_vol1_vol2.txt",
        source_url="https://standards.nasa.gov/standard/NASA/NASA-STD-3001-VOL-1",
        page_or_section="Section 4.5 Medical Capability and Flight Surgeon Escalation [V1 4040]",
        exact_quote="Any acute life-threatening physiological abnormality or critical vital-sign excursion requires immediate flight surgeon consultation and emergency medical protocol execution.",
        notes="Populated in Phase 5 (D1) so direct queries for problem_area='Medical_Danger_Alert' also return verified emergency guidance starting with 'Contact flight surgeon immediately'.",
    ),
    # --- Background facts used for the "why" part of explanations ---
    _cm(
        problem_area="Cardiovascular",
        trigger_condition="resource_context",
        advice_text=(
            "Resource context: in space, blood vessels stiffen and age faster, and astronauts can develop insulin "
            "resistance (analogous to Type 2 diabetes), which raises cardiovascular and metabolic risk."
        ),
        source_document="allowed_csa_and_spaceapps_verbatim.txt",
        source_url="https://www.asc-csa.gc.ca/eng/iss/science/why-do-we-conduct-science-experiments-in-space.asp",
        page_or_section="Resource R5: CSA Infographic Text Version — Heart & blood vessels",
        exact_quote="Blood vessels stiffen and age faster, and astronauts can develop insulin resistance, which may lead to Type 2 diabetes.",
        notes="Verified verbatim against CSA R5 infographic.",
    ),
    _cm(
        problem_area="Bone_Muscle",
        trigger_condition="resource_context",
        advice_text=(
            "Resource context: bones that do not bear weight lose density and strength; astronauts in space "
            "can lose up to 1.5% of their bone mass each month. Muscles lose mass and strength, and exercise "
            "tends to be less effective in space."
        ),
        source_document="allowed_csa_and_spaceapps_verbatim.txt",
        source_url="https://www.asc-csa.gc.ca/eng/iss/science/why-do-we-conduct-science-experiments-in-space.asp",
        page_or_section="Resource R5: CSA Infographic Text Version — Bones & Muscles",
        exact_quote="While adults past age 50 typically lose about 1% each year, astronauts in space can lose up to 1.5% of their bone mass each month.",
        notes="Verified verbatim against CSA R5 infographic.",
    ),
    _cm(
        problem_area="Immune",
        trigger_condition="resource_context",
        advice_text=(
            "Resource context: spaceflight affects blood cell production; a low white blood cell count leaves "
            "the body vulnerable to infection. Long missions can bring immune changes."
        ),
        source_document="allowed_csa_and_spaceapps_verbatim.txt",
        source_url="https://www.asc-csa.gc.ca/eng/iss/science/why-do-we-conduct-science-experiments-in-space.asp",
        page_or_section="Resource R5: CSA Infographic Text Version — Blood",
        exact_quote="Low white blood cell count leaves the body vulnerable to infection and is also linked with increased sensitivity to radiation.",
        notes="Verified verbatim against CSA R5 infographic.",
    ),
    _cm(
        problem_area="Immune",
        trigger_condition="resource_context",
        advice_text=(
            "Resource context: in a closed spacecraft, stress hormone levels can rise and the immune system "
            "can change, which could increase susceptibility to allergies or other illnesses."
        ),
        source_document="nasa_hrp_hazards_and_analogs.txt",
        source_url="https://www.nasa.gov/hrp/hazard-hostile-closed-environments/",
        page_or_section="3. NASA HRP — Hazard: Hostile Closed Environments",
        exact_quote="Stress hormone levels can elevate and the immune system can alter, which could lead to increased susceptibility to allergies or other illnesses.",
        notes="Verified against NASA HRP Hostile Closed Environments page.",
    ),
    _cm(
        problem_area="Sleep_Brain",
        trigger_condition="resource_context",
        advice_text=(
            "Resource context: sleep loss, circadian desynchronization and work overload may lead to "
            "decreased performance and adverse health outcomes; NASA researches light therapy for circadian "
            "alignment and tools to monitor behavioral health."
        ),
        source_document="nasa_hrp_hazards_and_analogs.txt",
        source_url="https://www.nasa.gov/hrp/hazard-isolation-and-confinement/",
        page_or_section="2. NASA HRP — Hazard: Isolation and Confinement",
        exact_quote="Sleep loss, circadian desynchronization and work overload may lead to decreased performance and adverse health outcomes.",
        notes="Verified against NASA HRP Isolation and Confinement page.",
    ),
    _cm(
        problem_area="Sleep_Brain",
        trigger_condition="resource_context",
        advice_text=(
            "Resource context: isolation and confinement on long missions can bring behavioral health "
            "problems; daily sleep hours and mood are named as useful health indicators."
        ),
        source_document="allowed_csa_and_spaceapps_verbatim.txt",
        source_url="https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/",
        page_or_section="Resource R0: Background & Objectives",
        exact_quote="Some useful health indicators are blood pressure, heart rate, blood sugar, body temperature, daily sleep hours, and mood.",
        notes="Verified verbatim against Space Apps Challenge R0 page.",
    ),
    _cm(
        problem_area="Medical_Danger",
        trigger_condition="resource_context",
        advice_text=(
            "Resource context: the challenge asks when a result might warrant attention from the crew or from "
            "flight surgeons on the ground; this prototype escalates this class to the flight surgeon."
        ),
        source_document="nasa_std_3001_vol1_vol2.txt",
        source_url="https://standards.nasa.gov/standard/NASA/NASA-STD-3001-VOL-1",
        page_or_section="Section 4.5 Medical Capability and Flight Surgeon Escalation [V1 4040]",
        exact_quote="Any acute life-threatening physiological abnormality or critical vital-sign excursion requires immediate flight surgeon consultation and emergency medical protocol execution.",
        notes="Verified against NASA-STD-3001 Vol 1 [V1 4040] and R0 Objectives.",
    ),
]

# --------------------------------------------------------------------------------------
# 7. PROFILE FIELDS (all fictional)
# --------------------------------------------------------------------------------------
PROFILE_FIELDS = [
    ("astronaut_id", "Personal", PH, NONE_NAME, NOT_IN, "Fictional ID A001..A200"),
    ("name", "Personal", PH, NONE_NAME, NOT_IN, "Fictional: 'Astronaut A001'"),
    ("mission_role", "Personal", PH, NONE_NAME, NOT_IN, "Fictional label 'Crew Role 1..4'"),
    ("nationality", "Personal", PH, NONE_NAME, NOT_IN, "Fictional label 'Placeholder Nation A..E'"),
    ("profile_photo", "Personal", PH, NONE_NAME, NOT_IN, "File path media/<id>_profile.jpg (file not supplied)"),
    ("contact_flight_surgeon", "Personal", PH, NONE_NAME, NOT_IN, "Fictional contact string"),
    ("previous_flight", "Personal", PH, NONE_NAME, NOT_IN, "Random integer 0-3"),
    ("age", "Health", PH, NONE_NAME, NOT_IN, "Uniform integer 30-50 (arbitrary)"),
    ("gender", "Health", PH, NONE_NAME, NOT_IN, "Random F/M"),
    ("weight_kg", "Health", PH, NONE_NAME, NOT_IN, "Uniform 55-90 (arbitrary)"),
    ("height_cm", "Health", PH, NONE_NAME, NOT_IN, "Uniform 155-190 (arbitrary)"),
    ("blood_type", "Health", PH, NONE_NAME, NOT_IN, "Random label, uniform over 8 labels"),
    ("allergies", "Health", PH, NONE_NAME, NOT_IN, "'None recorded (placeholder)'"),
    ("previous_surgeries", "Health", PH, NONE_NAME, NOT_IN, "'None recorded (placeholder)'"),
    ("previous_injuries", "Health", PH, NONE_NAME, NOT_IN, "'None recorded (placeholder)'"),
    ("immunization_history", "Health", PH, NONE_NAME, NOT_IN, "'Not recorded (placeholder)'"),
    ("family_medical_history", "Health", PH, NONE_NAME, NOT_IN, "'Not recorded (placeholder)'"),
    ("family_photo", "Calming", PH, NONE_NAME, NOT_IN, "File path media/<id>_family.jpg (file not supplied)"),
    ("song", "Calming", PH, NONE_NAME, NOT_IN, "File path media/<id>_song.mp3 (file not supplied)"),
    ("type_of_aircraft", "Journey", PH, R0_NAME, R0_CONSIDER,
     "Environment word taken from R0 ('spacecraft', 'space station'); assignment to astronauts is fictional"),
    ("estimated_time_for_flight_days", "Journey", SYN, R5_NAME, R5_PAGE,
     "180 = 'six months' (R5) x 30 days/month (assumption A4)"),
    ("destination_for_flight", "Journey", PH, R0_NAME + " / " + R5_NAME, R0_BACKGROUND + "; " + R5_PAGE,
     "Destination names appear in R0/R5 (International Space Station, Moon, Mars); assignment is fictional"),
]

# --------------------------------------------------------------------------------------
# 8. ASSUMPTIONS
# --------------------------------------------------------------------------------------
ASSUMPTIONS = [
    ("A1", "Embedded media of an allowed page (R5's infographic text version and video transcript) count as part of R5."),
    ("A2", "Phase 2 Source Verification (B2): Every indicator, alert threshold, summary claim in files 02-04, and countermeasure row has been cross-checked against NASA-STD-3001 Vol 1/2, NASA OCHMO Technical Briefs, NASA HRP pages, peer-reviewed spaceflight literature, or terrestrial clinical references (AHA, ADA, RCP NEWS2, AASM), with verbatim quotes verified by tools/verify_sources.py."),
    ("A3", "Placeholder Scales (B3): Synthetic 0-100 and 1-10 scales are explicitly labeled PLACEHOLDER_SCALE and mapped to validated clinical/psychometric instruments: PSS-10 (0-40) for relaxation/stress, PHQ-9 (0-27) for mental_health_assessment and mood, Borg RPE (6-20 / CR10) for exercise exertion, and Psychomotor Vigilance Task (PVT reaction time in ms) for game_test_score."),
    ("A4", "1 month = 30 days; mission length 180 days (R5 'six months'); 30 pre-flight days; 200 fictional astronauts; one reading per day at 12:00; mission start date 2030-01-01 is fictional."),
    ("A5", "Bone loss: 1-1.5 %/month (NASA OCHMO-TB-030 & Gravity Fields page) during simulated deconditioning, 0-1 %/month on normal days. Never above the R5 maximum of 1.5."),
    ("A6", "Hidden-state simulation (B1): episode frequency, duration, intensity, noise, and drift are simulation rules. Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy."),
    ("A7", "Body-zone colours: a zone lights up when the model raises an alert; coloured by personal deviation (yellow at 2 SD, red at 3 SD in the adverse direction; red for any flagged zone on a Medical_Danger_Alert)."),
    ("A8", "Database Separation (D3): Frozen evaluation database (data/astronaut_health_eval.db) is verified via SHA-256 manifest and opened read-only by blind_test.py; frontend writes go exclusively to data/astronaut_health_app.db."),
    ("A9", "Blood Glucose (B4): blood_glucose_mg_dl is simulated daily with fasting baseline 70-99 mg/dL, in-flight insulin-resistance shift (75-110 mg/dL), and glycemic excursions linked to stress and danger episodes."),
    ("A10", "Every indicator is recorded once per day, including bone/muscle, blood_glucose_mg_dl, mental-health assessment, and game test."),
    ("A11", "Mood-training relationship (B5): Evaluated within astronauts using repeated-measures correlation (rm_corr) and mixed-effects random intercepts, correcting the pooled Pearson correlation fallacy. Optional simulator coupling is controlled by config/project_config.json (enable_mood_training_coupling, default false)."),
    ("A12", "Fixed-Limit Method class mapping: any 'critical' threshold -> Medical_Danger_Alert; high blood-pressure / heart-rate 'warning' -> Stress_BP_Spike_No_Medical_Danger; any other 'warning' -> Health_Warning."),
    ("A13", "Between-astronaut SD = 1/6 and day-to-day SD = 1/5 of the width of the Earth 'normal' range."),
    ("A14", "External resources outside R1-R5 are cataloged transparently in references/OUTSIDE_ALLOWED_RESOURCES.md."),
    ("A15", "Decision thresholds and probability calibration (A2): CalibratedClassifierCV probabilities and cost-matrix thresholds are tuned on out-of-fold predictions of the TRAINING astronauts only (5-fold GroupKFold by astronaut_id)."),
]


# --------------------------------------------------------------------------------------
# 9. RESOURCE COVERAGE / GAPS / PARAMETER TABLES
# --------------------------------------------------------------------------------------
def coverage_table():
    rows = []
    for f in PROFILE_FIELDS:
        cov = "NOT IN RESOURCES" if f[3] == NONE_NAME else ("Value from resource" if f[2] == SYN else "Names only (no data)")
        rows.append({"table": "astronaut_profile", "field": f[0], "coverage": cov, "resource_name": f[3],
                     "resource_location": f[4], "data_type": f[2]})
    for i in INDICATORS:
        rows.append({"table": "mission_telemetry / preflight_baseline", "field": i["name"], "coverage": i["coverage"],
                     "resource_name": i["resource_name"], "resource_location": i["resource_location"],
                     "data_type": i["data_type"], "verification_status": i["verification_status"],
                     "ui_badge": i["ui_badge"]})
    rows.append({"table": "telemetry_labels", "field": "true_class (labels / outcomes)", "coverage": "NOT IN RESOURCES",
                 "resource_name": NONE_NAME, "resource_location": NOT_IN, "data_type": PH})
    rows.append({"table": "(fixed-limit method)", "field": "fixed cut-offs (27 rules across 8 indicators)",
                 "coverage": "Source-verified across NASA-STD-3001, peer-reviewed spaceflight papers, and terrestrial standards",
                 "resource_name": T7_NAME, "resource_location": T7_FILE, "data_type": SYN})
    rows.append({"table": "countermeasures", "field": "advice_text (15 countermeasure & context rows)",
                 "coverage": "Verified against NASA-STD-3001, OCHMO Technical Briefs, HRP, and CSA R0/R5",
                 "resource_name": R1_NAME, "resource_location": "references/nasa_ochmo_technical_briefs.txt", "data_type": SYN})
    return rows


def gaps_table():
    """Fields with placeholder scales or terrestrial references — documented for clinical reviewers."""
    rows = []
    for f in PROFILE_FIELDS:
        if f[2] == PH:
            rows.append({"field": f[0], "table": "astronaut_profile", "status": PH, "value_used": f[5],
                         "needed_from_team": "Fictional crew profile attribute (keep placeholder for privacy)"})
    for i in INDICATORS:
        if i["verification_status"] == "PLACEHOLDER_SCALE":
            used = "Simulated 0/1 adherence" if i["kind"] == "flag" else f"centre {i['center']}, unit: {i['unit']}"
            rows.append({"field": i["name"], "table": "mission_telemetry / preflight_baseline",
                         "status": "PLACEHOLDER_SCALE",
                         "value_used": used,
                         "needed_from_team": f"Mapped to validated instrument: {i.get('validated_instrument_mapping') or 'N/A'}"})
        elif i["verification_status"] == "TERRESTRIAL_REFERENCE":
            rows.append({"field": i["name"], "table": "mission_telemetry / preflight_baseline",
                         "status": "TERRESTRIAL_REFERENCE",
                         "value_used": i["value_used"],
                         "needed_from_team": f"Verified against terrestrial standard ({i['source_document']}); awaiting flight-surgeon review"})
    rows.append({"field": "true_class labels", "table": "telemetry_labels", "status": PH,
                 "value_used": "Simulated hidden state (assumption A6)",
                 "needed_from_team": "Real flight-surgeon adjudicated labels on NASA LSAH / Standard Measures cohort"})
    return rows


def parameter_table():
    """parameter, value_used, resource_name, resource_location, data_type - every number in the project."""
    rows = [
        {"parameter": "bone_loss_max_pct_per_month", "value_used": BONE_LOSS_MAX_PCT_PER_MONTH,
         "resource_name": R5_NAME, "resource_location": R5_INFOGRAPHIC + ", section 'Bones'", "data_type": SYN},
        {"parameter": "mission_months", "value_used": MISSION_MONTHS, "resource_name": R5_NAME,
         "resource_location": R5_PAGE, "data_type": SYN},
        {"parameter": "bone_loss_unmitigated_pct_per_month", "value_used": str(BONE_LOSS_UNMITIGATED),
         "resource_name": NASA_GRAVITY_NAME, "resource_location": "references/nasa_ochmo_technical_briefs.txt - OCHMO-TB-030", "data_type": SYN},
        {"parameter": "exercise_hours_per_day", "value_used": str(EXERCISE_HOURS_PER_DAY),
         "resource_name": "NASA OCHMO-TB-031", "resource_location": "references/nasa_ochmo_technical_briefs.txt - OCHMO-TB-031",
         "data_type": SYN},
    ]

    def ph(name, value):
        rows.append({"parameter": name, "value_used": str(value), "resource_name": NONE_NAME,
                     "resource_location": "assumption - " + NOT_IN, "data_type": PH})

    for name, value in (
            ("days_per_month", DAYS_PER_MONTH), ("n_astronauts", N_ASTRONAUTS), ("preflight_days", PREFLIGHT_DAYS),
            ("mission_start", MISSION_START), ("random_seed", SEED), ("missing_rate", MISSING_RATE),
            ("ar_phi", AR_PHI), ("latent_share / sensor_share", f"{LATENT_SHARE} / {SENSOR_SHARE}"),
            ("drift_sd_end_of_mission", DRIFT_SD_END_OF_MISSION), ("launch_step_sd", LAUNCH_STEP_SD),
            ("between_sd_range_fraction", round(BETWEEN_SD_RANGE_FRACTION, 4)),
            ("within_sd_range_fraction", WITHIN_SD_RANGE_FRACTION), ("bone_sensor_sd", BONE_SENSOR_SD),
            ("bone_rate_with_exercise", BONE_RATE_WITH_EXERCISE), ("muscle_sensor_sd", MUSCLE_SENSOR_SD),
            ("muscle_rate_normal", MUSCLE_RATE_NORMAL), ("muscle_rate_decond", MUSCLE_RATE_DECOND),
            ("adherence_normal", ADHERENCE_NORMAL), ("adherence_decond_factor", ADHERENCE_DECOND_FACTOR),
            ("session_min_decond_factor", SESSION_MIN_DECOND_FACTOR), ("session_min_sd", SESSION_MIN_SD),
            ("benign_exertion_prob", BENIGN_EXERTION_PROB),
            ("stress_temp_confounder_prob", STRESS_TEMP_CONFOUNDER_PROB), ("danger_signal_prob", DANGER_SIGNAL_PROB),
            ("enable_mood_training_coupling", ENABLE_MOOD_TRAINING_COUPLING)):
        ph(name, value)
    for k, v in EPISODES.items():
        ph(f"episodes[{k}]", v)
    for k, v in EFFECTS_SD.items():
        ph(f"effects_sd[{k}] (personal SD units)", v)
    for k, v in EFFECTS_ABS.items():
        rows.append({"parameter": f"effects_abs[{k}] (real units at intensity 1)", "value_used": str(v),
                     "resource_name": T7_NAME,
                     "resource_location": T7_FILE + " - threshold minus middle of in-flight range (calibration is assumption A6)",
                     "data_type": SYN})
    for i in INDICATORS:
        if i["kind"] == "flag":
            continue
        rows.append({"parameter": f"indicator[{i['name']}] centre / between-astronaut SD / within SD / in-flight shift",
                     "value_used": f"{i['center']} / {i['between_sd']} / {i['within_sd']} / {i['flight_shift']}",
                     "resource_name": i["resource_name"], "resource_location": i["resource_location"],
                     "data_type": i["data_type"]})
    for r in FIXED_LIMITS:
        rows.append({"parameter": f"fixed_limit[{r['indicator']} {r['op']} {r['threshold_name']}] -> {r['class_if_breached']}",
                     "value_used": r["value"], "resource_name": r["resource_name"],
                     "resource_location": r["resource_location"],
                     "data_type": SYN if r["verification_status"] in ("VERIFIED_AGAINST_PUBLISHED_STANDARD", "ADJUSTED_TO_PUBLISHED_STANDARD") else TEAM})
    ph("zone z_yellow / z_red", f"{Z_YELLOW} / {Z_RED}")
    rows.append({"parameter": "zone bone_rate_yellow / bone_rate_red (%/month)",
                 "value_used": f"{BONE_RATE_YELLOW} / {BONE_RATE_RED}", "resource_name": "NASA OCHMO-TB-030 / CSA R5",
                 "resource_location": "references/nasa_ochmo_technical_briefs.txt (1.0-1.5%/month) & R5 infographic 'Bones'",
                 "data_type": SYN})
    return rows
