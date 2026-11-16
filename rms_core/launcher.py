# -*- coding: utf-8 -*-
"""Start the tool with an interpreter that actually has its dependencies.

``where python`` is not a dependency check: it only proves that a *name*
exists on PATH. On a typical Windows machine several interpreters are
installed, and the one called ``python`` is often not the one with pandas.
When it is not, the engine dies with ``ModuleNotFoundError`` in a console
window that closes again before anybody can read it.

This module probes each candidate interpreter properly, then starts the real
program with the first one that can import every required package. It is
started by the two ``.bat`` files:

    python -m rms_core.launcher "hotel rms.py"          one pricing cycle
    python -m rms_core.launcher "rms_gui.py" --gui      the staff UI
    python -m rms_core.launcher --check                 diagnose, start nothing

All identifiers, comments and messages are English.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .paths import APP_DIR

REQUIRED_PACKAGES = ("pandas", "numpy", "requests")
PROBE_CODE = "import " + ", ".join(REQUIRED_PACKAGES)
DETAILS_CODE = "import sys; print(sys.executable); print(sys.version.split()[0])"

# Windows first. The "py" launcher normally selects the newest installed
# version, which is the one that tends to carry the packages; a bare "python"
# on PATH is frequently a different, dependency-free install.
CANDIDATES_WINDOWS = (["py", "-3"], ["py"], ["python"], ["python3"])
CANDIDATES_OTHER = (["python3"], ["python"])

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def candidates():
    """Interpreters to try, most likely to work first."""
    base = CANDIDATES_WINDOWS if os.name == "nt" else CANDIDATES_OTHER
    ordered = [list(item) for item in base] + [[sys.executable]]
    seen = set()
    unique = []
    for command in ordered:
        key = tuple(command)
        if key not in seen:
            seen.add(key)
            unique.append(command)
    return unique


def describe(command):
    return " ".join(command)


def _run(command, code, timeout):
    """Run an interpreter snippet, hiding any console window on Windows."""
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        list(command) + ["-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=flags,
    )


def probe(command, timeout=60):
    """Return ``(ok, detail)`` for one interpreter without raising."""
    try:
        result = _run(command, PROBE_CODE, timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "cannot run ({})".format(exc)
    if result.returncode == 0:
        return True, "ok"
    text = (result.stderr or b"").decode("utf-8", "replace").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    detail = lines[-1] if lines else "exit code {}".format(result.returncode)
    return False, detail


def find_interpreter(commands=None):
    """Return ``(command, reports)`` for the first interpreter that works.

    ``command`` is None when none of them can import the required packages.
    ``reports`` is a list of ``(command, ok, detail)`` for every attempt, so
    the failure message can say exactly what was tried.
    """
    commands = list(commands) if commands is not None else candidates()
    reports = []
    for command in commands:
        ok, detail = probe(command)
        reports.append((command, ok, detail))
        if ok:
            return command, reports
    return None, reports


def interpreter_details(command, timeout=60):
    """Return ``(executable_path, version)`` for a working interpreter."""
    try:
        result = _run(command, DETAILS_CODE, timeout)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if result.returncode != 0:
        return None, None
    lines = (result.stdout or b"").decode("utf-8", "replace").split()
    if len(lines) >= 2:
        return lines[0], lines[1]
    if lines:
        return lines[0], None
    return None, None


def missing_report(reports):
    """Explain the failure in terms a non-technical user can act on."""
    lines = [
        "[ERROR] No Python interpreter with the required packages was found.",
        "        Required: {}".format(", ".join(REQUIRED_PACKAGES)),
        "        Tried:",
    ]
    for command, ok, detail in reports:
        lines.append("          {:<26} {}".format(
            describe(command), "ok" if ok else detail))
    lines.append("")
    lines.append("        Install the packages with:")
    lines.append("          \"{}\" -m pip install {}".format(
        sys.executable, " ".join(REQUIRED_PACKAGES)))
    lines.append("        If Python itself is missing, install Python 3.9 or "
                 "newer from")
    lines.append("        https://www.python.org/downloads/ and tick "
                 "\"Add python.exe to PATH\".")
    return "\n".join(lines)


def check():
    """Diagnose the environment without starting anything. Returns 0 or 1."""
    command, reports = find_interpreter()
    if command is None:
        print(missing_report(reports), flush=True)
        return 1
    executable, version = interpreter_details(command)
    print("[OK] Interpreter: {} ({})".format(
        executable or describe(command), version or "version unknown"), flush=True)
    print("[OK] Packages: {}".format(", ".join(REQUIRED_PACKAGES)), flush=True)
    print("[OK] Program folder: {}".format(APP_DIR), flush=True)
    return 0


def _windowless(executable):
    """pythonw.exe beside the interpreter, when it exists."""
    if not executable:
        return None
    candidate = os.path.join(os.path.dirname(executable), "pythonw.exe")
    return candidate if os.path.isfile(candidate) else None


def launch(target, gui=False):
    """Start ``target`` with a working interpreter; return the exit code."""
    script = target if os.path.isabs(target) else os.path.join(APP_DIR, target)
    if not os.path.isfile(script):
        print("[ERROR] Cannot find {}.".format(script), flush=True)
        return 2

    command, reports = find_interpreter()
    if command is None:
        print(missing_report(reports), flush=True)
        return 1

    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    if gui:
        executable, _version = interpreter_details(command)
        windowless = _windowless(executable)
        args = [windowless or executable or command[0], script]
        try:
            subprocess.Popen(
                args,
                cwd=APP_DIR,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DETACHED_PROCESS,
            )
        except OSError as exc:
            print("[ERROR] Could not start the UI: {}".format(exc), flush=True)
            return 1
        print("[OK] Pricing UI started ({}).".format(", ".join(args[:1])),
              flush=True)
        return 0

    print("[INFO] Using {}".format(describe(command)), flush=True)
    code = subprocess.call(list(command) + [script], cwd=APP_DIR, env=env)
    if code == 0:
        print("[OK] Pricing cycle finished. Full log: {}".format(
            os.path.join(APP_DIR, "output", "rms_run.log")), flush=True)
    else:
        print("[ERROR] Pricing finished with exit code {}.".format(code),
              flush=True)
    return code


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    gui = "--gui" in args
    check_only = "--check" in args
    targets = [item for item in args if not item.startswith("--")]
    if check_only:
        return check()
    if not targets:
        print("[ERROR] No program to start. Expected a script name such as "
              "\"hotel rms.py\".", flush=True)
        return 2
    return launch(targets[0], gui=gui)


if __name__ == "__main__":
    sys.exit(main())
