HOTEL RMS REGRESSION BASELINE
=============================

This folder holds frozen snapshots of one pricing cycle each. They exist so
every later change can be checked against a known-good output instead of being
judged by eyeballing a rate table.

  v0/   captured before the step 7 pricing corrections.
        Kept as the historical reference: it is what the engine produced while
        pace was being read off an invented denominator.
  v7/   captured after the step 7 corrections, and the CURRENT gate baseline.

Contents of a snapshot
  manifest.json   fixed environment, runtime versions, input/code SHA-256,
                  output hashes and row counts, capture timestamp
  inputs/         copy of the exact Public holidays.csv used (v0 only)
  reports/        the two published CSV reports
  stdout.txt      complete engine output for the baseline run

How to verify a change (run from the script folder, using the `py` launcher
with pandas installed):

  1. Reproduce the same fixed inputs:
       RMS_AS_OF_DATE=2026/11/15 RMS_AS_OF_DATETIME="2026-11-15 17:00:00" py "hotel rms.py"

  2. Compare the freshly written reports with the current baseline:
       py golden/diff_reports.py --baseline golden/v7/reports --candidate output --strict

     --strict returns exit code 1 when any price-bearing column changed.

Gate rules
  * Changes that must NOT alter prices: every price-bearing diff must be 0.
    Added columns are allowed (the tool only compares baseline columns).
  * Guard hardening: 0 diffs with a normal calendar; abnormal calendar inputs
    are expected to be rejected or capped.
  * Pricing corrections: diffs are allowed, but the whole delta set must be
    closed, i.e. undoing the documented rules must reproduce the previous
    baseline exactly. v7/manifest.json records the rules and that proof.
  * Do NOT refresh the current baseline just to make a diff go away.

Notes
  * The baseline uses a reproducibility override, so report retention is
    skipped for baseline runs and the files stay where they are.
  * Never compare reports generated under a different AS_OF_DATE: the window,
    day-of-week factors and synthetic reservations all move with that date.
  * This folder is local verification data and is git-ignored.
