# -*- coding: utf-8 -*-
"""Public holiday / special event calendar loader for the Hotel RMS.

The calendar is a plain UTF-8 CSV maintained by hotel staff. It is the only
source of event pricing factors. The engine does NOT fall back to hard-coded
events when the file is missing or invalid: that would silently produce
untrustworthy rates.

Accepted header spellings (case, spaces, hyphens and underscores ignored):
    Date
    Event_Name / EventName / Event
    Event_Factor / Holiday_Factor / Special_Event_Factor / Factor
    Category / Event_Category
    Recurring / Repeat / Annual

Date format:
    YYYY/MM/DD   full date, the only format used by the shipped calendar
    YYYY-MM-DD   legacy ISO spelling, still accepted for older files

Recurring=Y ignores the written year and repeats the month/day every year;
otherwise the full date is priced once. There is no MM-DD shorthand, so every
row shows a complete date and no locale-dependent "month/day" notation.

A blank, NaN or infinite Event_Factor is rejected: those values cannot be
priced and silently treating them as "no event" would under-price a peak day.

This module is independent of the pricing engine so it can be tested alone.
All identifiers, comments, messages and exceptions are English.
"""

from __future__ import annotations

import csv
import math
import os
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd


CATEGORIES = ("Public Holiday", "Special Event", "School Holiday", "Custom")
DEFAULT_CATEGORY = "Special Event"

# Event_Factor guidance. A value outside the usual band still loads, because a
# genuine once-in-a-decade event may justify it, but the run says so loudly.
# Above the hard maximum the value is almost certainly a data-entry error, so
# the warning names the accepted maximum instead of only the usual range. The
# pricing engine additionally refuses to price any night above an absolute
# multiple of the base rate, so a mistyped factor can never inflate a rate
# without limit.
FACTOR_WARN_LOW = 0.50
FACTOR_WARN_HIGH = 3.00
FACTOR_HARD_MAX = 5.00
EVENT_COLUMNS = [
    "Date",
    "Event_Name",
    "Event_Factor",
    "Event_Category",
    "Event_Source",
]


class CalendarError(ValueError):
    """Raised when the event calendar is missing, malformed or unusable."""


@dataclass
class CalendarData:
    """Events inside the pricing window plus non-fatal review warnings."""

    events: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


# Canonical column name -> accepted normalised spellings.
_HEADER_MAP = {
    "date": "date",
    "eventname": "event_name",
    "event": "event_name",
    "eventfactor": "event_factor",
    "holidayfactor": "event_factor",
    "specialeventfactor": "event_factor",
    "factor": "event_factor",
    "category": "category",
    "eventcategory": "category",
    "recurring": "recurring",
    "repeat": "recurring",
    "annual": "recurring",
}


def _normalise(value: object) -> str:
    """Normalise a header or flag for tolerant comparison."""
    return re.sub(r"[\s_\-]+", "", str(value or "").strip()).lower()


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in ("y", "yes", "true", "1")


def _read_rows(path: str):
    """Return (DictReader, resolved columns, original line numbers)."""
    if not os.path.isfile(path):
        raise CalendarError(
            "Event calendar not found: {}. Create 'Public holidays.csv' next "
            "to the pricing engine; the run has been stopped so no rates are "
            "produced from an incomplete calendar.".format(path)
        )

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        pairs = [
            (number, line)
            for number, line in enumerate(handle, start=1)
            if line.strip() and not line.lstrip().startswith("#")
        ]

    if not pairs:
        raise CalendarError(
            "Event calendar is empty (only comments or blank lines): {}".format(path)
        )

    reader = csv.DictReader([line for _, line in pairs])
    if not reader.fieldnames:
        raise CalendarError("Event calendar has no header row: {}".format(path))

    columns: dict[str, str] = {}
    for original in reader.fieldnames:
        canonical = _HEADER_MAP.get(_normalise(original))
        if canonical:
            columns[canonical] = original

    missing = [name for name in ("date", "event_factor") if name not in columns]
    if missing:
        raise CalendarError(
            "Event calendar is missing required column(s) [{}] in {}. "
            "Expected at least: Date, Event_Factor. "
            "Holiday_Factor and Special_Event_Factor are accepted aliases.".format(
                ", ".join(missing), path
            )
        )

    return reader, columns, [number for number, _ in pairs][1:]


def _parse_calendar_date(raw: object, line_no: int, path: str):
    """Return (full_date, month, day) for a YYYY/MM/DD date.

    YYYY-MM-DD is accepted as a legacy spelling so older calendars keep
    working, but every row must still carry a four-digit year. A bare MM-DD
    is rejected: it is the source of locale-dependent date displays.
    """
    text = str(raw or "").strip()
    match = re.fullmatch(r"(\d{4})/(\d{2})/(\d{2})", text) or re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})", text
    )
    if not match:
        raise CalendarError(
            "Line {} in {}: unsupported Date '{}'. Use YYYY/MM/DD "
            "(for example 2026/12/25).".format(line_no, path, text)
        )
    year, month, day = (int(part) for part in match.groups())
    try:
        parsed = date(year, month, day)
    except ValueError as exc:
        raise CalendarError(
            "Line {} in {}: invalid date '{}'.".format(line_no, path, text)
        ) from exc
    return parsed, month, day


def _category_of(raw: object, line_no: int, warnings: list[str]) -> str:
    text = str(raw or "").strip()
    if not text:
        return DEFAULT_CATEGORY
    for category in CATEGORIES:
        if text.lower() == category.lower():
            return category
    warnings.append(
        "Line {}: unknown Category '{}' mapped to '{}'.".format(
            line_no, text, DEFAULT_CATEGORY
        )
    )
    return DEFAULT_CATEGORY


def annual_review_warnings(
    data: CalendarData, window_start, window_end
) -> list[str]:
    """Warn when a year covered by the window looks unmaintained.

    Two separate checks, because they catch different mistakes:

    * no event rows at all for the year - the calendar was never filled in;
    * event rows exist but none of them is a one-off row - only the fixed-date
      recurring holidays were maintained, so movable holidays (Chinese New
      Year, Easter, a motor race) are missing and will be priced as ordinary
      days. Counting recurring rows as coverage is what used to hide this.
    """
    start = pd.Timestamp(window_start).date()
    end = pd.Timestamp(window_end).date()
    messages = []
    for year in range(start.year, end.year + 1):
        if data.events.empty:
            year_rows = data.events
        else:
            year_rows = data.events[data.events["Date"].dt.year == year]
        if year_rows.empty:
            messages.append(
                "No event rows cover {}. Add that year's holidays to "
                "'Public holidays.csv' before relying on {} pricing.".format(
                    year, year
                )
            )
            continue
        if not (year_rows["Event_Source"] == "One-off").any():
            messages.append(
                "No one-off event is dated in {}: movable holidays such as "
                "Chinese New Year, Easter or a motor race will be priced at the "
                "neutral 1.00 factor. Add them with Recurring=N and refresh that "
                "list every year.".format(year)
            )
    return messages


def describe_coverage(data: CalendarData, window_start, window_end) -> str:
    """One-line summary of how much of the pricing window is event-priced."""
    start = pd.Timestamp(window_start).date()
    end = pd.Timestamp(window_end).date()
    total = (end - start).days + 1
    covered = len(data.events)
    share = (100.0 * covered / total) if total > 0 else 0.0
    if covered:
        one_off = int((data.events["Event_Source"] == "One-off").sum())
    else:
        one_off = 0
    return (
        "Calendar coverage: {} of {} stay dates carry an event factor "
        "({:.1f}%); {} recurring, {} one-off.".format(
            covered, total, share, covered - one_off, one_off
        )
    )


def _duplicate_warnings(rows: list[dict], kind: str) -> list[str]:
    """Name every date that is loaded twice with two different factors.

    The loader deliberately keeps the last row, but a silently overridden
    factor is indistinguishable from a correct one in the report, so the
    override is reported with both line numbers.
    """
    messages = []
    seen: dict = {}
    for record in rows:
        key = record["Date"].date()
        previous = seen.get(key)
        if previous is not None and previous["Event_Factor"] != record["Event_Factor"]:
            messages.append(
                "Line {}: {} event on {} repeats line {} with a different factor "
                "({} vs {}). The last row wins; delete the stale row so the "
                "intended factor is unambiguous.".format(
                    record["_Line"], kind, key.isoformat(), previous["_Line"],
                    record["Event_Factor"], previous["Event_Factor"]
                )
            )
        seen[key] = record
    return messages


def load_event_calendar(path: str, window_start, window_end) -> CalendarData:
    """Load, validate and expand the staff-maintained event calendar.

    Returns events whose Date falls inside [window_start, window_end], with
    columns Date, Event_Name, Event_Factor, Event_Category, Event_Source.
    Recurring=Y rows use only their month/day and are expanded for every year
    touched by the window, so the written year is a placeholder. One-off rows
    override recurring rows on the same date; otherwise the last row for a
    date wins. Invalid input raises CalendarError with a line number. A date
    that is loaded twice with two different factors is reported as a warning
    rather than silently overridden.
    """
    start = pd.Timestamp(window_start).date()
    end = pd.Timestamp(window_end).date()
    if end < start:
        raise CalendarError("Pricing window end is before its start.")

    reader, columns, line_numbers = _read_rows(path)
    warnings: list[str] = []
    one_off_rows: list[dict] = []
    recurring_rows: list[dict] = []

    date_col = columns["date"]
    factor_col = columns["event_factor"]
    name_col = columns.get("event_name")
    category_col = columns.get("category")
    recurring_col = columns.get("recurring")

    for row, line_no in zip(reader, line_numbers):
        if not any(str(value or "").strip() for value in row.values()):
            continue

        recurring = _truthy(row.get(recurring_col, "")) if recurring_col else False
        parsed_date, month, day = _parse_calendar_date(
            row.get(date_col, ""), line_no, path
        )

        try:
            factor = float(str(row.get(factor_col, "")).strip())
        except (TypeError, ValueError) as exc:
            raise CalendarError(
                "Line {} in {}: Event_Factor '{}' is not a number.".format(
                    line_no, path, row.get(factor_col, "")
                )
            ) from exc
        if not math.isfinite(factor):
            raise CalendarError(
                "Line {} in {}: Event_Factor '{}' is not a finite number. "
                "Enter a real multiplier such as 1.25; a blank, NaN or infinite "
                "factor cannot be priced, and the run has been stopped instead "
                "of quietly pricing the date as neutral.".format(
                    line_no, path, row.get(factor_col, "")
                )
            )
        if factor <= 0:
            raise CalendarError(
                "Line {} in {}: Event_Factor must be greater than 0 (got {}).".format(
                    line_no, path, factor
                )
            )
        if factor > FACTOR_WARN_HIGH or factor < FACTOR_WARN_LOW:
            warnings.append(
                "Line {}: Event_Factor {} is outside the usual {:.2f}-{:.2f} range.".format(
                    line_no, factor, FACTOR_WARN_LOW, FACTOR_WARN_HIGH
                )
            )
        if factor > FACTOR_HARD_MAX:
            warnings.append(
                "Line {}: Event_Factor {:.2f} exceeds the accepted maximum "
                "{:.2f} and looks like a data-entry error. The night will still "
                "be capped by the engine's absolute rate ceiling, so check the "
                "row before publishing rates.".format(
                    line_no, factor, FACTOR_HARD_MAX
                )
            )

        name = str(row.get(name_col, "") or "").strip() if name_col else ""
        category = _category_of(
            row.get(category_col, "") if category_col else "", line_no, warnings
        )
        record = {
            "Event_Name": name,
            "Event_Factor": factor,
            "Event_Category": category,
            # Kept for duplicate detection only; EVENT_COLUMNS drops it when
            # the frame is built.
            "_Line": line_no,
        }

        if recurring:
            # The written year is only a placeholder: repeat the month/day
            # for every year touched by the pricing window.
            for year in range(start.year, end.year + 1):
                try:
                    candidate = date(year, month, day)
                except ValueError:
                    continue  # 02/29 on a non-leap year
                if start <= candidate <= end:
                    recurring_rows.append(
                        {
                            "Date": pd.Timestamp(candidate),
                            "Event_Source": "Recurring",
                            **record,
                        }
                    )
        elif start <= parsed_date <= end:
            one_off_rows.append(
                {
                    "Date": pd.Timestamp(parsed_date),
                    "Event_Source": "One-off",
                    **record,
                }
            )

    warnings.extend(_duplicate_warnings(recurring_rows, "recurring"))
    warnings.extend(_duplicate_warnings(one_off_rows, "one-off"))

    if not one_off_rows and not recurring_rows:
        warnings.append(
            "No event dates fall inside {} .. {}. Every day uses the neutral "
            "1.00 factor.".format(start.isoformat(), end.isoformat())
        )

    events = pd.DataFrame(recurring_rows + one_off_rows, columns=EVENT_COLUMNS)
    events["Date"] = pd.to_datetime(events["Date"])
    events["Event_Factor"] = pd.to_numeric(
        events["Event_Factor"], errors="raise"
    ).astype(float)
    if not events.empty:
        # One-off rows are appended last so they win over recurring rows;
        # drop_duplicates(keep='last') also implements "last row wins".
        events = (
            events.drop_duplicates(subset="Date", keep="last")
            .sort_values("Date")
            .reset_index(drop=True)
        )

    data = CalendarData(events=events, warnings=warnings)
    data.warnings.extend(annual_review_warnings(data, start, end))
    return data
