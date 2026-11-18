# Sources Audit — Physiological Indicators, Thresholds, Summaries & Countermeasures

**Prototype for research/education only — not for clinical diagnosis.**  
**Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.**

This audit documents every physiological indicator, alert threshold, NASA summary claim (`02–04`), and operational countermeasure across `data_raw/team_supplied/07_health_indicators_schema.json` and `resource_facts.py`, comparing the pre-Phase 2 unverified baseline against the post-Phase 2 verified and reproducible state enforced by [`tools/verify_sources.py`](file:///d:/NASA%202/project/tools/verify_sources.py).

---

## 1. Hierarchical Source Verification Protocol (Phase 2 — B2)

Every parameter was cross-checked in strict priority order, with local verification copies saved in `references/`:

1. **(a) NASA-STD-3001 Volume 1 Rev C & Volume 2 Rev D** → [`nasa_std_3001_vol1_vol2.txt`](file:///d:/NASA%202/project/references/nasa_std_3001_vol1_vol2.txt)
2. **(b) NASA OCHMO Technical Briefs (`OCHMO-TB-004`, `015`, `025`, `030`, `031`, `033`, `038`)** → [`nasa_ochmo_technical_briefs.txt`](file:///d:/NASA%202/project/references/nasa_ochmo_technical_briefs.txt)
3. **(c) NASA Human Research Program (HRP) Hazard & Research Pages** → [`nasa_hrp_hazards_and_analogs.txt`](file:///d:/NASA%202/project/references/nasa_hrp_hazards_and_analogs.txt)
4. **(d) Peer-Reviewed Spaceflight Medicine Literature** (Stahn et al. 2017, Barger et al. 2014, Basner & Dinges 2011, Sirek et al. 2014, Cucinotta et al. 2008, Crucian et al. 2018) → [`spaceflight_peer_reviewed_papers.txt`](file:///d:/NASA%202/project/references/spaceflight_peer_reviewed_papers.txt)
5. **(e) Terrestrial Clinical References** (AHA/ACC Blood Pressure Guidelines, ADA Standards of Care 2024, Royal College of Physicians NEWS2, AASM/NSF Sleep Consensus, Cohen PSS-10, Kroenke PHQ-9, Borg RPE) — used **only** where no spaceflight-specific value is published → [`terrestrial_clinical_standards.txt`](file:///d:/NASA%202/project/references/terrestrial_clinical_standards.txt)
6. **Challenge R0–R5 Verbatim Texts** → [`allowed_csa_and_spaceapps_verbatim.txt`](file:///d:/NASA%202/project/references/allowed_csa_and_spaceapps_verbatim.txt)

All documents outside the initial five challenge links (`R1–R5`) are explicitly inventoried in [`references/OUTSIDE_ALLOWED_RESOURCES.md`](file:///d:/NASA%202/project/references/OUTSIDE_ALLOWED_RESOURCES.md).

---

## 2. Verification Status Counts: Before vs. After Audit

`tools/verify_sources.py` fails the build (`exit 1`) if any non-`UNVERIFIED` entry lacks a matching file in `references/`, lacks an `exact_quote` of `<= 25` words, fails a `>= 90%` fuzzy match against the extracted reference document text, uses an invalid `verification_status`, omits `old_value` after adjustment, or populates `reviewer_status` without `reviewer_role`, `review_date`, and `decision`.

| Audited Table / Collection | Total Items | Before Phase 2 (Version 3 Baseline) | After Phase 2–5 (`tools/verify_sources.py` = PASS) |
|---|---:|---|---|
| **Schema Indicators** (`07_health_indicators_schema.json`) | **18** *(added `blood_sugar`)* | Team file unverified / placeholder; `blood_sugar` absent | `VERIFIED_AGAINST_PUBLISHED_STANDARD`: **6** · `ADJUSTED_TO_PUBLISHED_STANDARD`: **3** · `TERRESTRIAL_REFERENCE`: **2** · `PLACEHOLDER_SCALE`: **7** · `UNVERIFIED`: **0** |
| **Schema Thresholds** (`07_health_indicators_schema.json`) | **27** *(23 old + 4 glucose)* | 23 rules labeled `synthetic_from_team_file_unverified` | `VERIFIED_AGAINST_PUBLISHED_STANDARD`: **1** · `ADJUSTED_TO_PUBLISHED_STANDARD`: **3** · `TERRESTRIAL_REFERENCE`: **21** · `PLACEHOLDER_SCALE`: **2** · `UNVERIFIED`: **0** |
| **Runtime Indicators** (`resource_facts.INDICATORS`) | **21** *(added `blood_glucose_mg_dl`)* | Mix of `team file, unverified` and `placeholder` | `VERIFIED_AGAINST_PUBLISHED_STANDARD`: **10** · `ADJUSTED_TO_PUBLISHED_STANDARD`: **2** · `TERRESTRIAL_REFERENCE`: **2** · `PLACEHOLDER_SCALE`: **7** · `UNVERIFIED`: **0** |
| **Runtime Fixed Limits** (`resource_facts.FIXED_LIMITS`) | **27** | 23 rules labeled `synthetic_from_team_file_unverified` | `VERIFIED_AGAINST_PUBLISHED_STANDARD`: **1** · `ADJUSTED_TO_PUBLISHED_STANDARD`: **3** · `TERRESTRIAL_REFERENCE`: **21** · `PLACEHOLDER_SCALE`: **2** · `UNVERIFIED`: **0** |
| **Summaries 02–04 Numerical Claims** | **9** | Rewritten summaries (`synthetic_from_team_file_unverified`), unchecked | `VERIFIED_AGAINST_PUBLISHED_STANDARD`: **9** · (`0` unverified) |
| **Countermeasures** (`resource_facts.COUNTERMEASURES`) | **15** | `verified_by` blank on every row; missing `Immune` zone & `Medical_Danger_Alert` guidance | `VERIFIED_AGAINST_PUBLISHED_STANDARD`: **15** (includes `Immune` & `[V1 4040]` emergency escalation; `reviewer_status` empty pending real clinician review) |

---

## 3. Thresholds & Indicators Adjusted to Published Standards (`ADJUSTED_TO_PUBLISHED_STANDARD`)

Four numerical cut-offs originally present in `07_health_indicators_schema.json` were revised to match published standards (`old_value` preserved in schema and `resource_facts.py`, and data regenerated with seed `42`):

| Item | Old Value (`old_value`) | New Value (`value_used`) | Authoritative Reference & Section |
|---|---|---|---|
| `blood_pressure_systolic.high_warning` *(indicator & threshold)* | `135` mmHg | **`140` mmHg** | AHA/ACC Blood Pressure Guidelines (`terrestrial_clinical_standards.txt`, Table 6 — Stage 2 Hypertension) |
| `blood_sugar.hypoglycemia_warning` *(indicator & threshold)* | `65` mg/dL | **`70` mg/dL** | ADA Standards of Care 2024 (`terrestrial_clinical_standards.txt`, Section 6 Table 6.4 — Level 1 Hypoglycemia) |
| `blood_sugar.hypoglycemia_critical` *(indicator & threshold)* | `55` mg/dL | **`54` mg/dL** | ADA Standards of Care 2024 (`terrestrial_clinical_standards.txt`, Section 6 Table 6.4 — Level 2 Clinically Significant Hypoglycemia) |
| `optic_nerve_sheath_diameter` *(indicator range)* | `elevated_icp_warning = 5.9` mm | **`5.8` mm** | Sirek et al. (2014) (*Aviat Space Environ Med*, `spaceflight_peer_reviewed_papers.txt`, Ocular Ultrasound Measurements 3 mm Posterior to Globe) |

---

## 4. Complete Breakdown of Schema Indicators (18) & Psychometric Placeholder Mappings (B3)

| Indicator | `verification_status` | UI Badge | Validated Scale / Published Standard |
|---|---|---|---|
| `body_temperature` | `VERIFIED_AGAINST_PUBLISHED_STANDARD` | **NASA standard** | Stahn et al. (2017) (`36.7–37.8 °C` resting in-flight; pyrexia warning `38.0 °C`) + NEWS2 extreme cut-offs |
| `sleep_hours` | `VERIFIED_AGAINST_PUBLISHED_STANDARD` | **NASA standard** | NASA-STD-3001 `[V1 4014]` (`8.5 h` planned / `7–8 h` sleep) & Barger et al. (2014) (`6.09 h` ISS observed mean) |
| `oxygen_saturation_spo2` | `VERIFIED_AGAINST_PUBLISHED_STANDARD` | **NASA standard** | NASA-STD-3001 `[V2 6003]` normoxic range (`95–99%`) + RCP NEWS2 hypoxia limits (`93%`, `89%`) |
| `radiation_daily_dose` | `VERIFIED_AGAINST_PUBLISHED_STANDARD` | **NASA standard** | Cucinotta et al. (2008) (`0.3–0.8 mSv/day` ISS), CSA CANS (`~30%` neutron), `[V1 4007]` (`600 mSv` career PEL) |
| `bone_health` | `VERIFIED_AGAINST_PUBLISHED_STANDARD` | **NASA standard** | R5 / OCHMO-TB-030 (`1.0–1.5%/month` loss) & `[V1 4027]` (`>=95%` hip/spine, `>=90%` femoral neck) |
| `exercise_and_exertion` | `VERIFIED_AGAINST_PUBLISHED_STANDARD` | **NASA standard** | OCHMO-TB-031 (`2.0–2.5 h/day` ARED/T2/CEVIS) + Borg RPE (`6–20` / CR10 `0–10`) |
| `blood_pressure_systolic` | `ADJUSTED_TO_PUBLISHED_STANDARD` | **Reference value** | AHA/ACC Table 6 (`140 mmHg` Stage 2 warning, adjusted from `135`) & hypotension cut-offs |
| `blood_sugar` (`blood_glucose_mg_dl`) | `ADJUSTED_TO_PUBLISHED_STANDARD` | **Reference value** | ADA 2024 fasting `70–99 mg/dL`; Level 1 `<70` (from `65`), Level 2 `<54` (from `55`), hyper `126`/`180 mg/dL` |
| `optic_nerve_sheath_diameter` | `ADJUSTED_TO_PUBLISHED_STANDARD` | **NASA standard** | Sirek et al. (2014) (`4.8–5.8 mm` in-flight; elevated ICP `>=5.8 mm`, adjusted from `5.9 mm`) |
| `heart_rate` | `TERRESTRIAL_REFERENCE` | **Reference value** | RCP NEWS2 Chart 1 (`50/40 bpm` low, `105/130 bpm` high) where no open NASA-STD-3001 cut-off is published |
| `blood_pressure_diastolic` | `TERRESTRIAL_REFERENCE` | **Reference value** | AHA/ACC Table 6 (`90/100 mmHg` high; `55/50 mmHg` hypotension warning/critical) |
| `mood_score` | `PLACEHOLDER_SCALE` | **Placeholder** | Prototype `1–10` VAS mapped to **PHQ-9** (`0–27`, Kroenke et al. 2001) |
| `muscle_health` | `PLACEHOLDER_SCALE` | **Placeholder** | Simulated `0–100` index mapped to **NASA-STD-3001 `[V1 4028]`** (`>=80%` baseline strength retention) |
| `immunity_indicators` | `PLACEHOLDER_SCALE` | **Placeholder** | Simulated `0–100` index mapped to **OCHMO-TB-038** T-cell function & viral reactivation monitoring |
| `hormones` | `PLACEHOLDER_SCALE` | **Placeholder** | Simulated `0–100` index mapped to **NASA HRP** cortisol/catecholamine stress hormone monitoring |
| `relaxation` | `PLACEHOLDER_SCALE` | **Placeholder** | Simulated `0–100` index mapped to inverted **PSS-10** (`0–40`, Cohen et al. 1983) |
| `mental_health_assessment` | `PLACEHOLDER_SCALE` | **Placeholder** | Simulated `0–100` index mapped to inverted **PHQ-9** (`0–27`, Kroenke et al. 2001) |
| `game_test_score` | `PLACEHOLDER_SCALE` | **Placeholder** | Simulated `0–100` score mapped to **PVT** reaction time in ms (Basner & Dinges 2011) |

*(In runtime `resource_facts.INDICATORS`, `21` indicators are tracked because exercise duration/completion flags (`cardio_session_done`, `cardio_session_min`, `resistance_training_done`, `resistance_training_min`, `daily_physical_activity_min`, `daily_training_hours`) are stored as separate columns — all 6 verified `VERIFIED_AGAINST_PUBLISHED_STANDARD` against OCHMO-TB-031, bringing `VERIFIED_AGAINST_PUBLISHED_STANDARD` to `10` in runtime.)*

---

## 5. Summary 02–04 Claims Verified (9/9)

| Claim ID | Verified Numerical Value | Source File & Section |
|---|---|---|
| `SUM02_BONE_LOSS_MONTHLY` | `1% to 1.5%` BMD loss/month | `nasa_ochmo_technical_briefs.txt` (`OCHMO-TB-030`) |
| `SUM02_EXERCISE_ALLOCATION` | `2 to 2.5` h/day ARED, T2, CEVIS | `nasa_ochmo_technical_briefs.txt` (`OCHMO-TB-031`) |
| `SUM02_CEPHALAD_FLUID_SHIFT` | `~2 L` cephalad fluid shift | `nasa_ochmo_technical_briefs.txt` (`OCHMO-TB-033`) |
| `SUM02_SMS_TIME_WINDOW` | `48–72 hours` SMS window | `nasa_ochmo_technical_briefs.txt` (`OCHMO-TB-015`) |
| `SUM02_CABIN_CO2_THRESHOLD` | `>3–5 mmHg` cabin ppCO2 | `nasa_ochmo_technical_briefs.txt` (`OCHMO-TB-004`) |
| `SUM02_SLEEP_DEBT_IN_FLIGHT` | `<6 h/night` debt (ISS `6.09 h` mean) | `spaceflight_peer_reviewed_papers.txt` (`Barger et al. 2014`) |
| `SUM02_MARS_DISTANCE_AND_LATENCY` | Moon `~240k mi`; Mars `~140M mi`, `20–22 min` delay | `nasa_hrp_hazards_and_analogs.txt` (`Distance from Earth`) |
| `SUM04_CIPHER_AND_ANALOGS` | CIPHER `14` studies, HERA `45 d`, CHAPEA `1 yr`, `-6 deg` HDT | `nasa_hrp_hazards_and_analogs.txt` (`Ongoing Research`) |
| `SUM05_CSA_NEUTRON_FRACTION` | `~30%` neutron radiation (`$5.5M` CANS contract) | `allowed_csa_and_spaceapps_verbatim.txt` (`Resource R4`) |

---

## 6. UI Badges & Clinical Human Sign-Off Packet

- **UI Badges** (`resource_facts.compute_ui_badge`):
  - `"Physician-reviewed"` (only when `reviewer_status` is non-empty from an imported human review)
  - `"NASA standard"` (`VERIFIED_AGAINST_PUBLISHED_STANDARD` or spaceflight `ADJUSTED_TO_PUBLISHED_STANDARD`)
  - `"Reference value"` (`TERRESTRIAL_REFERENCE` or terrestrial-reference adjustment such as BP/glucose)
  - `"Placeholder"` (`PLACEHOLDER_SCALE`)
  - `"Unverified"` (`UNVERIFIED`)
- **Human Review Packet**: Generated cleanly by `review/generate_review_packet.py` into:
  - [`review/clinical_review_packet.md`](file:///d:/NASA%202/project/review/clinical_review_packet.md)
  - [`review/clinical_review_packet.pdf`](file:///d:/NASA%202/project/review/clinical_review_packet.pdf)
  - [`review/clinical_review_template.csv`](file:///d:/NASA%202/project/review/clinical_review_template.csv) (**52 rows**: `27` thresholds + `10` indicators + `15` countermeasures)
- **Important Governance Constraint**: `reviewer_role`, `review_date`, `decision`, and `reviewer_status` remain **empty** across the schema and SQLite database until a real clinician imports a signed CSV via `python review/record_review.py <filled.csv>`. Review by a non-flight-surgeon physician is recorded explicitly as `"physician-reviewed"`, **never** `"flight-surgeon-verified"`.
