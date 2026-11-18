"""
review/record_review.py — Import a clinician-completed CSV review and write reviewer metadata (Phase 2 Step 4 & Phase 5 D4).

Usage:
    python review/record_review.py path/to/filled_clinical_review.csv

Rules enforced:
  - Leaves reviewer_role, review_date, decision, and reviewer_status empty until a real review is imported.
  - Review by a physician who is not a flight surgeon is recorded as reviewer_status = "physician-reviewed",
    NOT "flight-surgeon-verified". Only a reviewer_role explicitly indicating a flight surgeon
    (e.g., "flight_surgeon" or "Flight Surgeon") receives reviewer_status = "flight-surgeon-verified".
  - Writes reviewer_role, review_date, decision, and reviewer_status into:
      1. data_raw/team_supplied/07_health_indicators_schema.json
      2. data/astronaut_health_app.db (and legacy astronaut_health.db) countermeasures & data_dictionary tables
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
from typing import Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VALID_DECISIONS = {"approve", "change", "reject"}


def classify_reviewer_status(reviewer_role: str, decision: str) -> str:
    """
    Determine reviewer_status from reviewer_role and decision.
    Review by a physician who is not a flight surgeon counts as 'physician-reviewed',
    not 'flight-surgeon-verified'.
    """
    role_clean = (reviewer_role or "").strip().lower()
    dec_clean = (decision or "").strip().lower()
    if not role_clean or not dec_clean:
        return ""
    if dec_clean not in VALID_DECISIONS:
        raise ValueError(f"Invalid decision {decision!r}; must be one of {sorted(VALID_DECISIONS)}")

    is_negated_fs = any(
        neg in role_clean
        for neg in ("non-flight surgeon", "non flight surgeon", "not a flight surgeon", "non-flight_surgeon")
    )
    if not is_negated_fs and ("flight surgeon" in role_clean or "flight_surgeon" in role_clean):
        return "flight-surgeon-verified"
    if any(tok in role_clean for tok in ("physician", "md", "do", "doctor", "clinician", "medical")):
        return "physician-reviewed"
    return f"reviewed-by-{role_clean.replace(' ', '-')}"


def import_review_csv(
    csv_path: str,
    schema_path: str = None,
    app_db_paths: List[str] = None,
) -> Dict[str, int]:
    """Import a completed review CSV and update schema JSON and working SQLite databases."""
    schema_path = schema_path or os.path.join(ROOT, "data_raw", "team_supplied", "07_health_indicators_schema.json")
    if app_db_paths is None:
        app_db_paths = [
            p
            for p in (
                os.path.join(ROOT, "data", "astronaut_health_app.db"),
                os.path.join(ROOT, "astronaut_health.db"),
            )
            if os.path.isfile(p)
        ]

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    with open(schema_path, encoding="utf-8") as f:
        schema_doc = json.load(f)

    ind_by_name = {i["name"]: i for i in schema_doc.get("indicators", [])}
    updated_indicators = 0
    updated_thresholds = 0
    updated_countermeasures = 0

    cm_updates: List[Dict[str, str]] = []

    for row in rows:
        item_type = (row.get("item_type") or "").strip()
        item_id = (row.get("item_id") or "").strip()
        reviewer_role = (row.get("reviewer_role") or "").strip()
        review_date = (row.get("review_date") or "").strip()
        decision = (row.get("decision") or "").strip().lower()
        proposed_value = (row.get("proposed_value") or "").strip()

        if not decision and not reviewer_role and not review_date:
            continue

        reviewer_status = classify_reviewer_status(reviewer_role, decision)
        ui_badge = "Physician-reviewed" if reviewer_status else None

        if item_type == "indicator" and item_id in ind_by_name:
            ind = ind_by_name[item_id]
            ind["reviewer_role"] = reviewer_role
            ind["review_date"] = review_date
            ind["decision"] = decision
            ind["reviewer_status"] = reviewer_status
            if ui_badge:
                ind["ui_badge"] = ui_badge
            if decision == "change" and proposed_value:
                ind["value_used"] = proposed_value
            updated_indicators += 1

        elif item_type == "threshold" and "." in item_id:
            ind_name, thresh_key = item_id.split(".", 1)
            if ind_name in ind_by_name:
                ind = ind_by_name[ind_name]
                td = (ind.get("threshold_details") or {}).get(thresh_key)
                if td is not None:
                    td["reviewer_role"] = reviewer_role
                    td["review_date"] = review_date
                    td["decision"] = decision
                    td["reviewer_status"] = reviewer_status
                    if ui_badge:
                        td["ui_badge"] = ui_badge
                    if decision == "change" and proposed_value:
                        try:
                            new_val = float(proposed_value) if "." in proposed_value else int(proposed_value)
                        except ValueError:
                            new_val = proposed_value
                        td["old_value"] = td.get("value_used")
                        td["value_used"] = new_val
                        if "alert_thresholds" in ind and thresh_key in ind["alert_thresholds"]:
                            ind["alert_thresholds"][thresh_key] = new_val
                    updated_thresholds += 1

        elif item_type == "countermeasure":
            cm_updates.append({
                "item_id": item_id,
                "reviewer_role": reviewer_role,
                "review_date": review_date,
                "decision": decision,
                "reviewer_status": reviewer_status,
                "proposed_value": proposed_value,
            })
            updated_countermeasures += 1

    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema_doc, f, indent=2, ensure_ascii=False)

    for db_path in app_db_paths:
        con = sqlite3.connect(db_path)
        try:
            for u in cm_updates:
                # item_id format: CM:<countermeasure_id>:<problem_area>:<trigger_condition>
                parts = u["item_id"].split(":", 3)
                if len(parts) >= 2 and parts[1].isdigit():
                    cm_id = int(parts[1])
                    con.execute(
                        """UPDATE countermeasures
                           SET reviewer_status = ?, reviewer_role = ?, review_date = ?, decision = ?,
                               ui_badge = CASE WHEN ? != '' THEN 'Physician-reviewed' ELSE ui_badge END
                           WHERE countermeasure_id = ?""",
                        (
                            u["reviewer_status"],
                            u["reviewer_role"],
                            u["review_date"],
                            u["decision"],
                            u["reviewer_status"],
                            cm_id,
                        ),
                    )
            con.commit()
        finally:
            con.close()

    return {
        "updated_indicators": updated_indicators,
        "updated_thresholds": updated_thresholds,
        "updated_countermeasures": updated_countermeasures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import clinician review CSV into schema and database.")
    parser.add_argument("csv_path", help="Path to the filled-in clinical review CSV.")
    parser.add_argument("--schema", default=None, help="Optional path to 07_health_indicators_schema.json.")
    args = parser.parse_args()

    if not os.path.isfile(args.csv_path):
        print(f"Error: CSV file not found: {args.csv_path}", file=sys.stderr)
        return 1

    counts = import_review_csv(args.csv_path, schema_path=args.schema)
    print(f"Imported clinical review from {args.csv_path}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
