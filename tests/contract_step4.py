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
# Behaviour contract for step 4 (trustworthy staff UI).
# 
# A. describe_engine_exit() distinguishes success, invalid input, a price-guard
#    rejection and an unexpected crash.
# B. A failed run can no longer look like a successful one: the freshness label
#    turns stale, a red notice appears, and the data-mode banner is NOT
#    overwritten (the DEMO warning must survive a failure).
# C. Exit code 3 explains that the price guard stopped the run.
# D. Opening the UI loads the reports that already exist on disk, instead of
#    claiming nothing has been run.
# E. Cancelling a run terminates the child process and re-enables the button.
# F. Closing the window while a run is in progress kills the child too.

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

PACKAGE_DIR = "rms_core"
SOURCE_FILES = [
    "hotel rms.py", "event_calendar.py", "timezone_config.py",
    "report_retention.py", "report_writer.py", "price_guard.py",
    "rms_gui.py", "Public holidays.csv",
]
TECH_NAME = "hotel_name_Live_Dashboard_2026-11-15.csv"
MGR_NAME = "hotel_name_RMS_Manager_View_2026-11-15.csv"

SLEEP_ENGINE = """import time
print("fake engine started", flush=True)
time.sleep(120)
"""


def make_sandbox(source, golden):
    folder = tempfile.mkdtemp(prefix="rmsstep4.", dir=tempfile.gettempdir())
    for name in SOURCE_FILES:
        src = os.path.join(source, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(folder, name))
    # The UI must find existing reports at startup, so seed them.
    for name in (TECH_NAME, MGR_NAME):
        src = os.path.join(golden, "reports", name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(folder, name))
    package = os.path.join(source, PACKAGE_DIR)
    if os.path.isdir(package):
        shutil.copytree(package, os.path.join(folder, PACKAGE_DIR),
                        ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def load_module(sandbox):
    for name in list(sys.modules):
        if name == "rms_gui":
            del sys.modules[name]
    sys.path.insert(0, sandbox)
    import rms_gui
    return rms_gui


def new_app(rms_gui):
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    app = rms_gui.RMSApp(root)
    root.update()
    return root, app


def pump(root, seconds):
    """Run the Tk event loop for a while so queued callbacks execute."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=REPO_ROOT)
    ap.add_argument("--golden", default=os.path.join(REPO_ROOT, "golden", "v7"))
    args = ap.parse_args()
    failures = []
    summary = {}

    box = make_sandbox(args.source, args.golden)
    summary["sandbox"] = box
    rms_gui = load_module(box)

    # --- A: exit-code classification --------------------------------------
    kinds = {}
    try:
        for code in (0, 2, 3, 1, 42):
            kind, message = rms_gui.describe_engine_exit(code)
            kinds[code] = [kind, message]
        summary["exit_kinds"] = kinds
        if kinds[0][0] != "ok":
            failures.append("exit 0 was not classified as success")
        if kinds[2][0] != "input":
            failures.append("exit 2 (invalid calendar/input) was not classified as input")
        if kinds[3][0] != "guard":
            failures.append("exit 3 (price guard) was not classified as guard")
        if kinds[1][0] == "ok" or kinds[42][0] == "ok":
            failures.append("non-zero exit classified as success")
        if "calendar" not in kinds[2][1].lower():
            failures.append("exit 2 message does not point at the calendar input")
        if "guard" not in kinds[3][1].lower():
            failures.append("exit 3 message does not mention the price guard")
    except AttributeError as exc:
        failures.append("describe_engine_exit() missing ({})".format(exc))

    # --- D: startup loads the reports already on disk ---------------------
    root, app = new_app(rms_gui)
    summary["startup_records"] = len(app.records)
    summary["startup_label"] = app.last_run_lbl.cget("text")
    if not app.records:
        failures.append("UI did not load existing reports on startup")
    if "Not run yet" in str(app.last_run_lbl.cget("text")):
        failures.append("freshness label claims nothing has been run although "
                        "reports exist")

    # --- B: a failure cannot look like a success --------------------------
    before_rows = len(app.records)
    app.on_run_finished(1)
    root.update()
    stale_text = str(app.stale_lbl.cget("text")) if hasattr(app, "stale_lbl") else ""
    label_text = str(app.last_run_lbl.cget("text"))
    mode_text = str(app.mode_lbl.cget("text"))
    log_text = app.status.get("1.0", "end")
    summary["failure_state"] = {
        "rows_before": before_rows,
        "stale_label": stale_text,
        "freshness_label": label_text,
        "mode_banner": mode_text,
        "log_tail": [ln for ln in log_text.strip().splitlines()[-3:]],
    }
    if not stale_text:
        failures.append("no visible stale-results notice after a failed run")
    elif "not updated" not in stale_text.lower():
        failures.append("stale notice does not say the results were not updated: "
                        "{!r}".format(stale_text))
    if "stale" not in label_text.lower():
        failures.append("freshness label still looks current after a failure: "
                        "{!r}".format(label_text))
    if "DEMO" not in mode_text:
        failures.append("the data-mode banner was overwritten by the failure text")
    if "[ERROR]" not in log_text:
        failures.append("failure was not logged as [ERROR]")

    # --- C: exit 3 explains the guard -------------------------------------
    app.on_run_finished(3)
    root.update()
    log_text = app.status.get("1.0", "end")
    summary["guard_log_tail"] = [ln for ln in log_text.strip().splitlines()[-2:]]
    if "guard" not in log_text.lower():
        failures.append("exit 3 did not explain that the price guard stopped the run")
    app.on_close()

    # --- E/F: child process lifecycle -------------------------------------
    sleep_engine = os.path.join(tempfile.mkdtemp(prefix="rmssleep.",
                                                 dir=tempfile.gettempdir()),
                                "fake_engine.py")
    with open(sleep_engine, "w", encoding="utf-8") as handle:
        handle.write(SLEEP_ENGINE)
    original_script = rms_gui.RMS_SCRIPT
    original_ask = rms_gui.messagebox.askyesno
    rms_gui.RMS_SCRIPT = sleep_engine
    # The close confirmation is UI chrome; the contract is about the child.
    rms_gui.messagebox.askyesno = lambda *a, **k: True
    try:
        root, app = new_app(rms_gui)
        app.run_pricing()
        pump(root, 2.0)
        proc = getattr(app, "_proc", None)
        summary["cancel_started"] = bool(proc and proc.poll() is None)
        if not proc:
            failures.append("run_pricing() did not keep a handle on the child")
        else:
            app.cancel_run()
            pump(root, 8.0)
            summary["cancel_exit_code"] = proc.poll()
            if proc.poll() is None:
                failures.append("cancel_run() left the child process running")
            if app.running:
                failures.append("cancel_run() did not re-enable the UI")
        summary["cancel_log_tail"] = [
            ln for ln in app.status.get("1.0", "end").strip().splitlines()[-2:]]

        # Window close while a run is in flight.
        app.run_pricing()
        pump(root, 2.0)
        proc = getattr(app, "_proc", None)
        summary["close_started"] = bool(proc and proc.poll() is None)
        if not proc or proc.poll() is not None:
            failures.append("second run did not start")
        else:
            app.on_close()
            deadline = time.time() + 8.0
            while time.time() < deadline and proc.poll() is None:
                time.sleep(0.1)
            summary["close_exit_code"] = proc.poll()
            if proc.poll() is None:
                failures.append("closing the window left the child process running")
    except Exception as exc:
        failures.append("child lifecycle cannot be tested ({}: {})".format(
            type(exc).__name__, exc))
    finally:
        rms_gui.RMS_SCRIPT = original_script
        rms_gui.messagebox.askyesno = original_ask

    summary["failures"] = failures
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print("CONTRACT: {}".format("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
