# Vitalverse Mood Score & Telemetry Chart Mapping Specification

**Prototype Notice:** Check-in scoring and simulated mission mood metrics are wellness indicators for educational/prototype use, not clinical psychiatric diagnostics.

---

## 1. Daily Mental Check-In Score (`1.0 – 5.0`)

Both [static/mental.html](../static/mental.html) and [backend/services/mood_service.py](../backend/services/mood_service.py) implement the exact same scoring calculation:

1. **Five 1–5 Likert Scale Questions (`Q1`, `Q3`, `Q5`, `Q7`, `Q9`, indices `0, 2, 4, 6, 8`)**:
   - Base score = arithmetic mean of the 5 responses:
     $$\text{base} = \frac{a_0 + a_2 + a_4 + a_6 + a_8}{5}$$
2. **Categorical Modifiers**:
   - Question 6 (`index 5`, *"Have you felt overwhelmed at any point today?"*):
     - `"Often"` subtracts `0.7`
     - `"Never"` adds `0.2`
     - `"Sometimes"` adds `0.0`
   - Question 2 (`index 1`, *"What emotion best describes your day so far?"*):
     - `"Sad"` or `"Stressed"` subtracts `0.3`
3. **Bounds & Rounding**:
   - Clamped to `[1.0, 5.0]` and rounded to 1 decimal place (`round(max(1.0, min(5.0, s)), 1)`).
4. **Playlist / Photo Tag Recommendation (`comfort` | `happy` | `energy`)**:
   - Default threshold: `score < 2.7` -> `"comfort"`, `score < 3.8` -> `"happy"`, `score >= 3.8` -> `"energy"`.
   - Acute negative affect override: if `Q2` is `"Sad"`, `"Stressed"`, or `"Tired"`, or `Q6` is `"Often"`, the recommended tag switches to `"comfort"`.
5. **Support Alert Rule**:
   - Emits a `'warning'` alert (`source = 'mood'`) to approved doctors whenever a check-in scores `< 2.5` **or** the latest 3 consecutive check-ins are all `< 2.5`.

---

## 2. Health Dashboard Mood Series (`0 – 100`)

In [backend/services/health_service.py](../backend/services/health_service.py) (`METRIC_SPECS` for `"mood"`):

1. When a `mood_checkins` entry exists matching a mission day's date (`YYYY-MM-DD`):
   - Value = `round(clamp(score * 20.0, 0, 100), 1)`
   - Tooltip source = `"check-in"`
2. Otherwise:
   - Value = `round(clamp(mission_telemetry.mood * 10.0, 0, 100), 1)` (with preflight baseline scaled consistently)
   - Tooltip source = `"simulated data"`
