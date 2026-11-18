# Astronaut Health Monitoring — Comprehensive Evaluation Report (Version 4)

**Prototype for research/education only — not for clinical diagnosis.**  
**Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.**

---

## 1. Executive Summary & Experimental Integrity

This report summarizes the end-to-end validation, blind test results, robustness stress tests, within-astronaut statistical analysis, and four-source unbiased chatbot evaluation for the **NASA Space Apps 2026 Astronaut Health Monitoring** backend (`MODEL_VERSION = "personal_baseline_v4"`).

All experimental **Ground Rules** were strictly enforced:
- **Frozen Evaluation Integrity (D3):** `generate_data.py` runs deterministically with `seed = 42` (`config/project_config.json`) to produce the frozen evaluation database [`data/astronaut_health_eval.db`](file:///d:/NASA%202/project/data/astronaut_health_eval.db) (opened `?mode=ro` and verified against SHA-256 `b9a5bc4536256a441d638441c2980badb13122b6b8474acf4ebad5b4c0fdc8c5`) and the separate working database `data/astronaut_health_app.db`.
- **Zero Cohort Leakage:** The 200 synthetic astronauts (`A001–A200`, `180` mission days each = `36,000` rows) are split strictly by astronaut ID via `GroupShuffleSplit(test_size=0.2, random_state=42)`: **160 training astronauts (28,800 rows)** and **40 blind test astronauts (7,200 rows: `Normal=5562`, `Stress=497`, `Warning=970`, `Danger=171`)**, with **0 overlapping astronauts**.
- **No Test-Set Tuning:** All architecture selection, Platt probability calibration (`CalibratedClassifierCV`, `method="sigmoid"`), and cost-matrix threshold searches were performed exclusively using 5-fold `GroupKFold` cross-validation on the 160 training astronauts.
- **No Chatbot Test Contamination:** All chatbot training exemplars were audited via TF-IDF cosine similarity (`max <= 0.5983 < 0.60`, `0` violations across all datasets). [`eval/external_questions.csv`](file:///d:/NASA%202/project/eval/external_questions.csv) was never edited (`expected_behavior` preserved verbatim), with 4 disputes documented in [`eval/label_disputes.md`](file:///d:/NASA%202/project/eval/label_disputes.md).

---

## 2. ML Validation Comparison (Training Cohort Only — 5-Fold `GroupKFold`)

Every candidate model used **331 causal per-astronaut features** (past-only 3-, 7-, and 14-day rolling means/SDs, 7- and 14-day linear slopes, personal baseline z-scores, cumulative bone/muscle change, SpO2, systolic/diastolic BP, blood glucose `blood_glucose_mg_dl`, spike duration streaks, recovery rates, multi-system abnormal count, and stress-vs-danger discriminant terms), evaluated under an explicit cost matrix in `config/project_config.json` where a missed `Medical_Danger_Alert` costs **20x–40x** a false alert (`[40.0, 25.0, 20.0, 0.0]`).

| Candidate Architecture (5-Fold GroupKFold OOF) | Val Accuracy | Macro F1 | `Health_Warning` Recall | `Danger` Recall | `Danger` Precision | Expected Cost | Tuned Weights `[N, S, W, D]` | Selection Outcome |
|---|---:|---:|---:|---:|---:|---:|---|---|
| **`single_rf`** *(Calibrated RF, 10-leaf)* | `92.53% +/- 0.47%` | `88.74%` | **`81.58%`** | `93.08%` | `93.22%` | `0.2163` | `[1.0, 0.55, 3.0, 1.75]` | **SELECTED** |
| **`two_stage_rf`** *(Acute vs Not -> Stress vs Danger)* | `92.58%` | `88.64%` | `81.78%` | `91.38%` | `93.84%` | `0.2257` | `[1.0, 0.55, 3.0, 1.0]` | Rejected *(higher cost, lower Danger recall)* |
| **`hist_gbm`** *(Calibrated HistGradientBoosting)* | `93.52%` | `90.18%` | `80.31%` | `93.54%` | `96.66%` | `0.2127` | `[1.0, 0.4, 2.4, 1.15]` | Not adopted *(did not beat `single_rf` by `>0.03` objective AND `Warn Sens 80.31% < 81.58%`)* |

Fold accuracies for the selected `single_rf` model across the 5 astronaut folds: `91.68%`, `93.09%`, `92.53%`, `92.55%`, `92.78%` (`92.53% +/- 0.47%`).

---

## 3. ML Blind Test Results (`n = 7,200` Rows, 40 Unseen Astronauts)

### 3.1 Before (Version 3) vs. After (Version 4) Headline Comparison

| Metric | Version 3 Baseline | Version 4 (Final) | Change / Honest Assessment |
|---|---:|---:|---|
| **Overall Accuracy** | `91.53%` | **`92.42%`** `(95% CI [91.28, 93.40])` | **`+0.89` pts** |
| **Macro Sensitivity (Recall)** | `85.49%` | **`87.56%`** | **`+2.07` pts** |
| **Macro Specificity** | `94.26%` | **`94.82%`** | **`+0.56` pts** |
| **Macro Precision** | `81.21%` | **`89.95%`** | **`+8.74` pts** |
| **Macro F1** | `82.94%` | **`88.70%`** `(95% CI [86.56, 90.40])` | **`+5.76` pts** |
| **`Health_Warning` Recall (A1)** | `71.59%` (`235/256` called Normal) | **`78.56%`** (`207/208` called Normal) | **`+6.97` pts** *(precision traded `81.85% -> 76.35%`)* |
| **`Danger` Recall (A3)** | `88.46%` (`13/18` called Stress) | **`91.23%`** (`3/15` called Stress) | **`+2.77` pts** |
| **`Danger` Precision & False Alarms (A2)** | `69.70%` (`60` false alerts) | **`96.30%`** (`6` false alerts; **`0.83` FA / 1,000 days**) | **`+26.60` pts precision; `-90%` false alarms** |
| **`Normal` Specificity (A4)** | `82.02%` (`283` abnormal called Normal) | **`83.70%`** (`267` abnormal called Normal) | **`+1.68` pts** |

### 3.2 Per-Class Blind Test Metrics with 95% Confidence Intervals

*95% Wilson score intervals reported for sensitivity, precision, and specificity; 95% astronaut-cluster bootstrap intervals (resampling by astronaut ID) reported for F1.*

| Class | Support | Sensitivity (`95% Wilson CI`) | Precision (`95% Wilson CI`) | Specificity (`95% Wilson CI`) | F1 Score (`95% Bootstrap CI`) |
|---|---:|---|---|---|---|
| `Normal` | `5,562` | `95.54% [94.97, 96.05]` | `95.22% [94.62, 95.75]` | `83.70% [81.83, 85.41]` | `95.38% [94.66, 96.08]` |
| `Stress_BP_Spike_No_Medical_Danger` | `497` | `84.91% [81.50, 87.79]` | `91.94% [89.09, 94.10]` | `99.45% [99.24, 99.60]` | `88.28% [86.04, 90.59]` |
| `Health_Warning` | `970` | `78.56% [75.86, 81.02]` | `76.35% [73.62, 78.88]` | `96.21% [95.71, 96.66]` | `77.44% [71.48, 81.67]` |
| `Medical_Danger_Alert` | `171` | `91.23% [86.03, 94.61]` | `96.30% [92.16, 98.29]` | `99.91% [99.81, 99.96]` | `93.69% [89.27, 97.24]` |

*Note on trade-off:* `Stress_BP_Spike_No_Medical_Danger` sensitivity decreased slightly (`86.65% -> 84.91%`, `-1.74` pts) while its precision rose `+13.62` pts (`78.32% -> 91.94%`) and `Medical_Danger_Alert` misses as Stress dropped from `13` to `3`. Similarly, `Health_Warning` precision dropped (`81.85% -> 76.35%`, `-5.50` pts) in exchange for lifting `Health_Warning` sensitivity by `+6.97` pts (`71.59% -> 78.56%`).

### 3.3 Blind Test Confusion Matrices (Counts & Row-Normalized Percentages)

**Raw Counts (`Rows = True`, `Cols = Predicted`):**

| True \ Predicted | `Normal` | `Stress_BP_Spike` | `Health_Warning` | `Medical_Danger_Alert` | Row Total |
|---|---:|---:|---:|---:|---:|
| **`Normal`** | `5,314` | `33` | `213` | `2` | `5,562` |
| **`Stress_BP_Spike`** | `58` | `422` | `13` | `4` | `497` |
| **`Health_Warning`** | `207` | `1` | `762` | `0` | `970` |
| **`Medical_Danger_Alert`** | `2` | `3` | `10` | `156` | `171` |

**Row-Normalized (%):**

| True \ Predicted | `Normal` | `Stress_BP_Spike` | `Health_Warning` | `Medical_Danger_Alert` |
|---|---:|---:|---:|---:|
| **`Normal`** | **`95.54%`** | `0.59%` | `3.83%` | `0.04%` |
| **`Stress_BP_Spike`** | `11.67%` | **`84.91%`** | `2.62%` | `0.80%` |
| **`Health_Warning`** | `21.34%` | `0.10%` | **`78.56%`** | `0.00%` |
| **`Medical_Danger_Alert`** | `1.17%` | `1.75%` | `5.85%` | **`91.23%`** |

### 3.4 Tiered Danger Alerting (A2)

Configured in `config/project_config.json` (`danger_confirm_prob_threshold = 0.22`, `danger_high_prob_threshold = 0.45`, `danger_confirm_persistence_days = 2`):

| Alert Tier / Definition | Precision | Recall | F1 | False Alarms / 1,000 Astronaut-Days | Counts (`TP / FP / FN`) |
|---|---:|---:|---:|---:|---|
| **`Danger`** *(high prob `>=0.45` OR persistent `>=0.22` across `>=2` consecutive days)* | **`95.21%`** | **`92.98%`** | **`94.08%`** | **`1.11`** | `159 / 8 / 12` |
| **`Danger – confirm`** *(inclusive screening: moderate `>=0.22` + high `Danger`)* | **`93.02%`** | **`93.57%`** | **`93.29%`** | **`1.67`** | `160 / 12 / 11` |
| **`Danger – confirm` only** *(isolated re-measure band, `5` rows)* | `20.00%` | `0.58%` | `1.14%` | `0.56` | `1 / 4 / —` |

### 3.5 Sensor Noise, Missingness Robustness (B1) & Danger-Oversampled Stress Test (A5)

| Stress Condition (`n = 7,200` Blind Test Cohort) | Overall Accuracy | Macro F1 | `Health_Warning` Recall | `Danger` Recall | `Danger` Precision | `Danger` FA / 1,000d |
|---|---:|---:|---:|---:|---:|---:|
| **Baseline Blind Test (`1.0x` noise, `0%` missing)** | `92.42%` | `88.70%` | `78.56%` | `91.23%` | `96.30%` | `0.83` |
| **Robustness: `1.5x` Sensor Noise + `5%` Missing Readings** | `88.38%` (`-4.04`) | `83.94%` (`-4.76`) | `78.25%` (`-0.31`) | `92.40%` (`+1.17`) | `91.86%` (`-4.44`) | — |
| **Robustness: `2.0x` Sensor Noise + `5%` Missing Readings** | `80.51%` (`-11.91`) | `76.11%` (`-12.59`) | `77.11%` (`-1.45`) | `91.81%` (`+0.58`) | `89.20%` (`-7.10`) | — |
| **Oversampled-Danger Stress Test** *(separate set: `928` Danger, `850` Warn, `476` Stress, `4,946` Normal)* | `92.54% [91.04, 93.75]` | `88.43% [86.81, 89.86]` | — | **`93.75% [92.01, 95.13]`** | **`98.08% [96.95, 98.80]`** *(Spec `99.73%`)* | `2.36` |

---

## 4. Within-Astronaut Mood–Training Correlation Analysis (B5)

Implemented in `health_engine.mood_training_correlation()` with `enable_mood_training_coupling: false` (default simulator configuration in `config/project_config.json`):

| Statistical Estimator | Effect Size | 95% Confidence Interval | `p`-Value | Interpretation |
|---|---|---|---|---|
| **Repeated-Measures Correlation (`rm_corr`, Bakdash & Marusich)** | `r = 0.0152` | `[0.0045, 0.0258]` | `0.00536` | Negligible effect (`r^2 ≈ 0.0002`, `df = 33,728`, `n = 33,929`); statistically non-zero only due to huge `df`, practically zero (`< 0.02`). |
| **Linear Mixed-Effects Model (Random Intercepts per Astronaut)** | `slope = 0.0264` | `[0.0076, 0.0452]` | `0.00584` | Negligible within-astronaut slope (`0.026` mood points per training hour). |
| **Per-Astronaut Pearson `r` Summary (`200` crews)** | `mean r = 0.0144` | `[0.0016, 0.0272]` | `22/200` crews `< 0.05` | Only `11%` of crews show nominal `p < 0.05`; confirms independent generation. |
| **Pooled Pearson *(DEPRECATED — Do Not Use)*** | `r = 0.0007` | — | `0.896` | Violates repeated-measures independence (treats `180` days/astronaut as i.i.d.). |

---

## 5. Offline Chatbot Evaluation (Sources `(a)–(d)` & Anti-Leakage Proof)

All chatbot evaluations used **untrained test sets** audited with maximum TF-IDF cosine similarity against training templates (`<= 0.5983 < 0.60`, **`0` leakage violations**).

### 5.1 Four-Source Unbiased Suite + Internal Regression Summary

| Evaluation Dataset | Total Queries | Sensitivity (In-Scope / Routed) | Specificity (Out-of-Scope Refusal) | Overall Accuracy | Keyword Leakage / Violations | Max Train Cosine Sim (`>0.60` count) |
|---|---:|---:|---:|---:|---|---:|
| **Core Regression Suite (`test_chatbot.py`)** | `38` | `23/23` (`100.0%`) | `15/15` (`100.0%`) | `100.0%` | `0` misses | N/A |
| **Internal Development Set** | `40` | `25/25` (`100.0%`) | `15/15` (`100.0%`) | `100.0%` | `0` shared topic-word overlaps | `0.5847` (`0`) |
| **Internal Held-Out Set** *(post-38-leak removal)* | `72` | `41/42` (`97.62%`) *(1 miss: activity min -> `sleep_psych`)* | `30/30` (`100.0%`) | **`98.61%`** | `0` shared topic-word overlaps | `0.5942` (`0`) |
| **`(a)` Public Out-of-Scope (CLINC150 8 domains)** | `320` | — | **`100.0%` (`320/320`)** | `100.0%` | **`0.0%`** across all 8 domains (`40/40` each) | `0.4753` (`0`) |
| **`(b)` Public Health QA (MedQuAD/LiveQA + Guard)** | `220` | Scope `95.88%` (`163/170`) / Intent **`92.94%`** (`158/170`) | **`100.0%` (`50/50`)** | Scope `96.82%` / Strict **`94.55%`** | `0` false accepts | `0.5983` (`0`) |
| **`(c)` Paraphrase Stress Test (`3 x 42` perturbations)** | `126` | Intent **`84.13%`** (`106/126`) *(Answered `110/126`)* | — | **`-13.49` pt drop** vs `97.62%` | `synonym: 90.48%`, `word_order: 90.48%`, `typo_abbrev: 71.43%` | `0.5964` (`0`) |
| **`(d)` External CSV — All `100` Rows** *(AI-authored)* | `100` | Scope **`90.0%`** / Routed **`90.0%`** (`54/60`) | **`100.0%` (`40/40`)** | **`94.0%`** | Urgent escalation: **`4/4` (`100%`)** | `0.5847` (`0`) |
| **`(d)` External CSV — `96` Undisputed Rows** *(excl. `E005, E008, E030, E039`)* | `96` | Scope **`91.07%`** / Routed **`91.07%`** (`51/56`) | **`100.0%` (`40/40`)** | **`94.79%`** | Urgent escalation: **`4/4` (`100%`)** | `0.5847` (`0`) |

### 5.2 External Set `(d)` Detailed Breakdown by `style_tag` (`100` Rows vs. `96` Undisputed)

| `style_tag` | All 100 Rows (`Route Acc`) | Without 4 Disputed (`Route Acc`) | Notes |
|---|---:|---:|---|
| `abbreviation` | `2/2` (`100.0%`) | `2/2` (`100.0%`) | `HR`, `BP`, `O2` handled via glossary expansion |
| `borderline` | `2/2` (`100.0%`) | `2/2` (`100.0%`) | Safe scope-gate boundary handling |
| `colloquial` | `2/3` (`66.67%`) | `2/3` (`66.67%`) | Missed `E050` (*"skip treadmill today, I feel exhausted"*) |
| `data_lookup` | `11/11` (`100.0%`) | `11/11` (`100.0%`) | Direct vital/telemetry lookups |
| `general` | `11/11` (`100.0%`) | `11/11` (`100.0%`) | Out-of-scope refusals |
| `general_health` | `0/1` (`0.0%`) | *excluded (`E030`)* | Disputed general textbook vs personal query |
| `hard_negative_keyword` | `27/27` (`100.0%`) | `27/27` (`100.0%`) | Zero false accepts on non-human entities / equipment |
| `hard_positive_keyword` | `2/2` (`100.0%`) | `2/2` (`100.0%`) | Personal health queries preserved |
| `indirect` | `10/11` (`90.91%`) | `10/11` (`90.91%`) | Missed `E032` (*"I have a cold sore..."*) |
| `multi_topic` | `4/4` (`100.0%`) | `4/4` (`100.0%`) | Multi-domain health questions |
| `natural` | `14/16` (`87.5%`) | `11/13` (`84.62%`) | Missed `E001` (*"waking up around 3am"*), `E045` (*"what should I do if I get a medical danger alert"*); `E005`, `E008`, `E039` disputed |
| `synonym` | `1/1` (`100.0%`) | `1/1` (`100.0%`) | Synonym vocabulary match |
| `terse` | `3/3` (`100.0%`) | `3/3` (`100.0%`) | Short personal commands |
| `typo` | `0/1` (`0.0%`) | `0/1` (`0.0%`) | Missed `E009` (*"hart rate feels weird..."*) |
| `urgent` | `4/4` (`100.0%`) | `4/4` (`100.0%`) | Immediate `"Contact the flight surgeon immediately"` escalation |
| `vague` | `1/1` (`100.0%`) | `1/1` (`100.0%`) | Handled cleanly |

---

## 6. Path to Real Clinical Validation

Because open NASA resources contain no daily paired astronaut telemetry and clinical labels, moving from simulation recovery (`92.42%`) to flight-certified medical decision support requires:
1. **Real & Analog Datasets:** NASA Lifetime Surveillance of Astronaut Health (**LSAH**), NASA HRP **Standard Measures / CIPHER**, and ground analogs (**HERA** 45-day, **CHAPEA** 1-year, **:envihab** `-6°` HDT bed rest) under IRB / data-use agreements.
2. **Flight-Surgeon Ground-Truth Adjudication:** Independent blinded review by `>=2` board-certified NASA Flight Surgeons (tie-broken by a senior Flight Surgeon) using Private Medical Conferences (PMCs) and clinical logs, requiring inter-rater reliability **$\kappa \ge 0.80$**.
3. **Prospective Safety Gates:** Leave-mission-out evaluation measuring `Medical_Danger_Alert` and `Health_Warning` recall/precision with 95% CIs, AUPRC, False Alarms per 1,000 astronaut-days, detection latency, and Expected Calibration Error (ECE).
