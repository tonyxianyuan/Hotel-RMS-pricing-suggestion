"""Behaviour contract shipped with the project.

Verification net, not a unit-test framework: each module copies the real
files into a temporary sandbox, runs them, and asserts what a hotelier could
check by hand. Nothing under test is written to the repository.

Run one directly:
    py tests/contract_{name}.py

Run all of them:
    py tests/run_all.py
"""
import os

# The contracts live in tests/ and act on the project one level up.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Behaviour contract for step 3 (run ledger).
# 
# Runs against a COPY of the engine in a temp sandbox. Verifies:
#   1. the technical view exposes every factor needed to reproduce the price
#   2. the price can be recomputed by multiplication from those columns
#   3. engine warnings survive after the process exits (persistent run log)
#   4. Action agrees with the displayed percentage change
#   5. the frozen golden/v0 gate still reports 0 price-bearing diffs

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

def rd(folder):
    """Report folder: output/ once the engine writes there, else the sandbox."""
    out = os.path.join(folder, "output")
    return out if os.path.isdir(out) else folder


PACKAGE_DIR = "rms_core"
SOURCE_FILES = [
    "hotel rms.py", "event_calendar.py", "timezone_config.py",
    "report_retention.py", "report_writer.py", "price_guard.py", "Public holidays.csv",
]
FACTOR_COLS = [
    "Weekend_Factor", "Event_Factor", "Occupancy_Factor",
    "Lead_Time_Factor", "Booking_Pace_Factor", "Competitor_Factor",
    "Competitor_Ratio", "Pace_Ratio", "Effective_Occupancy",
    "Current_OTB_Rooms", "Hist_OTB_At_Same_LeadTime", "RoomType_Factor",
    "Model_ADR_Before_Adjustments", "Post_Model_Adjustment_Factor",
]
PRODUCT_COLS = [
    "Weekend_Factor", "Event_Factor", "Occupancy_Factor",
    "Lead_Time_Factor", "Booking_Pace_Factor", "Competitor_Factor",
    "Post_Model_Adjustment_Factor",
]


def load(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def expected_action(shown):
    if shown >= 25.0:
        return "Raise Aggressively"
    if shown >= 10.0:
        return "Raise Rate"
    if shown > -10.0:
        return "Hold Rate"
    return "Discount"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=REPO_ROOT)
    ap.add_argument("--golden", default=os.path.join(REPO_ROOT, "golden", "v7"))
    args = ap.parse_args()

    sandbox = tempfile.mkdtemp(prefix="rmsstep3.", dir=tempfile.gettempdir())
    for name in SOURCE_FILES:
        src = os.path.join(args.source, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(sandbox, name))
    package = os.path.join(args.source, PACKAGE_DIR)
    if os.path.isdir(package):
        shutil.copytree(package, os.path.join(sandbox, PACKAGE_DIR),
                        ignore=shutil.ignore_patterns("__pycache__"))

    env = dict(os.environ)
    for key in ("PMS_API_KEY", "PMS_BASE_URL"):
        env.pop(key, None)
    env["RMS_AS_OF_DATE"] = "2026/11/15"
    env["RMS_AS_OF_DATETIME"] = "2026-11-15 17:00:00"
    proc = subprocess.run(
        [sys.executable, "hotel rms.py"], cwd=sandbox, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=120)

    failures = []
    if proc.returncode != 0:
        failures.append("engine exit={}, tail={}".format(
            proc.returncode, proc.stdout.strip().splitlines()[-5:]))

    tech_path = os.path.join(rd(sandbox), "hotel_name_Live_Dashboard_2026-11-15.csv")
    mgr_path = os.path.join(rd(sandbox), "hotel_name_RMS_Manager_View_2026-11-15.csv")
    if not os.path.isfile(tech_path) or not os.path.isfile(mgr_path):
        failures.append("reports missing")
        print(json.dumps({"sandbox": sandbox, "failures": failures}, indent=2))
        print("CONTRACT: FAIL")
        return 1

    tech = load(tech_path)
    mgr = load(mgr_path)
    columns = list(tech[0].keys()) if tech else []
    missing = [c for c in FACTOR_COLS if c not in columns]
    if missing:
        failures.append("technical view missing factor columns: {}".format(missing))

    if not missing:
        bad = []
        for row in tech:
            try:
                value = float(row["Base_Room_ADR"])
                for col in PRODUCT_COLS:
                    value *= float(row[col])
                if not math.isclose(value, float(row["Recommended_ADR"]),
                                    rel_tol=1e-9, abs_tol=1e-6):
                    bad.append((row["Stay_Date"], row["Room_Type"], value,
                                row["Recommended_ADR"]))
            except (ValueError, KeyError, TypeError) as exc:
                bad.append((row.get("Stay_Date"), row.get("Room_Type"), str(exc)))
        if bad:
            failures.append("price cannot be recomputed from factor columns: "
                            "{} of {} rows differ; example={}".format(
                                len(bad), len(tech), bad[:2]))

    log_path = os.path.join(rd(sandbox), "rms_run.log")
    if not os.path.isfile(log_path):
        failures.append("no persistent run log (rms_run.log missing)")
    else:
        with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
            log_text = handle.read()
        if "[WARN]" not in log_text:
            failures.append("run log does not contain [WARN] lines")
        if "Pricing cycle complete" not in log_text:
            failures.append("run log does not contain the cycle completion line")

    mismatches = []
    for row in mgr:
        try:
            shown = float(row["ADR_Change_vs_Base"].replace("%", "").replace("+", ""))
        except ValueError:
            continue
        if expected_action(shown) != row["Action"]:
            mismatches.append((row["Stay_Date"], row["Room_Type"],
                               shown, row["Action"]))
    if mismatches:
        failures.append("Action disagrees with displayed change: {}".format(
            mismatches[:3]))

    diff_tool = os.path.join(args.source, "golden", "diff_reports.py")
    gate = subprocess.run(
        [sys.executable, diff_tool,
         "--baseline", os.path.join(args.golden, "reports"),
         "--candidate", rd(sandbox), "--strict"],
        cwd=args.source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=120)
    gate_line = gate.stdout.strip().splitlines()[-1] if gate.stdout.strip() else ""
    if gate.returncode != 0 or "DIFF PASS" not in gate.stdout:
        failures.append("golden gate failed: {} | {}".format(gate.returncode, gate_line))

    summary = {
        "sandbox": sandbox,
        "engine_exit": proc.returncode,
        "tech_column_count": len(columns),
        "missing_factor_columns": missing,
        "run_log_exists": os.path.isfile(log_path),
        "gate": gate_line,
        "failures": failures,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("CONTRACT: {}".format("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
