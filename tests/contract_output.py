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
# Behaviour contract for the output-layout change.
# 
# A. A fresh cycle writes both reports and the run log into output/, and leaves
#    no report or log behind in the program folder.
# B. Reports, logs and archive/ that predate output/ are MOVED into output/
#    exactly once, never deleted, and input data is never touched.
# C. A second cycle is idempotent: exit 0, same location, no duplicates.
# D. rms_core/paths.py is the single source of truth; in particular the timezone
#    settings file stays beside the entry points, not inside the package.
# E. The staff UI reads from output/ by default.
# F. Report retention archives into output/archive/.
# G. The frozen prices are still reproduced.

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ENTRY = "hotel rms.py"
TECH = "hotel_name_Live_Dashboard_{}.csv"
MGR = "hotel_name_RMS_Manager_View_{}.csv"
FIXED_ENV = {
    "RMS_AS_OF_DATE": "2026/11/15",
    "RMS_AS_OF_DATETIME": "2026-11-15 17:00:00",
}


def copy_tree(source, folder):
    for name in os.listdir(source):
        full = os.path.join(source, name)
        if os.path.isfile(full):
            shutil.copy2(full, os.path.join(folder, name))
    package = os.path.join(source, "rms_core")
    if os.path.isdir(package):
        shutil.copytree(package, os.path.join(folder, "rms_core"),
                        ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def make_sandbox(source):
    return copy_tree(source, tempfile.mkdtemp(
        prefix="rmsout.", dir=tempfile.gettempdir()))


def listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def report_env(fixed=True):
    env = dict(os.environ)
    for key in ("PMS_API_KEY", "PMS_BASE_URL"):
        env.pop(key, None)
    for key in ("RMS_AS_OF_DATE", "RMS_AS_OF_DATETIME"):
        env.pop(key, None)
    if fixed:
        env.update(FIXED_ENV)
    return env


def run(cmd, cwd, env=None, timeout=180):
    return subprocess.run(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", timeout=timeout)


def write_report(folder, stem, name, when):
    """Create a minimal but realistic report pair for retention/migration."""
    import csv
    path = os.path.join(folder, name.format(when))
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Stay_Date", "Room_Type", "Final_ADR", "Run_Timestamp",
                         "Data_Mode", "Data_Sources"])
        writer.writerow([when.replace("-", "/"), "Standard", "135.0",
                         when + "T00:00:00+0000", "DEMO", "x"])
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=REPO_ROOT)
    ap.add_argument("--golden", default=os.path.join(REPO_ROOT, "golden", "v7"))
    args = ap.parse_args()
    failures = []
    summary = {}

    # --- A: fresh cycle writes into output/ -------------------------------
    box = make_sandbox(args.source)
    elsewhere = tempfile.mkdtemp(prefix="rmscwd.", dir=tempfile.gettempdir())
    summary["sandbox"] = box
    proc = run([sys.executable, os.path.join(box, ENTRY)], cwd=elsewhere,
               env=report_env())
    summary["fresh_exit"] = proc.returncode
    if proc.returncode != 0:
        failures.append("fresh cycle exit={} tail={}".format(
            proc.returncode, proc.stdout.strip().splitlines()[-6:]))

    out_dir = os.path.join(box, "output")
    summary["output_dir_exists"] = os.path.isdir(out_dir)
    if not os.path.isdir(out_dir):
        failures.append("output/ was not created")
    for name in (TECH.format("2026-11-15"), MGR.format("2026-11-15")):
        if not os.path.isfile(os.path.join(out_dir, name)):
            failures.append("{} not found in output/".format(name))
    for name in ("rms_run.log",):
        if not os.path.isfile(os.path.join(out_dir, name)):
            failures.append("{} not found in output/".format(name))
    leftovers = [n for n in listdir(box)
                 if n.startswith("hotel_name_") or n == "rms_run.log"]
    summary["root_leftovers"] = leftovers
    if leftovers:
        failures.append("generated files left in the program folder: {}".format(
            leftovers))
    leaked = [n for n in os.listdir(elsewhere) if n.startswith("hotel_name_")]
    if leaked:
        failures.append("reports leaked into the caller cwd: {}".format(leaked))

    # --- B: legacy artefacts are moved, not deleted -----------------------
    box_b = make_sandbox(args.source)
    legacy_old = write_report(box_b, "tech", TECH, "2026-10-01")
    legacy_mgr = write_report(box_b, "mgr", MGR, "2026-10-01")
    legacy_log = os.path.join(box_b, "rms_run.log")
    with open(legacy_log, "a", encoding="utf-8") as handle:
        handle.write("2026-10-01 06:00:00 [INFO] legacy line\n")
    legacy_archive = os.path.join(box_b, "archive")
    os.makedirs(legacy_archive, exist_ok=True)
    archived = write_report(legacy_archive, "tech", TECH, "2026-09-01")
    calendar_hash = os.path.getsize(os.path.join(box_b, "Public holidays.csv"))
    proc = run([sys.executable, os.path.join(box_b, ENTRY)], cwd=elsewhere,
               env=report_env())
    summary["migrate_exit"] = proc.returncode
    if proc.returncode != 0:
        failures.append("migration cycle exit={} tail={}".format(
            proc.returncode, proc.stdout.strip().splitlines()[-6:]))
    out_b = os.path.join(box_b, "output")
    moved = {
        "old_tech": os.path.isfile(os.path.join(out_b, TECH.format("2026-10-01"))),
        "old_mgr": os.path.isfile(os.path.join(out_b, MGR.format("2026-10-01"))),
        "old_log": os.path.isfile(os.path.join(out_b, "rms_run.log")),
        "old_archive": os.path.isfile(os.path.join(
            out_b, "archive", TECH.format("2026-09-01"))),
    }
    summary["migrated"] = moved
    for key, ok in moved.items():
        if not ok:
            failures.append("legacy artefact was not migrated: {}".format(key))
    still_root = [n for n in (TECH.format("2026-10-01"), MGR.format("2026-10-01"))
                  if os.path.isfile(os.path.join(box_b, n))]
    if still_root:
        failures.append("legacy reports still in the program folder: {}".format(
            still_root))
    migrated_log = os.path.join(out_b, "rms_run.log")
    kept = False
    if os.path.isfile(migrated_log):
        with open(migrated_log, encoding="utf-8") as handle:
            kept = "legacy line" in handle.read()
    summary["legacy_log_kept_content"] = kept
    if not kept:
        failures.append("the migrated run log lost its existing content")
    if os.path.getsize(os.path.join(box_b, "Public holidays.csv")) != calendar_hash:
        failures.append("the staff calendar was modified by the migration")
    if not os.path.isfile(os.path.join(box_b, "Public holidays.csv")):
        failures.append("the staff calendar was moved by the migration")

    # --- C: idempotent second cycle ---------------------------------------
    # The sandbox is a copy of the real project, so the report count depends on
    # what happened to be in it. Compare before/after instead of hard-coding a
    # number: a repeat run must not create duplicates or move anything again.
    before_files = sorted(n for n in listdir(out_b) if n.startswith("hotel_name_"))
    proc = run([sys.executable, os.path.join(box_b, ENTRY)], cwd=elsewhere,
               env=report_env())
    summary["second_exit"] = proc.returncode
    if proc.returncode != 0:
        failures.append("second cycle exit={}".format(proc.returncode))
    after_files = sorted(n for n in listdir(out_b) if n.startswith("hotel_name_"))
    summary["second_cycle_files"] = after_files
    if after_files != before_files:
        failures.append("a repeat cycle changed the report set: {} -> {}".format(
            before_files, after_files))
    root_again = [n for n in listdir(box_b)
                  if n.startswith("hotel_name_") or n in ("rms_run.log", "archive")]
    if root_again:
        failures.append("a repeat cycle recreated files in the program folder: "
                        "{}".format(root_again))

    # --- D: single source of truth for paths ------------------------------
    probe = (
        "import json, os, sys\n"
        "sys.path.insert(0, r'{box}')\n"
        "from rms_core import paths\n"
        "from rms_core import timezone_config\n"
        "print(json.dumps({{\n"
        "  'app_dir': paths.APP_DIR,\n"
        "  'output_dir': paths.OUTPUT_DIR,\n"
        "  'run_log': paths.RUN_LOG_FILE,\n"
        "  'config_file': timezone_config.CONFIG_FILE,\n"
        "  'config_dir_eq_app': os.path.dirname(timezone_config.CONFIG_FILE) == paths.APP_DIR,\n"
        "  'output_under_app': paths.OUTPUT_DIR == os.path.join(paths.APP_DIR, 'output'),\n"
        "  'is_report_name': [paths.is_report_name('hotel_name_Live_Dashboard_2026-11-15.csv'),\n"
        "                     paths.is_report_name('Public holidays.csv')],\n"
        "}}))\n"
    ).format(box=box_b.replace("\\", "\\\\"))
    proc = run([sys.executable, "-c", probe], cwd=elsewhere)
    summary["paths_probe_raw"] = proc.stdout.strip()[-300:] if proc.returncode else ""
    if proc.returncode != 0:
        failures.append("rms_core.paths cannot be imported: {}".format(
            proc.stdout.strip()[-400:]))
    else:
        try:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            info = {}
            failures.append("path probe returned unparsable output")
        summary["paths"] = info
        if info:
            if os.path.normcase(info["app_dir"]) != os.path.normcase(box_b):
                failures.append("paths.APP_DIR points at {} instead of the "
                                "program folder".format(info["app_dir"]))
            if not info["output_under_app"]:
                failures.append("OUTPUT_DIR is not <app>/output")
            if not info["config_dir_eq_app"]:
                failures.append("timezone settings would be read from {}".format(
                    info["config_file"]))
            if info["is_report_name"] != [True, False]:
                failures.append("report-name detector is wrong: {}".format(
                    info["is_report_name"]))

    # --- E: the UI reads from output/ -------------------------------------
    probe = (
        "import json, sys\n"
        "sys.path.insert(0, r'{box}')\n"
        "import rms_gui\n"
        "records = rms_gui.load_latest_results()\n"
        "print(json.dumps({{\n"
        "  'latest': rms_gui.find_latest_csv(r'.*_RMS_Manager_View_\\d{{4}}-\\d{{2}}-\\d{{2}}.*\\.csv'),\n"
        "  'records': len(records) if records else 0,\n"
        "  'timestamp_found': rms_gui.latest_report_timestamp() is not None,\n"
        "}}))\n"
    ).format(box=box_b.replace("\\", "\\\\"))
    proc = run([sys.executable, "-c", probe], cwd=elsewhere)
    if proc.returncode != 0:
        failures.append("rms_gui helpers cannot run against output/: {}".format(
            proc.stdout.strip()[-400:]))
    else:
        try:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            info = {}
            failures.append("UI probe returned unparsable output")
        summary["ui"] = info
        if info:
            latest = info.get("latest") or ""
            if os.path.basename(os.path.dirname(latest)) != "output":
                failures.append("the UI looks outside output/: {!r}".format(latest))
            if not info.get("records"):
                failures.append("the UI loaded no records from output/")
            if not info.get("timestamp_found"):
                failures.append("the UI could not date the report in output/")

    # --- F: retention archives inside output/ -----------------------------
    box_f = make_sandbox(args.source)
    out_f = os.path.join(box_f, "output")
    os.makedirs(out_f, exist_ok=True)
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        write_report(out_f, "tech", TECH, day)
        write_report(out_f, "mgr", MGR, day)
    # No as-of override here: retention only runs on a real daily cycle.
    proc = run([sys.executable, os.path.join(box_f, ENTRY)], cwd=elsewhere,
               env=report_env(fixed=False))
    summary["retention_exit"] = proc.returncode
    if proc.returncode != 0:
        failures.append("retention cycle exit={} tail={}".format(
            proc.returncode, proc.stdout.strip().splitlines()[-6:]))
    archive_f = os.path.join(out_f, "archive")
    moved_oldest = os.path.isfile(os.path.join(archive_f, TECH.format("2026-10-01")))
    summary["archive_dir"] = os.path.relpath(archive_f, box_f)
    summary["oldest_archived"] = moved_oldest
    if not os.path.isdir(archive_f):
        failures.append("archive/ was not created inside output/")
    elif not moved_oldest:
        failures.append("the oldest report was not archived into output/archive/")
    if os.path.isdir(os.path.join(box_f, "archive")):
        failures.append("an archive/ folder was created in the program folder")

    # --- G: prices still frozen ------------------------------------------
    tool = os.path.join(args.source, "golden", "diff_reports.py")
    proc = run([sys.executable, tool, "--baseline",
                os.path.join(args.golden, "reports"), "--candidate", out_dir,
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
