"""
review/generate_review_packet.py — Generates the Human Clinical Sign-Off Packet (Phase 2 Step 4):
  - review/clinical_review_packet.md
  - review/clinical_review_packet.pdf (using reportlab)
  - review/clinical_review_template.csv (blank reviewer fields ready for import by review/record_review.py)
"""
import csv
import json
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import resource_facts as rf


def collect_review_rows() -> List[Dict[str, Any]]:
    """Collect one unified table of every threshold, indicator scale, and countermeasure."""
    rows: List[Dict[str, Any]] = []

    with open(rf.SCHEMA_JSON_PATH, encoding="utf-8") as f:
        schema_doc = json.load(f)

    # 1. Every alert threshold across all indicators
    for ind in schema_doc.get("indicators", []):
        ind_name = ind["name"]
        unit = ind.get("unit", "")
        t_details = ind.get("threshold_details") or {}
        if t_details:
            for t_key, td in t_details.items():
                rows.append({
                    "item_type": "threshold",
                    "item_id": f"{ind_name}.{t_key}",
                    "category_or_zone": ind.get("category", ""),
                    "description": f"{ind.get('display_name', ind_name)} — {t_key} ({unit})",
                    "value_used": f"{td.get('value_used')} {unit}".strip(),
                    "old_value": f"{td.get('old_value')} {unit}".strip() if "old_value" in td else "",
                    "source_document": td.get("source_document", ind.get("source_document", "")),
                    "page_or_section": td.get("page_or_section", ind.get("page_or_section", "")),
                    "source_status": td.get("verification_status", ind.get("verification_status", "")),
                    "ui_badge": td.get("ui_badge", ind.get("ui_badge", "")),
                    "reviewer_status": td.get("reviewer_status", ind.get("reviewer_status", "")),
                    "reviewer_role": td.get("reviewer_role", ind.get("reviewer_role", "")),
                    "review_date": td.get("review_date", ind.get("review_date", "")),
                    "decision": td.get("decision", ind.get("decision", "")),
                    "proposed_value": "",
                })
        else:
            # Indicator-level range / instrument mapping
            rows.append({
                "item_type": "indicator",
                "item_id": ind_name,
                "category_or_zone": ind.get("category", ""),
                "description": f"{ind.get('display_name', ind_name)} ({unit})",
                "value_used": str(ind.get("value_used", "")),
                "old_value": json.dumps(ind["old_value"]) if "old_value" in ind else "",
                "source_document": ind.get("source_document", ""),
                "page_or_section": ind.get("page_or_section", ""),
                "source_status": ind.get("verification_status", ""),
                "ui_badge": ind.get("ui_badge", ""),
                "reviewer_status": ind.get("reviewer_status", ""),
                "reviewer_role": ind.get("reviewer_role", ""),
                "review_date": ind.get("review_date", ""),
                "decision": ind.get("decision", ""),
                "proposed_value": "",
            })

    # 2. Every countermeasure row
    for idx, cm in enumerate(rf.COUNTERMEASURES, start=1):
        rows.append({
            "item_type": "countermeasure",
            "item_id": f"CM:{idx}:{cm['problem_area']}:{cm['trigger_condition']}",
            "category_or_zone": cm["problem_area"],
            "description": f"Countermeasure ({cm['problem_area']} / {cm['trigger_condition']})",
            "value_used": cm["advice_text"],
            "old_value": "",
            "source_document": cm.get("source_document", ""),
            "page_or_section": cm.get("page_or_section", ""),
            "source_status": cm.get("verification_status", ""),
            "ui_badge": cm.get("ui_badge", ""),
            "reviewer_status": cm.get("reviewer_status", ""),
            "reviewer_role": cm.get("reviewer_role", ""),
            "review_date": cm.get("review_date", ""),
            "decision": cm.get("decision", ""),
            "proposed_value": "",
        })

    return rows


def generate_markdown_and_csv(review_dir: str = None) -> Dict[str, str]:
    review_dir = review_dir or os.path.join(ROOT, "review")
    os.makedirs(review_dir, exist_ok=True)
    rows = collect_review_rows()

    csv_path = os.path.join(review_dir, "clinical_review_template.csv")
    fieldnames = [
        "item_type",
        "item_id",
        "category_or_zone",
        "description",
        "value_used",
        "old_value",
        "source_document",
        "page_or_section",
        "source_status",
        "ui_badge",
        "reviewer_status",
        "reviewer_role",
        "review_date",
        "decision",
        "proposed_value",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    md_path = os.path.join(review_dir, "clinical_review_packet.md")
    lines = [
        "# Clinical Review & Human Sign-Off Packet — Astronaut Health Monitoring Prototype",
        "",
        "**Prototype for research/education only — not for clinical diagnosis.**  ",
        "**Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.**",
        "",
        "---",
        "",
        "## Cover Note for Reviewing Physician / Flight Surgeon",
        "",
        "Dear Reviewing Clinician,",
        "",
        "Thank you for reviewing the physiological thresholds, psychometric scale mappings, and operational countermeasure recommendations used in our **2026 NASA Space Apps Astronaut Health Monitoring** software prototype.",
        "",
        "### Scope & Purpose of This Sign-Off Packet",
        "1. **Source Cross-Check Already Completed (`source_status`):** Every numerical range, alert threshold, and countermeasure row below has been cross-checked against published standards in the following priority order:",
        "   - **(a)** *NASA-STD-3001 Volume 1 (Crew Health)* and *Volume 2 (Human Factors, Habitability, and Environmental Health)*",
        "   - **(b)** *NASA Office of the Chief Health and Medical Officer (OCHMO) Technical Briefs* (`OCHMO-TB-004`, `015`, `025`, `030`, `031`, `033`, `038`)",
        "   - **(c)** *NASA Human Research Program (HRP)* hazard and risk summaries",
        "   - **(d)** Peer-reviewed spaceflight medicine literature (Stahn et al. 2017, Barger et al. 2014, Sirek et al. 2014, Cucinotta et al. 2008, Basner & Dinges 2011, Crucian et al. 2018)",
        "   - **(e)** Standard terrestrial clinical guidelines (*AHA/ACC Blood Pressure*, *ADA 2024 Diabetes & Hypoglycemia Standards*, *Royal College of Physicians NEWS2*, *AASM/NSF Sleep Consensus*) used **only** where no spaceflight-specific cut-off is published in open literature (`TERRESTRIAL_REFERENCE`).",
        "2. **How to Record Your Review:**",
        "   - Open `review/clinical_review_template.csv` (or mark the table below).",
        "   - For each row, enter your `reviewer_role` (e.g., `Flight Surgeon` or `Physician (MD)`), `review_date` (`YYYY-MM-DD`), and `decision` (`approve`, `change`, or `reject`). If `decision` is `change`, specify `proposed_value`.",
        "   - Import the completed CSV via: `python review/record_review.py path/to/filled_review.csv`.",
        "   - Until a real human review CSV is imported, `reviewer_role`, `review_date`, `decision`, and `reviewer_status` remain **blank** in the schema and database.",
        "",
        "> **IMPORTANT CREDENTIAL DISTINCTION:**  ",
        "> **Review by a physician who is not a flight surgeon counts as `\"physician-reviewed\"`, not `\"flight-surgeon-verified\"`.** Only review by a credentialed aerospace medicine flight surgeon may be recorded as `\"flight-surgeon-verified\"`.",
        "",
        "---",
        "",
        "## Unified Table of Thresholds, Scales, and Countermeasures for Clinical Sign-Off",
        "",
        "| # | Type | Item ID | Value / Guidance Used | Source (`references/`) & Section | Source Status (`source_status`) | UI Badge | Decision (`approve` / `change` / `reject`) | Reviewer Role & Date |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for idx, r in enumerate(rows, start=1):
        val_short = r["value_used"].replace("|", "/").replace("\n", " ")
        src_short = f"`{r['source_document']}` ({r['page_or_section']})".replace("|", "/")
        dec_col = r["decision"] if r["decision"] else "`[ ] approve  [ ] change  [ ] reject`"
        rev_col = f"{r['reviewer_role']} {r['review_date']}".strip() or "*(pending human review)*"
        lines.append(
            f"| {idx} | `{r['item_type']}` | `{r['item_id']}` | {val_short} | {src_short} | `{r['source_status']}` | **{r['ui_badge']}** | {dec_col} | {rev_col} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Reviewer Sign-Off Block",
        "",
        "- **Reviewer Name & Credentials:** `____________________________________________________`",
        "- **Reviewer Role (`Flight Surgeon` vs. `Physician — Non-Flight Surgeon`):** `____________________________________`",
        "- **Institutional Affiliation:** `____________________________________________________`",
        "- **Date (`YYYY-MM-DD`):** `____________________`",
        "- **Signature:** `____________________________________________________`",
        "",
    ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    pdf_path = os.path.join(review_dir, "clinical_review_packet.pdf")
    _generate_pdf_reportlab(pdf_path, rows)

    return {"md_path": md_path, "csv_path": csv_path, "pdf_path": pdf_path, "row_count": len(rows)}


def _generate_pdf_reportlab(pdf_path: str, rows: List[Dict[str, Any]]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=landscape(letter),
        leftMargin=0.4 * inch,
        rightMargin=0.4 * inch,
        topMargin=0.4 * inch,
        bottomMargin=0.4 * inch,
        title="Clinical Review & Human Sign-Off Packet — Astronaut Health Monitoring",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PacketTitle",
        parent=styles["Heading1"],
        fontSize=14,
        leading=17,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "PacketBody",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        spaceAfter=4,
    )
    bold_note_style = ParagraphStyle(
        "PacketBoldNote",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#7F1D1D"),
        spaceAfter=8,
    )
    cell_style = ParagraphStyle(
        "PacketCell",
        parent=styles["Normal"],
        fontSize=6.8,
        leading=8.5,
    )
    header_style = ParagraphStyle(
        "PacketHeader",
        parent=styles["Normal"],
        fontSize=7.2,
        leading=9,
        textColor=colors.whitesmoke,
    )

    story = [
        Paragraph("Clinical Review & Human Sign-Off Packet — Astronaut Health Monitoring Prototype", title_style),
        Paragraph(
            "<b>Disclaimer:</b> Prototype for research/education only — not for clinical diagnosis. "
            "Performance reflects recovery of the project's own simulation rules, not clinical diagnostic accuracy.",
            body_style,
        ),
        Paragraph(
            "<b>Cover Note for Reviewing Physician:</b> This packet lists every physiological alert threshold, "
            "validated psychometric instrument mapping, and operational countermeasure in the 2026 NASA Space Apps "
            "Astronaut Health Monitoring prototype, together with its source document in <i>references/</i> and "
            "automated verification status. Please mark each row as <b>Approve</b>, <b>Change</b> (with replacement value), "
            "or <b>Reject</b>, and import the completed CSV using <i>python review/record_review.py</i>. "
            "All reviewer fields remain blank until a real review is imported.",
            body_style,
        ),
        Paragraph(
            "<b>IMPORTANT DISTINCTION:</b> Review by a physician who is not a flight surgeon counts as "
            "\"physician-reviewed\", not \"flight-surgeon-verified\".",
            bold_note_style,
        ),
        Spacer(1, 4),
    ]

    table_data = [[
        Paragraph("<b>#</b>", header_style),
        Paragraph("<b>Type</b>", header_style),
        Paragraph("<b>Item ID</b>", header_style),
        Paragraph("<b>Value / Countermeasure Used</b>", header_style),
        Paragraph("<b>Source & Section</b>", header_style),
        Paragraph("<b>Source Status & Badge</b>", header_style),
        Paragraph("<b>Approve / Change / Reject</b>", header_style),
    ]]

    for idx, r in enumerate(rows, start=1):
        val_txt = (r["value_used"] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        src_txt = f"{r['source_document']} — {r['page_or_section']}".replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        st_txt = f"{r['source_status']}<br/>[{r['ui_badge']}]"
        dec_txt = r["decision"] if r["decision"] else "[ ] Approve   [ ] Change   [ ] Reject"
        table_data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(r["item_type"], cell_style),
            Paragraph(r["item_id"], cell_style),
            Paragraph(val_txt, cell_style),
            Paragraph(src_txt, cell_style),
            Paragraph(st_txt, cell_style),
            Paragraph(dec_txt, cell_style),
        ])

    col_widths = [0.35 * inch, 0.75 * inch, 1.55 * inch, 3.35 * inch, 1.95 * inch, 1.25 * inch, 1.0 * inch]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    doc.build(story)


if __name__ == "__main__":
    info = generate_markdown_and_csv()
    print(f"Generated clinical review packet ({info['row_count']} items):")
    print(f"  Markdown: {info['md_path']}")
    print(f"  PDF:      {info['pdf_path']}")
    print(f"  CSV:      {info['csv_path']}")
