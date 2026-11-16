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
# Behaviour contract for step 1 (data provenance honesty).
# 
# All runs happen in temp sandboxes against a COPY of the engine.
# 
# A. DEMO run: an explicit provenance column exists, Data_Mode stays DEMO,
#    and the frozen golden/v0 gate still reports 0 price-bearing diffs.
# B. LIVE credentials but an unreachable PMS: the report must NOT claim LIVE,
#    the provenance column must say the data fell back to synthetic, and the
#    persistent run log must say so. Prices must still match the DEMO baseline
#    (the fallback is the same synthetic feed).
# C. The GUI must not pass back-test overrides to the engine child process.
# D. The GUI banner must understand the fallback mode.

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
    "report_retention.py", "report_writer.py", "price_guard.py", "rms_gui.py",
    "Public holidays.csv",
]
REPORT_NAME = "hotel_name_Live_Dashboard_2026-11-15.csv"
FALLBACK_MODE = "PMS_FALLBACK_SYNTHETIC_MARKET"


def load(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def make_sandbox(source):
    folder = tempfile.mkdtemp(prefix="rmsstep1.", dir=tempfile.gettempdir())
    for name in SOURCE_FILES:
        src = os.path.join(source, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(folder, name))
    package = os.path.join(source, PACKAGE_DIR)
    if os.path.isdir(package):
        shutil.copytree(package, os.path.join(folder, PACKAGE_DIR),
                        ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def run_engine(folder, extra_env):
    env = dict(os.environ)
    for key in ("PMS_API_KEY", "PMS_BASE_URL"):
        env.pop(key, None)
    env["RMS_AS_OF_DATE"] = "2026/11/15"
    env["RMS_AS_OF_DATETIME"] = "2026-11-15 17:00:00"
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "hotel rms.py"], cwd=folder, env=env,
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

    # --- Scenario A: ordinary DEMO run -------------------------------------
    box_a = make_sandbox(args.source)
    proc_a = run_engine(box_a, {})
    summary["demo_exit"] = proc_a.returncode
    if proc_a.returncode != 0:
        failures.append("DEMO run exit={}".format(proc_a.returncode))
    rows_a = load(os.path.join(rd(box_a), REPORT_NAME)) if os.path.isfile(
        os.path.join(rd(box_a), REPORT_NAME)) else []
    cols_a = list(rows_a[0].keys()) if rows_a else []
    if "Data_Sources" not in cols_a:
        failures.append("technical view has no Data_Sources provenance column")
    if rows_a and rows_a[0].get("Data_Mode") != "DEMO":
        failures.append("DEMO run changed Data_Mode to {!r}".format(
            rows_a[0].get("Data_Mode")))
    if rows_a and "Data_Sources" in cols_a:
        sources = rows_a[0]["Data_Sources"]
        if "synthetic" not in sources.lower() or "constant" not in sources.lower():
            failures.append("Data_Sources does not mark synthetic inputs: {!r}".format(
                sources))
        summary["demo_sources"] = sources
    rc_a, line_a = gate(args.source, args.golden, rd(box_a))
    summary["demo_gate"] = line_a
    if rc_a != 0 or "DIFF PASS" not in line_a:
        failures.append("DEMO run broke the golden gate: {}".format(line_a))

    # --- Scenario B: LIVE credentials, unreachable PMS ---------------------
    box_b = make_sandbox(args.source)
    proc_b = run_engine(box_b, {
        "PMS_API_KEY": "INTEGRATION_TEST_KEY",
        "PMS_BASE_URL": "http://127.0.0.1:9/api",
        "NO_PROXY": "127.0.0.1",
    })
    summary["live_fallback_exit"] = proc_b.returncode
    if proc_b.returncode != 0:
        failures.append("LIVE fallback run exit={}".format(proc_b.returncode))
    path_b = os.path.join(rd(box_b), REPORT_NAME)
    rows_b = load(path_b) if os.path.isfile(path_b) else []
    mode_b = rows_b[0].get("Data_Mode") if rows_b else None
    summary["live_fallback_mode"] = mode_b
    if mode_b != FALLBACK_MODE:
        failures.append("unreachable PMS still reported mode {!r} (expected {!r})".format(
            mode_b, FALLBACK_MODE))
    sources_b = rows_b[0].get("Data_Sources", "") if rows_b else ""
    summary["live_fallback_sources"] = sources_b
    if "synthetic_fallback" not in sources_b:
        failures.append("fallback not visible in Data_Sources: {!r}".format(sources_b))
    log_path = os.path.join(rd(box_b), "rms_run.log")
    log_text = ""
    if os.path.isfile(log_path):
        with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
            log_text = handle.read()
    if "PMS" not in log_text or "fallback" not in log_text.lower():
        failures.append("persistent run log does not explain the PMS fallback")
    rc_b, line_b = gate(args.source, args.golden, rd(box_b))
    summary["live_fallback_gate"] = line_b
    if rc_b != 0 or "DIFF PASS" not in line_b:
        failures.append("fallback changed prices vs DEMO baseline: {}".format(line_b))

    # --- Scenario C: GUI must strip back-test overrides --------------------
    sys.path.insert(0, box_a)
    try:
        import rms_gui
        os.environ["RMS_AS_OF_DATE"] = "2020/01/01"
        os.environ["RMS_AS_OF_DATETIME"] = "2020-01-01 09:00:00"
        env = rms_gui.build_engine_env()
        leaked = [k for k in ("RMS_AS_OF_DATE", "RMS_AS_OF_DATETIME") if k in env]
        if leaked:
            failures.append("GUI passes back-test overrides to engine: {}".format(leaked))
        if env.get("PYTHONIOENCODING") != "utf-8":
            failures.append("GUI lost PYTHONIOENCODING while cleaning env")
        summary["env_clean"] = not leaked
    except Exception as exc:
        failures.append("GUI env contract cannot be tested ({}: {})".format(
            type(exc).__name__, exc))
    finally:
        os.environ.pop("RMS_AS_OF_DATE", None)
        os.environ.pop("RMS_AS_OF_DATETIME", None)

    # --- Scenario D: banner knows the fallback mode -----------------------
    with open(os.path.join(args.source, "rms_gui.py"), "r",
              encoding="utf-8") as handle:
        gui_source = handle.read()
    if FALLBACK_MODE not in gui_source:
        failures.append("GUI banner has no branch for {}".format(FALLBACK_MODE))

    summary["sandbox_demo"] = box_a
    summary["sandbox_fallback"] = box_b
    summary["failures"] = failures
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("CONTRACT: {}".format("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
