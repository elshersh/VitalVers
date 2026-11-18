"""
Phase 4 Unit Tests — Chatbot Scope Gate, Borderline Suggestions, Urgent Symptom Escalation,
RBAC Integration, and Anti-Leakage Cosine Similarity Audit
=============================================================================================
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import health_engine as he
import resource_facts as rf
from offline_ai_chatbot import OfflineChatbot

EVAL_DIR = ROOT / "eval"


@pytest.fixture(scope="module")
def bot():
    return OfflineChatbot()


def test_scope_gate_venus_and_oxygen_generator_vs_personal_telemetry(bot):
    """
    Phase 4 C1: Verify polysemous keywords pass for personal telemetry and fail for
    external planetary / spacecraft hardware contexts, with borderline 'Did you mean...?' suggestions.
    """
    # Must refuse
    for oos_q in (
        "What's the temperature on Venus?",
        "How do I fix the oxygen generator?",
    ):
        res = bot.ask("A001", oos_q)
        assert res["refused"] is True, f"Expected refusal for {oos_q!r}"
        assert res["answer"].startswith(rf.REFUSAL_TEXT)
        assert "Did you mean:" in res["answer"], f"Expected borderline suggestion for {oos_q!r}"

    # Must answer
    temp_ok = bot.ask("A001", "my temperature feels high")
    assert temp_ok["refused"] is False, f"Expected answer for personal temperature, got {temp_ok}"
    assert temp_ok["intent"] == "immune"

    spo2_ok = bot.ask("A001", "my oxygen saturation says 92%")
    assert spo2_ok["refused"] is False, f"Expected answer for personal SpO2, got {spo2_ok}"
    assert spo2_ok["intent"] == "cardio"


def test_urgent_symptom_escalation_always_advises_flight_surgeon(bot):
    """
    Phase 4 C1: Questions describing acute red-flag symptoms (chest pain, arm numbness,
    fainting, severe shortness of breath) must always advise contacting the flight surgeon immediately.
    """
    urgent_queries = [
        "chest pain and my left arm feels numb",
        "I passed out briefly during exercise",
        "I feel severe shortness of breath right now",
        "my oxygen levels feel low and I'm lightheaded",
        "I got a headache and my BP is up, is this an emergency?",
    ]
    for q in urgent_queries:
        res = bot.ask("A001", q)
        assert res["refused"] is False, f"Urgent query should be handled, not refused: {q!r}"
        assert "contact the flight surgeon immediately" in res["answer"].lower(), (
            f"Missing immediate flight surgeon escalation for {q!r}"
        )


def test_eval_leakage_cosine_similarity_below_threshold(bot):
    """
    Phase 4 C2: Verify no test question in (a)-(d) has TF-IDF cosine similarity > 0.60
    with any chatbot training example.
    """
    datasets = []
    for fname in ("clinc_oos_public.json", "medquad_in_scope_public.json", "paraphrases_in_scope.json"):
        p = EVAL_DIR / fname
        assert p.exists(), f"Missing dataset: {p}"
        for row in json.loads(p.read_text(encoding="utf-8")):
            datasets.append((fname, row["id"], row["question"]))

    with open(EVAL_DIR / "external_questions.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            datasets.append(("external_questions.csv", row["id"], row["question"]))

    leaks = []
    for src, qid, q in datasets:
        sim, nearest = bot.max_training_similarity(q)
        if sim > 0.60:
            leaks.append((src, qid, sim, q, nearest))

    assert not leaks, f"Found {len(leaks)} leaked eval items (>0.60 cosine sim): {leaks[:5]}"


def test_chatbot_rbac_session_token_enforcement(bot):
    """Verify chatbot ask() respects Phase 1 D2 RBAC tokens when supplied."""
    with open(he.AUTH_CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    a001_pin = cfg["astronaut_credential_rule"]["overrides"]["A001"]
    res_astro = he.login("A001", a001_pin)
    assert res_astro["ok"] is True
    tok = res_astro["session_token"]

    own = bot.ask("A001", "What is my blood pressure today?", session_token=tok)
    assert own["refused"] is False

    other = bot.ask("A002", "What is my blood pressure today?", session_token=tok)
    assert other["refused"] is True
    assert (
        "unauthorized" in other["sources"].lower()
        or "forbidden" in other["sources"].lower()
        or "access" in other["sources"].lower()
        or "own" in other["sources"].lower()
    )
