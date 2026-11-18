"""Simulated live telemetry stream helper for Vitalverse (Phase 4 DEMO feed)."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import DB_PATH  # noqa: E402
from backend.database import init_web_tables  # noqa: E402
from backend.services.model_service import ModelService  # noqa: E402
from backend.services.prediction_service import advance_demo_day  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate next mission telemetry day(s) and evaluate AI model alerts (DEMO).")
    parser.add_argument("--astronaut-id", default="A001", help="Target astronaut_id (default: A001).")
    parser.add_argument("--days", type=int, default=1, help="Number of simulated DEMO days to append (1-30).")
    parser.add_argument("--scenario", choices=("auto", "normal", "warning", "danger"), default="auto", help="Simulated vital pattern.")
    args = parser.parse_args()

    days = max(1, min(30, int(args.days)))
    db_file = Path(os.environ.get("ASTRO_HEALTH_DB") or DB_PATH)
    con = sqlite3.connect(str(db_file), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    init_web_tables(con)

    model_service = ModelService()
    try:
        for step in range(days):
            res = advance_demo_day(con, model_service, args.astronaut_id, scenario=args.scenario)
            alert_id = res["alert_created"]["id"] if res.get("alert_created") else None
            print(
                f"[DEMO {step + 1}/{days}] astronaut={res['astronaut_id']} day={res['mission_day']} "
                f"class={res['predicted_class']} confidence={res['confidence']:.2f} "
                f"scenario={res['scenario']} alert_id={alert_id}"
            )
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
