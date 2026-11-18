"""
Phase 5 Deliverable Verification Tests.

Validates presence and integrity of end-to-end runner scripts, audit reports,
evaluation reports, README credential documentation, and metric JSON schemas.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import resource_facts as rf


def test_required_deliverables_exist_and_nonempty():
    required_files = [
        "SOURCES_AUDIT.md",
        "LIMITATIONS.md",
        "EVALUATION_REPORT.md",
        "README.md",
        "run_all.py",
        "run_all.sh",
        "references/OUTSIDE_ALLOWED_RESOURCES.md",
        "review/clinical_review_packet.md",
        "review/clinical_review_packet.pdf",
        "review/clinical_review_template.csv",
        "review/record_review.py",
        "tools/verify_sources.py",
        "models/blind_test_metrics.json",
        "models/chatbot_metrics.json",
        "models/health_model.joblib",
        "NASA_Astronaut_Health_Analysis.xlsx",
    ]
    for rel in required_files:
        path = os.path.join(ROOT, rel)
        assert os.path.isfile(path), f"Missing required deliverable: {rel}"
        assert os.path.getsize(path) > 0, f"Deliverable is empty: {rel}"


def test_disclaimers_and_path_to_real_validation_present():
    for rel in ("README.md", "EVALUATION_REPORT.md", "LIMITATIONS.md", "SOURCES_AUDIT.md"):
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert rf.DISCLAIMER in text, f"Missing DISCLAIMER in {rel}"
        assert rf.SYNTHETIC_DATA_DISCLAIMER in text, f"Missing SYNTHETIC_DATA_DISCLAIMER in {rel}"

    for rel in ("README.md", "EVALUATION_REPORT.md"):
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "Path to Real" in text, f"Missing Path to Real Validation section in {rel}"
        assert "LSAH" in text and "CHAPEA" in text


def test_limitations_covers_all_audit_items():
    text = open(os.path.join(ROOT, "LIMITATIONS.md"), encoding="utf-8").read()
    for code in ("A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5", "C1", "C2", "D1", "D2", "D3", "D4"):
        assert f"**{code}**" in text, f"LIMITATIONS.md missing item {code}"


def test_readme_documents_actual_demo_credentials():
    creds = json.load(open(os.path.join(ROOT, "config", "demo_credentials.json"), encoding="utf-8"))
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for fs in creds["flight_surgeons"]:
        assert fs["user_id"] in readme and fs["credential"] in readme
    assert "PIN-" in readme
    for aid, pin in creds["astronaut_credential_rule"]["overrides"].items():
        assert aid in readme and pin in readme


def test_saved_metrics_artifacts_schema_and_anti_leakage():
    bt = json.load(open(os.path.join(ROOT, "models", "blind_test_metrics.json"), encoding="utf-8"))
    assert bt["train_test_overlap"] == 0
    assert "validation_model_comparison" in bt
    assert "tiered_danger_alerting" in bt
    assert "noise_and_missingness_robustness" in bt
    assert "danger_oversampled_stress_test" in bt
    assert bt["model_performance"]["confusion_matrix"]
    assert bt["model_performance"]["confusion_matrix_row_normalized_pct"]

    cm = json.load(open(os.path.join(ROOT, "models", "chatbot_metrics.json"), encoding="utf-8"))
    p4 = cm["phase4_unbiased_eval"]
    for key in ("a_public_oos", "b_public_health_qa", "c_paraphrase_stress_test", "d_external_questions_csv"):
        assert key in p4, f"Missing chatbot eval key {key}"
        assert p4[key]["leakage_audit"]["count_above_0_60"] == 0
    assert "all_100_rows" in p4["d_external_questions_csv"]
    assert "without_disputed_96_rows" in p4["d_external_questions_csv"]
