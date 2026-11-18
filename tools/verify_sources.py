"""
tools/verify_sources.py — Automated source and quote verifier (Phase 2 Step 3 & Phase 5 D4).

Fails the build (exits with code 1) if any non-UNVERIFIED entry in:
  - data_raw/team_supplied/07_health_indicators_schema.json (indicators, threshold_details, summary_02_04_verified_claims)
  - resource_facts.py (INDICATORS, FIXED_LIMITS, COUNTERMEASURES)
violates any of the following rules:
  1. verification_status is not in the 5 allowed values.
  2. source_document is missing or does not exist inside references/.
  3. exact_quote is empty or exceeds 25 words.
  4. exact_quote does not appear in references/<source_document> with fuzzy match >= 90%.
  5. reviewer_status is populated without reviewer_role / review_date / decision.
"""
import difflib
import json
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ALLOWED_STATUSES = {
    "VERIFIED_AGAINST_PUBLISHED_STANDARD",
    "ADJUSTED_TO_PUBLISHED_STANDARD",
    "TERRESTRIAL_REFERENCE",
    "PLACEHOLDER_SCALE",
    "UNVERIFIED",
}


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def best_fuzzy_match_ratio(quote: str, document_text: str) -> float:
    """Return the best fuzzy match ratio (0.0 to 1.0) of quote within document_text."""
    q_norm = _normalize_whitespace(quote).lower()
    d_norm = _normalize_whitespace(document_text).lower()
    if not q_norm or not d_norm:
        return 0.0
    if q_norm in d_norm:
        return 1.0

    q_words = q_norm.split()
    d_words = d_norm.split()
    n = len(q_words)
    if n == 0 or not d_words:
        return 0.0

    best = 0.0
    for window_len in sorted({max(1, n - 2), max(1, n - 1), n, n + 1, n + 2}):
        if window_len > len(d_words):
            r = difflib.SequenceMatcher(None, q_norm, d_norm).ratio()
            if r > best:
                best = r
            continue
        for i in range(0, len(d_words) - window_len + 1):
            candidate = " ".join(d_words[i : i + window_len])
            r = difflib.SequenceMatcher(None, q_norm, candidate).ratio()
            if r > best:
                best = r
                if best >= 0.99:
                    return best
    return best


def verify_entry(
    entry_id: str,
    entry: Dict[str, Any],
    references_dir: str,
    ref_cache: Dict[str, str],
    max_quote_words: int = 25,
    min_fuzzy_ratio: float = 0.90,
) -> List[str]:
    """Validate a single entry and return a list of error messages (empty if valid)."""
    errors: List[str] = []
    status = entry.get("verification_status")
    if status not in ALLOWED_STATUSES:
        errors.append(f"[{entry_id}] Invalid verification_status={status!r}; must be one of {sorted(ALLOWED_STATUSES)}")
        return errors

    if status == "UNVERIFIED":
        return errors

    if status == "ADJUSTED_TO_PUBLISHED_STANDARD" and "old_value" not in entry:
        errors.append(f"[{entry_id}] ADJUSTED_TO_PUBLISHED_STANDARD requires 'old_value' to be recorded.")

    src_doc = (entry.get("source_document") or "").strip()
    if not src_doc:
        errors.append(f"[{entry_id}] Non-UNVERIFIED entry ({status}) is missing 'source_document'.")
        return errors

    src_path = os.path.join(references_dir, src_doc)
    if not os.path.isfile(src_path):
        errors.append(f"[{entry_id}] Referenced file 'references/{src_doc}' does not exist.")
        return errors

    if src_doc not in ref_cache:
        with open(src_path, encoding="utf-8") as f:
            ref_cache[src_doc] = f.read()

    quote = _normalize_whitespace(entry.get("exact_quote") or "")
    if not quote:
        errors.append(f"[{entry_id}] Non-UNVERIFIED entry ({status}) has an empty 'exact_quote'.")
        return errors

    word_count = len(quote.split())
    if word_count > max_quote_words:
        errors.append(
            f"[{entry_id}] exact_quote has {word_count} words (max allowed is {max_quote_words}): {quote!r}"
        )

    ratio = best_fuzzy_match_ratio(quote, ref_cache[src_doc])
    if ratio < min_fuzzy_ratio:
        errors.append(
            f"[{entry_id}] exact_quote fuzzy match in 'references/{src_doc}' is {ratio * 100:.1f}% "
            f"(< {min_fuzzy_ratio * 100:.0f}%): {quote!r}"
        )

    reviewer_status = (entry.get("reviewer_status") or "").strip()
    if reviewer_status:
        if not (entry.get("reviewer_role") and entry.get("review_date") and entry.get("decision")):
            errors.append(
                f"[{entry_id}] reviewer_status={reviewer_status!r} is set without complete reviewer_role/review_date/decision."
            )

    return errors


def verify_all_sources(
    references_dir: str = None,
    schema_path: str = None,
    check_runtime_tables: bool = True,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Run all source and quote checks across schema JSON and resource_facts.py."""
    references_dir = references_dir or os.path.join(ROOT, "references")
    schema_path = schema_path or os.path.join(ROOT, "data_raw", "team_supplied", "07_health_indicators_schema.json")

    errors: List[str] = []
    ref_cache: Dict[str, str] = {}
    stats = {
        "schema_indicators_checked": 0,
        "schema_thresholds_checked": 0,
        "summary_claims_checked": 0,
        "runtime_indicators_checked": 0,
        "runtime_fixed_limits_checked": 0,
        "countermeasures_checked": 0,
        "status_counts_indicators": {},
        "status_counts_thresholds": {},
        "status_counts_countermeasures": {},
    }

    if not os.path.isdir(references_dir):
        return False, [f"References directory not found: {references_dir}"], stats
    if not os.path.isfile(schema_path):
        return False, [f"Schema file not found: {schema_path}"], stats

    with open(schema_path, encoding="utf-8") as f:
        schema_doc = json.load(f)

    for ind in schema_doc.get("indicators", []):
        name = ind.get("name", "<unknown>")
        stats["schema_indicators_checked"] += 1
        st = ind.get("verification_status", "UNVERIFIED")
        stats["status_counts_indicators"][st] = stats["status_counts_indicators"].get(st, 0) + 1
        errors.extend(verify_entry(f"schema.indicator:{name}", ind, references_dir, ref_cache))

        for t_key, t_detail in (ind.get("threshold_details") or {}).items():
            stats["schema_thresholds_checked"] += 1
            tst = t_detail.get("verification_status", "UNVERIFIED")
            stats["status_counts_thresholds"][tst] = stats["status_counts_thresholds"].get(tst, 0) + 1
            errors.extend(
                verify_entry(f"schema.threshold:{name}.{t_key}", t_detail, references_dir, ref_cache)
            )

    for claim in schema_doc.get("summary_02_04_verified_claims", []):
        cid = claim.get("claim_id", "<unknown>")
        stats["summary_claims_checked"] += 1
        errors.extend(verify_entry(f"schema.summary_claim:{cid}", claim, references_dir, ref_cache))

    if check_runtime_tables:
        import resource_facts as rf

        for ind in rf.INDICATORS:
            stats["runtime_indicators_checked"] += 1
            errors.extend(verify_entry(f"rf.indicator:{ind['name']}", ind, references_dir, ref_cache))

        for rule in rf.FIXED_LIMITS:
            stats["runtime_fixed_limits_checked"] += 1
            rid = f"rf.fixed_limit:{rule['indicator']}.{rule['threshold_name']}"
            errors.extend(verify_entry(rid, rule, references_dir, ref_cache))

        for idx, cm in enumerate(rf.COUNTERMEASURES, start=1):
            stats["countermeasures_checked"] += 1
            cst = cm.get("verification_status", "UNVERIFIED")
            stats["status_counts_countermeasures"][cst] = stats["status_counts_countermeasures"].get(cst, 0) + 1
            cid = f"rf.countermeasure:{idx}:{cm['problem_area']}:{cm['trigger_condition']}"
            errors.extend(verify_entry(cid, cm, references_dir, ref_cache))

    return (len(errors) == 0), errors, stats


def main() -> int:
    print("=" * 78)
    print("STEP 2B - tools/verify_sources.py (Automated Source & Verbatim Quote Audit)")
    print("=" * 78)
    ok, errors, stats = verify_all_sources()
    print(f"Schema indicators checked:      {stats['schema_indicators_checked']}")
    print(f"Schema thresholds checked:      {stats['schema_thresholds_checked']}")
    print(f"Summary 02-04 claims checked:   {stats['summary_claims_checked']}")
    print(f"Runtime indicators checked:     {stats['runtime_indicators_checked']}")
    print(f"Runtime fixed limits checked:   {stats['runtime_fixed_limits_checked']}")
    print(f"Countermeasures checked:        {stats['countermeasures_checked']}")
    print(f"Indicator status breakdown:     {stats['status_counts_indicators']}")
    print(f"Threshold status breakdown:     {stats['status_counts_thresholds']}")
    print(f"Countermeasure status breakdown:{stats['status_counts_countermeasures']}")

    if not ok:
        print(f"\n[FAIL] Source verification failed with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\n[PASS] All non-UNVERIFIED entries have matching files in references/ and exact_quote fuzzy match >= 90% (<= 25 words).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
