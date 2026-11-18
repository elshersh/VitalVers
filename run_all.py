"""
run_all.py — Clean end-to-end reproduction runner for the NASA Space Apps 2026
Astronaut Health Monitoring prototype.

Executes every pipeline stage in dependency order from a clean state and fails
immediately if any stage exits non-zero.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ("Step 1: Generate frozen eval DB + working app DB", [sys.executable, "generate_data.py"]),
    ("Step 2A: Verify sources & verbatim quotes (>=90% fuzzy match)", [sys.executable, "tools/verify_sources.py"]),
    ("Step 2B: Generate clinical review sign-off packet (.md/.pdf/.csv)", [sys.executable, "review/generate_review_packet.py"]),
    ("Step 2C: Build Excel analysis workbook (sheets 1-3)", [sys.executable, "analysis_to_excel.py"]),
    ("Step 3: Train 5-fold GroupKFold calibrated AI model", [sys.executable, "ai_health_model.py"]),
    ("Step 4: Run blind test, tiered alerts, noise & stress tests", [sys.executable, "blind_test.py"]),
    ("Step 5A: Build offline unbiased chatbot eval datasets", [sys.executable, "tools/build_chatbot_eval_datasets.py"]),
    ("Step 5B: Run chatbot core regression & 4-source eval", [sys.executable, "test_chatbot.py"]),
    ("Step 5C: Run full automated pytest suite (Phases 1-5)", [sys.executable, "-m", "pytest", "tests", "-v"]),
]


def main() -> int:
    t0 = time.perf_counter()
    print("=" * 78)
    print("NASA Space Apps 2026 — End-to-End Clean Reproduction (`run_all.py`)")
    print("Python interpreter:", sys.executable)
    print("Working directory: ", ROOT)
    print("=" * 78)

    for label, cmd in STEPS:
        step_start = time.perf_counter()
        print(f"\n>>> {label}")
        print(f"    Command: {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=ROOT)
        elapsed = time.perf_counter() - step_start
        if proc.returncode != 0:
            print(f"\n[ABORT] {label} failed with exit code {proc.returncode} after {elapsed:.2f}s.")
            return proc.returncode
        print(f"[OK] {label} completed in {elapsed:.2f}s.")

    total_elapsed = time.perf_counter() - t0
    print("\n" + "=" * 78)
    print(f"[SUCCESS] Full pipeline reproduced cleanly in {total_elapsed:.2f}s.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
