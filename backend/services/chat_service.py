"""Hybrid AI Chatbot service wrapping OfflineChatbot and OnlineLLM with RBAC, safety, and rate limits."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.config import ONLINE_RATE_LIMIT_MAX_MESSAGES, ONLINE_RATE_LIMIT_WINDOW_SECONDS
from backend.security import resolve_authorized_astronaut_id
from backend.services import online_llm
from offline_ai_chatbot import OfflineChatbot, _normalize

_PERSONAL_PRONOUNS = re.compile(r"\b(my|mine|i|me|myself|am i|do i|have i|did i)\b", re.IGNORECASE)
_PERSONAL_TOPICS = re.compile(
    r"\b(heart rate|blood pressure|bp|spo2|oxygen|temperature|glucose|sugar|sleep|mood|immune|bone|muscle|"
    r"cortisol|hormone|alert|warning|danger|status|baseline|to ?do|task|profile|weight|height|allerg|"
    r"chest pain|left arm|passed out|fainted|short of breath|confused|confusion|disoriented|dizzy|lightheaded|headache|pain)\b",
    re.IGNORECASE,
)


class ChatService:
    """Thread-safe orchestrator for On-board (offline) and Online AI assistants."""

    def __init__(self) -> None:
        self.bot = OfflineChatbot()

    @staticmethod
    def _check_and_record_rate_limit(con: sqlite3.Connection, rate_key: str) -> bool:
        """Return True if user/client is within 20 online messages per 10 minutes (and record attempt)."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=ONLINE_RATE_LIMIT_WINDOW_SECONDS)).isoformat()
        con.execute("DELETE FROM online_chat_rate_limits WHERE created_at < ?", (cutoff,))
        cnt = int(
            con.execute(
                "SELECT COUNT(*) FROM online_chat_rate_limits WHERE rate_key = ? AND created_at >= ?",
                (rate_key, cutoff),
            ).fetchone()[0]
        )
        if cnt >= ONLINE_RATE_LIMIT_MAX_MESSAGES:
            con.commit()
            return False
        con.execute(
            "INSERT INTO online_chat_rate_limits(rate_key, created_at) VALUES (?, ?)",
            (rate_key, now.isoformat()),
        )
        con.commit()
        return True

    def ask(
        self,
        con: sqlite3.Connection,
        user: dict[str, Any] | None,
        question: str,
        requested_astronaut_id: str | None = None,
        *,
        engine: str = "offline",
        client_id: str = "anonymous",
    ) -> dict[str, Any]:
        """Answer or refuse cleanly, running local safety + scope checks first for both engines."""
        req_engine = "online" if str(engine or "offline").strip().lower() == "online" else "offline"
        q = str(question or "").strip()
        if not q:
            return {
                "ok": False,
                "refused": True,
                "login_required": False,
                "urgent_escalation": False,
                "intent": "refusal",
                "answer": "Please enter a question about your health telemetry, alerts, or countermeasures.",
                "sources": "none",
                "engine_requested": req_engine,
                "engine_used": "offline",
                "engine_provider": "offline",
                "engine_label": "On-board",
                "fallback_notice": None,
                "rate_limited": False,
            }

        target_aid: str | None = None
        astronaut_name: str | None = None
        surgeon_contact: str | None = None

        if user is not None:
            if user["role"] == "astronaut":
                target_aid = user["astronaut_id"]
            elif user["role"] == "doctor":
                candidate = str(requested_astronaut_id or "").strip().upper()
                if not candidate:
                    first = con.execute(
                        "SELECT astronaut_id FROM doctor_astronaut_links WHERE doctor_user_id = ? AND status = 'approved' ORDER BY astronaut_id ASC LIMIT 1",
                        (int(user["user_id"]),),
                    ).fetchone()
                    if first is None:
                        return {
                            "ok": True,
                            "refused": True,
                            "login_required": False,
                            "urgent_escalation": False,
                            "intent": "refusal",
                            "answer": "No approved astronaut links exist for your doctor account yet.",
                            "sources": "doctor_astronaut_links",
                            "engine_requested": req_engine,
                            "engine_used": "offline",
                            "engine_provider": "offline",
                            "engine_label": "On-board",
                            "fallback_notice": None,
                            "rate_limited": False,
                        }
                    candidate = first["astronaut_id"]
                target_aid = resolve_authorized_astronaut_id(con, user, candidate)

            prof = con.execute(
                "SELECT name, contact_flight_surgeon FROM astronaut_profile WHERE astronaut_id = ?",
                (target_aid,),
            ).fetchone()
            if prof:
                astronaut_name = prof["name"]
                surgeon_contact = prof["contact_flight_surgeon"]
            offline_res = self.bot.ask(target_aid, q)
        else:
            norm_q = _normalize(q)
            if self.bot.is_urgent_symptom(q, norm_q):
                return {
                    "ok": True,
                    "refused": False,
                    "login_required": False,
                    "urgent_escalation": True,
                    "intent": "alerts",
                    "confidence": 1.0,
                    "answer": (
                        "URGENT ESCALATION: Contact the flight surgeon immediately — please contact your flight surgeon now "
                        "(Ground Medical Control). Stop current exertion and start real-time ground telemetry review.\n"
                        "Please sign in with your crew account if you also want to view active onboard alerts."
                    ),
                    "sources": "urgent_symptom_escalation",
                    "did_you_mean": None,
                    "flight_surgeon_contact": "Flight Surgeon Desk (Ground Control)",
                    "engine_requested": req_engine,
                    "engine_used": "offline",
                    "engine_provider": "offline",
                    "engine_label": "On-board",
                    "fallback_notice": None,
                    "rate_limited": False,
                }

            probe = self.bot.ask("A001", q)
            if probe.get("refused") and probe.get("refusal_kind") == "scope" and req_engine == "online":
                offline_res = probe                       # general question: the online assistant answers it below
            elif probe.get("refused"):
                offline_res = probe
            elif _PERSONAL_PRONOUNS.search(q) or _PERSONAL_TOPICS.search(q):
                return {
                    "ok": True,
                    "refused": False,
                    "login_required": True,
                    "urgent_escalation": False,
                    "intent": "login_required",
                    "confidence": 1.0,
                    "answer": "Sign in to your astronaut or approved doctor account so I can answer using your real mission telemetry and pre-flight baseline.",
                    "sources": "authentication",
                    "did_you_mean": None,
                    "engine_requested": req_engine,
                    "engine_used": "offline",
                    "engine_provider": "offline",
                    "engine_label": "On-board",
                    "fallback_notice": None,
                    "rate_limited": False,
                }
            else:
                offline_res = probe

        base_payload: dict[str, Any] = {
            "ok": True,
            "astronaut_id": target_aid,
            "astronaut_name": astronaut_name,
            "flight_surgeon_contact": surgeon_contact,
            "login_required": False,
            **offline_res,
            "engine_requested": req_engine,
            "engine_used": "offline",
            "engine_provider": "offline",
            "engine_label": "On-board",
            "fallback_notice": None,
            "rate_limited": False,
        }

        # The SAFETY gate blocks both engines before any external API call: urgent symptoms are escalated
        # locally, and invented data / medication / diagnosis / other astronauts' records are refused.
        # The offline SCOPE gate only means "no offline template for this"; in online mode those questions
        # go to the online assistant, whose system prompt still declines topics unrelated to health.
        offline_scope_only = bool(offline_res.get("refused")) and offline_res.get("refusal_kind") == "scope"
        if (
            req_engine != "online"
            or offline_res.get("urgent_escalation")
            or (offline_res.get("refused") and not offline_scope_only)
        ):
            return base_payload

        rate_key = f"user:{int(user['user_id'])}" if user is not None else f"guest:{client_id}"
        if not self._check_and_record_rate_limit(con, rate_key):
            return {
                **base_payload,
                "rate_limited": True,
                "fallback_notice": (
                    f"You have reached the {ONLINE_RATE_LIMIT_MAX_MESSAGES}-message limit for the online assistant "
                    "in a 10-minute window. Answered by the on-board assistant below."
                ),
            }

        summary_text, meta = online_llm.build_privacy_safe_summary(con, target_aid)
        try:
            llm_out = online_llm.generate_with_fallback(q, summary_text)
        except online_llm.OnlineProviderError:
            return {
                **base_payload,
                "fallback_notice": (
                    "Online unavailable, and the on-board assistant cannot answer this question."
                    if offline_scope_only else
                    "Online unavailable, answered by the on-board assistant."
                ),
            }

        online_answer = online_llm.finalize_online_answer(
            llm_out["text"],
            question=q,
            first_name=meta.get("first_name"),
            has_warning_or_danger=bool(meta.get("has_warning_or_danger")),
        )
        return {
            **base_payload,
            "refused": False,
            "intent": "online_general" if offline_scope_only else base_payload.get("intent"),
            "did_you_mean": None,
            "answer": online_answer,
            "sources": f"{llm_out['provider_label']} ({llm_out['model']}) + PII-free mission telemetry summary",
            "engine_used": "online",
            "engine_provider": llm_out["provider"],
            "engine_label": llm_out["provider_label"],
            "model": llm_out["model"],
            "fallback_notice": None,
        }
