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
# Behaviour contract for step 5 (launcher / dependency self-check).
# 
# The two .bat files must stop failing silently. On this machine `python` on
# PATH has no pandas while `py` does, so "where python" is not a dependency
# check - it only proves a name exists.
# 
# A. probe() never raises and reports failure for a command that cannot import
#    the required packages.
# B. find_interpreter() skips a broken interpreter and returns a working one.
# C. When nothing works, the report names the missing packages and the exact
#    install command.
# D. `python -m rms_core.launcher --check` succeeds and names the interpreter.
# E. Run_Pricing_Now.bat runs a real cycle through the launcher and publishes
#    the reports into output/.
# F. Start_Pricing_UI.bat --check validates the environment without opening a
#    window.
# G. With no Python on PATH, Run_Pricing_Now.bat fails loudly and does not hang.
# H. Both .bat files route through the launcher and keep a visible pause on
#    failure.

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ENTRY = "hotel rms.py"
TECH = "hotel_name_Live_Dashboard_2026-11-15.csv"
MGR = "hotel_name_RMS_Manager_View_2026-11-15.csv"
CMD = os.path.join(os.environ.get("SystemRoot", r"C://Windows"), "System32",
                   "cmd.exe")
FIXED_ENV = {
    "RMS_AS_OF_DATE": "2026/11/15",
    "RMS_AS_OF_DATETIME": "2026-11-15 17:00:00",
}


def make_sandbox(source):
    folder = tempfile.mkdtemp(prefix="rmsenv.", dir=tempfile.gettempdir())
    for name in os.listdir(source):
        full = os.path.join(source, name)
        if os.path.isfile(full):
            shutil.copy2(full, os.path.join(folder, name))
    package = os.path.join(source, "rms_core")
    if os.path.isdir(package):
        shutil.copytree(package, os.path.join(folder, "rms_core"),
                        ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def run(cmd, cwd, env=None, timeout=300):
    return subprocess.run(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", timeout=timeout)


def run_batch(cmd, cwd, env, timeout=120):
    """Run a .bat with a bounded wait: `pause` must not hang the contract."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", timeout=timeout)
        return proc.returncode, proc.stdout or "", False
    except subprocess.TimeoutExpired as exc:
        out = exc.output or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return None, out, True


def batch_env(extra=None, path=None):
    env = dict(os.environ)
    for key in ("PMS_API_KEY", "PMS_BASE_URL"):
        env.pop(key, None)
    env.update(FIXED_ENV)
    # Keeps a failing batch file from blocking the test on `pause`.
    env["RMS_NO_PAUSE"] = "1"
    if path is not None:
        env["PATH"] = path
    if extra:
        env.update(extra)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=REPO_ROOT)
    ap.add_argument("--golden", default=os.path.join(REPO_ROOT, "golden", "v7"))
    args = ap.parse_args()
    failures = []
    summary = {}

    box = make_sandbox(args.source)
    elsewhere = tempfile.mkdtemp(prefix="rmscwd.", dir=tempfile.gettempdir())
    summary["sandbox"] = box

    # --- A/B/C: the launcher decides, not `where python` ------------------
    probe_script = os.path.join(tempfile.mkdtemp(
        prefix="rmsprobe.", dir=tempfile.gettempdir()), "probe.py")
    with open(probe_script, "w", encoding="utf-8") as handle:
        handle.write('''# -*- coding: utf-8 -*-
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"{box}")
from rms_core import launcher

out = {{}}

# A broken interpreter: always exits 1, whatever it is asked to import.
broken = [sys.executable, "-c", "import sys; sys.exit(1)"]
good = [sys.executable]

ok_broken, detail_broken = launcher.probe(broken)
ok_good, detail_good = launcher.probe(good)
out["probe_broken"] = [ok_broken, detail_broken][:2]
out["probe_good"] = [ok_good, detail_good][:2]

out["probe_missing"] = list(launcher.probe(
    [os.path.join(r"{box}", "no-such-python-here")]))

chosen, reports = launcher.find_interpreter([broken, good])
out["chosen_is_good"] = chosen == good
out["report_count"] = len(reports)
out["first_report_ok"] = reports[0][1] if reports else None

none_chosen, none_reports = launcher.find_interpreter([broken])
out["none_chosen"] = none_chosen is None
report = launcher.missing_report(none_reports)
out["report_text"] = report
print(json.dumps(out))
'''.format(box=box.replace("\\", "\\\\")))

    proc = run([sys.executable, probe_script], cwd=elsewhere)
    if proc.returncode != 0:
        failures.append("launcher unit probe failed: {}".format(
            proc.stdout.strip()[-500:]))
    else:
        try:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            info = {}
            failures.append("launcher unit probe returned unparsable output")
        summary["launcher"] = info
        if info:
            if info.get("probe_broken", [None])[0] is not False:
                failures.append("probe() accepted an interpreter that cannot "
                                "import the packages")
            if info.get("probe_good", [None])[0] is not True:
                failures.append("probe() rejected a working interpreter")
            if info.get("probe_missing", [None])[0] is not False:
                failures.append("probe() did not survive a nonexistent command")
            if not info.get("chosen_is_good"):
                failures.append("find_interpreter() did not skip the broken "
                                "interpreter")
            if not info.get("none_chosen"):
                failures.append("find_interpreter() reported success with no "
                                "working interpreter")
            text = info.get("report_text") or ""
            for needle in ("pandas", "pip install"):
                if needle not in text:
                    failures.append("failure report does not mention {!r}".format(
                        needle))

    # --- D: --check -------------------------------------------------------
    proc = run([sys.executable, "-m", "rms_core.launcher", "--check"], cwd=box)
    summary["check_exit"] = proc.returncode
    summary["check_output"] = proc.stdout.strip().splitlines()[:4]
    if proc.returncode != 0:
        failures.append("launcher --check failed: {}".format(
            proc.stdout.strip()[-400:]))
    elif "[OK]" not in proc.stdout:
        failures.append("launcher --check did not confirm the environment")

    # --- H: both .bat files route through the launcher --------------------
    for name, gui in (("Run_Pricing_Now.bat", False),
                      ("Start_Pricing_UI.bat", True)):
        path = os.path.join(args.source, name)
        text = open(path, encoding="utf-8", errors="replace").read().lower()
        summary.setdefault("batch", {})[name] = {
            "uses_launcher": "-m rms_core.launcher" in text,
            "pauses": "pause" in text,
            "bare_python_call": ('python "hotel rms.py"' in text
                                 or "pythonw rms_gui.py" in text),
        }
        if "-m rms_core.launcher" not in text:
            failures.append("{} does not go through the launcher".format(name))
        if "pause" not in text:
            failures.append("{} has no visible pause on failure".format(name))
        if 'python "hotel rms.py"' in text or "pythonw rms_gui.py" in text:
            failures.append("{} still calls an interpreter directly".format(name))
        if gui and "--gui" not in text:
            failures.append("{} does not pass --gui to the launcher".format(name))

    # --- E: a real cycle through the batch file ---------------------------
    code, output, hung = run_batch([CMD, "/c", "Run_Pricing_Now.bat"], box,
                                   batch_env())
    summary["batch_run_exit"] = code
    summary["batch_run_tail"] = output.strip().splitlines()[-4:]
    if hung:
        failures.append("Run_Pricing_Now.bat never returned (it waits for a "
                        "key press even when nothing failed)")
    elif code != 0:
        failures.append("Run_Pricing_Now.bat exit={} tail={}".format(
            code, output.strip().splitlines()[-8:]))
    out_dir = os.path.join(box, "output")
    for name in (TECH, MGR):
        if not os.path.isfile(os.path.join(out_dir, name)):
            failures.append("{} was not produced by the batch run".format(name))
    if "ModuleNotFoundError" in output:
        failures.append("the batch run leaked a ModuleNotFoundError")

    tool = os.path.join(args.source, "golden", "diff_reports.py")
    proc_gate = run([sys.executable, tool, "--baseline",
                     os.path.join(args.golden, "reports"), "--candidate", out_dir,
                     "--strict"], cwd=args.source)
    line = (proc_gate.stdout.strip().splitlines()[-1]
            if proc_gate.stdout.strip() else "")
    summary["gate"] = line
    if proc_gate.returncode != 0 or "DIFF PASS" not in line:
        failures.append("golden gate failed after the batch run: {}".format(line))

    # --- F: UI self-check without a window -------------------------------
    code, output, hung = run_batch(
        [CMD, "/c", "Start_Pricing_UI.bat", "--check"], box, batch_env())
    summary["ui_check_exit"] = code
    summary["ui_check_output"] = output.strip().splitlines()[-3:]
    if hung:
        failures.append("Start_Pricing_UI.bat --check never returned")
    elif code != 0:
        failures.append("Start_Pricing_UI.bat --check exit={} tail={}".format(
            code, output.strip().splitlines()[-6:]))
    elif "Interpreter" not in output:
        failures.append("the UI self-check did not report an interpreter")

    # --- G: no Python at all must fail loudly ----------------------------
    empty_path = tempfile.mkdtemp(prefix="rmsnopy.", dir=tempfile.gettempdir())
    env = batch_env(path=empty_path)
    env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    code, output, hung = run_batch([CMD, "/c", "Run_Pricing_Now.bat"], box, env)
    summary["no_python_exit"] = code
    summary["no_python_output"] = output.strip().splitlines()[-4:]
    if hung:
        failures.append("the batch file hung instead of reporting the missing "
                        "Python")
    elif code == 0:
        failures.append("the batch file claimed success with no Python on PATH")
    combined = output.lower()
    if "python" not in combined:
        failures.append("the no-Python failure says nothing about Python")

    summary["failures"] = failures
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print("CONTRACT: {}".format("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
