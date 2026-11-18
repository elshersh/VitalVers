"""Online LLM integration layer (Gemini, Anthropic, Groq) with strict privacy and fallback."""
from __future__ import annotations

import logging
import re
import socket
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import health_engine as he
import resource_facts as rf
from backend.config import (
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_ONLINE_PROVIDER,
    GEMINI_BACKUP_MODEL,
    ONLINE_MAX_OUTPUT_TOKENS,
    ONLINE_SYSTEM_PROMPT_PATH,
    ONLINE_TIMEOUT_SECONDS,
    read_env_var,
)

log = logging.getLogger("vitalverse.online_llm")


@dataclass(frozen=True)
class ProviderSpec:
    slug: str
    key_env: str
    model_env: str
    default_model: str
    label: str
    service_name: str
    probe_host: str


PROVIDER_ORDER: tuple[str, ...] = ("gemini", "anthropic", "groq")

PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(
        slug="gemini",
        key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        default_model=DEFAULT_GEMINI_MODEL,
        label="Gemini",
        service_name="Google Gemini",
        probe_host="generativelanguage.googleapis.com",
    ),
    "anthropic": ProviderSpec(
        slug="anthropic",
        key_env="ANTHROPIC_API_KEY",
        model_env="CLAUDE_MODEL",
        default_model=DEFAULT_CLAUDE_MODEL,
        label="Claude",
        service_name="Anthropic Claude",
        probe_host="api.anthropic.com",
    ),
    "groq": ProviderSpec(
        slug="groq",
        key_env="GROQ_API_KEY",
        model_env="GROQ_MODEL",
        default_model=DEFAULT_GROQ_MODEL,
        label="Llama via Groq",
        service_name="Groq",
        probe_host="api.groq.com",
    ),
}

_PROVIDER_ALIASES = {
    "gemini": "gemini",
    "google": "gemini",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "groq": "groq",
    "llama": "groq",
}

_NET_CACHE: dict[str, tuple[float, bool]] = {}
_NET_CACHE_TTL_SECONDS = 15.0

_INDICATOR_LABELS: dict[str, tuple[str, str]] = {
    "heart_rate": ("Resting heart rate", "bpm"),
    "systolic_bp": ("Systolic blood pressure", "mmHg"),
    "diastolic_bp": ("Diastolic blood pressure", "mmHg"),
    "oxygen_saturation": ("Oxygen saturation (SpO2)", "%"),
    "temperature": ("Body temperature", "°C"),
    "blood_glucose_mg_dl": ("Blood glucose", "mg/dL"),
    "sleep_hours": ("Sleep duration", "hours"),
    "mood": ("Mood score", "/10"),
    "relaxation": ("Relaxation rating", "/10"),
    "mental_health_assessment": ("Mental wellbeing score", "/100"),
    "game_test_score": ("Alertness reaction score", "/100"),
    "daily_training_hours": ("Daily exercise duration", "hours"),
    "hormones": ("Cortisol hormone index", "PU"),
    "immunity_indicators": ("Immune resilience index", "PU"),
    "bone_health": ("Bone health index", "% of pre-flight mass"),
    "muscle_health": ("Muscle health index", "/100"),
}

_DETAILED_REQUEST_RE = re.compile(
    r"\b(more detail|in detail|detailed|explain more|longer|step by step|everything|full breakdown)\b",
    re.IGNORECASE,
)

# Forbidden clinical diagnosis words that must never appear in patient-facing coaching copy.
_DIAGNOSIS_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhypoglycemia\b", re.IGNORECASE), "lower-than-usual glucose"),
    (re.compile(r"\bhyperglycemia\b", re.IGNORECASE), "elevated glucose"),
    (re.compile(r"\bhypertension\b", re.IGNORECASE), "elevated blood pressure"),
    (re.compile(r"\bdiabetes\b", re.IGNORECASE), "glucose regulation"),
    (re.compile(r"\binsomnia\b", re.IGNORECASE), "difficulty sleeping"),
    (re.compile(r"\bdiagnosis\b|\bdiagnose[sd]?\b", re.IGNORECASE), "clinical assessment"),
    (re.compile(r"\binfection\b", re.IGNORECASE), "immune strain"),
    (re.compile(r"\bdisorder\b", re.IGNORECASE), "pattern"),
    (re.compile(r"\bsick\b|\billness\b", re.IGNORECASE), "under strain"),
)


class OnlineProviderError(RuntimeError):
    """Sanitized upstream LLM failure (never contains secrets)."""

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")


def _sanitize_error_text(exc: Exception, secrets_to_scrub: tuple[str, ...] = ()) -> str:
    msg = str(exc) or exc.__class__.__name__
    for secret in secrets_to_scrub:
        if secret and secret in msg:
            msg = msg.replace(secret, "[REDACTED]")
    msg = re.sub(
        r"(AIza[0-9A-Za-z\-_]{10,}|AQ\.[0-9A-Za-z\-_]{10,}|sk-[0-9A-Za-z\-_]{10,}|gsk_[0-9A-Za-z\-_]{10,})",
        "[REDACTED]",
        msg,
    )
    return msg[:220]


def get_primary_provider() -> str:
    raw = read_env_var("ONLINE_PROVIDER", DEFAULT_ONLINE_PROVIDER).strip().lower()
    return _PROVIDER_ALIASES.get(raw, DEFAULT_ONLINE_PROVIDER)


def get_configured_provider_order() -> list[str]:
    primary = get_primary_provider()
    return [primary] + [p for p in PROVIDER_ORDER if p != primary]


def _get_api_key(provider: str) -> str:
    spec = PROVIDER_SPECS[provider]
    return read_env_var(spec.key_env, "", env_only=True)


def _get_model_name(provider: str) -> str:
    spec = PROVIDER_SPECS[provider]
    return read_env_var(spec.model_env, spec.default_model)


def get_keyed_providers() -> list[str]:
    return [p for p in get_configured_provider_order() if bool(_get_api_key(p))]


def check_internet_reachable(host: str = "1.1.1.1", port: int = 443, timeout: float = 0.8) -> bool:
    """Quick cached TCP check to verify external connectivity without consuming API quota."""
    now = time.monotonic()
    cached = _NET_CACHE.get(host)
    if cached and (now - cached[0]) < _NET_CACHE_TTL_SECONDS:
        return cached[1]
    ok = False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ok = True
    except OSError:
        ok = False
    _NET_CACHE[host] = (now, ok)
    return ok


def get_online_status() -> dict[str, Any]:
    """Return safe public UI status metadata (never reveals keys or secrets)."""
    ordered = get_configured_provider_order()
    keyed = [p for p in ordered if bool(_get_api_key(p))]
    display_provider = keyed[0] if keyed else ordered[0]
    spec = PROVIDER_SPECS[display_provider]

    if not keyed:
        available = False
        reason = "no_key"
    else:
        probe_host = PROVIDER_SPECS[keyed[0]].probe_host
        if check_internet_reachable(host=probe_host):
            available = True
            reason = ""
        else:
            available = False
            reason = "offline"

    return {
        "available": available,
        "reason": reason,
        "active_provider": display_provider,
        "provider_label": spec.label,
        "service_name": spec.service_name,
        "button_label": "Online",
        "unavailable_hint": "Online assistant unavailable",
        "privacy_notice": (
            "Online mode sends your question and a short summary of your health data "
            f"to an external AI service ({spec.service_name})."
        ),
        "configured_providers": keyed,
    }


def load_online_system_prompt() -> str:
    if ONLINE_SYSTEM_PROMPT_PATH.is_file():
        return ONLINE_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return (
        "You are Vitalverse, a calm and caring health assistant for astronauts on a space mission. "
        "You help the astronaut understand their own health data. You are not a doctor and never diagnose."
    )


def _format_pct_diff(val: float | None, base: float | None) -> str:
    if val is None or base is None or abs(base) < 1e-9:
        return "no baseline comparison"
    pct = ((float(val) - float(base)) / float(base)) * 100.0
    if abs(pct) < 0.5:
        return "right around personal baseline"
    direction = "above" if pct > 0 else "below"
    return f"about {abs(pct):.0f}% {direction} baseline"


def build_privacy_safe_summary(con: sqlite3.Connection, astronaut_id: str | None) -> tuple[str, dict[str, Any]]:
    """
    Build a strictly PII-free health summary for external LLM calls.

    Never includes names, IDs, photos, emails, surgeon contact details, or free-text check-in answers.
    """
    if not astronaut_id:
        return (
            "No individual telemetry record is loaded for this session; offer supportive general onboard guidance without inventing numbers.",
            {"status_class": "Unknown", "has_warning_or_danger": False, "first_name": None},
        )

    aid = str(astronaut_id).strip().upper()
    prof = con.execute(
        "SELECT name FROM astronaut_profile WHERE astronaut_id = ?",
        (aid,),
    ).fetchone()
    raw_name = str(prof["name"]).strip() if prof and prof["name"] else ""
    first_name = raw_name.split()[0] if raw_name else None

    card = he.astronaut_card(aid)
    doc = he.earth_doctor_card(aid, last_n_days=1)
    if not card.get("ok") or not doc.get("ok"):
        return (
            "Telemetry summary could not be loaded for today; please be transparent that current measurements are missing.",
            {"status_class": "Unknown", "has_warning_or_danger": False, "first_name": first_name},
        )

    status_class = str(card.get("status_class") or "Normal")
    zones = card.get("zones") or {}
    has_warn_or_danger = (
        status_class in ("Health_Warning", "Medical_Danger_Alert")
        or any(v in ("yellow", "red") for v in zones.values())
    )

    lines = [
        f"Overall status classification: {status_class.replace('_', ' ')}",
        "Body zones: " + ", ".join(f"{z}={s}" for z, s in zones.items()),
        "Latest measurements vs personal pre-mission baseline:",
    ]

    devs = doc.get("baseline_deviations") or {}
    for key, (label, clean_unit) in _INDICATOR_LABELS.items():
        d = devs.get(key)
        if not d or d.get("value") is None:
            continue
        val = d.get("value")
        base = d.get("baseline_mean")
        pct_text = _format_pct_diff(val, base)
        if base is not None:
            lines.append(f"- {label}: {val} {clean_unit} (pre-mission baseline {base} {clean_unit}, {pct_text})".strip())
        else:
            lines.append(f"- {label}: {val} {clean_unit} (pre-mission baseline missing)".strip())

    # Explicitly list any key telemetry indicators with missing values so the LLM does not invent them.
    missing_labels = [
        label for key, (label, _) in _INDICATOR_LABELS.items()
        if key not in devs or devs[key].get("value") is None
    ]
    if missing_labels:
        lines.append("Missing measurements today: " + ", ".join(missing_labels))

    if card.get("active_alerts"):
        alert_areas = ", ".join(str(a.get("area", "")) for a in card["active_alerts"] if a.get("area"))
        if alert_areas:
            lines.append(f"Active alert areas: {alert_areas}")

    meta = {
        "status_class": status_class,
        "has_warning_or_danger": has_warn_or_danger,
        "first_name": first_name,
    }
    return "\n".join(lines), meta


def _extract_gemini_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    candidates = getattr(response, "candidates", None) or []
    parts_out: list[str] = []
    for cand in candidates:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            pt = getattr(part, "text", None)
            if pt:
                parts_out.append(str(pt))
    return "\n".join(parts_out).strip()


def _call_gemini(api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=ONLINE_TIMEOUT_SECONDS * 1000),
    )
    candidate_models = [model]
    if model == DEFAULT_GEMINI_MODEL and GEMINI_BACKUP_MODEL not in candidate_models:
        candidate_models.append(GEMINI_BACKUP_MODEL)

    last_exc: Exception | None = None
    for idx, mname in enumerate(candidate_models):
        use_zero_thinking = "lite" not in mname.lower()
        for thinking_flag in ([True, False] if use_zero_thinking else [False]):
            cfg_kwargs: dict[str, Any] = {
                "system_instruction": system_prompt,
                "max_output_tokens": ONLINE_MAX_OUTPUT_TOKENS,
                "temperature": 0.35,
            }
            if thinking_flag:
                cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            try:
                response = client.models.generate_content(
                    model=mname,
                    contents=user_message,
                    config=types.GenerateContentConfig(**cfg_kwargs),
                )
                txt = _extract_gemini_text(response)
                if txt:
                    return txt
            except Exception as exc:
                last_exc = exc
                err_low = str(exc).lower()
                if thinking_flag and ("invalid_argument" in err_low or "thinking" in err_low):
                    continue
                if idx == 0 and len(candidate_models) > 1:
                    break
                raise
    if last_exc is not None:
        raise last_exc
    return ""


def _call_anthropic(api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=float(ONLINE_TIMEOUT_SECONDS))
    message = client.messages.create(
        model=model,
        max_tokens=ONLINE_MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    chunks: list[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", "") == "text" and getattr(block, "text", None):
            chunks.append(str(block.text))
    return "\n".join(chunks).strip()


def _call_groq(api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    import groq

    client = groq.Groq(api_key=api_key, timeout=float(ONLINE_TIMEOUT_SECONDS))
    completion = client.chat.completions.create(
        model=model,
        max_completion_tokens=ONLINE_MAX_OUTPUT_TOKENS,
        temperature=0.35,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    choices = getattr(completion, "choices", None) or []
    if not choices:
        return ""
    msg = getattr(choices[0], "message", None)
    return str(getattr(msg, "content", "") or "").strip()


def call_provider(provider: str, system_prompt: str, user_message: str) -> tuple[str, str]:
    """Call a single external provider and return (text, model_name)."""
    api_key = _get_api_key(provider)
    if not api_key:
        raise OnlineProviderError(provider, "API key not configured")
    model = _get_model_name(provider)
    caller_map = {
        "gemini": _call_gemini,
        "anthropic": _call_anthropic,
        "groq": _call_groq,
    }
    caller = caller_map[provider]
    try:
        text = caller(api_key, model, system_prompt, user_message)
    except Exception as exc:
        raise OnlineProviderError(provider, _sanitize_error_text(exc, (api_key,))) from exc
    if not text or not text.strip():
        raise OnlineProviderError(provider, "empty response")
    return text.strip(), model


def generate_with_fallback(question: str, telemetry_summary: str) -> dict[str, Any]:
    """
    Try configured primary provider first, then fall back across remaining keyed providers.

    Raises OnlineProviderError("all", ...) when no external provider succeeds.
    """
    keyed = get_keyed_providers()
    if not keyed:
        raise OnlineProviderError("none", "no provider keys configured")

    system_prompt = load_online_system_prompt()
    user_prompt = (
        "Astronaut question:\n"
        f"{question}\n\n"
        "Personal health telemetry & pre-mission baseline summary (values only):\n"
        f"{telemetry_summary}"
    )

    errors: list[str] = []
    for provider in keyed:
        try:
            text, model = call_provider(provider, system_prompt, user_prompt)
            spec = PROVIDER_SPECS[provider]
            return {
                "text": text,
                "provider": provider,
                "provider_label": spec.label,
                "model": model,
                "fallback_providers_tried": errors,
            }
        except OnlineProviderError as exc:
            log.warning("Online AI provider failed (%s): %s", provider, exc.reason)
            errors.append(f"{provider}:{exc.reason}")
            continue

    raise OnlineProviderError("all", "; ".join(errors) if errors else "all providers unavailable")


def _trim_to_sentence(words: list[str]) -> str:
    """Join the kept words and cut back to the last full sentence, so answers never end mid-sentence.

    A numbered step ("2.") does not count as a sentence end. If no sentence end is found in the second half
    of the text, the words are kept and a full stop is added.
    """
    text = " ".join(words).rstrip(",;: ")
    ends = [m.end() for m in re.finditer(r"(?<!\b\d)[.!?](?=\s|$)", text)]
    if ends and ends[-1] >= len(text) * 0.5:
        return text[: ends[-1]].strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def finalize_online_answer(
    raw_text: str,
    *,
    question: str,
    first_name: str | None,
    has_warning_or_danger: bool,
) -> str:
    """Apply local gentle-tone guardrails: no diagnosis terms, optional local first-name greeting, surgeon line, <=120w."""
    text = re.sub(r"\r\n?", "\n", str(raw_text or "").strip())
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    for pat, repl in _DIAGNOSIS_REPLACEMENTS:
        text = pat.sub(repl, text)

    # Inject astronaut's first name strictly locally (never sent to external APIs).
    if first_name and not re.search(rf"\b{re.escape(first_name)}\b", text, re.IGNORECASE):
        if re.match(r"^(thanks|thank you|hi|hello|that sounds|i hear|it sounds)\b", text, re.IGNORECASE):
            m_comma = re.match(r"^([A-Za-z][^,.!?\n]{2,45}),(\s+)", text)
            if m_comma:
                text = f"{m_comma.group(1)}, {first_name},{m_comma.group(2)}{text[m_comma.end():]}"
            elif re.match(r"^[A-Z][^.!?]{2,90}[.!?]", text):
                text = re.sub(
                    r"^([A-Z][^.!?]{2,90})([.!?])",
                    rf"\1, {first_name}\2",
                    text,
                    count=1,
                )
            else:
                text = f"Thanks for checking in, {first_name}. {text}"
        else:
            text = f"Thanks for checking in, {first_name}. {text}"

    surgeon_line = "Please contact your flight surgeon to review these readings together."
    if has_warning_or_danger and "contact your flight surgeon" not in text.lower():
        text = f"{text}\n{surgeon_line}"

    wants_detail = bool(_DETAILED_REQUEST_RE.search(question))
    if not wants_detail:
        words = text.split()
        if len(words) > 120:
            budget = 118
            reserved = surgeon_line if (has_warning_or_danger and surgeon_line.lower() not in " ".join(words[:102]).lower()) else ""
            if reserved:
                r_words = reserved.split()
                trimmed = _trim_to_sentence(words[: max(40, budget - len(r_words) - 1)])
                text = f"{trimmed}\n{reserved}"
            else:
                text = _trim_to_sentence(words[:budget])

    return text.strip()
