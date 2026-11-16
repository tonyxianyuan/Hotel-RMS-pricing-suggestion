# -*- coding: utf-8 -*-
"""Run every behaviour contract in this folder and report one summary.

Each contract is a standalone script: it copies the project into a temporary
sandbox, exercises it, and exits non-zero when an assertion fails. This runner
only sequences them and prints one verdict, so a failure is easy to find and
easy to point at.

    py tests/run_all.py                 # everything
    py tests/run_all.py --only step7    # one or more, comma separated
    py tests/run_all.py --list          # names only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


def contracts():
    names = []
    for entry in sorted(os.listdir(HERE)):
        if entry.startswith("contract_") and entry.endswith(".py"):
            names.append(entry[len("contract_"):-len(".py")])
    return names


def sanitised_env():
    """Drop inherited RMS_* overrides so a shell session cannot bias a run."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("RMS_")}
    env["RMS_NO_PAUSE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    available = contracts()
    selected = available
    if args.only:
        wanted = [name.strip() for name in args.only.split(",") if name.strip()]
        unknown = [name for name in wanted if name not in available]
        if unknown:
            print("Unknown contract(s): {}".format(", ".join(unknown)))
            print("Available: {}".format(", ".join(available)))
            return 2
        selected = wanted
    if args.list:
        for name in selected:
            print(name)
        return 0

    results = []
    for name in selected:
        path = os.path.join(HERE, "contract_{}.py".format(name))
        started = time.time()
        print("\n=== {} ===".format(name), flush=True)
        proc = subprocess.run(
            [sys.executable, path],
            cwd=REPO_ROOT,
            env=sanitised_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
        )
        elapsed = time.time() - started
        output = proc.stdout or ""
        verdict = "PASS" if proc.returncode == 0 else "FAIL"
        results.append((name, verdict, elapsed))

        if proc.returncode == 0:
            print(output.strip().splitlines()[-1] if output.strip() else "PASS")
        else:
            # Show the assertion payload, not the whole engine log.
            print(output[-2500:])

    print("\n" + "=" * 58)
    for name, verdict, elapsed in results:
        print("{:<12} {:<5} {:>6.1f}s".format(name, verdict, elapsed))
    failed = [name for name, verdict, _ in results if verdict != "PASS"]
    print("=" * 58)
    print("{} of {} contracts passed".format(len(results) - len(failed), len(results)))
    if failed:
        print("failed: {}".format(", ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
