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
# Behaviour contract for step 7 - pricing correction.
# 
# Every assertion below is a statement a hotelier could check by hand:
#   * a date with no booking history must not be discounted for "weak pace";
#   * occupancy on day 0 must be ONE number, not two;
#   * a published rate must sit inside its own floor/ceiling band;
#   * a same-day guest-density signal must not reprice next month;
#   * a malformed PMS record must be skipped, never crash the cycle.
# 
# Run it against the project directory; it copies the code into a sandbox and
# never writes to the project.

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

PACKAGE_DIR = "rms_core"
SOURCE_FILES = [
    "hotel rms.py", "Public holidays.csv",
]

FIXED_ENV = {
    "RMS_AS_OF_DATE": "2026/11/15",
    "RMS_AS_OF_DATETIME": "2026-11-15 17:00:00",
    "RMS_REPORT_KEEP": "999",
    "RMS_NO_PAUSE": "1",
    "PYTHONIOENCODING": "utf-8",
}
TECH = "hotel_name_Live_Dashboard_2026-11-15.csv"
MGR = "hotel_name_RMS_Manager_View_2026-11-15.csv"


def rd(folder):
    out = os.path.join(folder, "output")
    return out if os.path.isdir(out) else folder


def load(path):
    with io.open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def make_sandbox(source):
    box = tempfile.mkdtemp(prefix="rmsstep7.", dir=tempfile.gettempdir())
    for name in SOURCE_FILES:
        src = os.path.join(source, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(box, name))
    package = os.path.join(source, PACKAGE_DIR)
    if os.path.isdir(package):
        shutil.copytree(package, os.path.join(box, PACKAGE_DIR),
                        ignore=shutil.ignore_patterns("__pycache__"))
    return box


def engine_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("RMS_")}
    env.update(FIXED_ENV)
    env.pop("PMS_API_KEY", None)
    env.pop("PMS_BASE_URL", None)
    return env


# The demo reservation feed, replayed so the expected history is derived, not
# guessed. Mirrors the tuples in hotel rms.py: created N days ago, stay from
# +start to +end.
DEMO = [
    ("1001", 45, 5, 7, "confirmed"),
    ("1002", 20, 5, 6, "confirmed"),
    ("1003", 2, 10, 12, "confirmed"),
    ("1004", 380, -360, -358, "checked_out"),
]


def expected_history():
    """Return {(stay_date_iso, lead_days): (pool_nights, otb_at_lead)}."""
    from datetime import date, timedelta
    as_of = date(2026, 11, 15)
    nights = []
    for _rid, created_back, start_off, end_off, _status in DEMO:
        created = as_of - timedelta(days=created_back)
        cursor = as_of + timedelta(days=start_off)
        end = as_of + timedelta(days=end_off)
        while cursor < end:
            nights.append((cursor, created))
            cursor += timedelta(days=1)

    result = {}
    for offset in range(90):
        stay = as_of + timedelta(days=offset)
        try:
            hist_stay = stay.replace(year=stay.year - 1)
        except ValueError:
            continue
        pool = [n for n in nights if n[0] == hist_stay]
        checkpoint = hist_stay - timedelta(days=offset)
        result[(stay.isoformat(), offset)] = (
            len(pool), sum(1 for n in pool if n[1] <= checkpoint))
    return result


def num(value):
    return float(str(value).replace("%", "").replace("+", ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=REPO_ROOT)
    parser.add_argument("--golden", default=os.path.join(REPO_ROOT, "golden", "v7"))
    args = parser.parse_args()

    summary = {}
    failures = []

    box = make_sandbox(args.source)
    summary["sandbox"] = box
    proc = subprocess.run(
        [sys.executable, os.path.join(box, "hotel rms.py")],
        cwd=box, env=engine_env(), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        timeout=300)
    summary["engine_exit"] = proc.returncode
    if proc.returncode != 0:
        failures.append("engine exit={} tail={}".format(
            proc.returncode, proc.stdout.strip().splitlines()[-8:]))
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print("CONTRACT: FAIL")
        return 1

    tech = {(r["Stay_Date"], r["Room_Type"]): r for r in load(os.path.join(rd(box), TECH))}
    mgr = {(r["Stay_Date"], r["Room_Type"]): r for r in load(os.path.join(rd(box), MGR))}
    summary["rows"] = len(tech)

    # --- A: the audit columns needed to explain a price exist ------------
    required = ["Pace_Basis", "Hist_Pool_Nights", "Hist_OTB_At_Same_LeadTime",
                "Effective_Occupancy", "Post_Model_Adjustment_Factor"]
    missing = [c for c in required if c not in next(iter(tech.values()))]
    if missing:
        failures.append("technical view is missing audit columns: {}".format(missing))

    # --- B: history counts are real, not floored to 1 --------------------
    expected = expected_history()
    hist_mismatch = []
    for (stay, rtype), row in tech.items():
        iso = stay.replace("/", "-")
        lead = int(num(row["Days_to_Checkin"]))
        pool, otb = expected[(iso, lead)]
        if int(num(row["Hist_OTB_At_Same_LeadTime"])) != otb:
            hist_mismatch.append((stay, rtype, row["Hist_OTB_At_Same_LeadTime"], otb))
        if "Hist_Pool_Nights" in row and int(num(row["Hist_Pool_Nights"])) != pool:
            hist_mismatch.append((stay, rtype, "pool " + row["Hist_Pool_Nights"], pool))
    summary["history_mismatches"] = hist_mismatch[:5]
    if hist_mismatch:
        failures.append("{} row(s) report a fabricated history count, e.g. {}".format(
            len(hist_mismatch), hist_mismatch[:3]))

    # --- C: a date without history is not discounted for weak pace ------
    no_history = [r for r in tech.values() if r.get("Pace_Basis") == "no_history"]
    bad_pace = [r["Stay_Date"] for r in no_history
                if abs(num(r["Pace_Ratio"]) - 1.0) > 1e-9
                or abs(num(r["Booking_Pace_Factor"]) - 1.00) > 1e-9]
    summary["no_history_rows"] = len(no_history)
    summary["no_history_bad_pace"] = bad_pace[:5]
    if not no_history:
        failures.append("no row is marked no_history - the basis column is unused")
    if bad_pace:
        failures.append("{} row(s) with no history still get a non-neutral pace "
                        "factor, e.g. {}".format(len(bad_pace), bad_pace[:3]))

    # --- D: a date WITH history is measured, and says so ----------------
    measured = [r for r in tech.values() if r.get("Pace_Basis") == "measured"]
    summary["measured_rows"] = len(measured)
    if not measured:
        failures.append("no row is marked measured although the demo feed has "
                        "two historical nights")
    for row in measured:
        otb = num(row["Current_OTB_Rooms"])
        hist = num(row["Hist_OTB_At_Same_LeadTime"])
        want = otb / hist if hist else None
        if want is not None and abs(num(row["Pace_Ratio"]) - want) > 1e-9:
            failures.append("measured row {} {} has pace {} but {}/{}={}".format(
                row["Stay_Date"], row["Room_Type"], row["Pace_Ratio"], otb, hist, want))

    # --- E: day 0 has ONE occupancy, and it is the live one -------------
    day0 = [r for r in tech.values() if int(num(r["Days_to_Checkin"])) == 0]
    summary["day0_occupancy"] = sorted({
        (r["Stay_Date"], r["Current_Occupancy"], r["Effective_Occupancy"],
         r["Occupancy_Factor"]) for r in day0})
    for row in day0:
        cur = num(row["Current_Occupancy"])
        eff = num(row["Effective_Occupancy"])
        if abs(cur - eff) > 1e-9:
            failures.append("day 0 {} {} reports occupancy {} but prices on {}".format(
                row["Stay_Date"], row["Room_Type"], cur, eff))
        if abs(cur - 80.0) > 1e-9:
            failures.append("day 0 {} {} lost the live occupancy: {}".format(
                row["Stay_Date"], row["Room_Type"], cur))
        if abs(num(row["Occupancy_Factor"]) - 1.20) > 1e-9:
            failures.append("day 0 {} {} prices at occupancy factor {} for {}% "
                            "occupancy".format(row["Stay_Date"], row["Room_Type"],
                                               row["Occupancy_Factor"], cur))

    # --- F: the published rate is a whole unit INSIDE its own band ------
    breaches, non_integral = [], []
    for row in tech.values():
        final, low, high = (num(row["Final_ADR"]), num(row["MIN_ADR"]),
                            num(row["MAX_ADR"]))
        if abs(final - round(final)) > 1e-9:
            non_integral.append((row["Stay_Date"], row["Room_Type"], final))
        if not (low - 1e-9 <= final <= high + 1e-9):
            breaches.append((row["Stay_Date"], row["Room_Type"], final, low, high))
    summary["band_breaches"] = breaches[:5]
    summary["non_integral_prices"] = non_integral[:5]
    if breaches:
        failures.append("{} published rate(s) sit outside their own band, e.g. {}".format(
            len(breaches), breaches[:3]))
    if non_integral:
        failures.append("{} published rate(s) are not whole currency units".format(
            len(non_integral)))

    # --- G: same-day guest density must not reprice future dates --------
    future = [r for r in tech.values() if int(num(r["Days_to_Checkin"])) > 0]
    polluted = [r["Stay_Date"] for r in future
                if abs(num(r["Post_Model_Adjustment_Factor"]) - 1.0) > 1e-9]
    summary["future_rows_repriced"] = polluted[:5]
    if polluted:
        failures.append("{} future date(s) were repriced by a same-day signal, "
                        "e.g. {}".format(len(polluted), polluted[:3]))
    today = [r for r in tech.values() if int(num(r["Days_to_Checkin"])) == 0]
    summary["day0_adjustment"] = sorted({r["Post_Model_Adjustment_Factor"] for r in today})
    for row in today:
        # 1.04 density x 1.00 time decay at 17:00
        if abs(num(row["Post_Model_Adjustment_Factor"]) - 1.04) > 1e-9:
            failures.append("day 0 {} {} lost the guest-density signal: {}".format(
                row["Stay_Date"], row["Room_Type"], row["Post_Model_Adjustment_Factor"]))

    # --- H: the price guard accepts the frame with ZERO tolerance -------
    sys.path.insert(0, box)
    try:
        import pandas as pd
        from rms_core import price_guard
        frame = pd.DataFrame(tech.values())
        for col in ("MIN_ADR", "MAX_ADR", "Recommended_ADR",
                    "Model_ADR_Before_Adjustments", "Post_Model_Adjustment_Factor",
                    "Final_ADR", "Expected_RevPAR", "Base_Room_ADR",
                    "Event_Factor", "Weekend_Factor", "Occupancy_Factor",
                    "Lead_Time_Factor", "Booking_Pace_Factor", "Competitor_Factor"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame["Stay_Date"] = pd.to_datetime(frame["Stay_Date"], format="%Y/%m/%d")
        summary["guard_tolerance"] = price_guard.ROUNDING_TOLERANCE
        problems = price_guard.find_violations(frame)
        summary["guard_problems"] = problems[:3]
        if problems:
            failures.append("the guard rejects the published frame: {}".format(
                problems[:3]))
        if abs(float(price_guard.ROUNDING_TOLERANCE)) > 1e-9:
            failures.append("the guard still hides rounding with tolerance {}"
                            .format(price_guard.ROUNDING_TOLERANCE))
    except Exception as exc:  # noqa: BLE001
        failures.append("guard could not be exercised ({}: {})".format(
            type(exc).__name__, exc))

    # --- I: malformed PMS records are skipped, not fatal ----------------
    try:
        from datetime import date
        from rms_core import reservations as rv
        payload = [
            {"reservationID": "OK1", "status": "confirmed",
             "dateCreated": "2026-11-01 10:00:00",
             "startDate": "2026-11-20", "endDate": "2026-11-22"},
            {"reservationID": "BADDATE", "status": "confirmed",
             "startDate": "not-a-date", "endDate": "2026-11-22"},
            {"reservationID": "INVERTED", "status": "confirmed",
             "startDate": "2026-11-25", "endDate": "2026-11-20"},
            {"reservationID": "CANCELLED", "status": "cancelled",
             "startDate": "2026-11-20", "endDate": "2026-11-22"},
            {"reservationID": "FOREVER", "status": "confirmed",
             "startDate": "2026-11-20", "endDate": "2030-11-20"},
        ]
        warnings = []
        parsed = rv.parse_reservations(payload, date(2026, 11, 15), warnings.append)
        nights = rv.expand_stay_nights(parsed, warnings.append)
        summary["dirty_feed"] = {
            "parsed_ids": sorted(parsed["Reservation_ID"].tolist()),
            "nights": len(nights),
            "warnings": len(warnings),
        }
        if len(nights) != 2 + rv.MAX_STAY_NIGHTS:
            failures.append("bad feed produced {} nights, expected {}".format(
                len(nights), 2 + rv.MAX_STAY_NIGHTS))
        text = " ".join(warnings)
        for rid in ("BADDATE", "INVERTED", "FOREVER"):
            if rid not in text:
                failures.append("{} was dropped without naming it in a warning".format(rid))
    except Exception as exc:  # noqa: BLE001
        failures.append("reservation hardening missing ({}: {})".format(
            type(exc).__name__, exc))

    # --- J: manager view still carries a readable reason ----------------
    blank_reasons = [k for k, r in mgr.items() if not str(r.get("Reason", "")).strip()]
    summary["blank_reasons"] = len(blank_reasons)
    if blank_reasons:
        failures.append("{} manager row(s) lost their reason".format(len(blank_reasons)))

    summary["failures"] = failures
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("CONTRACT: " + ("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
