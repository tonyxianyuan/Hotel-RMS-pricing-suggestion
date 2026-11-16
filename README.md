<p align="center"><a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a></p>

# Hotel RMS (Pricing Suggestion)

A self-contained **decision-support demo** for a single hotel property. It
builds a 90-day rate recommendation per room type from booking pace,
occupancy, lead time, competitor benchmarks and a staff-maintained
public-holiday / special-event calendar, then writes two CSV reports. A
separate Tkinter UI (`rms_gui.py`) can be launched to review those reports.

> **Read this first.** With no PMS credentials configured, the engine runs in
> `DEMO` mode: reservations, competitor rates and baseline ADR are synthetic.
> The reports carry a `Data_Mode` column and the UI shows a permanent warning.
> Rates produced in this mode are for demonstration and review only - do not
> publish them to a booking channel.

`User_Guide.txt` is the short operator quick-reference. Where the two differ,
this README is authoritative. A Chinese edition is available at
[README.zh-CN.md](README.zh-CN.md); it describes the same behaviour, and the
English text governs if wording differs. `Public holidays.csv` carries a
condensed copy of the calendar rules in its comment header.

## Contents

[Files](#files) · [Architecture](#architecture) · [Requirements](#requirements) ·
[Quick start](#quick-start) · [Public holidays / special events](#public-holidays--special-events) ·
[Pricing model](#pricing-model) · [Reproducibility](#reproducibility) ·
[Data sources (honest status)](#data-sources-honest-status) ·
[PMS data interface](#pms-data-interface) ·
[Scheduler and timezone](#scheduler-and-timezone) ·
[Generated outputs](#generated-outputs) · [Troubleshooting](#troubleshooting) ·
[Privacy](#privacy)

## Files

| File | Purpose |
| --- | --- |
| `hotel rms.py` | Pricing engine: PMS adapter, 90-day rate model, CSV exports |
| `rms_gui.py` | Tkinter staff UI: run pricing, browse results, explain rates, open the calendar |
| `scheduler.py` | Long-running scheduler for the daily 06:00 run (`--run-now` runs one cycle first, then stays resident) |
| `rms_core/` | Library package - imported by the three entry points above, never run directly (contents below) |
| `Public holidays.csv` | **Staff-maintained** holidays and special events (the only event input) |
| `Run_Pricing_Now.bat` | Windows: run one pricing cycle |
| `Start_Pricing_UI.bat` | Windows: open the staff UI |
| `User_Guide.txt` | Short operator guide |
| `HANDOVER.md` | Closing state: what was verified, what is still synthetic, what was deliberately left out |
| `tests/` | Nine behaviour contracts plus `run_all.py`; each copies the project to a sandbox and asserts behaviour. Not pytest, no dependencies beyond the engine's own |
| `golden/` | Frozen snapshots of one pricing cycle (`v7` current, `v0` pre-correction) and the read-only diff tool |
| `output/` | Generated at run time: the two reports, `rms_run.log`, `rms_scheduler.log` and `archive/`. Git-ignored |

Inside `rms_core/`:

| Module | Purpose |
| --- | --- |
| `event_calendar.py` | Loads and validates `Public holidays.csv` |
| `timezone_config.py` | Shared timezone settings and IANA availability checks |
| `report_writer.py` | Atomic report publishing (private temp file + one `os.replace`) |
| `report_retention.py` | Soft-delete archiving of old reports into `archive/` |
| `price_guard.py` | Read-only pre-publish sanity checks on the priced frame |

The runnable entry points are `hotel rms.py` (one cycle), `rms_gui.py` (UI) and
`scheduler.py` (resident scheduler); only those three sit at the top level, so
the `.bat` launchers and the scheduler keep finding them by name. Everything in
`rms_core/` is imported by those scripts and has no command-line interface. The
package folder itself is added to `sys.path` by each entry point, so the tool
still works when it is started from another directory.

`timezone_settings.json` is created locally by the staff UI when a timezone
is chosen; it is git-ignored, so a fresh clone starts on local system time.
Generated reports, runtime logs, `__pycache__` and local credentials are also
git-ignored (see `.gitignore`).

## Architecture

The diagram below shows how the scripts, staff-maintained inputs and generated
reports fit together at runtime. Solid arrows are direct interactions (launch,
read, write, maintain); the dotted arrow is the optional PMS fetch, which is
short-circuited to synthetic data in `DEMO` mode.

```mermaid
flowchart TD
subgraph group_operations["Staff Operations"]
node_ui["Staff pricing UI<br/>[rms_gui.py]"]
end
subgraph group_pricing["Pricing"]
node_engine["Pricing engine<br/>[hotel rms.py]"]
node_pms{{"PMS API"}}
node_reports["Pricing reports"]
end
subgraph group_configuration["Calendar & Time"]
node_calendar_loader["Event calendar loader<br/>[rms_core/event_calendar.py]"]
node_calendar["Event calendar CSV"]
node_timezone["Timezone settings<br/>[rms_core/timezone_config.py]"]
end
subgraph group_automation["Automation"]
node_scheduler["Daily scheduler<br/>[scheduler.py]"]
end
node_staff(("Hotel staff"))
node_staff -->|"reviews results"| node_ui
node_staff -->|"maintains events"| node_calendar
node_ui -->|"runs pricing"| node_engine
node_ui -->|"browses reports"| node_reports
node_ui -->|"opens calendar"| node_calendar
node_ui -->|"sets timezone"| node_timezone
node_engine -.->|"fetches reservations"| node_pms
node_engine -->|"loads events"| node_calendar_loader
node_calendar_loader -->|"reads and validates"| node_calendar
node_engine -->|"reads timezone"| node_timezone
node_engine -->|"writes CSV reports"| node_reports
node_scheduler -->|"launches daily"| node_engine
node_scheduler -->|"reads timezone"| node_timezone
click node_engine "https://github.com/yuanxiangtong1-commits/hotel-rms-pricing-suggestion/blob/main/hotel%20rms.py"
click node_calendar_loader "https://github.com/yuanxiangtong1-commits/hotel-rms-pricing-suggestion/blob/main/rms_core/event_calendar.py"
click node_calendar "https://github.com/yuanxiangtong1-commits/hotel-rms-pricing-suggestion/blob/main/Public%20holidays.csv"
click node_timezone "https://github.com/yuanxiangtong1-commits/hotel-rms-pricing-suggestion/blob/main/rms_core/timezone_config.py"
click node_ui "https://github.com/yuanxiangtong1-commits/hotel-rms-pricing-suggestion/blob/main/rms_gui.py"
click node_scheduler "https://github.com/yuanxiangtong1-commits/hotel-rms-pricing-suggestion/blob/main/scheduler.py"
classDef toneNeutral fill:#f8fafc,stroke:#334155,stroke-width:1.5px,color:#0f172a
classDef toneBlue fill:#dbeafe,stroke:#2563eb,stroke-width:1.5px,color:#172554
classDef toneAmber fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#78350f
classDef toneMint fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px,color:#14532d
classDef toneRose fill:#ffe4e6,stroke:#e11d48,stroke-width:1.5px,color:#881337
classDef toneIndigo fill:#e0e7ff,stroke:#4f46e5,stroke-width:1.5px,color:#312e81
classDef toneTeal fill:#ccfbf1,stroke:#0f766e,stroke-width:1.5px,color:#134e4a
class node_ui toneBlue
class node_engine,node_pms,node_reports toneAmber
class node_calendar_loader,node_calendar,node_timezone toneMint
class node_scheduler toneRose
class node_staff toneIndigo
```

`hotel rms.py` is the hub: it loads the event calendar through
`event_calendar.py`, reads the shared timezone settings, fetches reservations
only when the PMS client is enabled, and writes both CSV reports. A cycle is
started either from the staff UI or by `scheduler.py`; both also read the same
timezone settings. Which inputs are real and which are synthetic is spelled out
in [Data sources (honest status)](#data-sources-honest-status).

## Requirements

Python 3.9+ and:

```bat
pip install pandas numpy requests schedule
```

`schedule` is used only by `scheduler.py`. `tkinter` ships with standard
CPython on Windows and macOS; on some Linux distributions it is a separate
package (for example `python3-tk`). The two `.bat` files expect Python on
`PATH` and fall back to `py`; on other platforms run the scripts directly.

Named IANA timezones additionally need the system IANA timezone database; on
Windows install the optional `tzdata` package (`pip install tzdata`). The
default `Follow local system time` needs nothing extra and works out of the
box. No `pytz` dependency is required - see
[Scheduler and timezone](#scheduler-and-timezone).

## Quick start

Run all commands from the repository directory; the `.bat` launchers do this
for you. Reports are always published into **`output/`**, whichever directory the
engine was started from.

```bat
Run_Pricing_Now.bat --check    # diagnose: which interpreter, are the packages there?
Run_Pricing_Now.bat            # one pricing cycle -> two CSV reports
Start_Pricing_UI.bat           # staff UI (click "Run Pricing Now")
python "hotel rms.py"          # the same cycle, if you want to run Python yourself
python rms_gui.py              # the same UI, from a terminal you control
python scheduler.py --run-now  # one cycle now, then stay resident for daily 06:00 runs
```

### Why the `.bat` files do not just call `python`

`where python` proves that a *name* exists, not that the interpreter behind it
can import `pandas`. Machines with several Python installations - including
the development machine for this project - very often have a `python` on
`PATH` with no packages, while `py` points at a complete one. Double-clicking
`Run_Pricing_Now.bat` then failed with `ModuleNotFoundError` in a window that
closed before it could be read.

Both launchers therefore start `rms_core/launcher.py`, which probes each
candidate interpreter (`py -3`, `py`, `python`, `python3`, then the one
running the launcher) by actually importing the three packages, and uses the
first one that succeeds. It prints which interpreter it picked, and if none
works it lists every interpreter it tried, the reason each failed, and the
exact `pip install` command - then waits for a key press instead of vanishing.

`--check` runs the whole check without starting anything. `RMS_NO_PAUSE=1`
suppresses the closing key prompt, for unattended use.

`scheduler.py --run-now` does **not** return after the first cycle: it keeps
running to serve the daily job. Leave its window open and press `Ctrl+C` to
stop it. With no scheduler process running there is no automatic 06:00 run.

With no PMS credentials configured, the engine short-circuits to clearly
labelled synthetic data and makes no network requests - the default `DEMO`
mode works fully offline. Setting `PMS_API_KEY` and `PMS_BASE_URL` enables the
optional live HTTP client (see [PMS data interface](#pms-data-interface)), so
those configurations do require network access.

## The staff UI

`rms_gui.py` is built around one rule: **what is on screen must be true about
itself.** Four behaviours enforce that.

- **It opens with the last run already loaded.** Staff usually open the window
  after the scheduled run, so the table, the data-mode banner and
  `Data generated: <time>` are filled in at startup. An empty-looking window
  would suggest the tool had never run.
- **A failed run says so, and says why.** `describe_engine_exit()` maps the
  engine's exit code to a specific sentence: `0` success, `2` an invalid
  calendar or configuration value, `3` the price guard refused to publish,
  anything else an unexpected crash. On failure the freshness label turns red
  (`STALE - last updated ...`) and a separate red notice reads
  `RESULTS NOT UPDATED - showing data from ...`. The data-mode banner is a
  different label on purpose: a failure must never erase the DEMO warning.
- **The previous table is kept, but relabelled.** Blanking the rows would hide
  the last recommendation and leave staff guessing; keeping them with an
  explicit stale label preserves their context without pretending the run
  succeeded.
- **Runs can be cancelled, and closing the window stops the child.** `Cancel
  Run` terminates the engine process (escalating to a hard kill after five
  seconds) and returns the UI to idle. Closing the window during a run asks for
  confirmation and kills the child, so no orphan process keeps writing reports
  after the window is gone. A cancelled run is not a failure: the results on
  screen are left untouched and not marked stale.

Worker threads never call Tk directly - a reader thread raises
`main thread is not in main loop` when it does. All cross-thread work goes
through a `queue.Queue` drained on the main thread, which is why shutting the
window down mid-run no longer prints tracebacks.

## Public holidays / special events

`Public holidays.csv` is the **single source of event factors**. Staff edit it
directly in Excel or Notepad; there are no hard-coded events in the engine.
Click **Open Event Calendar** in the UI to open it, save the file as UTF-8
CSV, then click **Run Pricing Now** again. No restart is needed.

### Columns

| Column | Format | Meaning |
| --- | --- | --- |
| `Date` | `YYYY/MM/DD`, e.g. `2026/12/25` | A full date with a four-digit year. With `Recurring=Y` only its month/day is used, so it repeats every year and the written year is a placeholder. Otherwise the exact date is priced once |
| `Event_Name` | free text, may be empty | Shown in reports. If empty, the reason reads `Public Holiday Demand Window Triggered` |
| `Event_Factor` | finite number > 0 | Demand multiplier: `1.00` neutral, `1.25` = +25%, `0.90` = -10%. A blank, `NaN` or infinite value stops the run instead of being read as "no event". Usual range 0.50-3.00; values outside it are loaded with a `[WARN]`, and anything above 5.00 is additionally flagged as a likely typo |
| `Category` | `Public Holiday` / `Special Event` / `School Holiday` / `Custom` | Used in the pricing reason. Unknown values are mapped to `Special Event` with a warning |
| `Recurring` | `Y` or `N` (blank = `N`) | `Y` repeats the same month/day every year |

`Holiday_Factor` and `Special_Event_Factor` are accepted as aliases for
`Event_Factor`, so older files using those column names still load. Every row
must still carry a complete date: `YYYY/MM/DD` is the current format and the
legacy `YYYY-MM-DD` spelling is accepted, but a bare `MM-DD` is **not**.
An older calendar that used `MM-DD` rows needs those dates rewritten before
it can be used. Lines starting with `#` and blank lines are ignored, which is
why the shipped file can carry its own instructions.

### Rules

- Dates are **absolute**. A stay date always gets the same event factor, no
  matter which day the engine runs; no `today + N` offsets are used.
- With `Recurring=Y` only the month and day are used, so fixed-date holidays
  carry over to future years.
- A one-off row (`Recurring=N`) overrides a recurring row on that same date,
  regardless of which one appears first in the file. Among rows of the **same
  kind**, the last row wins. Use a one-off row to override a holiday for one
  specific year.
- Only dates inside the current 90-day window are priced. The window starts
  on the current date in the selected property timezone, so switching across
  the date line can shift it by one day and change which calendar rows fall
  inside it. This is expected behaviour, not a calendar error.
- A missing file, a missing `Date` / `Event_Factor` column, a bad date, a
  non-numeric, non-finite or non-positive factor stops the run with an error
  and a line number. The engine does **not** silently fall back to demo events.
- Calendar maintenance is checked at two levels and the run reports how much
  of the window is actually covered, for example
  `Calendar coverage: 5 of 90 stay dates carry an event factor (5.6%)`.
  - A year with no event rows at all warns that the year was never filled in.
  - A year with **only** recurring rows warns that no one-off event is dated
    there, so movable holidays (Chinese New Year, Easter, a motor race) would
    be priced as ordinary days. Recurring placeholders no longer count as
    coverage, which is how a forgotten movable holiday used to stay silent.
- If the same date is loaded twice with two different factors, the last row
  still wins, but the run prints a warning naming both line numbers so an
  unintended override cannot pass as a correct rate.
- Fatal vs non-fatal input problems: only malformed calendar rows abort a
  run. A bad PMS timestamp or an invalid stored timezone emits a `[WARN]`
  line and falls back to a default, so neither can block a pricing run.

### About the shipped calendar

`Public holidays.csv` ships with five fixed-date example rows, all
`Recurring=Y`: New Year's Day, Christmas Eve, Christmas Day, Christmas
Weekend and New Year's Eve. Their factors range from 1.20 to 1.50 and the
written year is only a placeholder, so they also apply in later years.

These rows are examples, not a complete holiday list. Replace or extend them
with the dates that matter to your property. Use `Recurring=N` for movable
dates that change every year (for example lunar-new-year dates, school
holiday periods and observed-in-lieu holidays), and refresh those rows each
year from your local official holiday calendar. The demo does not assume any
particular country or property; the shipped rows are generic fixed dates.

**Excel note.** The CSV itself is plain ASCII English text with no non-ASCII
characters. Excel may reformat a date cell using your system locale - on a
Chinese locale, `2026/12/25` may be displayed as `2026年12月25日` - even
though the file contains no such characters. To keep the exact `YYYY/MM/DD`
text, format the `Date` column as Text before editing, or use Notepad /
VS Code. The on-screen format does not change what the engine reads.

## Pricing model

```text
Base_Room_ADR     = BASELINE_ADR x RoomType_Factor
                    (Standard 135 x 1.00 = 135; Premium 160 x 1.25 = 200)
Recommended_ADR   = Base_Room_ADR x Weekend x Event_Factor x Occupancy
                         x Lead_Time x Booking_Pace x Competitor
Final_ADR         = clamp(floor(clamp(Recommended_ADR, MIN, MAX) + 0.5),
                          ceil(MIN), floor(MAX))
```

The factor tables (weekend, occupancy, pace, lead time, competitor), the
same-day time-decay layer and the guest-density surcharge are defined in
`hotel rms.py`. "Baseline" in this document always means the shipped
`BASELINE_ADR` configuration, not a previous release of the tool.

Three details decide a rate as much as the factor tables do:

- **Occupancy has one definition.** `Current_Occupancy` is the only occupancy
  figure in the engine, and `Effective_Occupancy` is now by definition the same
  number. Net of blocked rooms, and on day 0 taken from the live dashboard
  because rooms sold for tonight are already occupied rather than "on the
  books". A row can no longer display 80% occupancy while pricing at 0%.
- **Booking pace needs a denominator.** `Pace_Basis` says whether the ratio was
  actually measured. When last year's comparable date carries no bookings at
  all, the basis is `no_history` and the pace factor is neutral `1.00` — the
  engine does not invent a denominator of 1 and call it "10% behind pace".
- **Guest density is a same-day signal.** Guests per occupied room describes
  who is in the building tonight, so the surcharge only applies to arrivals
  with `Days_to_Checkin = 0`. It never reprices next month.

A rate is published in whole currency units and always inside its own band:
the engine rounds half up and then clamps to `[ceil(MIN_ADR), floor(MAX_ADR)]`,
so `MIN_ADR = 94.5` can never be published as `94`.

Rate guards give event days extra headroom so a strong event factor is not
clipped by the generic ceiling, but the headroom itself has a hard limit:

```text
MIN_ADR = Base_Room_ADR x 0.70
MAX_ADR = Base_Room_ADR x min(max(2.00, Event_Factor x 1.60), 4.00)
```

With the largest shipped event factor of `1.50`, the ceiling becomes
`max(2.00, 1.50 x 1.60) = 2.40 x Base_Room_ADR`, so those holiday rows have
room to affect `Final_ADR` instead of being clipped at `2.00 x Base_Room_ADR`.
Every clipped row is flagged with `Rate_Cap_Applied` in the technical view and
`| Rate ceiling applied` / `| Rate floor applied` in the manager view, so a
guard hit is never hidden.

The outer `4.00` is an absolute ceiling. Event headroom stays fully effective
up to an `Event_Factor` of `2.50`; above that the cap stops growing, so a
mistyped `15.00` can no longer turn a `135` base rate into a `2924` nightly
rate. When the absolute ceiling binds, the run logs a `[WARN]` naming the stay
date, the factor and the headroom that would have been allowed.

Before anything is published, `price_guard.find_violations()` re-checks the
priced frame: all seven price columns (`MIN_ADR`, `MAX_ADR`,
`Recommended_ADR`, `Model_ADR_Before_Adjustments`,
`Post_Model_Adjustment_Factor`, `Final_ADR`, `Expected_RevPAR`) must be
finite, `Final_ADR` must sit inside `MIN_ADR`/`MAX_ADR` with **no** rounding
tolerance (the whole-unit clamp above guarantees it), `MAX_ADR` must exceed
`MIN_ADR`, `MIN_ADR` must be positive, and no stay date / room type may appear
twice. A violation stops the run with exit code `3` and writes `[ERROR]` lines
to the log instead of publishing rates that contradict their own guard.

## Reproducibility

Event factors are absolute and competitor ADR is a deterministic hash of the
stay date, so those inputs are comparable across runs and years.

To replay a complete window - for back-testing, training or year-over-year
comparison - set `RMS_AS_OF_DATE` in `YYYY/MM/DD` form before running. The
synthetic reservation feed and the report date suffix are then anchored to
that date too:

```bat
set RMS_AS_OF_DATE=2026/09/01
python "hotel rms.py"
```

PowerShell: `$env:RMS_AS_OF_DATE = "2026/09/01"`, then the same `python` line.
On bash / macOS: `export RMS_AS_OF_DATE=2026/09/01`.

For a repeatable *time of day* (used to check the same-day discount tiers),
set `RMS_AS_OF_DATETIME` to a wall-clock timestamp in the selected timezone.
This variable keeps the ISO `YYYY-MM-DD HH:MM:SS` form because it is parsed
as a PMS timestamp, not as a calendar date:

```bat
set RMS_AS_OF_DATETIME=2026-09-01 22:30:00
python "hotel rms.py"
```

## Verification

Every behaviour the system promises is covered by a contract in `tests/`. They
are ordinary scripts, not pytest: each copies the project into a temporary
sandbox, runs the real entry points and asserts the outcome, so running them
never touches `output/`:

```bat
py tests/run_all.py                 :: all nine, about 80 seconds
py tests/run_all.py --only step7    :: one contract
```

Price-bearing changes are guarded separately by a frozen baseline:

```bat
py golden/diff_reports.py --baseline golden/v7/reports --candidate output --strict
```

`--strict` returns exit code 1 if any price column moved. A change that is not
meant to affect prices must report zero diffs; a change that is must be able to
prove its delta set is closed. `tests/README.txt` maps each contract to the
failure it exists to catch, and `HANDOVER.md` records the current state.

PowerShell: `$env:RMS_AS_OF_DATETIME = "2026-09-01 22:30:00"`.
On bash / macOS: `export RMS_AS_OF_DATETIME="2026-09-01 22:30:00"`.
Quote the value on those shells because it contains a space.

Leave both variables unset for normal daily operation. In `DEMO` mode the
synthetic reservation feed is anchored to the run date, so OTB and pace
figures differ between runs on *different* days; `RMS_AS_OF_DATE` removes
even that variation. Reproducible *operational* inputs would additionally
require a live PMS integration, which is not bundled with this demo; see the
next section for the optional HTTP client.

## Data sources (honest status)

| Input | `DEMO` | `LIVE_PMS_SYNTHETIC_MARKET` | `PMS_FALLBACK_SYNTHETIC_MARKET` |
| --- | --- | --- | --- |
| Reservations / occupancy | Synthetic, anchored to the run date | Live PMS v1.3 | Synthetic fallback (at least one PMS read failed or stayed pending) |
| Competitor ADR | Deterministic synthetic hash per stay date | Deterministic synthetic hash per stay date | Deterministic synthetic hash per stay date |
| Baseline ADR | Constant `BASELINE_ADR` | Constant `BASELINE_ADR` | Constant `BASELINE_ADR` |
| Holidays / events | `Public holidays.csv` (staff-maintained) | `Public holidays.csv` (staff-maintained) | `Public holidays.csv` (staff-maintained) |

`deterministic_competitor_adr()` and `BASELINE_ADR` in `hotel rms.py` are the
two replacement points for a real rate-shopper feed and a real historical ADR
feed. Until those are replaced, even a live PMS connection still produces a
partly synthetic recommendation; that is why the mode is named
`LIVE_PMS_SYNTHETIC_MARKET` rather than `LIVE`.

A configured key does not guarantee live data. Both PMS reads report what
they actually used, and `Data_Mode` is resolved only **after** both finish.
If either call fails, the report is marked `PMS_FALLBACK_SYNTHETIC_MARKET`,
the UI banner turns red, and a `[WARN]` line is written to `rms_run.log`. A
report therefore cannot claim LIVE data it did not receive. The
`Data_Sources` column records the per-input outcome
(`demo_synthetic` / `synthetic_fallback` / `PMS_live`).

## PMS data interface

The request layout follows Cloudbeds API v1.3 conventions as a **format
reference only**. This repository is not affiliated with any vendor, ships no
real endpoint or credential, and bundles no working integration.

To point the optional HTTP client at your own PMS, set both `PMS_BASE_URL`
(the base URL of an API implementing the two endpoints below) and
`PMS_API_KEY` (the value sent as `x-api-key`), then start any of the pricing
entry points. The engine stays in `DEMO` mode if either variable is unset, if
the key still starts with `YOUR_`, or if `PMS_BASE_URL` still contains
`example-pms.com`.

- Header: `x-api-key: <your key>` - the value of `PMS_API_KEY`
- `GET {BASE_URL}/getDashboard` -> `data` with `capacity`, `roomsBlocked`,
  `inHouse`, `guestsInHouse`, `percentageOccupied`, `property_now`
- `GET {BASE_URL}/getReservations` -> `data[]` with `reservationID`,
  `dateCreated`, `status`, `startDate`, `endDate`, `balance`
  (statuses used: `confirmed`, `checked_in`, `checked_out`)

`{BASE_URL}` above is the value of `PMS_BASE_URL`. `property_now` is
interpreted in the selected property timezone: a value without a UTC offset
is treated as wall-clock time in that timezone, while a value with an offset
is converted to it. Missing or unparseable values fall back to the current
property time with a `[WARN]` line, so a bad timestamp never stops a run.

Never commit real credentials. Without them the engine short-circuits to
synthetic data instead of waiting on a network timeout, although the console
still prints a "Connecting to PMS API v1.3" line before falling back.

## Scheduler and timezone

Pick the property timezone from the second-row **Timezone** dropdown in the
staff UI. The choice takes effect as soon as it is selected - there is no
Apply button - and pricing is re-run automatically so the table shows rates
for the new timezone.

The default is `Follow local system time`, which needs no timezone database at
all. Named IANA zones (for example `Europe/London`) need the system IANA
database; on Windows install `tzdata` (see [Requirements](#requirements)). If
the database is missing the UI explains what to install and keeps the
local-time setting; an invalid stored value only emits a `[WARN]` line and
never blocks a pricing run. UTC offsets shown in the dropdown are computed at
runtime, so daylight-saving changes are handled automatically.

The choice is stored in `timezone_settings.json` in the script folder:

```json
{"timezone": "Europe/London", "schema_version": 1}
```

`"timezone": null` means local system time. This file is written only by the
UI and is git-ignored.

Timezone handling uses the standard library only. The scheduler converts
06:00 in the selected zone into the equivalent machine-local wall-clock time
and registers a plain daily job; it does not pass a timezone to `schedule`
and does not require `pytz`. It recomputes that time every minute, so
daylight-saving transitions are picked up automatically without a restart.

The same setting drives **all** of the following:

- The unattended 06:00 run. It requires `scheduler.py` to be running as a
  long-lived process (`python scheduler.py --run-now`); see
  [Quick start](#quick-start). A running scheduler notices a configuration
  change within about a minute and rebuilds its job, so no restart is needed.
- The pricing engine's "today": the 90-day window, day-of-week factors,
  days-to-check-in and the report date suffix.
- The PMS `property_now` hour, which drives the same-day discount tiers
  (18:00 / 20:00 / 22:00). In `DEMO` mode this hour is the current wall-clock
  time in the selected timezone, so the sample rates react to a switch too.

Switching across the date line can therefore move the window by one day and
change which holiday rows are inside it - see the calendar **Rules** section
above.

## Generated outputs

Each run writes two CSV reports into **`output/`**, no matter which directory
launched the engine. Nothing generated is ever written beside the code:

| Report | View | Columns to know |
| --- | --- | --- |
| `hotel_name_Live_Dashboard_YYYY-MM-DD.csv` | Technical, 36 columns | Per-day factors, `Pace_Basis`, guard flags, `Recommended_ADR`, `Data_Mode`, `Data_Sources`, `Run_Timestamp` |
| `hotel_name_RMS_Manager_View_YYYY-MM-DD.csv` | Manager, 12 columns | `Stay_Date`, `Room_Type`, `Final_ADR`, `ADR_Change_vs_Base`, `Demand_Status`, `Action`, `Reason`, `Confidence_Score`, `Data_Mode`, `Data_Sources`, `Run_Timestamp` |

`ADR_Change_vs_Base` and `Action` both use the displayed, rounded percentage.

### Reading the technical view

`Recommended_ADR` is the pre-guard rate. Rebuild it by multiplying
`Base_Room_ADR` by `Weekend_Factor`, `Event_Factor`, `Occupancy_Factor`,
`Lead_Time_Factor`, `Booking_Pace_Factor`, `Competitor_Factor` and
`Post_Model_Adjustment_Factor`. `Model_ADR_Before_Adjustments` is that product
before same-day adjustments. The 14 factor columns make every step auditable.

`Pace_Basis` states how much evidence the pace ratio rests on:

| Value | Meaning | Pace factor |
| --- | --- | --- |
| `measured` | Last year's comparable date had bookings, and `Hist_OTB_At_Same_LeadTime` is the count on the books at the same lead time | `Pace_Ratio = Current_OTB_Rooms / Hist_OTB_At_Same_LeadTime` |
| `no_history` | `Hist_Pool_Nights` is 0 — there is no comparable date to divide by | neutral `1.00` |

`Hist_Pool_Nights` is the raw number of room-nights sold for the same date one
year earlier, so "no data" and "no bookings" can be told apart.

`Data_Sources` records what was actually used: `baseline=constant_synthetic`,
`competitor=synthetic_hash`, and `dashboard=` / `reservations=` as
`demo_synthetic`, `synthetic_fallback` or `PMS_live`. `Run_Timestamp` is
identical in both reports, so the pair can be traced to one cycle; the UI
warns if the two files on screen do not match.

### File names and safety

- `Stay_Date` uses `YYYY/MM/DD`; file names keep the ISO `YYYY-MM-DD` suffix
  because `/` is not allowed in Windows file names. The UI finds reports by
  that suffix.
- Reports are written atomically, never exposed half-written. If a report is
  open in Excel, the engine saves `..._YYYY-MM-DD_FALLBACK.csv` and logs a
  `[WARN]`; later runs reuse that name.
- Cycle warnings and errors are appended to `output/rms_run.log` beside the
  reports.
- The UI strips `RMS_AS_OF_DATE` / `RMS_AS_OF_DATETIME` before launching the
  engine, so a leftover back-test setting cannot pass as today's rates.
- Report files, logs and `archive/` all live under `output/`; nothing the tool
  generates is written beside the code any more. Files that predate `output/`
  are moved into it on the next run (or when the UI opens), reported as
  `Moved N generated file(s) ...`, and never deleted or overwritten.

### Report retention

After the two reports are written, the engine keeps only the newest 3 distinct
report dates in `output/` and MOVES older ones - including their `_FALLBACK`
copies and any legacy `_HHMMSS` copies - into `output/archive/`. This is a soft delete: nothing
is deleted, so drag a file back out of `output/archive/` to restore it. The decision
uses the ISO date parsed from the file name in the selected property timezone,
not the file modification time or calendar days; a report date in the future
or an unparseable name is left alone with a `[WARN]`.

Tune the window with `RMS_REPORT_KEEP` (default `3`). Preview the exact file
list without moving anything by setting `RMS_REPORT_RETENTION_DRY_RUN=1`.
Back-test runs that set `RMS_AS_OF_DATE` or `RMS_AS_OF_DATETIME` skip
retention entirely, so replay reports are never archived. Retention failures
only produce a `[WARN]` and never fail a pricing cycle. The staff UI scans
only `output/`, so archived reports are not shown as the latest result.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `python` is not recognised | Install Python 3.9+ and put it on `PATH`. The `.bat` launchers try `py -3`, `py`, `python` and `python3` in turn. |
| `[ERROR] No Python interpreter with the required packages` | The launchers could not find a usable interpreter. The message lists every interpreter tried and the failure for each; run the quoted `pip install pandas numpy requests` command, or install Python from python.org with "Add python.exe to PATH" ticked. |
| `ModuleNotFoundError` when running `python "hotel rms.py"` directly | That `python` is not the interpreter with the packages. Run `Run_Pricing_Now.bat --check` to see the one that works, or use the `.bat` launcher. The UI also reports missing packages in its log box. |
| `[ERROR] Event calendar not found` | Confirm `Public holidays.csv` exists beside the scripts. If it is missing, restore it from version control or recreate it with the header shown in **Columns**; the engine will not produce rates from an incomplete calendar. |
| An error names a calendar line number | Fix that row in `Public holidays.csv` and run again. Bare `MM-DD` dates and non-numeric, non-finite or non-positive factors are rejected. |
| Reports are not where you expected | They are written to `output/`. Check the `[OK] ... written: <path>` line in the log for the exact location. |
| Reports from earlier dates are missing | Older report dates were moved, not deleted, into `output/archive/`. Drag a file back out to `output/` to restore it; see [Report retention](#report-retention). |
| No automatic 06:00 run | A scheduler process must be running (`python scheduler.py --run-now`). It stays resident; close its window or press `Ctrl+C` to stop it. |
| `Timezone data not available` in the UI | Run `pip install tzdata`, then reopen the UI; or keep `Follow local system time`. |
| Excel shows dates differently | See the **Excel note** above and format the `Date` column as Text. |
| Dates shifted by one day after a timezone switch | Expected: the 90-day window starts on the current date in the selected property timezone. |
| UI shows `RESULTS NOT UPDATED` / `STALE` | The last run failed, so the table is the previous report. Read the `[ERROR]` line in the log box: exit `2` is a bad calendar or configuration value, exit `3` is the price guard. Fix it and run again; do not publish the stale rows. |
| UI was closed while a run was in progress | Expected: closing the window stops the engine, so the cycle may not have written reports. Run pricing again from a fresh window. |

## Privacy

Property and brand names, vendor names in code, machine-specific paths, real
credentials, historic business reports and personal metadata have been
replaced with generic placeholders such as `hotel_name`. No real customer,
business or personal data is included; all figures are demo values. Third-party
API names appear in this document only as format references; no vendor
endpoint or integration is bundled.
