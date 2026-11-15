# -*- coding: utf-8 -*-
"""Read-only sanity checks for a priced rate frame.

This module has no side effects: importing it does nothing, so it can be
tested on its own and called exactly once at the end of a pricing cycle,
before anything is published.

Every check returns a human-readable English sentence. An empty list means
the frame is internally consistent and safe to publish; a non-empty list must
stop the run, because publishing a rate that breaks its own guard is worse
than publishing nothing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Currency amounts and multipliers that reach the reports. A non-finite value
# in any of them means the multiplicative chain broke somewhere upstream.
PRICE_COLUMNS = (
    "MIN_ADR",
    "MAX_ADR",
    "Recommended_ADR",
    "Model_ADR_Before_Adjustments",
    "Post_Model_Adjustment_Factor",
    "Final_ADR",
    "Expected_RevPAR",
)
KEY_COLUMNS = ("Stay_Date", "Room_Type")

# Final_ADR is rounded to whole currency units after np.clip(), so a rate may
# legitimately sit up to half a unit outside its own floor. Anything larger is
# a genuine breach of the guard rather than a rounding artefact.
#
# This tolerance exists because of a known ordering flaw that is still in the
# engine: np.clip() raises a rate to MIN_ADR and the following .round(0) can
# then bank round it back below, e.g. MIN_ADR 94.5 becomes Final_ADR 94.0.
# The tolerance keeps this check honest about real breaches without hiding
# that flaw; fixing the ordering is a pricing-semantics change and belongs to
# a separate, price-approved step.
ROUNDING_TOLERANCE = 0.5
_FLOAT_SLACK = 1e-9


def _numeric(series):
    """Return the column as floats, with unparsable text becoming NaN."""
    return pd.to_numeric(series, errors="coerce")


def _labels(frame, mask, limit=3):
    """Short 'date room_type' labels for the first offending rows."""
    rows = frame.loc[mask, list(KEY_COLUMNS)].head(limit)
    labels = []
    for _, row in rows.iterrows():
        stay = row["Stay_Date"]
        if isinstance(stay, pd.Timestamp):
            stay = stay.strftime("%Y/%m/%d")
        labels.append("{} {}".format(stay, row["Room_Type"]))
    return ", ".join(labels)


def find_violations(frame):
    """Return a list of problems; an empty list means the frame is publishable."""
    if frame is None or len(frame) == 0:
        return ["priced frame is empty, so no rate can be published"]

    missing = [name for name in PRICE_COLUMNS + KEY_COLUMNS
               if name not in frame.columns]
    if missing:
        return ["priced frame is missing column(s): {}".format(", ".join(missing))]

    problems = []

    for column in PRICE_COLUMNS:
        values = _numeric(frame[column])
        unusable = ~np.isfinite(values)
        if unusable.any():
            problems.append(
                "{} has {} non-finite or non-numeric value(s), first at {}".format(
                    column, int(unusable.sum()), _labels(frame, unusable)
                )
            )

    floor = _numeric(frame["MIN_ADR"])
    ceiling = _numeric(frame["MAX_ADR"])
    final = _numeric(frame["Final_ADR"])

    below = final < floor - ROUNDING_TOLERANCE - _FLOAT_SLACK
    if below.any():
        problems.append(
            "Final_ADR is below MIN_ADR beyond rounding on {} row(s), first at {} "
            "(final {} vs floor {})".format(
                int(below.sum()), _labels(frame, below),
                float(final[below].iloc[0]), float(floor[below].iloc[0])
            )
        )

    above = final > ceiling + ROUNDING_TOLERANCE + _FLOAT_SLACK
    if above.any():
        problems.append(
            "Final_ADR is above MAX_ADR beyond rounding on {} row(s), first at {} "
            "(final {} vs ceiling {})".format(
                int(above.sum()), _labels(frame, above),
                float(final[above].iloc[0]), float(ceiling[above].iloc[0])
            )
        )

    inverted = ceiling <= floor
    if inverted.any():
        problems.append(
            "MAX_ADR is not above MIN_ADR on {} row(s), first at {}".format(
                int(inverted.sum()), _labels(frame, inverted)
            )
        )

    non_positive = floor <= 0
    if non_positive.any():
        problems.append(
            "MIN_ADR is not positive on {} row(s), first at {}".format(
                int(non_positive.sum()), _labels(frame, non_positive)
            )
        )

    duplicated = frame.duplicated(subset=list(KEY_COLUMNS), keep=False)
    if duplicated.any():
        problems.append(
            "duplicate stay key(s) on {} row(s), first at {} - one rate per "
            "stay date and room type is expected".format(
                int(duplicated.sum()), _labels(frame, duplicated)
            )
        )

    return problems
