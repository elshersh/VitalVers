"""
analysis_to_excel.py — STEP 2: write NASA_Astronaut_Health_Analysis.xlsx from astronaut_health.db

Sheets 1, 2, 3 are written here. Sheets 4 and 5 are created as stubs and are filled
by blind_test.py from the actual blind-test run (never typed by hand).

Clean executive presentation formatting without debug color legends or provenance stubs.
"""
import os
import sqlite3

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import ai_health_model as aim
import health_engine as he
import resource_facts as rf

HERE = os.path.dirname(os.path.abspath(__file__))
XLSX_PATH = os.path.join(HERE, "NASA_Astronaut_Health_Analysis.xlsx")
SHEETS = ["Astronaut_Profiles_Baselines", "Mission_Telemetry_Data", "Problem_Statistical_Analysis",
          "AI_Model_Performance_Metrics", "Blind_Test_Accuracy_Sensitivity"]

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=12)


# ----------------------------------------------------------------------------- helpers
def _cell_value(v):
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (dict, list, tuple)):
        return str(v)
    return v


def write_table(ws, row, df, title=None):
    """Write a clean DataFrame at `row` with dark blue headers and clean cells."""
    if title:
        ws.cell(row=row, column=1, value=title).font = TITLE_FONT
        row += 1
    for j, col in enumerate(df.columns, start=1):
        c = ws.cell(row=row, column=j, value=str(col))
        c.font, c.fill = HEAD_FONT, HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="top")
    header_row = row
    for rec in df.itertuples(index=False, name=None):
        row += 1
        for j, v in enumerate(rec, start=1):
            ws.cell(row=row, column=j, value=_cell_value(v))
    return row + 2, header_row


def autosize(ws, max_width=60, sample_rows=300):
    widths = {}
    for r, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if r > sample_rows:
            break
        for j, v in enumerate(row, start=1):
            if v is not None:
                widths[j] = max(widths.get(j, 0), len(str(v)))
    for j, w in widths.items():
        ws.column_dimensions[get_column_letter(j)].width = max(10, min(max_width, w + 2))


# ----------------------------------------------------------------------------- sheets
def sheet_profiles(wb, con):
    ws = wb.create_sheet(SHEETS[0])
    prof = pd.read_sql_query("SELECT * FROM astronaut_profile ORDER BY astronaut_id", con)
    base = pd.read_sql_query("SELECT * FROM preflight_baseline ORDER BY astronaut_id", con)
    df = prof.merge(base, on="astronaut_id")
    _, header_row = write_table(ws, 1, df, title="Astronaut Profiles & Pre-Flight Baseline Records")
    ws.freeze_panes = ws.cell(row=header_row + 1, column=3)
    autosize(ws, max_width=34)
    return len(df)


def sheet_telemetry(wb, con):
    ws = wb.create_sheet(SHEETS[1])
    df = pd.read_sql_query(
        "SELECT t.*, l.true_class AS health_state FROM mission_telemetry t "
        "JOIN telemetry_labels l ON l.record_id = t.record_id ORDER BY t.astronaut_id, t.mission_day", con)
    _, header_row = write_table(ws, 1, df, title="Mission Telemetry & Health States")
    ws.freeze_panes = ws.cell(row=header_row + 1, column=5)
    autosize(ws, max_width=30, sample_rows=50)
    return len(df)


def descriptive_stats(con):
    tel = pd.read_sql_query("SELECT * FROM mission_telemetry", con)
    labels = pd.read_sql_query("SELECT * FROM telemetry_labels", con)
    base = pd.read_sql_query("SELECT * FROM preflight_baseline", con)
    rows = []
    for zone, inds in rf.ZONES.items():
        names = list(inds)
        if zone == "Bone_Muscle":
            names += ["cardio_session_done", "resistance_training_done"]
        for n in names:
            s, ind = tel[n].astype(float), rf.IND[n]
            rows.append({"problem": rf.ZONE_TITLES[zone], "indicator": n, "unit": ind["unit"],
                         "n": int(s.notna().sum()), "missing_pct": round(100 * s.isna().mean(), 2),
                         "mean": round(s.mean(), 3), "std": round(s.std(), 3), "min": round(s.min(), 3),
                         "p25": round(s.quantile(0.25), 3), "median": round(s.median(), 3),
                         "p75": round(s.quantile(0.75), 3), "max": round(s.max(), 3),
                         "preflight_baseline_mean_across_astronauts": round(base[n + "_mean"].mean(), 3),
                         "preflight_baseline_std_across_astronauts": round(base[n + "_std"].mean(), 3)})
    desc = pd.DataFrame(rows)

    feats = aim.build_features(tel, base).merge(labels, on="record_id")
    zrows = []
    for zone, inds in rf.ZONES.items():
        for n in inds:
            if n in ("bone_health", "muscle_health"):
                continue
            rec = {"problem": rf.ZONE_TITLES[zone], "indicator": n}
            for c in rf.CLASSES:
                rec[f"mean_z__{c}"] = round(feats.loc[feats["true_class"] == c, f"{n}_z"].mean(), 3)
            zrows.append(rec)
    by_class = pd.DataFrame(zrows)

    balance = labels["true_class"].value_counts().reindex(rf.CLASSES).fillna(0).astype(int).reset_index()
    balance.columns = ["health_state", "records"]
    balance["percent"] = (100 * balance["records"] / balance["records"].sum()).round(2)
    return desc, by_class, balance


def sheet_statistics(wb, con):
    ws = wb.create_sheet(SHEETS[2])
    desc, by_class, balance = descriptive_stats(con)
    corr = he.mood_training_correlation()

    row, header_row = write_table(ws, 1, desc, title="A. Descriptive statistics of in-flight telemetry, per problem")
    ws.freeze_panes = ws.cell(row=header_row + 1, column=3)
    row, _ = write_table(ws, row, balance, title="B. Class balance across mission telemetry")
    row, _ = write_table(ws, row, by_class,
                         title="C. Mean personal z-score of each indicator by health class")
    rm_df = pd.DataFrame([{
        "scope": "within-astronaut repeated-measures (rm_corr) & mixed-effects random intercept",
        **{k: str(v) if isinstance(v, list) else v for k, v in corr["repeated_measures_and_mixed_effects"].items()},
    }])
    ws_summary = {k: str(v) if isinstance(v, list) else v for k, v in corr["within_summary"].items()}
    row, _ = write_table(ws, row, rm_df,
                         title="D. Mood vs daily training hours (within-astronaut repeated-measures & mixed-effects)")
    row, _ = write_table(ws, row, pd.DataFrame([ws_summary]),
                         title="E. Within-astronaut correlation summary (95% CIs)")
    autosize(ws, max_width=44)
    return corr


def sheet_stub(wb, name):
    ws = wb.create_sheet(name)
    ws.cell(row=1, column=1, value="Pending test run: populated automatically by `python blind_test.py`.").font = TITLE_FONT
    ws.column_dimensions["A"].width = 60


# ----------------------------------------------------------------------------- main
def main():
    print("=" * 78)
    print("STEP 2 - analysis_to_excel.py (Clean Executive Formatting)")
    print("=" * 78)
    con = aim.connect_eval_readonly()
    wb = Workbook()
    wb.remove(wb.active)
    n_prof = sheet_profiles(wb, con)
    n_tel = sheet_telemetry(wb, con)
    corr = sheet_statistics(wb, con)
    sheet_stub(wb, SHEETS[3])
    sheet_stub(wb, SHEETS[4])
    con.close()
    wb.save(XLSX_PATH)
    print(f"Workbook written: {XLSX_PATH}")
    print(f"  1 {SHEETS[0]:<34} {n_prof} astronauts")
    print(f"  2 {SHEETS[1]:<34} {n_tel} telemetry rows")
    print(f"  3 {SHEETS[2]:<34} descriptive stats + mood/training correlation")
    print(f"  4 {SHEETS[3]:<34} stub (filled by blind_test.py)")
    print(f"  5 {SHEETS[4]:<34} stub (filled by blind_test.py)")


if __name__ == "__main__":
    main()
