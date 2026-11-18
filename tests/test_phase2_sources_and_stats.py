"""
tests/test_phase2_sources_and_stats.py — Unit tests for Phase 2 (B1, B2, B3, B4, B5) and Phase 5 (D1, D4).
"""
import csv
import json
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import health_engine as he
import resource_facts as rf
from review.record_review import classify_reviewer_status, import_review_csv
from tools.verify_sources import verify_all_sources, verify_entry


def test_verify_sources_passes_on_repository():
    ok, errors, stats = verify_all_sources()
    assert ok is True, f"verify_sources failed: {errors}"
    assert stats["schema_indicators_checked"] >= 15
    assert stats["schema_thresholds_checked"] >= 27
    assert stats["countermeasures_checked"] >= 15


def test_verify_sources_rejects_missing_file_and_bad_quote(tmp_path):
    refs = tmp_path / "references"
    refs.mkdir()
    sample_doc = refs / "sample_ref.txt"
    sample_doc.write_text(
        "Astronauts on the ISS are allocated approximately 2.0 to 2.5 hours per day for exercise.",
        encoding="utf-8",
    )
    cache = {}

    # 1. Missing reference file must fail
    err_missing = verify_entry(
        "test_missing",
        {
            "verification_status": "VERIFIED_AGAINST_PUBLISHED_STANDARD",
            "source_document": "nonexistent.txt",
            "exact_quote": "Astronauts on the ISS are allocated approximately",
        },
        str(refs),
        cache,
    )
    assert any("does not exist" in e for e in err_missing)

    # 2. Quote not matching text (< 90%) must fail
    err_mismatch = verify_entry(
        "test_mismatch",
        {
            "verification_status": "VERIFIED_AGAINST_PUBLISHED_STANDARD",
            "source_document": "sample_ref.txt",
            "exact_quote": "Completely fabricated quote that does not appear anywhere in the document.",
        },
        str(refs),
        cache,
    )
    assert any("fuzzy match" in e for e in err_mismatch)

    # 3. Quote > 25 words must fail
    long_quote = " ".join(["word"] * 28)
    err_long = verify_entry(
        "test_long",
        {
            "verification_status": "VERIFIED_AGAINST_PUBLISHED_STANDARD",
            "source_document": "sample_ref.txt",
            "exact_quote": long_quote,
        },
        str(refs),
        cache,
    )
    assert any("max allowed is 25" in e for e in err_long)


def test_record_review_physician_vs_flight_surgeon_and_import(tmp_path):
    # Physician who is not a flight surgeon -> "physician-reviewed", NOT "flight-surgeon-verified"
    assert classify_reviewer_status("Physician (MD)", "approve") == "physician-reviewed"
    assert classify_reviewer_status("Internal Medicine Doctor", "change") == "physician-reviewed"
    assert classify_reviewer_status("NASA Flight Surgeon", "approve") == "flight-surgeon-verified"

    schema_copy = tmp_path / "07_health_indicators_schema.json"
    shutil.copy2(rf.SCHEMA_JSON_PATH, schema_copy)

    csv_file = tmp_path / "review_filled.csv"
    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["item_type", "item_id", "reviewer_role", "review_date", "decision", "proposed_value"],
        )
        writer.writeheader()
        writer.writerow({
            "item_type": "threshold",
            "item_id": "heart_rate.high_warning",
            "reviewer_role": "Physician (MD, non-flight surgeon)",
            "review_date": "2026-11-14",
            "decision": "approve",
            "proposed_value": "",
        })

    res = import_review_csv(str(csv_file), schema_path=str(schema_copy), app_db_paths=[])
    assert res["updated_thresholds"] == 1
    updated_doc = json.loads(schema_copy.read_text(encoding="utf-8"))
    hr_ind = next(i for i in updated_doc["indicators"] if i["name"] == "heart_rate")
    td = hr_ind["threshold_details"]["high_warning"]
    assert td["reviewer_status"] == "physician-reviewed"
    assert td["ui_badge"] == "Physician-reviewed"
    assert td["decision"] == "approve"


def test_blood_glucose_and_countermeasure_fallbacks():
    assert "blood_glucose_mg_dl" in rf.IND
    assert "blood_glucose_mg_dl" in rf.CONTINUOUS

    # Countermeasures for Immune and Medical_Danger_Alert are populated and Danger starts with required prefix
    immune_cm = he.get_countermeasures_for_category("Immune", "zone_alert")
    assert immune_cm["ok"] is True
    assert len(immune_cm["countermeasures"]) >= 1
    assert "No verified guidance" not in immune_cm["countermeasures"][0]["advice_text"]

    danger_cm = he.get_countermeasures_for_category("Medical_Danger", "class_Medical_Danger_Alert")
    assert danger_cm["ok"] is True
    for row in danger_cm["countermeasures"]:
        assert row["advice_text"].startswith("Contact flight surgeon immediately")

    # Unknown category returns safe fallback instead of empty list
    unknown_cm = he.get_countermeasures_for_category("Nonexistent_Category_XYZ", "zone_alert")
    assert unknown_cm["ok"] is True
    assert len(unknown_cm["countermeasures"]) == 1
    assert unknown_cm["countermeasures"][0]["source_status"] == "SAFE_FALLBACK"


def test_within_astronaut_mood_training_correlation_and_badges():
    corr = he.mood_training_correlation()
    assert corr["ok"] is True
    rm = corr["repeated_measures_and_mixed_effects"]
    assert rm["rm_corr_r"] is not None
    assert rm["ci_95_low"] is not None and rm["ci_95_high"] is not None
    assert rm["ci_95_low"] <= rm["rm_corr_r"] <= rm["ci_95_high"]
    assert rm["mixed_effects_slope"] is not None
    assert len(rm["mixed_effects_slope_ci_95"]) == 2

    badges = he.get_threshold_badges()
    assert badges["ok"] is True
    allowed_badges = {"NASA standard", "Physician-reviewed", "Reference value", "Placeholder", "Unverified"}
    for b in badges["thresholds"]:
        assert b["ui_badge"] in allowed_badges
