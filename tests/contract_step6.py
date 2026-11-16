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
# Behaviour contract for step 6 (guardrail hardening).
# 
# A. The shipped calendar still produces exactly the frozen baseline prices.
# B. The run states its calendar coverage and warns that no movable (one-off)
#    events are maintained for a year covered by the window.
# C. An absurd Event_Factor (15.00) cannot inflate a price beyond the absolute
#    ceiling: MAX_ADR <= Base x 4.00, the row is flagged as capped, and the
#    engine warns about the ceiling instead of silently pricing 15x.
# D. A NaN Event_Factor stops the run with a line number and publishes nothing.
# E. An infinite Event_Factor stops the run with a line number and publishes
#    nothing.
# F. price_guard.find_violations() is silent on a healthy report and detects a
#    non-finite price, a below-floor price and a duplicated stay key.

import argparse
import csv
import json
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
    "report_retention.py", "report_writer.py", "rms_gui.py",
    "price_guard.py", "Public holidays.csv",
]
TECH_NAME = "hotel_name_Live_Dashboard_2026-11-15.csv"
MGR_NAME = "hotel_name_RMS_Manager_View_2026-11-15.csv"
FIXED_ENV = {
    "RMS_AS_OF_DATE": "2026/11/15",
    "RMS_AS_OF_DATETIME": "2026-11-15 17:00:00",
}
PRICE_COLUMNS = (
    "MIN_ADR", "MAX_ADR", "Recommended_ADR", "Final_ADR",
    "Model_ADR_Before_Adjustments", "Post_Model_Adjustment_Factor",
    "Expected_RevPAR",
)


def make_sandbox(source, calendar_extra=None):
    folder = tempfile.mkdtemp(prefix="rmsstep6.", dir=tempfile.gettempdir())
    for name in SOURCE_FILES:
        src = os.path.join(source, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(folder, name))
    package = os.path.join(source, PACKAGE_DIR)
    if os.path.isdir(package):
        shutil.copytree(package, os.path.join(folder, PACKAGE_DIR),
                        ignore=shutil.ignore_patterns("__pycache__"))
    if calendar_extra:
        with open(os.path.join(folder, "Public holidays.csv"), "a",
                  encoding="utf-8") as handle:
            handle.write(calendar_extra)
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


def run_engine(script_dir, cwd=None):
    return subprocess.run(
        [sys.executable, os.path.join(script_dir, "hotel rms.py")],
        cwd=cwd or script_dir, env=engine_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=180)


def gate(source, golden, candidate):
    tool = os.path.join(source, "golden", "diff_reports.py")
    proc = subprocess.run(
        [sys.executable, tool, "--baseline", os.path.join(golden, "reports"),
         "--candidate", candidate, "--strict"],
        cwd=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=120)
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return proc.returncode, tail


def non_finite_cells(rows, columns):
    bad = []
    for row in rows:
        for column in columns:
            raw = row.get(column, "")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                bad.append((row.get("Stay_Date"), row.get("Room_Type"), column, raw))
                continue
            if value != value or value in (float("inf"), float("-inf")):
                bad.append((row.get("Stay_Date"), row.get("Room_Type"), column, raw))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=REPO_ROOT)
    ap.add_argument("--golden", default=os.path.join(REPO_ROOT, "golden", "v7"))
    args = ap.parse_args()
    failures = []
    summary = {}

    # --- A + B: shipped calendar keeps prices, states coverage ------------
    box = make_sandbox(args.source)
    proc = run_engine(box)
    text = proc.stdout or ""
    summary["normal_exit"] = proc.returncode
    if proc.returncode != 0:
        failures.append("normal run exit={} tail={}".format(
            proc.returncode, text.strip().splitlines()[-6:]))

    rc, line = gate(args.source, args.golden, rd(box))
    summary["gate_shipped_calendar"] = line
    if rc != 0 or "DIFF PASS" not in line:
        failures.append("golden gate failed on the shipped calendar: {}".format(line))

    coverage_lines = [ln for ln in text.splitlines() if "Calendar coverage:" in ln]
    summary["coverage_lines"] = coverage_lines
    if not coverage_lines:
        failures.append("run does not report calendar coverage")
    elif not any("stay dates carry an event factor" in ln for ln in coverage_lines):
        failures.append("coverage line does not state how many stay dates are covered")

    movable_warnings = [ln for ln in text.splitlines()
                        if "[WARN]" in ln and "one-off" in ln.lower()]
    summary["movable_event_warnings"] = movable_warnings
    if not movable_warnings:
        failures.append(
            "no warning about missing one-off (movable) events was emitted")

    # --- C: absurd factor is bounded by the absolute ceiling --------------
    box_c = make_sandbox(args.source, "2026/11/20,Extreme Test,15.0,Special Event,N\n")
    proc_c = run_engine(box_c)
    text_c = proc_c.stdout or ""
    summary["absurd_exit"] = proc_c.returncode
    if proc_c.returncode != 0:
        failures.append("absurd-factor run exit={} tail={}".format(
            proc_c.returncode, text_c.strip().splitlines()[-6:]))
    tech_c = load(os.path.join(rd(box_c), TECH_NAME)) if os.path.isfile(
        os.path.join(rd(box_c), TECH_NAME)) else []
    target = [r for r in tech_c
              if r.get("Stay_Date") == "2026/11/20" and r.get("Room_Type") == "Standard"]
    if not target:
        failures.append("absurd-factor row did not reach the report")
    else:
        row = target[0]
        base = float(row["Base_Room_ADR"])
        ratio = float(row["MAX_ADR"]) / base
        summary["absurd_event_factor"] = row.get("Event_Factor")
        summary["absurd_max_ratio"] = round(ratio, 4)
        summary["absurd_final_adr"] = row.get("Final_ADR")
        summary["absurd_cap_flag"] = row.get("Rate_Cap_Applied")
        if ratio > 4.0 + 1e-9:
            failures.append(
                "absolute ceiling not enforced: MAX_ADR/Base = {:.4f}".format(ratio))
        if row.get("Rate_Cap_Applied") != "True":
            failures.append("clipped row is not flagged by Rate_Cap_Applied")
        if float(row["Final_ADR"]) > float(row["MAX_ADR"]) + 0.5:
            failures.append("Final_ADR exceeds MAX_ADR on the absurd-factor row")
    ceiling_warnings = [ln for ln in text_c.splitlines()
                        if "[WARN]" in ln and "ceiling" in ln.lower()]
    summary["ceiling_warnings"] = ceiling_warnings
    if not ceiling_warnings:
        failures.append("engine did not warn that the absolute ceiling was applied")
    bad_cells = non_finite_cells(tech_c, PRICE_COLUMNS)
    summary["non_finite_cells_absurd"] = bad_cells[:5]
    if bad_cells:
        failures.append("non-finite price cells in the absurd-factor report")

    # --- D + E: non-finite factors stop the run --------------------------
    for label, bad_value in (("nan", "nan"), ("inf", "inf")):
        box_bad = make_sandbox(
            args.source, "2026/11/21,Broken Input,{},Special Event,N\n".format(bad_value))
        proc_bad = run_engine(box_bad)
        text_bad = proc_bad.stdout or ""
        published = os.path.isfile(os.path.join(rd(box_bad), TECH_NAME)) or os.path.isfile(
            os.path.join(rd(box_bad), MGR_NAME))
        summary["{}_exit".format(label)] = proc_bad.returncode
        summary["{}_published".format(label)] = published
        summary["{}_message".format(label)] = [
            ln for ln in text_bad.splitlines() if "Event_Factor" in ln][:2]
        if proc_bad.returncode == 0:
            failures.append("Event_Factor={} did not stop the run".format(bad_value))
        if published:
            failures.append("Event_Factor={} still published a report".format(bad_value))
        if not any("finite" in ln.lower() for ln in text_bad.splitlines()):
            failures.append(
                "Event_Factor={} failed without a clear 'finite' message".format(bad_value))
        if not any("Line 47" in ln or " Line " in ln for ln in text_bad.splitlines()):
            failures.append(
                "Event_Factor={} failure carries no calendar line number".format(bad_value))

    # --- G: a duplicate date with a different factor is named --------------
    box_g = make_sandbox(
        args.source,
        "2026/11/22,Duplicate A,1.30,Special Event,N\n"
        "2026/11/22,Duplicate B,1.80,Special Event,N\n")
    proc_g = run_engine(box_g)
    text_g = proc_g.stdout or ""
    dup_warnings = [ln for ln in text_g.splitlines()
                    if "[WARN]" in ln and "repeats line" in ln]
    summary["duplicate_warnings"] = dup_warnings
    if proc_g.returncode != 0:
        failures.append("duplicate-row run exit={}".format(proc_g.returncode))
    if not dup_warnings:
        failures.append("conflicting duplicate date was silently overridden")
    tech_g = load(os.path.join(rd(box_g), TECH_NAME)) if os.path.isfile(
        os.path.join(rd(box_g), TECH_NAME)) else []
    dup_rows = [r for r in tech_g if r.get("Stay_Date") == "2026/11/22"]
    summary["duplicate_effective_factor"] = (
        dup_rows[0].get("Event_Factor") if dup_rows else None)
    if dup_rows and abs(float(dup_rows[0]["Event_Factor"]) - 1.80) > 1e-9:
        failures.append("last row did not win on a duplicated date")

    # --- H: a legitimate high factor keeps its event headroom -------------
    # 2.20 must still price at 2.20 x 1.60 = 3.52x, i.e. the new absolute
    # ceiling must not flatten genuine peak nights.
    box_h = make_sandbox(args.source, "2026/11/23,Motor Race,2.2,Special Event,N\n")
    proc_h = run_engine(box_h)
    text_h = proc_h.stdout or ""
    tech_h = load(os.path.join(rd(box_h), TECH_NAME)) if os.path.isfile(
        os.path.join(rd(box_h), TECH_NAME)) else []
    race = [r for r in tech_h
            if r.get("Stay_Date") == "2026/11/23" and r.get("Room_Type") == "Standard"]
    if proc_h.returncode != 0 or not race:
        failures.append("legitimate 2.20 event factor did not produce a report")
    else:
        ratio_h = float(race[0]["MAX_ADR"]) / float(race[0]["Base_Room_ADR"])
        summary["event_220_max_ratio"] = round(ratio_h, 4)
        if abs(ratio_h - 3.52) > 1e-6:
            failures.append(
                "legitimate event headroom was clipped: MAX_ADR/Base = {:.4f}, "
                "expected 3.5200".format(ratio_h))
    summary["absurd_ceiling_warning_on_220"] = [
        ln for ln in text_h.splitlines() if "Absolute rate ceiling" in ln]
    if summary["absurd_ceiling_warning_on_220"]:
        failures.append("absolute ceiling warned on a legitimate 2.20 event factor")

    # --- F: price_guard detects broken frames ----------------------------
    sys.path.insert(0, args.source)
    try:
        from rms_core import price_guard
    except Exception as exc:
        failures.append("price_guard cannot be imported ({}: {})".format(
            type(exc).__name__, exc))
        price_guard = None

    if price_guard is not None:
        # Use this run's report, not the frozen baseline: golden/v0 predates
        # the audit columns, so it has no Model_ADR_Before_Adjustments.
        loaded = load(os.path.join(rd(box), TECH_NAME))
        import pandas as pd
        healthy = pd.DataFrame(loaded)
        for column in price_guard.PRICE_COLUMNS:
            healthy[column] = pd.to_numeric(healthy[column])
        healthy["Stay_Date"] = pd.to_datetime(healthy["Stay_Date"], format="%Y/%m/%d")
        clean = price_guard.find_violations(healthy)
        summary["guard_clean_violations"] = clean
        if clean:
            failures.append("price_guard flagged a healthy report: {}".format(clean[:3]))

        broken = healthy.copy()
        broken.loc[0, "Final_ADR"] = float("inf")
        broken.loc[1, "Final_ADR"] = broken.loc[1, "MIN_ADR"] - 50.0
        broken = pd.concat([broken, broken.iloc[[2]]], ignore_index=True)
        found = price_guard.find_violations(broken)
        summary["guard_broken_violations"] = found
        if not any("finite" in item.lower() for item in found):
            failures.append("price_guard missed a non-finite price")
        if not any("floor" in item.lower() or "MIN_ADR" in item for item in found):
            failures.append("price_guard missed a below-floor price")
        if not any("duplicate" in item.lower() for item in found):
            failures.append("price_guard missed a duplicated stay key")

    summary["failures"] = failures
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print("CONTRACT: {}".format("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
