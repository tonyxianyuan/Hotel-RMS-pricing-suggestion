# -*- coding: utf-8 -*-
"""Read-only regression diff for the two Hotel RMS daily CSV reports.

Compare a candidate folder against a frozen baseline. Reports are aligned by
(Stay_Date, Room_Type); only columns present in the baseline are compared, so
a later cycle that ADDS columns (for example factor columns) is still valid.

The candidate is pinned to the baseline's own file name. Comparing "the newest
report in each folder" would silently diff one stay date against another and
report a phantom regression as soon as somebody runs the engine on a new day.

Usage:
    py golden/diff_reports.py --baseline golden/v7/reports --candidate output
    py golden/diff_reports.py --baseline golden/v7/reports --candidate output --strict

--strict fails when any price-bearing column changed. Use it as the gate for
every change that must leave the pricing numbers untouched. Reproduce the
baseline's fixed inputs first, otherwise there is simply no candidate report
for that stay date and the tool says so.

This tool never writes, imports the pricing engine, or modifies any report.
Standard library only; all output is English.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

TECH_PREFIX = "hotel_name_Live_Dashboard_"
MGR_PREFIX = "hotel_name_RMS_Manager_View_"

# Columns whose values must not change while prices are frozen.
PRICE_BEARING = frozenset((
    "Base_Room_ADR", "Competitor_ADR", "Recommended_ADR", "MIN_ADR",
    "MAX_ADR", "Final_ADR", "Expected_RevPAR", "ADR_Change_vs_Base",
    "Current_Occupancy", "Pace_Ratio", "Confidence_Score",
    "Demand_Status", "Action", "Reason", "Rate_Cap_Applied",
))


def pick(folder, prefix, wanted=None):
    """Return ``(path, names)``.

    ``wanted`` pins an exact file name. The candidate side must always be
    pinned to the baseline's own file name: picking "the newest report" there
    compares one stay date against another and reports a phantom regression
    the moment somebody runs the tool on a newer day.
    """
    names = sorted(n for n in os.listdir(folder)
                   if n.startswith(prefix) and n.endswith(".csv"))
    if not names:
        return None, []
    if wanted is None:
        newest = max(names, key=lambda n: os.path.getmtime(os.path.join(folder, n)))
        return os.path.join(folder, newest), names
    if wanted in names:
        return os.path.join(folder, wanted), names
    # Excel can hold the canonical file open; the writer then publishes a
    # fixed _FALLBACK name. Accept it, but only for the same stay date.
    stem, extension = os.path.splitext(wanted)
    alternative = "{}_FALLBACK{}".format(stem, extension)
    if alternative in names:
        return os.path.join(folder, alternative), names
    return None, names


def load(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows, (list(rows[0].keys()) if rows else [])


def compare(before_path, after_path):
    before, before_cols = load(before_path)
    after, after_cols = load(after_path)
    key = lambda r: (r.get("Stay_Date", ""), r.get("Room_Type", ""))
    bmap = {key(r): r for r in before}
    amap = {key(r): r for r in after}

    missing_keys = sorted(set(bmap) - set(amap))
    extra_keys = sorted(set(amap) - set(bmap))
    missing_cols = [c for c in before_cols if c not in after_cols]
    added_cols = [c for c in after_cols if c not in before_cols]

    per_column = {}
    examples = {}
    for col in before_cols:
        if col in missing_cols:
            per_column[col] = "MISSING IN CANDIDATE"
            continue
        diffs = [(k, bmap[k].get(col, ""), amap[k].get(col, ""))
                 for k in bmap if k in amap
                 and bmap[k].get(col, "") != amap[k].get(col, "")]
        per_column[col] = len(diffs)
        if diffs:
            examples[col] = diffs[:3]

    return {
        "rows_before": len(before), "rows_after": len(after),
        "missing_keys": missing_keys[:5], "extra_keys": extra_keys[:5],
        "missing_columns": missing_cols, "added_columns": added_cols,
        "per_column_diffs": per_column, "examples": examples,
        "price_bearing_diffs": {c: n for c, n in per_column.items()
                                if c in PRICE_BEARING and n != 0},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    result = {}
    for label, prefix in (("technical", TECH_PREFIX), ("manager", MGR_PREFIX)):
        before, before_names = pick(args.baseline, prefix)
        if not before:
            result[label] = {"error": "missing baseline report",
                             "baseline_files": before_names}
            continue
        expected = os.path.basename(before)
        after, after_names = pick(args.candidate, prefix, wanted=expected)
        if not after:
            result[label] = {
                "error": ("candidate has no report for the baseline stay date; "
                          "expected {} (or its _FALLBACK copy) in {}".format(
                              expected, args.candidate)),
                "expected": expected,
                "baseline_files": before_names,
                "candidate_files": after_names,
            }
            continue
        result[label] = {
            "baseline": expected,
            "candidate": os.path.basename(after),
            "baseline_file_count": len(before_names),
            "candidate_file_count": len(after_names),
            **compare(before, after),
        }

    problems = []
    for label, block in result.items():
        if "error" in block:
            problems.append("{}: {}".format(label, block["error"]))
            continue
        if block["missing_keys"] or block["extra_keys"] or block["missing_columns"]:
            problems.append("{}: row/column shape changed".format(label))
        if block["price_bearing_diffs"]:
            problems.append("{}: price-bearing columns changed: {}".format(
                label, block["price_bearing_diffs"]))

    result["strict"] = args.strict
    result["verdict"] = "FAIL" if problems else "PASS"
    result["problems"] = problems
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("DIFF {}: {}".format(
        result["verdict"],
        "price columns unchanged" if not problems else "; ".join(problems)))
    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    sys.exit(main())
