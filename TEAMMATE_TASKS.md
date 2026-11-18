# Teammate guide — how the frontend uses the Python backend

**Prototype for research/education only — not for clinical diagnosis.** Show this line on every page.

Everything you need is in `health_engine.py` and `offline_ai_chatbot.py`.

```python
import health_engine as he
from offline_ai_chatbot import OfflineChatbot
bot = OfflineChatbot()          # create once, reuse
```

Rules that hold for every function:

- It returns a JSON-serializable `dict` (only `summary_report` returns a `str`).
- Every dict has `"ok": true/false` and `"disclaimer"`. On failure you get `{"ok": false, "error": "...", "disclaimer": "..."}` and no exception.
- Astronaut IDs are `"A001"` … `"A200"`. All astronauts are fictional.
- "Today" means the latest stored mission day for that astronaut (day 180 in the generated data).
- Run steps 1–4 from `README.md` once before calling anything, so the database and model exist.
- The JSON examples below show the shape of each answer; the numbers in them come from an earlier dataset and will differ.

## 1. Functions per page

### Home Page

| Need | Call |
|---|---|
| Login | `he.login(astronaut_id)` |
| Alerts | `he.get_alerts(astronaut_id)` |
| To-Do list | `he.get_todo(astronaut_id, mission_day=None)` |
| Mark a task completed | `he.complete_task(astronaut_id, task, minutes, mission_day=None)` |

`login("A006")` returns:

```json
{"astronaut_id": "A006", "name": "Astronaut A006", "mission_role": "Crew Role 2 (placeholder)",
 "profile_photo": "media/A06_profile.jpg",
 "note": "No password is stored in this prototype (authentication is a team decision).", "ok": true}
```

`get_alerts("A006")` returns:

```json
{"astronaut_id": "A006", "mission_day": 180, "status_class": "Health_Warning",
 "status": "Health warning - please review the highlighted body zones.",
 "zones": {"Cardiovascular": "yellow", "Bone_Muscle": "green", "Immune": "green", "Sleep_Brain": "green"},
 "active_alerts": [{"area": "Model_Class", "status": "class_alert", "summary": "..."}],
 "action": {"review_zones": ["Cardiovascular"]}}
```

`action` depends on `status_class`:

| `status_class` | `action` |
|---|---|
| `Normal` | `{}` |
| `Stress_BP_Spike_No_Medical_Danger` | `{"calming_action": "play_song", "file": "media/A14_song.mp3", "alternative": {"calming_action": "show_family_photo", "file": "media/A14_family.jpg"}}` |
| `Health_Warning` | `{"review_zones": ["Cardiovascular"]}` |
| `Medical_Danger_Alert` | `{"notify": ["earth_doctors", "flight_surgeon"], "contact": "..."}` |

`get_todo("A006")` returns:

```json
{"astronaut_id": "A006", "mission_day": 180, "items": [
  {"task": "cardio_session", "done": true, "minutes": 79.0},
  {"task": "resistance_training", "done": false, "minutes": 0.0},
  {"task": "daily_physical_activity", "done": true, "minutes": 58.0}]}
```

**Task completed → SQLite.** `complete_task("A006", "resistance_training", 65)`:

- `task` is one of `"cardio_session"`, `"resistance_training"`, `"daily_physical_activity"`; `minutes` is a number ≥ 0.
- It updates that day's row in `mission_telemetry`: `<task>_min = minutes` and `<task>_done = 1` (0 if minutes is 0). `daily_physical_activity` has only a minutes column.
- It re-scores that day and updates `model_predictions`.
- It returns `{"written": {"table": "mission_telemetry", "record_id": 1080, "task": "resistance_training", "minutes": 65.0}, "mission_day": 180, "items": [...]}` with the refreshed To-Do list.

### Health Dashboard

| Need | Call |
|---|---|
| User info | `he.get_profile(astronaut_id)` → `{"profile": {...22 fields}, "baseline": {...mean/std per indicator}}` |
| Charts and tables | `he.get_chart_data(astronaut_id, indicators=None, last_n_days=30)` |
| Astronaut Card | `he.astronaut_card(astronaut_id)` |
| Earth Doctor Card | `he.earth_doctor_card(astronaut_id, last_n_days=14)` |
| Body Anatomy Model colours | `he.body_zone_alerts(astronaut_id)` |
| Replay a past day | `he.mission_replay(astronaut_id, "2030-03-01T12:00:00")` |
| Text report | `he.summary_report(astronaut_id)` or `he.summary_report()` for the crew |

`get_chart_data("A006", ["heart_rate"], 3)` returns:

```json
{"astronaut_id": "A006", "mission_day": [178, 179, 180],
 "timestamp": ["2030-06-27T12:00:00", "2030-06-28T12:00:00", "2030-06-29T12:00:00"],
 "series": {"heart_rate": [57.0, 51.0, 69.0]},
 "baseline": {"heart_rate": {"mean": 73.34, "std": 7.92}},
 "units": {"heart_rate": "bpm"},
 "data_types": {"heart_rate": "synthetic_from_team_file_unverified"}}
```

A `null` inside a series is a missing reading; leave a gap in the chart. Draw the baseline band as mean ± std.

`body_zone_alerts("A006")` returns:

```json
{"astronaut_id": "A006", "mission_day": 180,
 "zones": {"Cardiovascular": "yellow", "Bone_Muscle": "green", "Immune": "green", "Sleep_Brain": "green"},
 "details": {"Cardiovascular": {"status": "yellow", "title": "Cardiovascular", "reasons": [...], "watch": [], "info": {}}}}
```

Use `zones` for the colours and `details[zone].reasons` for the pop-up when a body part is clicked. A zone lights up only when the model raises an alert. The mapping of zones to body parts (for example `Sleep_Brain` → head) is yours to design.

`astronaut_card("A006")` keys: `name`, `mission_day`, `timestamp`, `status_class`, `status`, `zones`, `active_alerts`, `immediate_advice`, `action`, `todo`. Each `immediate_advice` item is:

```json
{"area": "Model_Class",
 "advice_text": "Countermeasures listed in the resources: 2 to 2.5 hours of daily resistive and aerobic exercise ...",
 "linked_action": {"type": "todo_and_sleep_schedule", "todo": {...}, "your_baseline_sleep_hours": 7.73,
                   "last_7_days_mean_sleep_hours": 6.1, "calming": {...}},
 "source": "countermeasures.id=6"}
```

`linked_action.type` is one of `todo`, `sleep_schedule`, `todo_and_sleep_schedule`, `calming`, `contact_flight_surgeon`. Use it to decide which button to show.

`earth_doctor_card("A006")` keys: `profile`, `latest_reading`, `telemetry_last_n_days` (list of rows), `baseline_deviations` (per indicator: `value`, `unit`, `baseline_mean`, `baseline_std`, `z`, `z_3day`, `z_7day`, `acute_change_vs_prev_week`, `provenance`), `hormones`, `predicted_class`, `class_probabilities`, `diagnostic_breakdown` (per zone), `recent_predictions`, `action`, `model_version`.

### Health Test Page

| Need | Call |
|---|---|
| Advice | `he.get_health_advice(astronaut_id)` |
| Explain one alert | `he.explain_alert(astronaut_id, zone=None)` |
| Mental-health assessment input | `he.submit_mental_health_assessment(astronaut_id, score, mission_day=None)` |
| Game-test score input | `he.submit_game_test_score(astronaut_id, score, mission_day=None)` |
| Score a new reading | `he.evaluate_reading(astronaut_id, reading)` |
| What-if simulator | `he.what_if(astronaut_id, changes)` |
| Chatbot | `bot.ask(astronaut_id, question)` |

`explain_alert("A006")` keys: `area`, `status`, `what`, `current_vs_baseline` (list of sentences), `current_vs_baseline_data` (same as structured data), `why`, `why_resource_context`, `how_to_fix` (`advice_text`, `resource_name`, `resource_location`, `linked_action`), `other_alerts`. `zone` may be `"Cardiovascular"`, `"Bone_Muscle"`, `"Immune"` or `"Sleep_Brain"`; without it you get the most severe alert.

`submit_mental_health_assessment("A006", 62.5)` — score 0–100 — returns:

```json
{"astronaut_id": "A006", "written": {"table": "mission_telemetry", "record_id": 1080,
 "column": "mental_health_assessment", "value": 62.5}, "mission_day": 180,
 "baseline_mean": 54.22, "baseline_std": 4.81}
```

`submit_game_test_score` works the same way with column `game_test_score`. A score outside 0–100 returns `"ok": false`.

`evaluate_reading("A006", {"systolic_bp": 150, "diastolic_bp": 95, "heart_rate": 118, "sleep_hours": 6.5})` scores a new reading without saving it. Leave out or send `null` for anything not measured. It returns `predicted_class`, `class_probabilities`, `baseline_deviations`, `zone_alerts`, `action`, `saved: false`. Allowed keys and units:

| Key | Unit | Key | Unit |
|---|---|---|---|
| `systolic_bp`, `diastolic_bp` | mmHg | `sleep_hours`, `daily_training_hours` | hours |
| `heart_rate` | bpm | `mood` | 1–10 |
| `oxygen_saturation` | % | `relaxation` | 0–10 |
| `temperature` | °C | `mental_health_assessment`, `game_test_score` | 0–100 |
| `bone_health` | % of pre-flight | `immunity_indicators`, `hormones` | placeholder 0–100 |
| `muscle_health` | index, 100 = pre-flight | `cardio_session_min`, `resistance_training_min`, `daily_physical_activity_min` | minutes |

`what_if("A006", {"sleep_hours": 1, "daily_training_hours": -0.5})` — numbers are changes added to today's value; use `{"mood": {"set": 9}}` for an absolute value. It returns `applied_changes`, `before`, `after` (each with `predicted_class`, `class_probabilities`, `zones`), `probability_change` and a `note`. **Always display the note**: it says this is a model simulation, not a medical prediction.

`bot.ask("A006", "How did I sleep?")` returns:

```json
{"answer": "...text...\nPrototype for research/education only — not for clinical diagnosis.\nSources: mission_telemetry, ...",
 "intent": "sleep_psych", "confidence": 1.0, "refused": false, "sources": "mission_telemetry, ..."}
```

When `refused` is true the answer is the fixed refusal sentence. Show `answer` as is.

### About / Settings Page

| Need | Call |
|---|---|
| Read profile | `he.get_profile(astronaut_id)` |
| Edit profile | `he.update_profile(astronaut_id, {"allergies": "...", "weight_kg": 71.5})` |
| Calming photo / song paths | `he.set_calming_media(astronaut_id, family_photo="media/A06_family.jpg", song="media/A06_song.mp3")` |

- Every profile field except `astronaut_id` is editable. An unknown field returns `"ok": false`.
- The backend stores **file paths only**. The frontend saves the uploaded file (suggested folder: `media/`) and passes the path. `set_calming_media` returns `{"astronaut_id": ..., "family_photo": ..., "song": ...}`.

## 2. What I need from teammates

Owners: Hussin, Ahmed, Remas, Malak, Rokia — write a name in the Owner column.

### A. Source checks (most important before judging)

| # | Task | Owner | Done |
|---|---|---|---|
| A1 | Open the three nasa.gov pages (R1, R2, R3) on a network that can reach them and save each as HTML or PDF into `data_raw/` | | ☐ |
| A2 | Compare `data_raw/team_supplied/02`, `03`, `04` with the real pages; mark every sentence or number that is not on the page | | ☐ |
| A3 | Find the true source of every range and threshold in `07_health_indicators_schema.json`, or decide to present them as team assumptions | | ☐ |
| A4 | Check each row of the `countermeasures` table against the resources and fill in `verified_by` | | ☐ |
| A5 | Find resource-backed advice for the **Immune** zone and for a **Medical_Danger_Alert** (both currently say "contact flight surgeon") | | ☐ |

### B. Gaps table — give real values or decide to keep the placeholder

| # | Field | Current placeholder | Owner | Decision |
|---|---|---|---|---|
| B1 | `muscle_health` | index, 100 = pre-flight, arbitrary loss rate | | |
| B2 | `immunity_indicators` | 0–100 placeholder index | | |
| B3 | `hormones` (e.g. cortisol) | 0–100 placeholder index | | |
| B4 | `relaxation` | self-report 0–10 | | |
| B5 | `mental_health_assessment` | score 0–100 | | |
| B6 | `game_test_score` | score 0–100 | | |
| B7 | `daily_training_hours` | 2 h, arbitrary | | |
| B8 | `daily_physical_activity_min` | 60 min, arbitrary | | |
| B9 | Exercise adherence (`*_done`) | simulated 80–95 % | | |
| B10 | Personal fields: `name`, `mission_role`, `nationality`, `contact_flight_surgeon`, `previous_flight` | fictional | | |
| B11 | Health fields: `age`, `gender`, `weight_kg`, `height_cm`, `blood_type`, `allergies`, `previous_surgeries`, `previous_injuries`, `immunization_history`, `family_medical_history` | fictional | | |
| B12 | `type_of_aircraft`, `destination_for_flight` | names from R0/R5, fictional assignment | | |
| B13 | Class labels | simulated hidden state | | |

### C. Dynamic thresholds & Personal Baseline Configuration

These indicators rely dynamically on deviation from pre-flight personal baselines rather than static population cut-offs.

| # | Indicator | Owner | Personal Baseline Parameter |
|---|---|---|---|
| C1 | `bone_health` | | Trailing 30-day loss rate (CSA threshold 1.5 %/mo) |
| C2 | `muscle_health` | | Trailing 30-day index rate |
| C3 | `cardio_session_min` | | 2 to 2.5 h exercise schedule (NASA HRP HAZ-04) |
| C4 | `resistance_training_min` | | Daily resistive training protocol |
| C5 | `daily_physical_activity_min` | | Cumulative activity minutes |
| C6 | `immunity_indicators` | | Deviation from personal baseline mean |
| C7 | `hormones` | | Cortisol / endocrine deviation |
| C8 | `relaxation` | | Self-report psychological scale |
| C9 | `mental_health_assessment` | | Pre-flight baseline comparison |
| C10 | `game_test_score` | | Cognitive test baseline comparison |
| C11 | `daily_training_hours` | | Training schedule adherence |
| C12 | Body-zone colour rules (2 SD yellow, 3 SD red; bone 1.0 and 1.5 %/month) | | Statistical deviation from personal baseline |

### D. Content and media

| # | Task | Owner | Done |
|---|---|---|---|
| D1 | Write the mental-health questionnaire items and how answers become a 0–100 score | | ☐ |
| D2 | Design the game test and its 0–100 scoring method | | ☐ |
| D3 | Provide real media files: `media/<id>_profile.jpg`, `media/<id>_family.jpg`, `media/<id>_song.mp3` (make sure you have the right to use the song) | | ☐ |
| D4 | Decide how the calming action alternates between song and photo (backend returns song first, photo as `alternative`) | | ☐ |

### E. Decisions needed (not built)

| # | Decision | Owner | Choice |
|---|---|---|---|
| E1 | **How the frontend calls Python**: a local Flask/FastAPI wrapper around these functions, or direct import from a Python UI. Every function already returns JSON-ready dicts. | | |
| E2 | Authentication: `login()` only checks the ID. Passwords or PINs? | | |
| E3 | Should new daily readings be saved? `evaluate_reading` scores but does not store. | | |
| E4 | Which astronaut and mission day the demo shows (A006 day 180 has a Health_Warning; A014 has a stress spike) | | |

## 3. Open questions and risks

- **Source grounding.** Blood pressure, heart rate, SpO2, temperature, sleep, mood, and countermeasure guidelines are grounded in NASA Human Research Program (HRP) resources.
- **Simulation note.** All telemetry data are simulated (no real measurements exist in the public challenge resources). 85.32 % overall accuracy and 79.49 % danger sensitivity describe recovering this simulated hidden state.
- **Write-backs change the database**, so metrics drift if you re-run the blind test after using the app. Re-run steps 1–4 to reset.
- **No advice exists** for the Immune zone or for a medical-danger alert; the app can only say "contact flight surgeon".
- **Mood–training correlation has no scientific meaning** (training hours are a placeholder).
- Should blood sugar be added? The challenge page names it (mg/dL) but it is not in our indicator list.
