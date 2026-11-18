# Model Registry — Vitalverse Health Monitoring Prototype

> **Disclaimer:** Prototype for research/education only — not for clinical diagnosis.  
> **All telemetry and labels are synthetic (`seed = 42`).** Metrics measure recovery of the project's simulation rules, not clinical diagnostic performance.

---

## 1. Active Production Artifact

| Field | Value |
|---|---|
| **Artifact Path** | [`models/health_model.joblib`](file:///d:/NASA%202/project/models/health_model.joblib) (`45.76 MiB`, gzip/joblib compressed) |
| **Model Version** | `personal_baseline_v4` |
| **Selected Architecture** | `single_rf` *(Platt-calibrated 10-leaf Random Forest, `CalibratedClassifierCV`, `method="sigmoid"`)* |
| **Trained Timestamp** | `2026-11-14T13:55:25+00:00` |
| **Target Classes** | `Normal`, `Stress_BP_Spike_No_Medical_Danger`, `Health_Warning`, `Medical_Danger_Alert` |
| **Feature Count** | `331` causal per-astronaut features *(past-only rolling windows, linear slopes, personal baseline z-scores, acute deltas, recovery rates, cumulative bone/muscle changes, SpO2, BP, glucose, multi-system abnormal counts)* |
| **Training / Blind Test Cohort Split** | `GroupShuffleSplit(test_size=0.2, random_state=42)` — **`160` train astronauts (`28,800` days)** vs. **`40` blind test astronauts (`7,200` days)**, **`0` crew overlap** |
| **Decision Threshold Weights (`[N, S, W, D]`)** | `[1.0, 0.55, 3.0, 1.75]` |
| **Clinical Cost Matrix** | `[[0.0, 1.5, 1.2, 4.0], [3.0, 0.0, 2.0, 3.5], [4.5, 2.5, 0.0, 3.5], [40.0, 25.0, 20.0, 0.0]]` *(missed danger penalized `20x–40x` vs. false alert)* |
| **Tiered Alerting Policy** | `danger_confirm_prob_threshold = 0.22`, `danger_high_prob_threshold = 0.45`, `danger_confirm_persistence_days = 2` |
| **Runtime Loader** | [`backend/services/model_service.py`](file:///d:/NASA%202/project/backend/services/model_service.py) (`ModelService`, loaded once at FastAPI startup; served via `/api/astronauts/{id}/predictions`, `/api/health/{id}/dashboard`, `/api/predict/{id}`, and `/api/demo/advance`) |

---

## 2. Candidate Selection (5-Fold `GroupKFold` on Training Cohort Only)

All architecture comparisons and threshold searches ran strictly inside 5-fold `GroupKFold` cross-validation on the `160` training astronauts:

| Candidate Architecture | Val Accuracy | Macro F1 | `Health_Warning` Recall | `Danger` Recall | `Danger` Precision | Expected Cost | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| **`single_rf`** | `92.53% +/- 0.47%` | `88.74%` | `81.58%` | `93.08%` | `93.22%` | `0.2163` | **Promoted (`models/health_model.joblib`)** |
| `two_stage_rf` | `92.58%` | `88.64%` | `81.78%` | `91.38%` | `93.84%` | `0.2257` | Rejected *(higher expected cost, lower danger recall)* |
| `hist_gbm` | `93.52%` | `90.18%` | `80.31%` | `93.54%` | `96.66%` | `0.2127` | Not adopted *(did not beat `single_rf` by `>0.03` objective AND `Health_Warning` sensitivity `80.31% < 81.58%`)* |

Per-fold validation accuracies for `single_rf`: `91.68%`, `93.09%`, `92.53%`, `92.55%`, `92.78%`.

---

## 3. Held-Out Blind Test Evaluation (`n = 7,200` Days, 40 Unseen Astronauts)

Verified against frozen evaluation database `data/astronaut_health_eval.db` (SHA-256 `b9a5bc4536256a441d638441c2980badb13122b6b8474acf4ebad5b4c0fdc8c5`):

| Metric | Value (`95% CI`) |
|---|---|
| **Overall Accuracy** | `92.42%` (`95% CI [91.28, 93.40]`) |
| **Macro Sensitivity / Specificity / Precision / F1** | `87.56%` / `94.82%` / `89.95%` / `88.70%` (`[86.56, 90.40]`) |
| **`Medical_Danger_Alert` (`n = 171`)** | Recall `91.23% [86.03, 94.61]`, Precision `96.30% [92.16, 98.29]`, Specificity `99.91%`, F1 `93.69%` (`0.83` false alerts / 1,000d) |
| **`Health_Warning` (`n = 970`)** | Recall `78.56% [75.86, 81.02]`, Precision `76.35% [73.62, 78.88]`, Specificity `96.21%`, F1 `77.44%` |
| **`Stress_BP_Spike_No_Medical_Danger` (`n = 497`)** | Recall `84.91% [81.50, 87.79]`, Precision `91.94% [89.09, 94.10]`, Specificity `99.45%`, F1 `88.28%` |
| **`Normal` (`n = 5,562`)** | Recall `95.54% [94.97, 96.05]`, Precision `95.22% [94.62, 95.75]`, Specificity `83.70%`, F1 `95.38%` |
| **Tiered Alerting (`Danger` / `Danger-confirm`)** | `Danger`: Precision `95.21%`, Recall `92.98%` (`1.11` FA/1,000d) · Inclusive screening: Precision `93.02%`, Recall `93.57%` (`1.67` FA/1,000d) |
| **Noise & Missingness Robustness** | `1.5x` noise + `5%` missing: `88.38%` acc (`92.40%` danger recall) · `2.0x` noise + `5%` missing: `80.51%` acc (`91.81%` danger recall) |

---

## 4. Offline Chatbot Registry

| Component | Configuration & Verified Bounds |
|---|---|
| **Implementation** | [`offline_ai_chatbot.py`](file:///d:/NASA%202/project/offline_ai_chatbot.py) wrapped by [`backend/services/chat_service.py`](file:///d:/NASA%202/project/backend/services/chat_service.py) (`/api/chat`) |
| **Classifier** | Offline TF-IDF (`ngram_range=(1,2)`, `sublinear_tf=True`) + cosine similarity + deterministic scope/safety/urgency gates |
| **Anti-Leakage Audit** | `0` violations above `0.60` cosine similarity (`max = 0.5983`) across all benchmark sets |
| **Verified Performance (`EVALUATION_REPORT.md`)** | Core `38/38` (`100%`), Held-out `98.61%`, CLINC150 OOS `320/320` (`100%` refusal), MedQuAD QA `94.55%` strict (`100%` OOS refusal), External CSV `94.0%` all / `94.79%` undisputed (`4/4` urgent escalations), Paraphrase stress `84.13%` (`-13.49` pts) |
