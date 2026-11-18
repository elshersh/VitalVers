# Vitalverse Full-Stack Integration Plan (`PLAN.md` — Updated for `vitalverse_frontend_v2`, Parts A & B)

**Prototype built with fictional data. Not a certified medical device.**  
**Model metrics reflect recovery of the project's own simulation rules, not clinical diagnostic accuracy.**

> **Plan Gate Only:** No Phase 1–4 code changes have been made yet. This plan incorporates every file in `d:\NASA 2\project\frontend_extra\vitalverse_frontend_v2\` and all **Part A** and **Part B** specifications. Implementation begins only after your approval, stopping after **every phase** with `1440px` and `390px` screenshots and explicit diff checks.

---

## 1. Audited Source Files (`vitalverse_frontend_v2`) & Existing Backend Map

### 1.1 Teammate `vitalverse_frontend_v2` Assets (Read in Full)

| Source File | Key Design Tokens / Patterns Observed | Integration Action |
|---|---|---|
| `index.html` (515 lines) | `16:9` `.hero` (`max-width:1600px`, `container-type:inline-size`), `cqw` navbar/text, `--green:#a8e07a`, `--green-btn:#e4f7c8`, `WelcomeModal` (`#welcomeOverlay`), `"Index.html"` typo, bell present in `.tools` | Keep layout & welcome modal cleanly with no `.stat` overlays / no live vitals; move to `static/index.html`; hide bell; fix `Index.html` -> `index.html`; point bg to `img/astronaut.png`; wire `Launch Mission` & `#profileBtn` via `shell.js` |
| `astronaut.png` (`1600×900` RGB) | Final hero artwork (`astronaut.png` is FINAL) | Place at `static/img/astronaut.png`; displayed directly with no `.stat` overlays (Home page no longer shows live vitals) |
| `_reference_old_index_with_stat_overlays.html` (185 lines) | Archived earlier Home draft containing `.stat` overlay boxes | Reference only — do **not** deploy `_reference_old_index_with_stat_overlays.html` or `.stat` overlays into `static/` |
| `about.html` (696 lines) | Canonical pill navbar (`padding:30px 4%`, `.logo 25px`, `.menu` `border-radius:50px` `12px 17px`, `.circle 39px`, `.profile 39px`, `#c5cbd0`), `#05080a` bg w/ green/blue radials, `.mission-content` glass card, `.disclaimer`, `.team-grid`/`.team-card`, `footer` | Basis for `css/shell.css`; move to `static/about.html` with shared navbar (clipboard replacing search, bell `.dot`, 38px mobile `.tools` kept visible) & footer disclaimer; leave body content untouched |
| `todo.html` (900 lines) | `#030609` + twin radials + `body::before` 250px starfield, `--muted:#b9c1c8`, `.eyebrow`, `.page-header h1`, `.progress-card` (`9px` glowing bar), `.task-grid`/`.task` cards, hardcoded `20` in HTML, `"To-do list"` in `.menu`, search icon, no `.profile` | Source of starfield/title/progress/card tokens for `css/theme.css`; move to `static/todo.html` with shared navbar (no `"To-do list"` in menu, clipboard + bell + profile added), footer + disclaimer, dynamic task totals, and API sync (`todo.js`) |
| `mental_astronaut.html` (197 lines) & `mental_doctor.html` (190 lines) | `--mut:#9aa6ab`, `--card:#0f1417`, `--field:#090f11`, `--track:#31373a`, `.mh` (`max-width:640px`), `.pills`, green-filled sliders, `.song`, `.ph`/`.lb`, `MH.save()` mood formula, Q4 `"Something else"` bug (`!= "Yes"`), unescaped `'`, `localStorage`, `tone()`, `pic()`, dead `addSong()`/`drawLib()` | Merge into `static/mental.html` (wrapped in shared navbar/footer + notice); delete separate `mental_astronaut.html` / `mental_doctor.html` from `static/`; fix Q4 `"Something else"`, Q1/Q3/Q5 validation, `esc()` `'`, same-day editability, SMTP/mailto backend, low-mood alert, doctor mood chart |
| `login.html` (200 lines) | `Space Grotesk 700` `h1`, tilted boarding-pass `.pass` with notches & barcode, `#101518` `.card`, `.roles`, `.go` primary btn (`52px`), `.err`, uppercase `input`, `VV` `localStorage` auth | Move to `static/login.html` with shared navbar + footer, add non-uppercase Password field, replace `VV` `localStorage` with `/api/auth/login` cookie+CSRF session |
| `signup.html` (150 lines) | `radial-gradient` `#070b0e` + `#101518` `.card`, boarding pass `.pass`, 3-step astronaut & 2-step doctor `.FLOW` w/ progress `.steps`, file `shrink()` base64, old minimal `.nav` | Move to `static/signup.html`; add shared navbar + footer; add Password + Confirm Password on Step 1 (no uppercase); replace scalar `playlist`/`prefPhoto` with tagged list managers (`comfort`/`happy`/`energy`); upload files via multipart API (no base64); create `pending` doctor requests |
| `astronaut-dashboard.html` (168 lines), `doctor-dashboard.html` (174 lines), `dashboard.css` (323 lines), `dashboard.js` (1015 lines) | Pure `#000` bg, `#0a0a0a` `.card`, `--red:#ff7a6b`, `--amber:#f5c451`, sticky `.navbar` w/ orbit logo & `.role-switch`, `.subbar` 4 section tabs, `.demo-banner`, `.pill-normal/.pill-watch/.pill-alert`, `METRICS` (`hr`, `bp`, `sleep`, `activity`, `mood`, `immune`, `bone`), `ASTRONAUTS`, `buildAstronautData()`, Chart.js CDN | Unify under single role-checked `GET /health.html` route (no `.role-switch` or `?astronaut=` preview); replace sticky `.navbar` w/ shared pill navbar & footer; keep everything below navbar identical; bundle Chart.js in `static/vendor/chart.umd.min.js`; replace `ASTRONAUTS`/`buildAstronautData()` w/ API calls; expand `METRICS` to 10 (adding `SpO2`, `temperature`, `blood_glucose`); label `"Personal trend"` vs `"Health status / alerts"`; add B8 replay slider |
| `_unused_alternative_dashboard/` (`health.html/css/js`) | Sidebar layout (`#080b0d`, `#11171b`) with extra metrics (`Oxygen saturation` `%`, `Body temperature` `°C`) | Do **not** deploy into `static/`; copy only `"Oxygen saturation"` (`%`) and `"Body temperature"` (`°C`) definitions into `dashboard.js` `METRICS` |

### 1.2 Keep / Change / Delete Inventory (Repo-Wide & `static/`)

- **Keep Read-Only / Untouched:**
  - `d:\NASA 2\all_project_codes\` (never modified; read-only in Phase 4 benchmark only)
  - `d:\NASA 2\project\frontend_extra\vitalverse_frontend_v2\` (untouched original snapshot used for `screenshots/before/` verification; excluded from served `static/` files)
  - `data/astronaut_health_eval.db`, `data/astronaut_health_eval.db.sha256` (frozen blind-test DB)
  - `data_raw/team_supplied/07_health_indicators_schema.json`, `references/`, `review/`, `eval/`, `config/project_config.json`, `config/demo_credentials.json`
  - Existing `generate_data.py`, `blind_test.py`, `resource_facts.py`, `tests/test_phase*.py` (all 23 existing tests must remain green)
- **Keep & Extend / Update In Place:**
  - `PLAN.md` (updated now)
  - `requirements.txt` (pin `fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`, `python-multipart`, `pywebpush`, `httpx`, `playwright` + existing dependencies after install)
  - `data/astronaut_health_app.db` (non-destructive additive ORM tables; existing 10 tables preserved)
  - `health_engine.py`, `ai_health_model.py`, `offline_ai_chatbot.py` (preserve CLI/test compatibility; wrap into backend services & verify winning candidate in Phase 4 `MODEL_REGISTRY.md`)
  - `README.md` (document one-command run, `.env`, Web Push localhost/HTTPS requirement, demo logins)
- **Create (New Files):**
  - Root & config: `app.py`, `.env.example`, `MODEL_REGISTRY.md` (Phase 4), `docs/mood_score.md` (Phase 2)
  - `backend/`: `__init__.py`, `config.py`, `database.py`, `models.py`, `schemas.py`, `security.py`, `services/{__init__.py,mood_service.py,alert_service.py,upload_service.py,email_service.py,model_service.py,chat_service.py}`, `routers/{__init__.py,auth.py,profile.py,doctor.py,health.py,todo.py,mental.py,alerts.py,chat.py}`
  - `uploads_private/` (outside `static/` web root; `.gitignore` runtime uploads if needed)
  - `scripts/`: `seed_demo.py`, `simulate_feed.py`, `capture_screenshots.py`
  - `static/`: `manifest.json`, `sw.js`, `vendor/chart.umd.min.js`, `fonts/{inter-latin-{400,500,600,700}-normal.woff2,space-grotesk-latin-{500,600,700}-normal.woff2,LICENSE-inter.txt,LICENSE-space-grotesk.txt}`, `img/astronaut.png`, `img/icon-192.png`, `img/icon-512.png`, `css/{fonts.css,shell.css,theme.css,dashboard.css}`, `js/{shell.js,auth.js,signup.js,dashboard.js,todo.js,mental.js,profile.js,alerts.js,chatbot.js}`, pages `{index.html,about.html,todo.html,mental.html,login.html,signup.html,astronaut-dashboard.html,doctor-dashboard.html,profile.html,alerts.html,chatbot.html,404.html,error.html}`
  - `tests/`: `test_web_auth_rbac.py`, `test_web_mood_todo_alerts.py`, `test_web_uploads_email_chat_model.py`, `test_e2e_playwright.py`
- **Exclude / Remove from Final Website (`static/`) & Plan:**
  - `mental_astronaut.html`, `mental_doctor.html` -> replaced by unified `static/mental.html`
  - `_reference_old_index_with_stat_overlays.html` -> not deployed into `static/` (Home page uses no `.stat` overlays)
  - `_unused_alternative_dashboard/` (`health.html`, `health.css`, `health.js`) -> not deployed
  - Prior Phase 0 draft pages `onboarding.html` and `doctor_setup.html` -> superseded by teammate `signup.html` + unified **B3** `profile.html`

---

## 2. Part A & Part B Design Decisions & Gap Analysis

### 2.1 Part A — Existing Pages Unification & Fixes

1. **A1 — Shared Navbar, Alert Tokens & Mobile Rule:**
   - **Shared pill navbar (`css/shell.css` + `js/shell.js`)** adopts the `about.html` pixel navbar layout (`padding:30px 4%`, `.logo 25px` heartbeat SVG, `.menu` pill bar `12px` `12px 17px`, `.tools` `39px` icon buttons & `.profile` pill + `.avatar`) and footer + `.disclaimer` one-liner (`"Prototype built with fictional data. Not a certified medical device."`) on **every page except `index.html`**.
   - `index.html` retains its exact `cqw` hero navbar and `16:9` layout wired cleanly to `shell.js`.
   - Menu items everywhere (exact labels & lowercase links): `Home page` (`index.html`), `Health dashboard` (`health.html`), `Ai chatbot` (`chatbot.html`), `Mental Health` (`mental.html`), `About` (`about.html`). (`"To-do list"` removed from `todo.html` menu; `Index.html` fixed to `index.html`.)
   - `.tools` buttons (semantic `<button aria-label="...">` matching `.circle`/`.profile` pixels cleanly):
     - `(a)` To-Do clipboard SVG (`index.html` stroke paths) -> navigates to `todo.html` (replaces search SVG on `about.html` & `todo.html`); **B6** renders a `2px` `--green` circular progress ring proportional to today's completion %, hidden when `0%` or logged out.
     - `(b)` Alerts bell + `.dot` -> **removed/hidden on `index.html`**; rendered on all other pages, toggling **B2** alerts dropdown; `.dot` hidden when `unread_count == 0`, `--danger` + pulse when unacknowledged danger alert exists.
     - `(c)` Profile pill -> added to `todo.html` & `signup.html`; opens **B4** profile dropdown when logged in, or opens the `index.html` welcome modal (`Create an Account` + `Log In`) when logged out.
   - **Mobile rule (`<= 700px`):** `about.html` and `todo.html` previously hid `.tools { display: none }`; in `shell.css`, keep `.tools { display: flex; gap: 8px; }` visible at `38px` (`width:38px; height:38px` `.circle` & `height:38px` `.profile`) on mobile with `.menu` wrapping cleanly onto row 2 (`order: 3; width: 100%`).
   - **Dashboards (`astronaut-dashboard.html`, `doctor-dashboard.html`):** Shared pill navbar + `.disclaimer` footer replaces sticky black `.navbar`, orbit placeholder SVG, and `.role-switch` controls; everything inside `.subbar`, `.demo-banner`, and `<main>` keeps its exact `#000` design. CSS classes in `shell.css` are scoped cleanly (`header.nav ...`, `.vv-dropdown`, `.vv-banner`, `.vv-toast`) so `dashboard.css`'s `.dot`, `.pill`, `.panel`, `.avatar`, `.split` inside `<main>` never collide.
   - **Exact alert tokens (no new tokens added):** `--danger: #ff7a6b` (`--red`) and `--warn: #f5c451` (`--amber`).

2. **A2 & B8 — Unified Role-Locked `/health.html` Dashboard:**
   - Single menu route `GET /health.html`: server inspects the authenticated `HttpOnly` session and serves `astronaut-dashboard.html` for `role='astronaut'` or `doctor-dashboard.html` for `role='doctor'` (unauthenticated redirects to `login.html`). Direct URL access to `/astronaut-dashboard.html` or `/doctor-dashboard.html` redirects to `/health.html`. Once Phase 2 auth exists, **remove all `?view=` and `?astronaut=` URL parameters everywhere** across the frontend and backend (`health.html`, `mental.html`, `profile.html`), remove the `.role-switch` control, and resolve role and approved astronauts strictly from the server session and `doctor_astronaut_links` (`status='approved'`). Add an automated pytest proving `?view=doctor` does nothing for an astronaut account.
   - Replace hardcoded `ASTRONAUTS`, `DOCTOR`, and `buildAstronautData()` in `dashboard.js` with `GET /api/health/...` calls preserving `{ times, series, channels, baseline }` so Chart.js and table logic stay intact.
   - **Daily granularity:** Telemetry in `mission_telemetry` is daily (`1..180`). Hide the `Day` button (`[data-range="day"]`) whenever `granularity === 'daily'` (never fabricating hourly readings) and update chart notes honestly to describe daily readings (`Week = 7 days`, `Month = 30 days`).
   - **Expanded `METRICS` (10 indicators across all cards, explorer chips, charts, tables & insights):**
     1. `hr` — Heart Rate (`bpm`, col `heart_rate`)
     2. `bp` — Blood Pressure (`mmHg`, cols `systolic_bp` / `diastolic_bp`)
     3. `spo2` — Oxygen Saturation (`%`, col `oxygen_saturation`, from `_unused/health.js`)
     4. `temp` — Body Temperature (`°C`, col `temperature`, from `_unused/health.js`)
     5. `glucose` — Blood Glucose (`mg/dL`, col `blood_glucose_mg_dl`)
     6. `sleep` — Sleep Monitoring (`hours`, col `sleep_hours`)
     7. `activity` — Physical Activity (`min`, col `daily_physical_activity_min`)
     8. `mood` — Psychological State / Mood (`/ 100`: daily check-in `score * 20` when present for that day, else DB `mood` `×10` / `mental_health_assessment` converted to `0–100`; tooltip always displays source `"check-in"` or `"simulated data"`, never leaving the chart empty when DB values exist)
     9. `immune` — Immune System (`/ 100`, col `immunity_indicators`)
     10. `bone` — Bone Health (`% index`, col `bone_health`)
   - **Two clearly labeled status layers:**
     - **Personal trend (illustrative %):** keeps `dashboard.js`'s `statusFor()` % deviation from each astronaut's pre-flight baseline, labeled `"Personal trend (illustrative %)"` matching the footnote.
     - **Health status / alerts (AI + Schema):** drives the overall `#overallStatus` pill, crew cards, notifications, and escalation banner using the server's Phase 4 ML prediction + verified `07_health_indicators_schema.json` thresholds w/ B0 source badges (`NASA standard`, `Reference value`, `Placeholder`, etc.).
   - **B8 Doctor Mission Replay:** Medical History gets a green-filled white-thumb range slider (`label`: `"Mission day X of Y"`, e.g. `"Mission day 42 of 180"`). Moving it loads `GET /api/health/{astronaut_id}/replay?day=X` and redraws history chart, table, and status as of day `X`.
   - **Chart.js bundled locally:** `static/vendor/chart.umd.min.js` replaces all CDN `<script>` tags. Keep `.demo-banner` `"Simulated data"` banners.

3. **A3 — Login, Signup, Onboarding Media & Doctor Approval Flow:**
   - `login.html`: Add `<input id="pwd" type="password">` (explicitly `text-transform: none; letter-spacing: normal`), Vitalverse ID / email + password login against `/api/auth/login` (Argon2id + 5-attempt lockout + `HttpOnly` cookie + CSRF), retaining `.pass` crew/medical boarding-pass animation.
   - `signup.html`:
     - Add Password + Confirm Password inputs in Step 1 for both Astronaut and Doctor (`text-transform: none`).
     - Replace scalar `playlist` and `prefPhoto` fields in Astronaut Step 1 with reusable list managers built using `signup.html`'s own `input`, `select`, `button.btn`, `button.btn.ghost`: each song has `title`, `tag` (`comfort|happy|energy`), and either an `https://`/`http://` link OR `.mp3/.m4a/.wav` audio `File`; each photo supports multi-file `.jpg/.png/.webp` + `tag` (`comfort|happy|energy`).
     - Remove `shrink()` base64 DataURL serialization: hold `File` objects in JS memory through Step 3, then post `/api/auth/signup` + authenticated multipart `POST /api/uploads/{astronaut_id}` (server Pillow re-encode for images `<=5 MB`, audio `<=15 MB` stored under `uploads_private/`).
     - Doctor Step 2 validates target astronaut's Vitalverse ID, requires authorization checkbox, and creates a `pending` row in `doctor_astronaut_links` (`403` on all astronaut data until approved in `profile.html`). Once approved, doctor can view everything and edit that astronaut's Health & Flight tabs.

4. **A4 — Home (`index.html`) Hero & CTA:**
   - The Home page renders the hero artwork directly with no `.stat` overlays (`.bpm`, `.oxy`, `.tmp`) and no live vitals.
   - Screenshot verify at `1440px` & `390px`.
   - `"Launch Mission"` links to `health.html` when logged in or `login.html` when logged out.

5. **A5 & B5 — Daily To-Do & Merged `mental.html`:**
   - `todo.html`: Daily state per `(astronaut_id, YYYY-MM-DD)` via `/api/todo/{astronaut_id}`; new day starts clean (`done=false`); `"Reset Day"` clears today via API; `totalTasks = tasks.length` populates `/ <span id="totalCount">` & initial `Remaining` dynamically.
   - `mental.html`: Merges `mental_astronaut.html` & `mental_doctor.html` inside shared navbar & footer + `"WELLBEING / DAILY CHECK-IN"` `<h1>Mental <span>Health</span></h1>` header + notice (`"Your flight surgeon can see your check-in answers."` in `.disclaimer` style). Fixes Q4 (`Yes` or `Something else` reveals `#smile`), validates unanswered choices, fixes `esc()` (`'` -> `&#39;`), removes `localStorage`, `tone()`, `pic()`, dead `addSong()`/`drawLib()`. Same-day check-in is editable once/day (showing result card first w/ `"Edit today's answers"` ghost button); score computed identically on backend (`docs/mood_score.md`); email validates recipient + rate-limits + SMTP/`mailto:` fallback without logging bodies; `score < 2.5` or 3 consecutive Low days creates a `'warning'` alert for approved doctors; Doctor view (temporary Phase 1 static `?view=doctor` preview **removed in Phase 2** so role comes strictly from server session) adds linked astronaut selector, Chart.js mood history chart (`1–5` w/ `rgba(255,122,107,.08)` zone below `2.5`), `"Low mood for 3+ days"` `--warn` card, and results table.

### 2.2 Part B — Theme & Missing Pages

- **B0 — `static/css/theme.css`**: Exact tokens (`--green:#a8e07a`, `--green-btn:#e4f7c8`, `--text:#fff`, `--muted:#aeb8bd`, `--line:rgba(255,255,255,.2)`, `--field:#0a0f12`, `--glass:rgba(8,13,19,.78)`, `--danger:#ff7a6b`, `--warn:#f5c451`), `todo.html` `#030609` radials + starfield, Inter 400/500/600 & Space Grotesk 700 (auth/profile `h1` only), `.eyebrow`, `.page-header h1`, glass card, interactive card, `.team-card` lift, primary `.btn`/`.go`, `.btn.ghost`, inputs w/o uppercase, `.pills` chips, `.progress-bar`, mental table, `.ov`/`.modal`, `--danger` `.err`, `.pill-normal/.pill-watch/.pill-alert`, `.25s` motion & `prefers-reduced-motion`, plus reusable **Toast**, **Skeleton**, **Empty state**, and **Threshold source badges** (`NASA standard` / `Physician-reviewed` in green; `Reference value` / `Placeholder` / `Unverified` in muted). Used **only** by new pages (`chatbot.html`, `alerts.html`, `profile.html`, `404.html`, `error.html`).
- **B1 — `chatbot.html`**: Offline QA card (`max-width:900px`), scrolling chat + bottom `.menu`-styled pill textarea + `--green-btn` `.circle` send button (`Enter` send, `Shift+Enter` newline), heartbeat SVG avatar on bot bubbles, right-aligned `--green-btn` user bubbles, 3 green pulsing dots typing indicator, 4 suggested prompt chips, `"New chat"` ghost button, muted dashed refusal card, `--danger` left-bar urgent escalation card (w/ `"View alerts"` + surgeon contact), doctor approved-astronaut selector, logged-out `"my ..."` login CTA card.
- **B2 — Alerts Dropdown, `alerts.html`, Danger Banner, SSE & Web Push**: Navbar bell dropdown (6 latest items, `"Mark all read"`, `"View all alerts"`, `"All clear. No alerts."`), `alerts.html` w/ filter chips (`All / Danger / Warning / Info / Unread`), short astronaut cards vs expandable detailed doctor cards (model probability bars, triggered vitals w/ source badges, local Chart.js 7-day line w/ `--danger` points, prioritized countermeasures w/ `"Contact flight surgeon immediately"` first on danger, `"Open dashboard"` + `"Acknowledge"`), full-width `--danger` banner below navbar while unacknowledged danger exists, live Server-Sent Events (`/api/alerts/stream`), PWA `manifest.json` + `sw.js` + `pywebpush` VAPID notifications (HTTPS or `localhost` documented).
- **B3 — `profile.html`**: `.pass` boarding pass (`"Verified"`) + right tabbed glass card: Astronaut tabs (`Personal | Health | Flight | Songs & Photos | Access | Security`); Doctor tabs (`Doctor info | My astronauts | Security`). Includes pending request Approve/Decline, Revoke access w/ confirm modal, `"Request access to another astronaut"` w/ consent checkbox, password change, and `"Log out of all devices"`. Also allows approved doctors to edit an approved astronaut's Health & Flight tabs selected in-page from their approved list (`/api/doctor/astronauts`, no URL query overrides; enforced server-side with `403`).
- **B4 — Profile Dropdown**: Navbar `.profile` glass panel (avatar photo, name, green Vitalverse ID, role pill, `My profile`, `Access requests` badge for astronauts, `My astronauts` for doctors, `Log out`); logged out opens welcome modal.
- **B6 — To-do Progress Ring**: `2px` green SVG ring on `.circle` clipboard icon (`0%` hidden).
- **B7 — `404.html` & `error.html`**: `"SIGNAL LOST"` / `"Lost in <span>space</span>"` / `"Back to Home"`, shared layout for HTTP `404` & `500` (`"Something went wrong on our side."`).

---

## 3. Database Schema (`data/astronaut_health_app.db` via SQLAlchemy)

Existing 10 tables in `data/astronaut_health_app.db` remain intact (`astronaut_profile`, `auth_users`, `auth_sessions`, `preflight_baseline`, `mission_telemetry`, `telemetry_labels`, `model_predictions`, `countermeasures`, `data_provenance`, `data_dictionary`). New tables created idempotently:

| Table | Key Columns | Purpose |
|---|---|---|
| `users` | `id PK`, `vitalverse_id UNIQUE NOT NULL` (`VTA-*`/`VTD-*`), `email NULLABLE UNIQUE`, `password_hash NOT NULL` (`argon2id`), `role NOT NULL` (`astronaut`\|`doctor`), `astronaut_id NULLABLE UNIQUE FK`, `legacy_user_id NULLABLE UNIQUE`, `failed_attempts`, `locked_until`, `created_at` | Unified auth linking seeded `A001–A200` / `FS001–FS002` + web signups (`VTA-xxxxxx` / `VTD-xxxxxx`) |
| `web_sessions` | `session_id PK`, `user_id FK`, `csrf_token NOT NULL`, `created_at`, `expires_at`, `revoked DEFAULT 0` | Stateful `HttpOnly; SameSite=Lax` cookies + CSRF + `"Log out of all devices"` |
| `uploaded_files` | `id PK`, `owner_astronaut_id FK`, `uploaded_by_user_id FK`, `kind` (`image`\|`audio`), `mime_type`, `original_filename`, `storage_relpath` (in `uploads_private/`), `byte_size`, `sha256`, `created_at` | Server-validated uploads (`jpg/png/webp <=5MB` Pillow re-encoded; `mp3/m4a/wav <=15MB`) served only to authorized owners/approved doctors |
| `astronaut_playlist_items` | `id PK`, `astronaut_id FK`, `title`, `tag` (`comfort`\|`happy`\|`energy`), `kind` (`audio`\|`link`), `url NULLABLE`, `upload_id NULLABLE FK`, `created_at` | Onboarding Step 1, Profile library & Mental check-in song selection |
| `astronaut_photo_items` | `id PK`, `astronaut_id FK`, `tag`, `upload_id NULLABLE FK`, `url NULLABLE`, `caption`, `created_at` | Multi-photo tagged library for onboarding, profile & Mental slideshow |
| `doctor_profiles` | `user_id PK FK`, `staff_id`, `full_name`, `specialization`, `organization`, `contact`, `credential`, `created_at` | Doctor setup & profile editing |
| `doctor_astronaut_links` | `id PK`, `doctor_user_id FK`, `astronaut_id FK`, `status NOT NULL` (`pending`\|`approved`\|`declined`\|`revoked`), `mission_crew_note`, `consent_confirmed BOOL`, `created_at`, `decided_at`, `UNIQUE(doctor_user_id, astronaut_id)` | Strict RBAC: zero visibility until `approved`; controls view + Health/Flight edit rights |
| `daily_todo` | `id PK`, `astronaut_id FK`, `todo_date DATE`, `item_key`, `label`, `done BOOL`, `updated_at`, `UNIQUE(astronaut_id, todo_date, item_key)` | Daily checklist per date (new day starts clean; `"Reset Day"` clears today) |
| `mood_checkins` | `id PK`, `astronaut_id FK`, `checkin_date DATE`, `answers_json`, `score REAL`, `recommended_tag`, `created_at`, `updated_at`, `UNIQUE(astronaut_id, checkin_date)` | 1 editable check-in/day; exact backend score + low-mood trigger |
| `alerts` | `id PK`, `astronaut_id FK`, `mission_day INT NULL`, `severity` (`info`\|`warning`\|`danger-confirm`\|`danger`), `source` (`model`\|`mood`\|`access`), `short_message`, `detailed_explanation_json`, `read_at NULL`, `acknowledged_at NULL`, `acknowledged_by_user_id NULL FK`, `created_at` | Tiered role-filtered alerts powering bell dropdown, danger banner, `alerts.html`, SSE & Web Push |
| `push_subscriptions` | `id PK`, `user_id FK`, `endpoint UNIQUE`, `p256dh`, `auth`, `created_at` | PWA Web Push browser subscriptions (`VAPID`) |
| `email_rate_limits` | `id PK`, `user_id FK`, `recipient_email`, `sent_at`, `status` | Per-user SMTP rate-limiting (never logs email bodies) |

---

## 4. Full API Endpoint List

Every state-changing route (`POST`/`PUT`/`PATCH`/`DELETE`, except `/api/auth/login` & `/api/auth/signup`) enforces active `HttpOnly` cookie + `X-CSRF-Token`. Every `{astronaut_id}` route enforces `403 Forbidden` unless owning `astronaut` or `doctor` with `doctor_astronaut_links.status == 'approved'`.

- **Auth (`/api/auth/*`):** `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `POST /api/auth/logout-all`, `PUT /api/auth/password`, `GET /api/auth/me` (user, role, `csrf_token`, `unread_alert_count`, `unack_danger_count`, `pending_access_count`, `todo_percent`; Home page no longer shows live vitals).
- **Uploads & Media (`/api/uploads/*`, `/api/media/*`):** `POST /api/uploads/{astronaut_id}`, `GET /api/media/{upload_id}` (authorized stream w/ `Cache-Control: private, no-store`).
- **Profile & Onboarding (`/api/profile/*`):** `GET /api/profile/{astronaut_id}`, `PUT /api/profile/{astronaut_id}/personal` (astronaut only; Access tab also astronaut only), `PUT /api/profile/{astronaut_id}/health` (astronaut or approved doctor), `PUT /api/profile/{astronaut_id}/flight` (astronaut or approved doctor), `POST /api/profile/{astronaut_id}/playlist`, `DELETE /api/profile/{astronaut_id}/playlist/{id}`, `POST /api/profile/{astronaut_id}/photos`, `DELETE /api/profile/{astronaut_id}/photos/{id}`.
- **Access Requests (`/api/access/*`) & Doctor (`/api/doctor/*`):** `GET /api/doctor/profile`, `PUT /api/doctor/profile`, `GET /api/doctor/astronauts` (approved + pending), `POST /api/doctor/requests` (by Vitalverse ID + consent checkbox), `GET /api/access/requests` (astronaut pending/approved list), `POST /api/access/requests/{id}/approve`, `POST /api/access/requests/{id}/decline`, `POST /api/access/requests/{id}/revoke`.
- **Health & Model (`/api/health/*`, `/api/predict/*`, `/api/demo/*`):**
  - `GET /api/health/{astronaut_id}/dashboard?range=week|month` (10 `METRICS` in `{times, series, channels, baseline}` shape, `granularity: "daily"`, Personal trend deviations, AI status/probabilities + verified schema thresholds & badges, advice/insights/followups)
  - `GET /api/health/{astronaut_id}/replay?day={1..N}` (B8 doctor mission day replay state)
  - `POST /api/predict/{astronaut_id}` (Phase 4 startup-loaded model inference -> persists `model_predictions` + creates `alerts` + SSE/Web Push)
  - `POST /api/demo/advance` (**DEMO**-labeled live telemetry feed step -> runs prediction + alerts)
- **Daily To-Do (`/api/todo/*`):** `GET /api/todo/{astronaut_id}`, `PATCH /api/todo/{astronaut_id}/items/{key}`, `POST /api/todo/{astronaut_id}/reset`.
- **Mental Health (`/api/mental/*`):** `GET /api/mental/{astronaut_id}/checkins`, `POST /api/mental/{astronaut_id}/checkins`, `PUT /api/mental/{astronaut_id}/checkins/today`, `POST /api/mental/email`.
- **Alerts, SSE & Push (`/api/alerts/*`, `/api/push/*`):** `GET /api/alerts`, `POST /api/alerts/read-all`, `POST /api/alerts/{id}/acknowledge`, `GET /api/alerts/stream` (SSE), `GET /api/push/vapid-public-key`, `POST /api/push/subscribe`.
- **Offline Chatbot (`/api/chat`):** `POST /api/chat` (session role + optional approved `astronaut_id` for doctors; scope gate + urgent escalation + personal telemetry/alerts grounding; logged-out allowed for general Q&A, login prompt card on `"my ..."`).
- **Static & Error Routes:** `/health.html` (role-resolved), `/`, `/{page}.html`, `/manifest.json`, `/sw.js`, custom `404.html` & `500` `error.html`.

---

## 5. Page Access Matrix per Role

| Page | Logged Out | Astronaut (`role='astronaut'`) | Doctor (`role='doctor'`) |
|---|---|---|---|
| `index.html` | Clean hero (no `.stat` overlays or live vitals), welcome modal on profile, CTA -> `login.html` | Clean hero (no live vitals), profile dropdown, CTA -> `health.html` | Clean hero (no live vitals), profile dropdown, CTA -> `health.html` |
| `about.html` | Public | Public + live shell state | Public + live shell state |
| `login.html` / `signup.html` | Role choice + login/multi-step signup w/ password & list managers | Access/switch account | Access/switch account |
| `/health.html` | Redirect -> `login.html` | `astronaut-dashboard.html` (own data, 10 metrics, Personal trend vs AI/schema status) | `doctor-dashboard.html` (approved crew only, 10 metrics, B8 Mission Day replay slider, Insights) |
| `todo.html` | Redirect -> `login.html` | Dynamic daily checklist, API save & `"Reset Day"`, navbar progress ring | Crew/info notice or read-only approved astronaut checklist |
| `mental.html` | Redirect -> `login.html` | 1/day editable check-in, saved song+photo recs, SMTP/mailto email | Approved astronaut selector, Chart.js 1–5 trend + `<2.5` band, 3-day Low `--warn` card, check-in table |
| `profile.html` | Redirect -> `login.html` | Boarding pass + `Personal \| Health \| Flight \| Songs & Photos \| Access \| Security` tabs | Boarding pass + `Doctor info \| My astronauts \| Security` tabs (+ edit Health/Flight of approved astronaut) |
| `alerts.html` | Redirect -> `login.html` | `short_message` cards + `"Acknowledge"` | Detailed expandable cards (prob bars, vitals+badges, 7d chart, countermeasures) |
| `chatbot.html` | General Q&A + `"Log in"` card for `"my ..."` | Full personal Q&A + urgent escalation + suggested chips | Approved astronaut selector + Q&A + urgent escalation |
| `404.html` / `error.html` | Rendered cleanly for HTTP 404 / 500 | Same | Same |

---

## 6. Expected Visual Differences & Phased Schedule (Stop + Screenshots After Each Phase)

### Expected Visual Differences (Phase 1 vs Unmodified `vitalverse_frontend_v2` "Before" Screenshots)
1. **`index.html`**: (a) Bell icon + green `.dot` removed from `.tools`; (b) `.circle`/`.profile` focusable buttons (`<button>`) keep identical styling; (c) `Index.html` fixed to `index.html`. No `.stat` overlays or live vitals on Home; zero other changes to image/title/hero/welcome modal.
2. **`about.html`**: (a) Search icon -> Clipboard To-Do icon; (b) Bell `.dot` dynamic (hidden at 0 unread); (c) **Mobile `<= 700px`**: 3 icon controls (`To-do`, `Bell`, `Profile`) remain visible at `38px` instead of `display: none`; (d) Footer adds the `.disclaimer` line (`"Prototype built with fictional data. Not a certified medical device."`).
3. **`todo.html`**: (a) `"To-do list"` removed from `.menu` (6 -> 5 links); (b) Search icon -> Clipboard To-Do icon; (c) `.profile` pill added to `.tools`; (d) Pill navbar normalized to `css/shell.css` (`about.html` px metrics) + **Mobile `<= 700px`** keeps `.tools` visible at `38px`; (e) Footer normalized + `.disclaimer` line added; (f) `/ 20` replaced dynamically from task count (`20` visually unchanged for default list).
4. **`mental.html`**: Merged `mental_astronaut.html` + `mental_doctor.html` gains the shared pill navbar on top, `WELLBEING / DAILY CHECK-IN` `<h1>Mental <span>Health</span></h1>` header + flight-surgeon `.disclaimer` notice above `.mh`, and shared footer + disclaimer below. Everything inside `.mh` stays identical (`--mut: #9aa6ab`).
5. **`login.html`**: (a) Navbar uses `css/shell.css` pill spacing + adds footer/disclaimer at bottom; (b) Password input added under Vitalverse ID.
6. **`signup.html`**: (a) Old bottom-border `.nav` (`Home page | Log In`) replaced by shared pill navbar + footer/disclaimer; (b) Password + Confirm Password inputs added in Step 1; (c) Step 1 single Playlist/Photo inputs replaced by compact Song & Photo list managers in `signup.html` style.
7. **`astronaut-dashboard.html` & `doctor-dashboard.html`**: (a) Sticky black `.navbar`, orbit logo, and `.role-switch` replaced by shared pill navbar + footer/disclaimer; (b) `Day` range button hidden when daily-only (`granularity='daily'`); (c) `SpO2`, `Body Temperature`, and `Blood Glucose` chips/columns/cards appear in existing sections; (d) Personal trend vs Health status/alerts badges clearly labeled; (e) B8 green Mission Day replay slider added in Doctor `Medical History` card.

### Phase 3 Must-Fix: Temporary Demo Values (Must Be Replaced by Real API Data)
1. **`static/mental.html`:** Doctor `<select>` fallback option (`"Approved Astronaut (Phase 2/3 demo)"`), fallback 3-point sample `Mood score trend (1–5)` chart (`Day 1..3`: `[3.8, 3.4, 3.1]`), and static `"No check-ins yet."` card -> replace in Phase 3 with live `/api/doctor/astronauts` and `/api/mental/{astronaut_id}/checkins`.
2. **`static/js/dashboard.js` (`ASTRONAUTS`, `DOCTOR`, `buildAstronautData()`):** Generated 5-astronaut crew list and deterministic synthetic telemetry series -> replace in Phase 3 with `/api/health/{astronaut_id}/dashboard`, `/api/health/{astronaut_id}/replay`, and `/api/doctor/astronauts`.
3. **`"Mission Day 30"` & `historyDays = 30` (`static/js/dashboard.js`, `static/astronaut-dashboard.html`, `static/doctor-dashboard.html`):** Temporary `CONFIG.historyDays = 30`, `ASTRONAUTS[i].missionDay = 30`, and initial slider `<input id="missionDaySlider" min="1" max="30" value="30">` / `"Mission day 30 of 30"` -> replace in Phase 3 using the astronaut's real `1..180` mission days from `mission_telemetry` (`min="1"`, `max=total_days`, current `mission_day`, replay slider covering the real 180-day range).
4. **`"SIMULATED PREVIEW"` label (`static/js/dashboard.js` `#overallStatus`):** Eyebrow `"Health Status / Alerts (AI + Schema · Simulated preview)"` -> update in Phase 3 to real API AI model + verified schema status while preserving the simulated-dataset disclaimer (`astronaut_health_app.db` is synthetic crew data, not real clinical measurements).

### Phased Build Order (User Approval Gate Between Every Phase)
0. **Plan Gate (Completed):** Approved `PLAN.md` -> commit & tag `pre-website-build` -> pinned deps (`requirements.txt`), bundled `static/vendor/chart.umd.min.js`, captured `1440px` & `390px` **Before** screenshots (`screenshots/before/`).
1. **Phase 1 — Unify Existing Pages + Shared Navbar + `theme.css` + Offline Fonts (Done & Pending Final Overlay-Removal Approval):** `astronaut.png` is served directly with `.stat` overlays removed completely (Home page no longer shows live vitals); local `static/fonts/` (Inter `400/500/600/700` & Space Grotesk `500/600/700` `.woff2` + SIL OFL licenses) + `static/css/fonts.css` replacing every Google Fonts `<link>`, verified by Playwright zero-external-requests check.
2. **Phase 2 — FastAPI Backend, SQLite Schema, Security, Uploads, Push/SSE & Pytest:** Pass unit tests for auth/403s/approval/mood parity/todo reset/uploads/email/alerts; **remove all `?view=` / `?astronaut=` URL parameters** (resolve role & approved astronauts only from server session + approved DB links; add pytest verifying `?view=doctor` does nothing for an astronaut account); add `scripts/seed_demo.py` (from `config/demo_credentials.json`: 1 linked `A0xx` astronaut w/ `comfort`/`happy`/`energy` songs & photos, 1 approved doctor, 1 pending doctor; all 3 fake `DEMO ONLY` logins documented in `README.md`); capture verification screenshots & **STOP for approval**.
3. **Phase 3 — Build Part B Pages (`chatbot.html`, `alerts.html`, `profile.html`, `404.html`) & Wire All APIs:** Connect every page (`loading/empty/error/success` states, offline Chart.js, offline local fonts, live 180-day telemetry/replay/mental/todo/profile/alerts) and eliminate every item in **Phase 3 Must-Fix: Temporary Demo Values** above; verify Playwright zero external requests & screenshot all new/existing pages (`1440px` & `390px`), **STOP for approval**.
4. **Phase 4 (LAST) — Model & Chatbot Registry (`MODEL_REGISTRY.md`), Merge, Demo Feed & Full E2E:** Tag `pre-merge-archive`, run grouped `GroupKFold` selection + single blind test, merge winner into `/api/predict` & `/api/chat` (dashboards/alerts only; Home page has no live vitals or `.stat` overlays), build `scripts/simulate_feed.py`, run full `pytest` + Playwright zero-external-request + E2E flows (a) & (b) + final screenshots, update `README.md` & deliver final report.
