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
# Behaviour contract for step 2 (output hardening).
# 
# A. Running from an unrelated working directory still publishes the reports
#    into the SCRIPT folder, and never into the caller's cwd.
# B. Both reports carry an identical Run_Timestamp, so a consumer can prove the
#    pair came from one run.
# C. A calendar cell starting with "=" is neutralised before it reaches a
#    spreadsheet, while the +/- percentage column is left untouched.
# D. The GUI helper reports a mismatch when the two newest files disagree.
# E. The frozen golden/v0 gate still reports 0 price-bearing diffs.

import argparse
import csv
import json
import os
import re
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
    "report_retention.py", "report_writer.py", "price_guard.py", "rms_gui.py",
    "Public holidays.csv",
]
REPORT_NAME = "hotel_name_Live_Dashboard_2026-11-15.csv"
MGR_NAME = "hotel_name_RMS_Manager_View_2026-11-15.csv"
FIXED_ENV = {
    "RMS_AS_OF_DATE": "2026/11/15",
    "RMS_AS_OF_DATETIME": "2026-11-15 17:00:00",
}


def make_sandbox(source):
    folder = tempfile.mkdtemp(prefix="rmsstep2.", dir=tempfile.gettempdir())
    for name in SOURCE_FILES:
        src = os.path.join(source, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(folder, name))
    package = os.path.join(source, PACKAGE_DIR)
    if os.path.isdir(package):
        shutil.copytree(package, os.path.join(folder, PACKAGE_DIR),
                        ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def load(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def engine_env():
    env = dict(os.environ)
    for key in ("PMS_API_KEY", "PMS_BASE_URL"):
        env.pop(key, None)
    env.update(FIXED_ENV)
    return env


def run_engine(script_dir, cwd):
    return subprocess.run(
        [sys.executable, os.path.join(script_dir, "hotel rms.py")],
        cwd=cwd, env=engine_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=120)


def gate(source, golden, candidate):
    tool = os.path.join(source, "golden", "diff_reports.py")
    proc = subprocess.run(
        [sys.executable, tool, "--baseline", os.path.join(golden, "reports"),
         "--candidate", candidate, "--strict"],
        cwd=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=120)
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return proc.returncode, tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=REPO_ROOT)
    ap.add_argument("--golden", default=os.path.join(REPO_ROOT, "golden", "v7"))
    args = ap.parse_args()
    failures = []
    summary = {}

    # --- A: publish target is the engine's output folder, not the cwd ---
    box = make_sandbox(args.source)
    elsewhere = tempfile.mkdtemp(prefix="rmscwd.", dir=tempfile.gettempdir())
    proc = run_engine(box, elsewhere)
    summary["exit"] = proc.returncode
    if proc.returncode != 0:
        failures.append("engine exit={}, tail={}".format(
            proc.returncode, proc.stdout.strip().splitlines()[-5:]))
    in_script = os.path.isfile(os.path.join(rd(box), REPORT_NAME))
    in_cwd = os.path.isfile(os.path.join(elsewhere, REPORT_NAME))
    summary["report_in_script_folder"] = in_script
    summary["report_in_caller_cwd"] = in_cwd
    if not in_script:
        failures.append("report was not published into the output folder")
    if in_cwd:
        failures.append("report leaked into the caller's working directory")

    if not in_script:
        print(json.dumps({**summary, "failures": failures}, indent=2,
                         ensure_ascii=False))
        print("CONTRACT: FAIL")
        return 1

    # --- B: both reports share one Run_Timestamp -------------------------
    tech = load(os.path.join(rd(box), REPORT_NAME))
    mgr = load(os.path.join(rd(box), MGR_NAME))
    if "Run_Timestamp" not in (tech[0] if tech else {}):
        failures.append("technical view has no Run_Timestamp column")
    if "Run_Timestamp" not in (mgr[0] if mgr else {}):
        failures.append("manager view has no Run_Timestamp column")
    if tech and mgr and "Run_Timestamp" in tech[0] and "Run_Timestamp" in mgr[0]:
        stamps = {r["Run_Timestamp"] for r in tech} | {r["Run_Timestamp"] for r in mgr}
        summary["run_timestamps"] = sorted(stamps)
        if len(stamps) != 1:
            failures.append("reports disagree on Run_Timestamp: {}".format(
                sorted(stamps)))

    # --- C: spreadsheet formula prefixes are neutralised ------------------
    # A separate sandbox keeps the injected event out of the gate comparison.
    box_c = make_sandbox(args.source)
    calendar = os.path.join(box_c, "Public holidays.csv")
    with open(calendar, "a", encoding="utf-8") as handle:
        handle.write("2026/11/20,=1+1,1.3,Special Event,N\n")
    proc2 = run_engine(box_c, elsewhere)
    if proc2.returncode != 0:
        failures.append("run with injected calendar row exit={}".format(
            proc2.returncode))
    rows = load(os.path.join(rd(box_c), REPORT_NAME))
    target = [r for r in rows
              if r.get("Stay_Date") == "2026/11/20" and r.get("Room_Type") == "Standard"]
    if not target:
        failures.append("injected event row did not reach the window")
    else:
        value = target[0].get("Event_Name", "")
        summary["injected_event_name"] = value
        if not value.startswith("'"):
            failures.append("formula-like event name was not neutralised: {!r}".format(
                value))
        # The signed percentage lives in the MANAGER view; verify that the
        # hardening step did not prepend anything to it.
        mgr_rows = load(os.path.join(rd(box_c), MGR_NAME))
        mgr_target = [r for r in mgr_rows
                      if r.get("Stay_Date") == "2026/11/20"
                      and r.get("Room_Type") == "Standard"]
        change = mgr_target[0].get("ADR_Change_vs_Base", "") if mgr_target else ""
        summary["preserved_change_value"] = change
        if not re.match(r"^[+-]?\d+\.\d%$", change):
            failures.append(
                "percentage column lost its +/- format: {!r}".format(change))

    # --- D: GUI notices a mismatched pair --------------------------------
    pair_dir = tempfile.mkdtemp(prefix="rmspair.", dir=tempfile.gettempdir())
    shutil.copy2(os.path.join(rd(box), REPORT_NAME), pair_dir)
    shutil.copy2(os.path.join(rd(box), MGR_NAME), pair_dir)
    sys.path.insert(0, box)
    try:
        import rms_gui
        same = rms_gui.report_pair_mismatch(pair_dir)
        summary["pair_same_run_message"] = same
        if same is not None:
            failures.append("matching pair was reported as a mismatch: {!r}".format(same))

        mgr_path = os.path.join(pair_dir, MGR_NAME)
        rows_m = load(mgr_path)
        cols_m = list(rows_m[0].keys())
        for row in rows_m:
            row["Run_Timestamp"] = "1999-01-01T00:00:00+0000"
        with open(mgr_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=cols_m)
            writer.writeheader()
            writer.writerows(rows_m)
        differ = rms_gui.report_pair_mismatch(pair_dir)
        summary["pair_diff_run_message"] = differ
        if not differ:
            failures.append("mismatched Run_Timestamp was NOT reported")
    except Exception as exc:
        failures.append("GUI pair check cannot be tested ({}: {})".format(
            type(exc).__name__, exc))

    # --- E: prices still frozen ------------------------------------------
    rc, line = gate(args.source, args.golden, rd(box))
    summary["gate_normal_calendar"] = line
    if rc != 0 or "DIFF PASS" not in line:
        failures.append("golden gate failed: {}".format(line))

    summary["sandbox"] = box
    summary["failures"] = failures
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("CONTRACT: {}".format("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
