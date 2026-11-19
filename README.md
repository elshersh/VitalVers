# Vitalverse — AI health monitoring for astronauts

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/elshersh/VitalVers?quickstart=1)

**Run the live site in one click:** press the button above (free with a GitHub account, no credit card).
The website starts by itself and opens in a new tab; see [Live link with GitHub Codespaces](#live-link-with-github-codespaces).

Vitalverse is a personal health co-pilot for astronauts on long missions, built for the
**NASA Space Apps Challenge 2026** challenge *"Create Health Monitoring Software for Astronauts on Space Missions"*.
It gathers daily health indicators, compares every reading with the astronaut's own pre-flight baseline,
explains what changed and what to do next, and escalates to the flight surgeon when it matters.

> Educational prototype built with fictional, simulated data. Not a certified medical device.

## What's inside

| Page | What it does |
|---|---|
| **Home** | Scroll story: the camera zooms from a NASA spacewalk photo into the astronaut, with live holographic vitals, a project overview and a live crew-vitals monitor |
| **Health dashboard** | Every indicator with its personal baseline, 180-day trends, body-zone status and the AI model's daily verdict (astronaut and flight-surgeon views) |
| **AI chatbot** | On-board assistant that works offline, plus an online mode powered by Google Gemini |
| **Mental health** | Daily check-in with calming songs and family photos |
| **Alerts** | Real-time alerts with the reason behind them, acknowledged by crew and flight surgeon |
| **Daily routine** | Cardio, resistance and activity goals that protect bone and muscle |

The whole site shares an animated deep-space sky (Milky Way, nebulae, shooting stars) and smooth
"drift through space" page transitions.

## Try it

Demo accounts (fake, for testing only):

| Role | Vitalverse ID | Password |
|---|---|---|
| Astronaut | `VTA-DEMO01` | `DemoAstro#2026` |
| Flight surgeon (approved) | `VTD-DEMO01` | `DemoDoctor#2026` |
| Flight surgeon (pending approval) | `VTD-DEMO02` | `PendingDoc#2026` |

On the hosted site the data resets whenever the server restarts.

## Run it on your computer

Requires Python 3.12 or newer (developed on 3.14).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m uvicorn app:app --port 8000
```

Then open http://127.0.0.1:8000. On Windows you can also double-click `open_vitalverse.bat`.

To enable the online chatbot, copy `.env.example` to `.env` and set `GEMINI_API_KEY`
(get one free at https://aistudio.google.com). Never commit `.env`.

## Live link with GitHub Codespaces

Free with any GitHub account (no credit card; 60 hours a month on the 2-core machine).

1. Press **Open in GitHub Codespaces** above, or on GitHub: **Code → Codespaces → Create codespace on main**.
2. GitHub may ask for `GEMINI_API_KEY`: paste your Google AI Studio key to enable the online chatbot
   (stored as your private Codespaces secret, never in the repo), or leave it empty.
3. Wait for the first setup (about 3–5 minutes). The website starts by itself and the terminal prints
   `Vitalverse is live: https://<codespace-name>-8000.app.github.dev`. That is the public link to share.
   If it says to change the port: open the **PORTS** tab, right-click port **8000** → **Port Visibility → Public**.
   If nothing is printed, run `bash .devcontainer/start.sh` in the terminal.
4. Visitors first see GitHub's notice *"You are about to access a development port served by someone's
   codespace"*; they click **Continue** once and the site opens.
5. The link works while the codespace is running. It stops after 30 minutes without activity
   (raise this to 4 hours in GitHub **Settings → Codespaces → Default idle timeout**).
   To bring the site back: **Code → Codespaces →** your codespace; the same link works again.

To add or change the Gemini key later: GitHub **Settings → Codespaces → Secrets → New secret**,
name `GEMINI_API_KEY`, repository `elshersh/VitalVers`. Then in the codespace accept *Reload to apply*
and run `pkill -f "uvicorn app:app"; bash .devcontainer/start.sh` in a new terminal.

The repo also contains a `Dockerfile` and `render.yaml`, so it can run on any Docker host
(for example Render or Hugging Face Spaces on a paid plan).

## Project layout

```
app.py                 FastAPI web app (pages + API)
backend/               routers, services, security, online LLM integration
static/                website: HTML, CSS, JS, images
ai_health_model.py     personal-baseline AI health model (scikit-learn)
health_engine.py       analysis functions used by the dashboard and chatbot
offline_ai_chatbot.py  on-board chatbot (no internet needed)
models/                trained model
data/                  SQLite databases with the simulated mission data
generate_data.py       builds the simulated dataset
tests/                 automated tests (pytest)
*.md (root)            project reports: evaluation, limitations, sources, plan
Dockerfile, render.yaml, scripts/render_start.py   hosting
```

## Credits

- Home-page photos: NASA, mission STS-41-B (1984), Bruce McCandless II on the first untethered spacewalk —
  public domain (images S84-27017, S84-27018). Health readings shown on them are simulated, not his.
- Health facts on the home page: NASA Human Research Program hazard pages and the Canadian Space Agency.
- Fonts: Inter and Space Grotesk (SIL Open Font License), served locally.

---

# Full project documentation

# Astronaut Health Monitoring — data, model and offline chatbot

**Prototype for research/education only — not for clinical diagnosis.**  
**Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.**

Backend prototype for the 2026 NASA Space Apps Challenge *"Create Health Monitoring Software for Astronauts on Space Missions"*. It contains the dataset, SQLite database, Excel analysis, ML model, blind test, offline chatbot and a Python interface for the frontend team. There is no frontend code here.

**All telemetry is simulated.** No allowed resource contains real astronaut measurements or outcomes, so every metric below describes how well the model recovers a *simulated* hidden state. It says nothing about real medical performance.

## How to run

Python 3.10+ (tested on 3.14). After the install step everything runs offline.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python generate_data.py               # step 1 -> frozen eval.db + working app.db (seed 42)
python tools/verify_sources.py        # step 2A -> verify all sources & verbatim quotes (>=90% fuzzy match)
python review/generate_review_packet.py # step 2B -> clinical review packet (.md, .pdf, .csv)
python analysis_to_excel.py           # step 2C -> NASA_Astronaut_Health_Analysis.xlsx (sheets 1-3)
python ai_health_model.py             # step 3 -> 5-fold GroupKFold calibrated model + app.db predictions
python blind_test.py                  # step 4 -> blind test + tiered alerts + noise/oversampled stress tests
python tools/build_chatbot_eval_datasets.py # step 5A -> build offline public & paraphrase eval benchmarks
python test_chatbot.py                # step 5B -> 38 core tests + 4 unbiased eval benchmarks (a)-(d)
pytest tests -v                       # step 5C -> end-to-end automated unit & Playwright web test suite
uvicorn app:app --host 127.0.0.1 --port 8000 # launch full Vitalverse web application
python scripts/simulate_feed.py --astronaut-id A001 --days 1 # append simulated DEMO telemetry day & evaluate alerts
python run_all.py                     # clean end-to-end reproduction (runs ML/data pipeline + pytest)
python offline_ai_chatbot.py A007     # interactive authenticated chatbot CLI
```

### Web Application Pages & Live Telemetry Simulation
- **Public Pages:** `index.html`, `about.html`, `login.html`, `signup.html` (multi-step astronaut/doctor registration with onboarding file uploads to `uploads_private/`).
- **Authenticated Pages (session cookie + CSRF protected):**
  - `/health.html` (auto-routes by role to `astronaut-dashboard.html` or `doctor-dashboard.html` with 180-day Chart.js telemetry, replay slider, and model status predictions)
  - `/chatbot.html` (Offline AI Chatbot with urgent flight-surgeon escalation card and out-of-scope gate)
  - `/todo.html` (Daily Countermeasures To-Do list persisted in SQLite `daily_todo` with top-nav circular progress ring)
  - `/mental.html` (Daily Mental Health Check-In persisted in SQLite `mood_checkins`, same-day editable scoring, optional flight-surgeon email/mailto handoff, and automatic `< 2.5` low-mood alert creation)
  - `/alerts.html` (Real-time Alerts Center with role-appropriate cards, filter chips, SSE `/api/alerts/stream`, `"Run AI Check"`, `"Advance Demo Day (DEMO)"`, and Web Push notifications)
  - `/profile.html` (Crew onboarding boarding-pass card, editable Personal/Health/Flight tabs, playlist & family photos manager, doctor access request/approve/revoke workflow, and password change / logout-all-devices security controls)
- **Browser Web Push & Optional SMTP:** Copy [`.env.example`](file:///d:/NASA%202/project/.env.example) if you want custom `SMTP_*` or `VAPID_*` keys. Browser Push requires `localhost` (`127.0.0.1`) or HTTPS; when VAPID env vars are unset in development, keys are auto-generated in gitignored `uploads_private/.vapid_dev.json`. See [`MODEL_REGISTRY.md`](file:///d:/NASA%202/project/MODEL_REGISTRY.md) for ML & Chatbot artifact specifications.

Close the Excel file before running Excel generation steps (Windows locks open workbooks). All dependencies in `requirements.txt` run offline.

Frontend write-backs (`complete_task`, score submissions, profile edits) write exclusively to the working application database (`data/astronaut_health_app.db`), while the frozen evaluation database (`data/astronaut_health_eval.db`) is opened read-only (`?mode=ro`) and checked against its generation-time SHA-256 manifest (`data/astronaut_health_eval.db.sha256`). If the evaluation database is modified, `blind_test.py` and `ai_health_model.py` refuse to run.

## Authentication, Role-Based Access Control (RBAC), and Demo Credentials

Authentication uses **Argon2id** (`argon2-cffi` PHC format) with per-user random salts, session tokens with a 1-hour expiry (`session_ttl_seconds = 3600`), automatic account lockout for 15 minutes (`lockout_duration_seconds = 900`) after **5 failed attempts**, and strict role-based access control:
- **`astronaut` role (`A001`–`A200`)**: Can view and modify **only their own** profile, daily telemetry, countermeasures, and scores (`PermissionError` is raised on cross-astronaut access).
- **`flight_surgeon` role (`FS001`, `FS002`)**: Can view all 200 astronauts' profiles, telemetry, and alerts via `list_all_astronauts(session_token=...)` and `get_astronaut_dashboard(astronaut_id, session_token=...)`.

Demo credentials are seeded at database generation time from `config/demo_credentials.json` (never hardcoded in application logic):
- **Flight Surgeons**:
  - `FS001`: `Surgeon#2026`
  - `FS002`: `MedOps#2026`
- **Astronauts (`A001`–`A200`)**:
  - Default deterministic demo PIN pattern (`config/demo_credentials.json` `astronaut_credential_rule`): `PIN-<ID>` (e.g., `PIN-A002`, `PIN-A042`).
  - Specific overrides configured in `config/demo_credentials.json`: `A001` = `482101`, `A006` = `482106`, `A007` = `482107`, `A014` = `482114`.
  - Pass a `credential` to `health_engine.login(astronaut_id, credential)` to receive a `session_token`.

### Web Application Demo Logins (**DEMO ONLY**)
Run `python scripts/seed_demo.py` to seed these clearly fake **DEMO ONLY** accounts (`config/demo_credentials.json`, `web_demo_accounts`) into `data/astronaut_health_app.db` using official `argon2-cffi`:
- **Astronaut (linked to `A001`, with `comfort` / `happy` / `energy` starter songs & photos)**: `VTA-DEMO01` / `DemoAstro#2026` (**DEMO ONLY**)
- **Doctor (approved for `A001`)**: `VTD-DEMO01` / `DemoDoctor#2026` (**DEMO ONLY**)
- **Doctor (pending access — blocked `403` until approved)**: `VTD-DEMO02` / `PendingDoc#2026` (**DEMO ONLY**)

## Results of the last clean run (Version 4, Phase 1–5 Overhaul)

Dataset: **200 fictional astronauts × 180 days = 36,000 records** (with deterministic `seed = 42`, plus `30` pre-flight baseline days each and ADA 2024 `blood_glucose_mg_dl`).
Blind test: `GroupShuffleSplit(test_size=0.2, groups=astronaut_id, random_state=42)` — 160 train astronauts (28,800 records), **40 blind astronauts (7,200 records)**, zero cohort overlap (verified against frozen `data/astronaut_health_eval.db` SHA-256).

| Metric (Smart Personalized AI, Blind Test) | Version 3 (132 features) | Version 4 (331 causal features, Calibrated + Cost Matrix) |
|---|---:|---:|
| Overall accuracy | `91.53%` | **`92.42%`** `(95% CI [91.28, 93.40])` |
| Macro sensitivity (recall) | `85.49%` | **`87.56%`** |
| Macro specificity | `94.26%` | **`94.82%`** |
| Macro precision | `81.21%` | **`89.95%`** |
| Macro F1 | `82.94%` | **`88.70%`** `(95% CI [86.56, 90.40])` |
| **`Health_Warning` sensitivity (A1)** | `71.59%` (`235` called Normal) | **`78.56%`** `[75.86, 81.02]` (`207` called Normal) |
| **`Medical_Danger_Alert` sensitivity (A3)** | `88.46%` (`13` called Stress) | **`91.23%`** `[86.03, 94.61]` (`3` called Stress) |
| **`Medical_Danger_Alert` precision & FA/1000d (A2)** | `69.70%` (`60` false alerts) | **`96.30%`** `[92.16, 98.29]` (**`6` false alerts; `0.83` / 1,000 days**) |
| `Normal` specificity (A4) | `82.02%` (`283` abnormal called Normal) | **`83.70%`** `[81.83, 85.41]` (`267` abnormal called Normal) |
| 5-fold `GroupKFold` CV (training cohort) | `90.53% +/- 1.33%` | **`92.53% +/- 0.47%`** |

Additional stress & clinical metrics (full breakdowns in `EVALUATION_REPORT.md`):
- **Tiered Danger Alerting**: `Danger` (high `>=0.45` or persistent `>=0.22` for `>=2` days) achieves **`95.21%` precision / `92.98%` recall** (`1.11` FA/1,000d); inclusive `Danger – confirm` screening reaches **`93.02%` precision / `93.57%` recall** (`1.67` FA/1,000d).
- **Robustness (`1.5x` / `2.0x` Noise + `5%` Missing)**: Accuracy drops `-4.04` pts (`88.38%`) at `1.5x` and `-11.91` pts (`80.51%`) at `2.0x`, while Danger recall remains `92.40%` / `91.81%`.
- **Oversampled-Danger Stress Test** (`7,200` rows, `928` Danger): **`93.75%`** recall, **`98.08%`** precision (`2.36` FA/1,000d).
- **Mood–Training Correlation (B5)**: Within-astronaut `rm_corr = 0.0152` `[0.0045, 0.0258]` and mixed-effects `slope = 0.0264` `[0.0076, 0.0452]` (replaces deprecated pooled Pearson `r = 0.0007, p = 0.896`).

### Offline Chatbot (4-Source Unbiased Evaluation & Anti-Leakage Gate)

| Evaluation Set | Sensitivity | Specificity | Accuracy | Anti-Leakage (`CosSim > 0.60`) |
|---|---:|---:|---:|---:|
| Core verification tests (`test_chatbot.py`) | `23/23` (`100.0%`) | `15/15` (`100.0%`) | `100.0%` | N/A |
| Internal Held-Out Set | `41/42` (`97.62%`) | `30/30` (`100.0%`) | **`98.61%`** | `0` (`max 0.5942`) |
| `(a)` Public OOS (CLINC150, `320` queries) | — | **`100.0%`** (`320/320`) | **`100.0%`** | `0` (`max 0.4753`) |
| `(b)` Public Health QA (MedQuAD, `220` queries) | Scope `95.88%` / Intent `92.94%` | **`100.0%`** (`50/50`) | Strict `94.55%` | `0` (`max 0.5983`) |
| `(c)` Paraphrase Stress Test (`126` queries) | Intent `84.13%` (`-13.49` pt drop; typos `71.43%`) | — | `84.13%` | `0` (`max 0.5964`) |
| `(d)` External CSV (`100` rows / `96` undisputed, AI-authored) | `90.0%` / `91.07%` | **`100.0%`** (`40/40`) | **`94.0%` / `94.79%`** | `0` (`max 0.5847`) |

## Audited Resources & Source Verification (`SOURCES_AUDIT.md`)

Every threshold, indicator range, summary claim (`02–04`), and countermeasure was cross-checked in Phase 2 against published standards saved in `references/`:

| Priority | Source Collection in `references/` | Usage in Prototype |
|---|---|---|
| **(a)** NASA-STD-3001 Vol 1 & Vol 2 | [`references/nasa_std_3001_vol1_vol2.txt`](file:///d:/NASA%202/project/references/nasa_std_3001_vol1_vol2.txt) | Sleep duration `[V1 4014]`, BMD retention `[V1 4027]`, muscle `[V1 4028]`, cardiovascular `[V1 4029]`, career dose `[V1 4007]`, flight-surgeon escalation `[V1 4040]`, SpO2 `[V2 6003]`, circadian lighting `[V2 6050]`. |
| **(b)** NASA OCHMO Technical Briefs | [`references/nasa_ochmo_technical_briefs.txt`](file:///d:/NASA%202/project/references/nasa_ochmo_technical_briefs.txt) | `2.0–2.5 h/day` exercise (`OCHMO-TB-031`), `~2 L` fluid shift (`TB-033`), `48–72 h` SMS window (`TB-015`), immune countermeasures (`TB-038`), sleep/behavioral (`TB-025`). |
| **(c)** NASA HRP Hazards & Analogs | [`references/nasa_hrp_hazards_and_analogs.txt`](file:///d:/NASA%202/project/references/nasa_hrp_hazards_and_analogs.txt) | Verifies `02–04` numbers (`CIPHER` 14 studies, `HERA` 45d, `CHAPEA` 1y, `-6°` HDT, Mars `20–22 min` comm delay). |
| **(d)** Spaceflight Peer-Reviewed Papers | [`references/spaceflight_peer_reviewed_papers.txt`](file:///d:/NASA%202/project/references/spaceflight_peer_reviewed_papers.txt) | Stahn 2017 (`38.0 °C` fever), Barger 2014 (`6.09 h` ISS sleep), Sirek 2014 (`>=5.8 mm` ONSD, adjusted from `5.9`), Cucinotta 2008 (`0.3–0.8 mSv/day`), Basner & Dinges 2011 (PVT), Crucian 2018 (Immune). |
| **(e)** Terrestrial Clinical Standards | [`references/terrestrial_clinical_standards.txt`](file:///d:/NASA%202/project/references/terrestrial_clinical_standards.txt) | AHA/ACC BP (`140 mmHg` Stage 2, adjusted from `135`), ADA 2024 fasting glucose (`70/54` hypoglycemia adjusted from `65/55`, `126/180` hyper), RCP NEWS2 (HR/temp/SpO2), PSS-10, PHQ-9, Borg RPE. |
| **Challenge R0–R5 Verbatim** | [`references/allowed_csa_and_spaceapps_verbatim.txt`](file:///d:/NASA%202/project/references/allowed_csa_and_spaceapps_verbatim.txt) | `1–1.5%/month` bone loss, `180-day` mission, `~30%` neutron radiation (`$5.5M` CANS). |

- `python tools/verify_sources.py` enforces **0** unverified claims (`>=90%` fuzzy match on `<=25`-word verbatim quotes across all `18` schema indicators, `21` runtime indicators, `27` thresholds, `9` summary claims, and `15` countermeasures).
- Every indicator/threshold carries a computed UI badge (`"NASA standard"`, `"Physician-reviewed"`, `"Reference value"`, `"Placeholder"`, or `"Unverified"`).
- External documents beyond initial links `R1–R5` are inventoried in [`references/OUTSIDE_ALLOWED_RESOURCES.md`](file:///d:/NASA%202/project/references/OUTSIDE_ALLOWED_RESOURCES.md).
- Human clinician sign-off uses [`review/clinical_review_packet.pdf`](file:///d:/NASA%202/project/review/clinical_review_packet.pdf) (`52` items) and [`review/record_review.py`](file:///d:/NASA%202/project/review/record_review.py); all clinician fields remain blank until a real physician/flight surgeon imports a signed CSV.

## Known Limitations (`LIMITATIONS.md`)

- **No real astronaut data (CANNOT FIX):** Labels are simulated, so metrics measure simulator-rule fidelity. **Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.**
- **Placeholder scales (MITIGATED):** `muscle_health`, `immunity_indicators`, `hormones`, `relaxation`, `mental_health_assessment`, `game_test_score`, and `mood` use synthetic scales explicitly labeled `PLACEHOLDER_SCALE` (`Placeholder` badge) and mapped to validated clinical/psychometric instruments (PSS-10, PHQ-9, PVT, Borg RPE, `[V1 4028]`, `OCHMO-TB-038`).
- **Pending clinician sign-off (PENDING HUMAN REVIEW):** `reviewer_status` remains empty across schema/database rows until a real physician (`"physician-reviewed"`) or credentialed flight surgeon (`"flight-surgeon-verified"`) signs and imports `review/clinical_review_template.csv`.
- **Offline lexical chatbot boundaries (MITIGATED):** `sentence-transformers` is not installed offline, so TF-IDF + scope-gate classification achieves `100.0%` specificity across all OOS/control sets at the cost of a `-13.49` pt drop (`84.13%`) under heavy paraphrases/unmapped spelling typos (`71.43%`).

## Path to Real Validation

Because no open NASA resource provides per-astronaut daily clinical time series paired with adjudicated medical alert labels, all metrics in this repository measure how well the classifier recovers the simulator's hidden Markov/episode rules. Transitioning this prototype to a clinically validated decision-support system requires:

1. **Required Real Datasets:**
   - **NASA Lifetime Surveillance of Astronaut Health (LSAH)** and **NASA HRP Standard Measures / CIPHER** longitudinal cohorts (pre-flight baseline + daily in-flight wearable telemetry, actigraphy, ARED/T2 exercise logs, point-of-care i-STAT blood chemistry including fasting glucose, and ocular ultrasound ONSD measurements), accessed under NASA Johnson Space Center Institutional Review Board (IRB) approval and privacy-preserving data-use agreements.
   - **Ground-Based Analog Cohorts:** Multi-campaign data from **HERA** (45-day confinement), **CHAPEA** (365-day Mars habitat), and **:envihab** (`-6°` head-down tilt bed rest) to validate sub-acute deconditioning, sleep debt, and behavioral trends prior to flight deployment.
2. **Clinical Adjudication & Ground-Truth Labeling Protocol:**
   - Independent **blinded adjudication** by a panel of at least **two board-certified NASA Flight Surgeons** (with a third senior Flight Surgeon resolving discordant cases), reviewing complete medical logs, private medical conferences (PMCs), and post-flight outcomes to assign daily ground-truth severity tiers (`Normal`, `Stress_BP_Spike_No_Medical_Danger`, `Health_Warning`, `Medical_Danger_Alert`).
   - Inter-rater reliability must be quantified using **Cohen's / Fleiss' $\kappa \ge 0.80$** before locking the reference standard.
3. **Prospective Validation Metrics & Safety Gates:**
   - **Strict Leave-Multi-Astronaut-Out / Mission-Level Split:** Evaluate strictly on held-out missions/crews never seen during feature selection, calibration, or cost-matrix tuning.
   - **Primary Safety Metrics:** Sensitivity (recall) and Precision for `Medical_Danger_Alert` and `Health_Warning` with **95% Wilson and astronaut-cluster bootstrap confidence intervals**, Area Under the Precision-Recall Curve (AUPRC), **False Alarms per 1,000 astronaut-days**, **time-to-detection latency**, and **Expected Calibration Error (ECE) / Brier Score**.

## Repository Map & Files

| File / Folder | Purpose |
|---|---|
| `run_all.py`, `run_all.sh` | Clean end-to-end reproduction runner (Steps 1–5 + pytest) |
| `config/project_config.json`, `config/demo_credentials.json` | Fixed simulation seed (`42`), mood coupling flag (`false`), cost matrix, tiered thresholds, demo logins |
| `resource_facts.py`, `tools/verify_sources.py` | Verified single source of truth (`INDICATORS`, `FIXED_LIMITS`, `COUNTERMEASURES`) + automated quote verifier |
| `generate_data.py` | Builds frozen read-only `data/astronaut_health_eval.db` (`+.sha256`) & writable `data/astronaut_health_app.db` |
| `analysis_to_excel.py` | Builds `NASA_Astronaut_Health_Analysis.xlsx` (sheets 1–3) |
| `ai_health_model.py` | Causal temporal features (`331`), 5-fold GroupKFold validation, Platt calibration, cost matrix, saved model |
| `blind_test.py` | Frozen DB SHA-256 verification, blind evaluation, CIs, tiered alerting, noise/stress tests, Excel sheets 4–5 |
| `health_engine.py` | Argon2id auth, RBAC, within-astronaut `rm_corr`/mixed-effects analytics, dashboard/alert APIs |
| `offline_ai_chatbot.py`, `chatbot_eval_sets.py`, `test_chatbot.py` | Offline TF-IDF scope-gated chatbot, urgent escalation, 4-source unbiased benchmark evaluation |
| `tools/build_chatbot_eval_datasets.py`, `eval/` | Builds & stores `(a)` CLINC OOS, `(b)` MedQuAD QA, `(c)` Paraphrase stress test, `(d)` `external_questions.csv`, `topic_map.json`, `label_disputes.md` |
| `review/` | `generate_review_packet.py`, `record_review.py`, `clinical_review_packet.{md,pdf}`, `clinical_review_template.csv` |
| `references/` | Saved NASA/OCHMO/HRP/paper/clinical texts + `OUTSIDE_ALLOWED_RESOURCES.md` |
| `SOURCES_AUDIT.md`, `LIMITATIONS.md`, `EVALUATION_REPORT.md` | Comprehensive audit, remediation matrix, and honest experimental evaluation reports |
| `tests/` | Automated pytest suite covering Phases 1–5 (`test_phase1_auth_and_repro.py` … `test_phase5_deliverables.py`) |
