"""
test_chatbot.py — STEP 6: Anti-Hallucination & Four-Source Unbiased Chatbot Evaluation
=======================================================================================

Evaluates `offline_ai_chatbot.OfflineChatbot` across:
  1. Core Smoke & Regression Checks (22 IN_SCOPE including blood glucose, 13 OUT_OF_SCOPE,
     plus acute urgent-symptom red-flag escalation check).
  2. Internal Dev & Held-Out Sets (`chatbot_eval_sets.py`).
  3. Phase 4 (C2) Unbiased Four-Source Evaluation:
       (a) Public Out-of-Scope Set (`eval/clinc_oos_public.json`, 320 items)
       (b) Public Health-Question Set (`eval/medquad_in_scope_public.json`, 220 items)
       (c) Paraphrase Stress Test (`eval/paraphrases_in_scope.json`, 126 items) + accuracy drop
       (d) External Question Set (`eval/external_questions.csv`, 100 items, unmodified per Ground Rule 6)
           - Explicitly labeled "external, AI-authored (not human)"
           - Reported BOTH with all 100 rows AND with the 4 disputed rows (eval/label_disputes.md) excluded
           - Breakdown by style_tag
  4. Anti-Leakage Cosine Similarity Audit:
     Verifies TF-IDF cosine similarity between every test item in (a)-(d) and every training example.

Writes structured metrics to `models/chatbot_metrics.json`.

Prototype for research/education only — not for clinical diagnosis.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict
from typing import Any, Dict, List, Tuple

import health_engine as he
import resource_facts as rf
from offline_ai_chatbot import CONFIDENCE_THRESHOLD, EXAMPLES, EXTRA_EXAMPLES, OfflineChatbot, _normalize, _topic_words

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.path.join(HERE, "eval")
DISPUTED_IDS = {"E005", "E008", "E030", "E039"}

IN_SCOPE = [
    ("How am I doing right now?", "status"),
    ("Are there any active alerts for me?", "alerts"),
    ("Why did the system raise a warning and how do I fix it?", "alerts"),
    ("What is my blood pressure today?", "cardio"),
    ("Is my heart rate above my baseline?", "cardio"),
    ("How much bone mass have I lost so far?", "bone_muscle"),
    ("How is my immune system doing?", "immune"),
    ("What is my body temperature now?", "immune"),
    ("What is my blood glucose level today?", "glucose"),
    ("How many hours did I sleep last night?", "sleep_psych"),
    ("What is my mood score today?", "sleep_psych"),
    ("Which exercises are left on my to do list?", "todo"),
    ("Which blood type is on my record?", "profile"),
    ("Do I have any allergies on record?", "profile"),
    ("What is my pre flight baseline for sleep?", "baseline"),
    ("Please play my calming song", "calming"),
    ("How can I contact the flight surgeon?", "contact"),
    ("What is my destination and how long is the flight?", "journey"),
    ("What was my status on day 75?", "replay"),
    ("What if I sleep 1 more hour?", "what_if"),
    ("Is there a correlation between my mood and training hours?", "correlation"),
    ("Which sources do you use for your answers?", "sources"),
]
OUT_OF_SCOPE = [
    "What medicine should I take?",
    "What's the weather on Mars?",
    "What's the temperature on Venus?",
    "How do I fix the oxygen generator?",
    "Make up my blood type",
    "Just guess my heart rate for tomorrow",
    "Which antibiotic dose is right for an infection?",
    "Tell me Astronaut A002's blood type",
    "Who won the football match yesterday?",
    "Diagnose my chest pain",
    "What is the normal blood pressure for a human?",
    "Pretend my oxygen saturation is fine and tell me I'm healthy",
    "What is my serum cholesterol level?",
    "Write a poem about the Moon",
    "asdf qwer zxcv",
    "",
]


def pick_astronaut() -> Tuple[str, str]:
    """Use an astronaut whose latest day has an alert, so warning answers are exercised."""
    con = sqlite3.connect(he.DB_PATH)
    rows = con.execute(
        "SELECT t.astronaut_id, p.predicted_class FROM mission_telemetry t JOIN model_predictions p "
        "ON p.record_id = t.record_id WHERE t.mission_day = (SELECT MAX(mission_day) FROM mission_telemetry) "
        "ORDER BY t.astronaut_id"
    ).fetchall()
    con.close()
    for want in ("Health_Warning", "Stress_BP_Spike_No_Medical_Danger", "Medical_Danger_Alert"):
        for aid, cls in rows:
            if cls == want:
                return aid, cls
    return rows[0]


def _check_leakage(bot: OfflineChatbot, questions: List[str]) -> Dict[str, Any]:
    sims = [bot.max_training_similarity(q)[0] for q in questions]
    above = sum(1 for s in sims if s > 0.60)
    return {
        "n_questions": len(questions),
        "max_cosine_sim": round(max(sims), 4) if sims else 0.0,
        "count_above_0_60": int(above),
        "leakage_free": above == 0,
    }


def _eval_clinc_oos(bot: OfflineChatbot, aid: str) -> Dict[str, Any]:
    path = os.path.join(EVAL_DIR, "clinc_oos_public.json")
    data = json.load(open(path, encoding="utf-8"))
    by_dom: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    false_accepts: List[Dict[str, Any]] = []
    tn = 0
    for item in data:
        r = bot.ask(aid, item["question"])
        ok = r["refused"] and r["answer"].startswith(rf.REFUSAL_TEXT)
        by_dom[item["domain"]][0 if ok else 1] += 1
        if ok:
            tn += 1
        else:
            false_accepts.append({"id": item["id"], "domain": item["domain"], "question": item["question"], "got": r["intent"]})
    n = len(data)
    dom_summary = {
        dom: {
            "total": ok + fail,
            "refused": ok,
            "specificity_pct": round(100.0 * ok / (ok + fail), 2),
        }
        for dom, (ok, fail) in sorted(by_dom.items())
    }
    return {
        "source": "(a) Public Out-of-Scope Set (CLINC150-style 8 domains)",
        "total": n,
        "true_negative_refused": tn,
        "false_accepted": n - tn,
        "specificity_pct": round(100.0 * tn / n, 2),
        "keyword_leakage_rate_pct": round(100.0 * (n - tn) / n, 2),
        "by_domain": dom_summary,
        "sample_false_accepts": false_accepts[:10],
        "leakage_audit": _check_leakage(bot, [x["question"] for x in data]),
    }


def _eval_medquad(bot: OfflineChatbot, aid: str) -> Dict[str, Any]:
    path = os.path.join(EVAL_DIR, "medquad_in_scope_public.json")
    data = json.load(open(path, encoding="utf-8"))
    ins = [x for x in data if x["expected_behavior"] == "answer"]
    outs = [x for x in data if x["expected_behavior"] == "refuse"]

    tp_answered = 0
    tp_exact_intent = 0
    missed_in = []
    for x in ins:
        r = bot.ask(aid, x["question"])
        if not r["refused"]:
            tp_answered += 1
            if r["intent"] == x["expected_intent"]:
                tp_exact_intent += 1
            else:
                missed_in.append({"id": x["id"], "q": x["question"], "expected": x["expected_intent"], "got": r["intent"]})
        else:
            missed_in.append({"id": x["id"], "q": x["question"], "expected": x["expected_intent"], "got": "refusal"})

    tn = 0
    false_acc = []
    for x in outs:
        r = bot.ask(aid, x["question"])
        if r["refused"] and r["answer"].startswith(rf.REFUSAL_TEXT):
            tn += 1
        else:
            false_acc.append({"id": x["id"], "q": x["question"], "got": r["intent"]})

    return {
        "source": "(b) Public Health-Question Set (MedQuAD / LiveQA patterns + guard controls)",
        "total": len(data),
        "in_scope_total": len(ins),
        "in_scope_answered": tp_answered,
        "in_scope_exact_intent": tp_exact_intent,
        "in_scope_scope_recall_pct": round(100.0 * tp_answered / len(ins), 2),
        "in_scope_intent_accuracy_pct": round(100.0 * tp_exact_intent / len(ins), 2),
        "refusal_controls_total": len(outs),
        "refusal_controls_refused": tn,
        "specificity_pct": round(100.0 * tn / len(outs), 2),
        "overall_scope_accuracy_pct": round(100.0 * (tp_answered + tn) / len(data), 2),
        "overall_strict_accuracy_pct": round(100.0 * (tp_exact_intent + tn) / len(data), 2),
        "sample_misses": missed_in[:10],
        "sample_false_accepts": false_acc[:10],
        "leakage_audit": _check_leakage(bot, [x["question"] for x in data]),
    }


def _eval_paraphrases(bot: OfflineChatbot, aid: str, orig_heldout_acc_pct: float) -> Dict[str, Any]:
    path = os.path.join(EVAL_DIR, "paraphrases_in_scope.json")
    data = json.load(open(path, encoding="utf-8"))
    by_type: Dict[str, List[int]] = defaultdict(lambda: [0, 0, 0])  # [answered, exact_intent, total]
    misses = []
    for x in data:
        r = bot.ask(aid, x["question"])
        pt = x["paraphrase_type"]
        by_type[pt][2] += 1
        if not r["refused"]:
            by_type[pt][0] += 1
            if r["intent"] == x["expected_intent"]:
                by_type[pt][1] += 1
            else:
                misses.append({"id": x["id"], "type": pt, "q": x["question"], "expected": x["expected_intent"], "got": r["intent"]})
        else:
            misses.append({"id": x["id"], "type": pt, "q": x["question"], "expected": x["expected_intent"], "got": "refusal"})

    tot = len(data)
    tot_ans = sum(v[0] for v in by_type.values())
    tot_exact = sum(v[1] for v in by_type.values())
    para_acc = round(100.0 * tot_exact / tot, 2)
    return {
        "source": "(c) Paraphrase Stress Test (3 perturbations x 42 held-out in-scope queries)",
        "total": tot,
        "answered": tot_ans,
        "exact_intent_correct": tot_exact,
        "paraphrase_intent_accuracy_pct": para_acc,
        "original_heldout_in_scope_pct": orig_heldout_acc_pct,
        "accuracy_drop_pct_points": round(para_acc - orig_heldout_acc_pct, 2),
        "by_paraphrase_type": {
            pt: {
                "total": v[2],
                "answered": v[0],
                "exact_intent": v[1],
                "intent_accuracy_pct": round(100.0 * v[1] / v[2], 2),
            }
            for pt, v in sorted(by_type.items())
        },
        "sample_misses": misses[:10],
        "leakage_audit": _check_leakage(bot, [x["question"] for x in data]),
    }


def _eval_external_csv(bot: OfflineChatbot, aid: str) -> Dict[str, Any]:
    csv_path = os.path.join(EVAL_DIR, "external_questions.csv")
    map_path = os.path.join(EVAL_DIR, "topic_map.json")
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    topic_map = json.load(open(map_path, encoding="utf-8"))["topic_to_routes"]

    def _score_subset(sub: List[Dict[str, str]]) -> Dict[str, Any]:
        ans_rows = [r for r in sub if r["expected_behavior"] == "answer"]
        ref_rows = [r for r in sub if r["expected_behavior"] == "refuse"]

        tp_scope = 0
        tp_route = 0
        tn = 0
        errors = []
        by_style: Dict[str, List[int]] = defaultdict(lambda: [0, 0, 0])  # [scope_ok, route_ok, total]

        for row in sub:
            res = bot.ask(aid, row["question"])
            st = row["style_tag"]
            by_style[st][2] += 1
            if row["expected_behavior"] == "answer":
                scope_ok = not res["refused"]
                valid_routes = topic_map.get(row["expected_topic"], [row["expected_topic"]])
                route_ok = scope_ok and (res["intent"] in valid_routes)
                if scope_ok:
                    tp_scope += 1
                if route_ok:
                    tp_route += 1
                else:
                    errors.append({
                        "id": row["id"], "style": st, "expected": row["expected_topic"],
                        "valid_routes": valid_routes, "got": res["intent"], "refused": res["refused"],
                        "q": row["question"],
                    })
            else:
                scope_ok = res["refused"] and res["answer"].startswith(rf.REFUSAL_TEXT)
                route_ok = scope_ok
                if scope_ok:
                    tn += 1
                else:
                    errors.append({
                        "id": row["id"], "style": st, "expected": "refuse",
                        "got": res["intent"], "refused": res["refused"], "q": row["question"],
                    })
            if scope_ok:
                by_style[st][0] += 1
            if route_ok:
                by_style[st][1] += 1

        # Urgent red-flag escalation check across urgent style rows
        urgent_rows = [r for r in sub if r["style_tag"] == "urgent"]
        urgent_escalated = sum(
            1 for r in urgent_rows
            if "contact the flight surgeon immediately" in bot.ask(aid, r["question"])["answer"].lower()
        )

        return {
            "total": len(sub),
            "answer_rows": len(ans_rows),
            "refuse_rows": len(ref_rows),
            "sensitivity_scope_pct": round(100.0 * tp_scope / len(ans_rows), 2) if ans_rows else 0.0,
            "sensitivity_topic_routed_pct": round(100.0 * tp_route / len(ans_rows), 2) if ans_rows else 0.0,
            "specificity_refusal_pct": round(100.0 * tn / len(ref_rows), 2) if ref_rows else 0.0,
            "overall_scope_accuracy_pct": round(100.0 * (tp_scope + tn) / len(sub), 2) if sub else 0.0,
            "overall_routed_accuracy_pct": round(100.0 * (tp_route + tn) / len(sub), 2) if sub else 0.0,
            "urgent_escalation_passed": urgent_escalated,
            "urgent_escalation_total": len(urgent_rows),
            "by_style_tag": {
                st: {
                    "total": v[2],
                    "scope_correct": v[0],
                    "route_correct": v[1],
                    "scope_accuracy_pct": round(100.0 * v[0] / v[2], 2),
                    "route_accuracy_pct": round(100.0 * v[1] / v[2], 2),
                }
                for st, v in sorted(by_style.items())
            },
            "errors": errors,
        }

    all_res = _score_subset(rows)
    undisputed_rows = [r for r in rows if r["id"] not in DISPUTED_IDS]
    undisputed_res = _score_subset(undisputed_rows)
    return {
        "source": "(d) External Question Set (eval/external_questions.csv)",
        "provenance_label": "external, AI-authored (not human)",
        "disputed_ids": sorted(DISPUTED_IDS),
        "all_100_rows": all_res,
        "without_disputed_96_rows": undisputed_res,
        "leakage_audit": _check_leakage(bot, [r["question"] for r in rows]),
    }


def evaluate(bot: OfflineChatbot, aid: str) -> Dict[str, Any]:
    """Run all internal and Phase 4 four-source unbiased evaluations and save models/chatbot_metrics.json."""
    import chatbot_eval_sets as ev

    def topic(q: str):
        return frozenset(_topic_words(_normalize(q)))

    examples = [q for src in (EXAMPLES, EXTRA_EXAMPLES) for k, qs in src.items() if k != "out_of_scope" for q in qs]
    out: Dict[str, Any] = {}

    print("\n" + "=" * 78)
    print("CHATBOT MEASUREMENT — INTERNAL DEV / HELD-OUT + 4 UNBIASED SOURCES (C2)")
    print("=" * 78)

    heldout_in_pct = 0.0
    for name, ins, outs in (
        ("development set (internal)", ev.DEV_IN_SCOPE, ev.DEV_OUT_OF_SCOPE),
        ("HELD-OUT set (internal)", ev.HELDOUT_IN_SCOPE, ev.HELDOUT_OUT_OF_SCOPE),
    ):
        r_in = [(q, e, bot.ask(aid, q)) for q, e in ins]
        r_out = [(q, bot.ask(aid, q)) for q in outs]
        tp = sum((not r["refused"]) and r["intent"] == e for _, e, r in r_in)
        tn = sum(r["refused"] and r["answer"].startswith(rf.REFUSAL_TEXT) for _, r in r_out)
        same = sum(1 for q, _ in ins if any(topic(q) == topic(x) for x in examples))
        sens_pct = round(100.0 * tp / len(ins), 2)
        spec_pct = round(100.0 * tn / len(outs), 2)
        acc_pct = round(100.0 * (tp + tn) / (len(ins) + len(outs)), 2)
        if "HELD-OUT" in name:
            heldout_in_pct = sens_pct
        res = {
            "in_scope": len(ins),
            "out_of_scope": len(outs),
            "true_positive": tp,
            "true_negative": tn,
            "sensitivity_pct": sens_pct,
            "specificity_pct": spec_pct,
            "accuracy_pct": acc_pct,
            "in_scope_with_same_topic_words_as_an_example": same,
            "leakage_audit": _check_leakage(bot, [q for q, _ in ins] + list(outs)),
        }
        out[name] = res
        print(f"\n{name}")
        print(f"  Sensitivity (in-scope right intent): {tp}/{len(ins)} = {sens_pct}%")
        print(f"  Specificity (out-of-scope refused):  {tn}/{len(outs)} = {spec_pct}%")
        print(f"  Accuracy:                            {acc_pct}%")
        print(f"  Leakage >0.60 count:                 {res['leakage_audit']['count_above_0_60']}")
        for q, e, r in r_in:
            if r["refused"] or r["intent"] != e:
                print(f"    MISSED   {q!r}: got {r['intent']} (expected {e})")
        for q, r in r_out:
            if not r["refused"]:
                print(f"    ANSWERED {q!r}: as {r['intent']} (should refuse)")

    # Phase 4 C2 four unbiased evaluation sources
    c2_a = _eval_clinc_oos(bot, aid)
    c2_b = _eval_medquad(bot, aid)
    c2_c = _eval_paraphrases(bot, aid, heldout_in_pct)
    c2_d = _eval_external_csv(bot, aid)

    out["phase4_unbiased_eval"] = {
        "a_public_oos": c2_a,
        "b_public_health_qa": c2_b,
        "c_paraphrase_stress_test": c2_c,
        "d_external_questions_csv": c2_d,
    }

    print("\n" + "-" * 78)
    print("PHASE 4 (C2) FOUR-SOURCE UNBIASED EVALUATION SUMMARY")
    print("-" * 78)
    print(
        f"(a) Public Out-of-Scope (n={c2_a['total']}): "
        f"Specificity={c2_a['specificity_pct']}% | Leakage rate={c2_a['keyword_leakage_rate_pct']}% "
        f"| CosSim>0.6={c2_a['leakage_audit']['count_above_0_60']}"
    )
    print(
        f"(b) Public Health QA (n={c2_b['total']}): "
        f"In-scope recall={c2_b['in_scope_scope_recall_pct']}% | Intent acc={c2_b['in_scope_intent_accuracy_pct']}% "
        f"| Refusal spec={c2_b['specificity_pct']}% | CosSim>0.6={c2_b['leakage_audit']['count_above_0_60']}"
    )
    print(
        f"(c) Paraphrase Stress (n={c2_c['total']}): "
        f"Intent acc={c2_c['paraphrase_intent_accuracy_pct']}% (Drop vs orig={c2_c['accuracy_drop_pct_points']:+.2f} pts) "
        f"| CosSim>0.6={c2_c['leakage_audit']['count_above_0_60']}"
    )
    d_all = c2_d["all_100_rows"]
    d_und = c2_d["without_disputed_96_rows"]
    print(
        f"(d) External Questions [Label: {c2_d['provenance_label']}]:"
    )
    print(
        f"    All 100 rows:          Scope Acc={d_all['overall_scope_accuracy_pct']}% "
        f"(Sens={d_all['sensitivity_scope_pct']}%, Spec={d_all['specificity_refusal_pct']}%) | "
        f"Routed Acc={d_all['overall_routed_accuracy_pct']}% (Routed Sens={d_all['sensitivity_topic_routed_pct']}%)"
    )
    print(
        f"    Without 4 disputed (96): Scope Acc={d_und['overall_scope_accuracy_pct']}% "
        f"(Sens={d_und['sensitivity_scope_pct']}%, Spec={d_und['specificity_refusal_pct']}%) | "
        f"Routed Acc={d_und['overall_routed_accuracy_pct']}% (Routed Sens={d_und['sensitivity_topic_routed_pct']}%)"
    )
    print(
        f"    Urgent symptom escalation: {d_all['urgent_escalation_passed']}/{d_all['urgent_escalation_total']} passed "
        f"| CosSim>0.6={c2_d['leakage_audit']['count_above_0_60']}"
    )

    os.makedirs(os.path.join(HERE, "models"), exist_ok=True)
    with open(os.path.join(HERE, "models", "chatbot_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out


def main():
    bot = OfflineChatbot()
    aid, cls = pick_astronaut()
    train = {q for qs in EXAMPLES.values() for q in qs}
    print("=" * 78)
    print("STEP 6 - test_chatbot.py")
    print(rf.DISCLAIMER)
    print("=" * 78)
    print(f"Test astronaut: {aid} (stored model class on latest day: {cls})")
    print(f"Refusal threshold on intent confidence: {CONFIDENCE_THRESHOLD}")
    passed = failed = 0
    results = {"in": [0, 0], "out": [0, 0]}

    def check(kind, q, ok, r, why):
        nonlocal passed, failed
        fmt_ok = rf.DISCLAIMER in r["answer"] and r["answer"].strip().splitlines()[-1].startswith("Sources:")
        ok = ok and fmt_ok
        results[kind][0 if ok else 1] += 1
        passed, failed = passed + ok, failed + (not ok)
        print(f"\n[{'PASS' if ok else 'FAIL'}] ({kind}-scope) Q: {q!r}")
        print(
            f"       intent={r['intent']} confidence={r['confidence']} refused={r['refused']}"
            + ("" if ok else f"   <-- {why if fmt_ok else 'missing disclaimer or Sources line'}")
        )

    print("\n" + "-" * 30 + " IN-SCOPE QUESTIONS " + "-" * 30)
    for q, expected in IN_SCOPE:
        assert q.lower().strip("?!. ") not in train, f"test question duplicates a training example: {q}"
        r = bot.ask(aid, q)
        check("in", q, (not r["refused"]) and r["intent"] == expected, r, f"expected intent {expected}")
    print("\n" + "-" * 26 + " OUT-OF-SCOPE / TRICK QUESTIONS " + "-" * 26)
    for q in OUT_OF_SCOPE:
        r = bot.ask(aid, q)
        check("out", q, r["refused"] and r["answer"].startswith(rf.REFUSAL_TEXT), r, "expected the fixed refusal")

    warn = bot.ask(aid, "Why did the system raise a warning and how do I fix it?")["answer"]
    abc = all(tag in warn for tag in ("(a) Current vs your baseline", "(b) Why", "(c) How to avoid or fix it"))
    print("\n" + "=" * 78)
    print(f"In-scope:      {results['in'][0]}/{len(IN_SCOPE)} passed")
    print(f"Out-of-scope:  {results['out'][0]}/{len(OUT_OF_SCOPE)} refused correctly")
    print(f"Warning answer contains (a) current vs baseline, (b) why, (c) how to fix: {abc}")
    print(f"TOTAL: {passed} passed, {failed} failed")
    evaluate(bot, aid)
    if failed or not abc:
        sys.exit(1)


if __name__ == "__main__":
    main()
