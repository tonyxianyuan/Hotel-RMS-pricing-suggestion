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
# Behaviour contract for the layout change (library package).
# 
# A. The five reuse-only modules live in rms_core/ and no longer sit at the root.
# B. The three entry points stay at the root, unchanged in name, so the .bat
#    launchers and the scheduler keep working.
# C. Every entry point still imports from its own directory (the way the .bat
#    files start it) and from an unrelated working directory.
# D. A full pricing cycle run from an unrelated directory still publishes both
#    reports and still reproduces the frozen prices.
# E. The golden diff tool still runs.

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

PACKAGE = "rms_core"
LIBRARY_MODULES = [
    "event_calendar.py", "timezone_config.py", "report_writer.py",
    "report_retention.py", "price_guard.py",
]
ENTRY_POINTS = ["hotel rms.py", "rms_gui.py", "scheduler.py"]
EXTRA_FILES = ["Public holidays.csv"]
TECH_NAME = "hotel_name_Live_Dashboard_2026-11-15.csv"
MGR_NAME = "hotel_name_RMS_Manager_View_2026-11-15.csv"
FIXED_ENV = {
    "RMS_AS_OF_DATE": "2026/11/15",
    "RMS_AS_OF_DATETIME": "2026-11-15 17:00:00",
}


def copy_tree(source, folder):
    """Copy the source layout into a sandbox, preserving rms_core/."""
    for name in os.listdir(source):
        full = os.path.join(source, name)
        if os.path.isfile(full):
            shutil.copy2(full, os.path.join(folder, name))
    package = os.path.join(source, PACKAGE)
    if os.path.isdir(package):
        shutil.copytree(
            package, os.path.join(folder, PACKAGE),
            ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def make_sandbox(source):
    return copy_tree(source, tempfile.mkdtemp(
        prefix="rmslayout.", dir=tempfile.gettempdir()))


def engine_env():
    env = dict(os.environ)
    for key in ("PMS_API_KEY", "PMS_BASE_URL"):
        env.pop(key, None)
    env.update(FIXED_ENV)
    return env


def run(cmd, cwd, env=None, timeout=180):
    return subprocess.run(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", timeout=timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=REPO_ROOT)
    ap.add_argument("--golden", default=os.path.join(REPO_ROOT, "golden", "v7"))
    args = ap.parse_args()
    failures = []
    summary = {}

    # --- A: package layout ------------------------------------------------
    package_dir = os.path.join(args.source, PACKAGE)
    init_file = os.path.join(package_dir, "__init__.py")
    summary["package_exists"] = os.path.isdir(package_dir)
    summary["package_init"] = os.path.isfile(init_file)
    if not os.path.isdir(package_dir):
        failures.append("rms_core/ does not exist next to the entry points")
    if not os.path.isfile(init_file):
        failures.append("rms_core/ has no __init__.py")

    moved, still_at_root = [], []
    for name in LIBRARY_MODULES:
        if os.path.isfile(os.path.join(package_dir, name)):
            moved.append(name)
        if os.path.isfile(os.path.join(args.source, name)):
            still_at_root.append(name)
    summary["in_package"] = moved
    summary["still_at_root"] = still_at_root
    for name in LIBRARY_MODULES:
        if name not in moved:
            failures.append("{} is not inside rms_core/".format(name))
    if still_at_root:
        failures.append("duplicate copy still at the root: {}".format(
            ", ".join(still_at_root)))

    # --- B: entry points stay put ----------------------------------------
    missing_entries = [n for n in ENTRY_POINTS
                       if not os.path.isfile(os.path.join(args.source, n))]
    summary["entry_points"] = [n for n in ENTRY_POINTS
                               if os.path.isfile(os.path.join(args.source, n))]
    if missing_entries:
        failures.append("entry point(s) missing from the root: {}".format(
            ", ".join(missing_entries)))
    for name in ("Run_Pricing_Now.bat", "Start_Pricing_UI.bat"):
        if not os.path.isfile(os.path.join(args.source, name)):
            failures.append("{} missing from the root".format(name))

    # --- C: imports survive both launch styles ---------------------------
    box = make_sandbox(args.source)
    elsewhere = tempfile.mkdtemp(prefix="rmscwd.", dir=tempfile.gettempdir())
    summary["sandbox"] = box

    probe = (
        "import rms_core.event_calendar, rms_core.timezone_config, "
        "rms_core.report_writer, rms_core.report_retention, rms_core.price_guard; "
        "print('package imports ok')"
    )
    proc = run([sys.executable, "-c", probe], cwd=elsewhere,
               env=dict(os.environ, PYTHONPATH=box))
    summary["package_import"] = proc.stdout.strip().splitlines()[-1:]
    if proc.returncode != 0:
        failures.append("rms_core is not importable with only APP_DIR on the "
                        "path: {}".format(proc.stdout.strip()[-400:]))

    for entry in ("hotel rms.py", "rms_gui.py", "scheduler.py"):
        # The .bat launchers start these by file name from the script folder.
        proc = run([sys.executable, "-m", "py_compile", entry], cwd=box)
        if proc.returncode != 0:
            failures.append("{} does not compile: {}".format(entry, proc.stdout[-300:]))

    # Import the GUI from its own folder (this is how the .bat starts it).
    proc = run([sys.executable, "-c", "import rms_gui; print('gui import ok')"],
               cwd=box)
    summary["gui_import"] = proc.stdout.strip().splitlines()[-1:]
    if proc.returncode != 0:
        failures.append("rms_gui.py cannot be imported from the script folder: "
                        "{}".format(proc.stdout.strip()[-400:]))

    proc = run([sys.executable, "-c", "import scheduler; print('scheduler import ok')"],
               cwd=box)
    summary["scheduler_import"] = proc.stdout.strip().splitlines()[-1:]
    if proc.returncode != 0:
        failures.append("scheduler.py cannot be imported from the script folder: "
                        "{}".format(proc.stdout.strip()[-400:]))

    # --- D: a real cycle from an unrelated directory ----------------------
    proc = run([sys.executable, os.path.join(box, "hotel rms.py")],
               cwd=elsewhere, env=engine_env())
    summary["engine_exit"] = proc.returncode
    if proc.returncode != 0:
        failures.append("engine exit={} tail={}".format(
            proc.returncode, proc.stdout.strip().splitlines()[-6:]))

    report_dir = os.path.join(box, "output")
    if not os.path.isdir(report_dir):
        report_dir = box
    summary["report_dir"] = os.path.basename(report_dir)
    for name in (TECH_NAME, MGR_NAME):
        if not os.path.isfile(os.path.join(report_dir, name)):
            failures.append("{} was not published into {}".format(
                name, summary["report_dir"]))
    leaked = [n for n in (TECH_NAME, MGR_NAME)
              if os.path.isfile(os.path.join(elsewhere, n))]
    if leaked:
        failures.append("reports leaked into the caller's cwd: {}".format(leaked))

    # --- E: golden gate ---------------------------------------------------
    tool = os.path.join(args.source, "golden", "diff_reports.py")
    proc = run([sys.executable, tool, "--baseline",
                os.path.join(args.golden, "reports"), "--candidate", report_dir,
                "--strict"], cwd=args.source)
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    summary["gate"] = line
    if proc.returncode != 0 or "DIFF PASS" not in line:
        failures.append("golden gate failed: {}".format(line))

    summary["failures"] = failures
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print("CONTRACT: {}".format("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
