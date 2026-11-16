# Handover

A 90-day hotel rate recommendation engine with a staff UI, built around a
multiplicative yield model. This document is the closing state: what works,
what was verified, what was deliberately left out, and what a successor needs
to know before trusting a number that comes out of it.

Read this before changing the pricing model. Everything else is in `README.md`
(English), `README.zh-CN.md` (Chinese translation) and `User_Guide.txt`
(operator-facing).

---

## 1. What it does

For each of the next 90 days and each room type it publishes one rate:

```text
Recommended_ADR = Base_Room_ADR x Weekend x Event x Occupancy
                                x Lead_Time x Booking_Pace x Competitor
Final_ADR       = clamp(floor(clamp(Recommended_ADR, MIN, MAX) + 0.5),
                        ceil(MIN), floor(MAX))
```

Outputs are two CSV reports in `output/`: a technical view carrying every factor
plus an audit chain, and a one-row-per-stay manager view with a plain-language
reason. A Tkinter UI browses the results and explains each rate. Three entry
points: `hotel rms.py` (one cycle), `rms_gui.py` (UI), `scheduler.py` (resident
scheduler). Reusable logic lives in `rms_core/`.

---

## 2. What works

- The full cycle runs end to end, offline, with no credentials.
- Every published rate can be rebuilt by hand from the exported factor columns.
- Logs persist to `output/rms_run.log`, so a past run stays auditable.
- The UI distinguishes success / bad input / guard refusal / crash, marks stale
  results instead of showing them as current, and can cancel a run.
- Bad input is refused with a reason: a non-numeric or non-finite event factor
  stops the run with a calendar line number; a rate that breaks its own floor or
  ceiling is never published (exit code 3).
- Dirty PMS rows are dropped with a warning naming the reservation, not fatal.
- Nine behaviour contracts cover all of the above (`tests/`, see section 4).

---

## 3. What is NOT true yet — read this first

The model has **never run on real hotel data**. It is a working engine with a
synthetic data layer:

| Input | Current state |
| --- | --- |
| `Base_Room_ADR` | Hard-coded constant (`BASELINE_ADR`: 135 / 200), exported in a column named `Historical_ADR` |
| `Competitor_ADR` | SHA-256 hash of the stay date, i.e. stable but meaningless |
| Reservations / OTB | Four demo reservations, which cover 5 nights of the 90-day window |
| Booking history | Effectively none: 176 of 180 rows have no comparable date last year, so their pace factor is neutral by definition |

Consequences worth stating plainly:

- The demo feed is sparse enough that the current report is driven mostly by
  day-of-week and lead time. It does **not** demonstrate what the model would
  do with real occupancy.
- The PMS adapter's field names (`property_now`, `capacity`, `roomsBlocked`,
  `inHouse`, `guestsInHouse`, `percentageOccupied`) have never been checked
  against a real Cloudbeds response. Because the fallback used to be silent,
  this went unnoticed: the sibling hotel script appears to have been running on
  synthetic data since at least 2026-08 without anyone seeing it.
- The only credential ever tested returned
  `401 {"success": false, "message": "User who approved this connection is not
  active anymore"}` on 2026-11-16 — the token was valid in shape and the network
  was fine, but the authorising Cloudbeds user had been deactivated. A successor
  needs a fresh token issued by an **active** admin, plus a `propertyID`;
  `getReservations` requires one and the local script calls it without.

So: `Data_Mode` is `DEMO` on every report this project has ever produced.
Do not put these rates in front of a revenue manager as advice.

---

## 4. How to verify a change

```bat
py tests/run_all.py                 :: nine contracts, ~80 seconds
```

Each contract copies the project into a temp sandbox and asserts behaviour; it
never writes to `output/`. See `tests/README.txt` for what each one protects.

For the price itself:

```bat
RMS_AS_OF_DATE=2026/11/15 RMS_AS_OF_DATETIME="2026-11-15 17:00:00" py "hotel rms.py"
py golden/diff_reports.py --baseline golden/v7/reports --candidate output --strict
```

`golden/v7` is the frozen output after the last pricing corrections; `golden/v0`
is the pre-correction reference, kept so that change stays auditable. A change
that is not supposed to move prices must produce zero price-bearing diffs. A
change that IS supposed to move prices must close its delta set: undoing the
documented rules has to reproduce the previous baseline exactly (this is how
the last correction was proven, see `golden/v7/manifest.json`).

---

## 5. Deliberately not done

| Item | Why |
| --- | --- |
| Weighted model instead of equal-weight multiplication | With every input synthetic, tuning weights fits noise. Do it after real data. |
| Calibrating the factor thresholds | Same reason: `get_pace_factor` and friends are unvalidated experience values. |
| Daily 06:00 automatic run | No operational need was ever established; `scheduler.py` exists but nothing launches it. |
| Run-id file names, file locks | Atomic publish (`private .tmp` + one `os.replace`) plus a shared `Run_Timestamp` already covers the real failure modes without new problems. |
| Progress bar / run duration in the UI | Cosmetic; a run takes a few seconds. |
| Renaming `Historical_ADR` | It would break every saved report and the baseline; needs a deliberate migration, not a drive-by edit. |

Two known rough edges, documented rather than hidden:

- Cancelling a run kills the child process, so a cycle can leave the technical
  report written and the manager report not. The UI detects the mismatched pair
  (`report_pair_mismatch`) and warns; a two-phase publish would fix it properly.
- `output/rms_run.log` is append-only and never rotated.

---

## 6. Data and credentials

- The engine reads `PMS_API_KEY` and `PMS_BASE_URL` from the environment. No key
  is stored in the repository, and none should be.
- `.gitignore` excludes `output/`, `*.log`, generated reports,
  `timezone_settings.json`, `__pycache__/`, and all agent/assistant working
  data. `golden/` is tracked on purpose: it is the behavioural specification.
- `Public holidays.csv` is staff-maintained input. It is the only file a
  non-developer needs to edit, and a wrong factor there changes prices, so it is
  validated hard (line numbers, range warnings, coverage report).

---

## 7. If you pick this up

1. Get a live PMS token from an active admin plus the `propertyID`, point
   `PMS_API_KEY` / `PMS_BASE_URL` at it, and run one cycle.
2. Capture the raw `getDashboard` and `getReservations` payloads and reconcile
   them with `rms_core/reservations.py` and `fetch_dashboard_data()`. Expect the
   field names to be wrong; fix the adapter, not the model.
3. Replace `BASELINE_ADR` with a real historical ADR feed. That is the single
   biggest improvement available, and it will move every price.
4. Only then revisit the model shape and the factor thresholds.
5. Freeze a new baseline (`golden/v8`) once the numbers are trusted, and keep
   the previous one.

Every step above changes prices, so each one needs the same treatment the last
correction got: a contract that fails first, a closed delta set afterwards, and
a manifest entry explaining the change.
