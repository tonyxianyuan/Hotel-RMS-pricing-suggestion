# Hotel RMS (Pricing Suggestion)

A self-contained pricing-suggestion demo for a single hotel property.
It pulls booking pace from a PMS, applies demand / lead-time / competitor /
holiday factors, and writes two CSV reports plus a small staff-facing UI.

## Files

| File | Purpose |
| --- | --- |
| `hotel rms.py` | Pricing engine: PMS adapter, 90-day rate model, CSV exports |
| `rms_gui.py` | Tkinter staff UI: run pricing, browse results, explain each rate |
| `scheduler.py` | Unattended daily 06:00 run (`--run-now` for an immediate cycle) |
| `Run_Pricing_Now.bat` | Windows: run one pricing cycle |
| `Start_Pricing_UI.bat` | Windows: open the staff UI |
| `User_Guide.txt` | Short operator guide |
| `public_holidays.csv` | Holiday / special-date format template (see below) |

Excluded on purpose: generated report CSVs, runtime logs, `__pycache__`,
and any machine-specific paths or credentials. See `.gitignore`.

## Requirements

Python 3.9+ and:

```
pip install pandas numpy requests schedule
```

`tkinter` ships with standard CPython. The two `.bat` files expect Python on
`PATH`; on other platforms run the scripts directly.

## Quick start

```
python "hotel rms.py"          # one pricing cycle -> two CSV reports
python rms_gui.py              # staff UI (click "Run Pricing Now")
python scheduler.py --run-now  # immediate run, then daily at 06:00
```

If the PMS call fails or no key is configured, the engine falls back to
built-in demo data, so everything runs offline out of the box.

## PMS data interface (read this before wiring your own API)

The request/field layout follows the **Cloudbeds API v1.3** conventions
(this is a format reference only; this repository is not affiliated with any
vendor and contains no real endpoint or credential):

- Header: `x-api-key: <your key>`
- `GET {BASE_URL}/getDashboard` -> `data` with
  `capacity`, `roomsBlocked`, `inHouse`, `guestsInHouse`,
  `percentageOccupied`, `property_now`
- `GET {BASE_URL}/getReservations` -> `data[]` with
  `reservationID`, `dateCreated`, `status`, `startDate`, `endDate`, `balance`
  (`status` values used: `confirmed`, `checked_in`, `checked_out`)

In `hotel rms.py`, both `API_KEY` and `BASE_URL` are placeholders
(`YOUR_PMS_API_KEY_HERE` and `https://api.example-pms.com/api/v1.3`).
Replace them with your own PMS endpoint and key. **Do not commit real
credentials** - use an environment variable or a local `.env` (git-ignored).

## Public holidays / special dates

`public_holidays.csv` documents the expected format:

| Column | Format | Meaning |
| --- | --- | --- |
| `Date` | `YYYY-MM-DD` | The stay date the factor applies to |
| `Event_Name` | free text | Shown in the UI as the demand reason |
| `Holiday_Factor` | float >= 1.0 | Demand multiplier, e.g. `1.20` = +20% uplift |

Example rows (New Year's Day and Christmas) are included as generic samples.
Add one row per special date; keep the header row exactly as shown.

> **Note:** in this version the holiday table inside `hotel rms.py` is a
> hard-coded demo `DataFrame`; this CSV is a format template and is **not
> read by the engine yet**. To activate it, replace that `df_holidays`
> definition with `pd.read_csv("public_holidays.csv")` (and parse `Date`).

## Timezone

`scheduler.py` uses a single configurable constant:

```python
PROPERTY_TIMEZONE = None          # local time by default
```

Set it to an IANA name (for example `"Europe/London"`) to pin the daily run
to a specific timezone; that requires `tzdata` or `pytz` to be installed.
With `None` the scheduler simply uses the machine's local time, so the repo
runs out of the box with no extra timezone dependency. A timezone picker in
the staff UI is planned for a later version.

## Generated outputs

Running the engine creates two reports next to the scripts:
`hotel_name_Live_Dashboard_YYYY-MM-DD.csv` (technical view) and
`hotel_name_RMS_Manager_View_YYYY-MM-DD.csv` (manager view).
They are generated artifacts and are git-ignored.

## Privacy

All property / brand names, vendor names in code, personal or machine-specific
paths, real credentials, historic business reports and personal metadata have
been removed or replaced with generic placeholders. No real customer, business
or personal data is included; all figures are demo values.
