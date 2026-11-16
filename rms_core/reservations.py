# -*- coding: utf-8 -*-
"""Turn a PMS reservation payload into a stay-night matrix.

These are pure functions with no side effects, so they can be exercised on
their own: the engine hands in the raw payload and a warning callback, and gets
back two DataFrames.

The guiding rule is that ONE malformed booking must never abort a pricing
cycle. A single reservation with a typo in its dates used to raise outside the
network ``try`` block and kill the whole run, which is the worst possible
trade: the hotel loses all 90 days of recommendations because of one row it
could have ignored with a warning. Bad records are therefore dropped, named in
a ``[WARN]`` line, and the cycle continues with the records that are usable.

All identifiers, comments, messages and exceptions are English.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

#: A reservation cannot legitimately hold a room for longer than this. The cap
#: also bounds the stay-night expansion loop, so a typo such as "2126-11-20"
#: cannot stall a run or exhaust memory.
MAX_STAY_NIGHTS = 365

#: Statuses that represent real occupancy. Anything else (cancelled, no-show,
#: tentative) is ignored without a warning, because that is normal PMS noise.
ACCEPTED_STATUSES = ("confirmed", "checked_in", "checked_out")

RECORD_COLUMNS = [
    "Reservation_ID",
    "Created_Date",
    "CheckIn_Date",
    "CheckOut_Date",
    "Status",
]
NIGHT_COLUMNS = ["Stay_Date", "Created_Date"]


def _warn(warn, message):
    """Emit a warning through the caller's logger, or print if none was given."""
    if warn is None:
        print("[WARN] {}".format(message))
        return
    try:
        warn(message)
    except Exception:  # noqa: BLE001 - a logger must never break the caller
        pass


def _as_date(value):
    """Return a ``date``, or ``None`` when the value is missing or unparsable."""
    if value in (None, ""):
        return None
    try:
        stamp = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return None
    if stamp is pd.NaT or pd.isna(stamp):
        return None
    return stamp.date()


def parse_reservations(payload, as_of, warn=None):
    """Normalise a PMS payload into one row per usable reservation.

    ``payload`` may be the raw list or the ``{"data": [...]}`` envelope the
    PMS returns. ``as_of`` is used as the creation date when the payload omits
    one, which keeps the history filter honest instead of dropping the record.
    """
    if isinstance(payload, dict):
        payload = payload.get("data", [])
    if not isinstance(payload, (list, tuple)):
        _warn(warn, "Reservation payload is not a list ({}); treating it as "
                    "empty.".format(type(payload).__name__))
        payload = []

    records = []
    for position, reservation in enumerate(payload, start=1):
        if not isinstance(reservation, dict):
            _warn(warn, "Reservation #{} is not an object; ignored.".format(position))
            continue

        reservation_id = reservation.get("reservationID") or "row {}".format(position)
        status = str(reservation.get("status", "")).strip().lower()
        if status not in ACCEPTED_STATUSES:
            continue

        check_in = _as_date(reservation.get("startDate"))
        check_out = _as_date(reservation.get("endDate"))
        if check_in is None or check_out is None:
            _warn(warn, "Reservation {} has an unreadable check-in/check-out date "
                        "({!r} -> {!r}); ignored.".format(
                            reservation_id, reservation.get("startDate"),
                            reservation.get("endDate")))
            continue
        if check_out <= check_in:
            _warn(warn, "Reservation {} checks out on or before check-in "
                        "({} -> {}); ignored.".format(
                            reservation_id, check_in, check_out))
            continue

        created = _as_date(reservation.get("dateCreated"))
        if created is None:
            created = as_of
        if created > check_in:
            # A booking cannot predate its own creation date by more than zero
            # nights; clamp instead of dropping, so pace history stays usable.
            created = check_in

        records.append(
            {
                "Reservation_ID": reservation_id,
                "Created_Date": created,
                "CheckIn_Date": check_in,
                "CheckOut_Date": check_out,
                "Status": status,
            }
        )

    return pd.DataFrame(records, columns=RECORD_COLUMNS)


def expand_stay_nights(parsed, warn=None):
    """Explode reservations into one row per occupied room-night."""
    if parsed is None or len(parsed) == 0:
        return pd.DataFrame(columns=NIGHT_COLUMNS)

    rows = []
    for record in parsed.itertuples(index=False):
        nights = (record.CheckOut_Date - record.CheckIn_Date).days
        if nights > MAX_STAY_NIGHTS:
            _warn(warn, "Reservation {} spans {} nights, which exceeds the "
                        "{} night limit; truncated. Check the reservation "
                        "dates in the PMS.".format(
                            record.Reservation_ID, nights, MAX_STAY_NIGHTS))
            nights = MAX_STAY_NIGHTS
        for offset in range(nights):
            rows.append(
                {
                    "Stay_Date": record.CheckIn_Date + timedelta(days=offset),
                    "Created_Date": record.Created_Date,
                }
            )

    frame = pd.DataFrame(rows, columns=NIGHT_COLUMNS)
    if not frame.empty:
        frame["Stay_Date"] = pd.to_datetime(frame["Stay_Date"])
        frame["Created_Date"] = pd.to_datetime(frame["Created_Date"])
    return frame
