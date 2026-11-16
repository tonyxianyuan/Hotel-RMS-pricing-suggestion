"""Behaviour contract for the regression gate itself.

# The gate is the only thing standing between a "harmless refactor" and a
# silent price change, and it has one failure mode that matters more than the
# others: comparing the wrong pair of files. Picking "the newest report" in each
# folder looks reasonable and is wrong - run the engine on a new day and the
# gate reports a phantom regression, which teaches everyone to ignore it.
#
# This contract pins the gate to the baseline's own stay date and proves it
# says so out loud when that date is missing.
"""

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TECH = "hotel_name_Live_Dashboard_{}.csv"
MGR = "hotel_name_RMS_Manager_View_{}.csv"

TECH_COLUMNS = ["Stay_Date", "Room_Type", "Base_Room_ADR", "Competitor_ADR",
                "Recommended_ADR", "MIN_ADR", "MAX_ADR", "Final_ADR",
                "Expected_RevPAR", "Current_Occupancy", "Pace_Ratio",
                "Confidence_Score", "Rate_Cap_Applied"]
MGR_COLUMNS = ["Stay_Date", "Room_Type", "Final_ADR", "ADR_Change_vs_Base",
               "Demand_Status", "Action", "Confidence_Score", "Reason"]

TECH_ROWS = [
    {"Stay_Date": "2026/11/15", "Room_Type": "Standard", "Base_Room_ADR": "135.0",
     "Competitor_ADR": "126.1", "Recommended_ADR": "184.06", "MIN_ADR": "94.5",
     "MAX_ADR": "270.0", "Final_ADR": "184.0", "Expected_RevPAR": "147.2",
     "Current_Occupancy": "80.0", "Pace_Ratio": "1.0", "Confidence_Score": "75",
     "Rate_Cap_Applied": "False"},
    {"Stay_Date": "2026/11/20", "Room_Type": "Standard", "Base_Room_ADR": "135.0",
     "Competitor_ADR": "128.4", "Recommended_ADR": "194.91", "MIN_ADR": "94.5",
     "MAX_ADR": "270.0", "Final_ADR": "195.0", "Expected_RevPAR": "78.0",
     "Current_Occupancy": "40.0", "Pace_Ratio": "2.0", "Confidence_Score": "65",
     "Rate_Cap_Applied": "False"},
]
MGR_ROWS = [
    {"Stay_Date": "2026/11/15", "Room_Type": "Standard", "Final_ADR": "184.0",
     "ADR_Change_vs_Base": "+36.3%", "Demand_Status": "High Demand",
     "Action": "Raise Aggressively", "Confidence_Score": "75",
     "Reason": "Peak Occupancy + Strong Booking Pace"},
    {"Stay_Date": "2026/11/20", "Room_Type": "Standard", "Final_ADR": "195.0",
     "ADR_Change_vs_Base": "+44.4%", "Demand_Status": "Normal Demand",
     "Action": "Raise Aggressively", "Confidence_Score": "65",
     "Reason": "Peak Occupancy + Strong Booking Pace"},
]


def write_report(path, columns, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def make_snapshot(folder, stay_date, tech_rows, mgr_rows):
    os.makedirs(folder, exist_ok=True)
    write_report(os.path.join(folder, TECH.format(stay_date)),
                 TECH_COLUMNS, tech_rows)
    write_report(os.path.join(folder, MGR.format(stay_date)),
                 MGR_COLUMNS, mgr_rows)


def gate(baseline, candidate, strict=True):
    command = [sys.executable, os.path.join(REPO_ROOT, "golden", "diff_reports.py"),
               "--baseline", baseline, "--candidate", candidate]
    if strict:
        command.append("--strict")
    proc = subprocess.run(command, cwd=REPO_ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    body = proc.stdout or ""
    try:
        payload = json.loads(body[:body.rfind("DIFF ")])
    except ValueError:
        payload = {}
    return proc.returncode, payload, body


def main():
    failures = []
    summary = {}
    workspace = tempfile.mkdtemp(prefix="rmsgate.", dir=tempfile.gettempdir())
    baseline = os.path.join(workspace, "baseline")
    try:
        make_snapshot(baseline, "2026-11-15", TECH_ROWS, MGR_ROWS)

        # --- A: identical copy passes -------------------------------------
        same = os.path.join(workspace, "same")
        make_snapshot(same, "2026-11-15", TECH_ROWS, MGR_ROWS)
        code, payload, body = gate(baseline, same)
        summary["identical_exit"] = code
        if code != 0:
            failures.append("an identical copy did not pass: {}".format(body[-400:]))

        # --- B: a NEWER report in the candidate folder must not be used ----
        # This is the trap: without date pinning the gate compares 11/16 with
        # 11/15 and reports a phantom regression.
        newer = os.path.join(workspace, "newer")
        make_snapshot(newer, "2026-11-16", TECH_ROWS, MGR_ROWS)
        code, payload, body = gate(baseline, newer)
        summary["newer_only_exit"] = code
        summary["newer_only_problem"] = payload.get("problems", [])[:1]
        if code == 0:
            failures.append("the gate silently passed by comparing a different "
                            "stay date (11/16 against an 11/15 baseline)")
        elif "no report for the baseline stay date" not in body:
            failures.append("the gate failed for the wrong reason: {}".format(
                body[-400:]))

        # --- C: same date plus a newer one compares the RIGHT pair --------
        mixed = os.path.join(workspace, "mixed")
        make_snapshot(mixed, "2026-11-15", TECH_ROWS, MGR_ROWS)
        make_snapshot(mixed, "2026-11-16", TECH_ROWS, MGR_ROWS)
        # Make the older file look stale so mtime picking would choose 11/16.
        for name in (TECH.format("2026-11-15"), MGR.format("2026-11-15")):
            stamp = os.path.getmtime(os.path.join(baseline, name))
            os.utime(os.path.join(mixed, name), (stamp, stamp))
        code, payload, body = gate(baseline, mixed)
        summary["mixed_exit"] = code
        summary["mixed_candidate"] = (payload.get("technical") or {}).get("candidate")
        if code != 0:
            failures.append("a folder holding the baseline date failed: {}".format(
                body[-400:]))
        if summary["mixed_candidate"] != TECH.format("2026-11-15"):
            failures.append("the gate compared {} instead of the baseline date".format(
                summary["mixed_candidate"]))

        # --- D: one changed price is caught -------------------------------
        tampered = os.path.join(workspace, "tampered")
        bad = [dict(row) for row in TECH_ROWS]
        bad[0]["Final_ADR"] = "999.0"
        bad[0]["Recommended_ADR"] = "999.0"
        make_snapshot(tampered, "2026-11-15", bad, MGR_ROWS)
        code, payload, body = gate(baseline, tampered)
        summary["tampered_exit"] = code
        summary["tampered_diffs"] = (payload.get("technical") or {}).get(
            "price_bearing_diffs")
        if code == 0:
            failures.append("a changed price was not caught")
        elif not (summary["tampered_diffs"] or {}).get("Final_ADR"):
            failures.append("the diff did not name Final_ADR: {}".format(
                summary["tampered_diffs"]))

        # --- E: a _FALLBACK copy of the same date is accepted -------------
        fallback = os.path.join(workspace, "fallback")
        os.makedirs(fallback, exist_ok=True)
        for prefix, columns, rows in ((TECH, TECH_COLUMNS, TECH_ROWS),
                                      (MGR, MGR_COLUMNS, MGR_ROWS)):
            name = prefix.format("2026-11-15").replace(
                ".csv", "_FALLBACK.csv")
            write_report(os.path.join(fallback, name), columns, rows)
        code, payload, body = gate(baseline, fallback)
        summary["fallback_exit"] = code
        summary["fallback_candidate"] = (payload.get("technical") or {}).get("candidate")
        if code != 0:
            failures.append("a locked-file fallback copy was rejected: {}".format(
                body[-400:]))

        # --- F: non-strict mode reports but does not fail ------------------
        code, payload, body = gate(baseline, tampered, strict=False)
        summary["non_strict_exit"] = code
        if code != 0:
            failures.append("non-strict mode should report without failing")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    summary["failures"] = failures
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("CONTRACT: " + ("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
