# -*- coding: utf-8 -*-
"""Atomic publishing for the two daily CSV reports.

A pricing cycle can be started many times on the same day, from the UI, the
batch files, or the scheduler, sometimes while a previous report is still
open in a spreadsheet. The writer therefore never opens a final report name
for writing: it writes a private temporary file and publishes it with a
single os.replace.

Guarantees:
  * A reader never sees a half-written report.
  * Concurrent cycles cannot interleave bytes in the same file: each one
    replaces its own complete temporary file.
  * No unbounded accumulation. If the canonical name is locked, the report
    goes to ONE fixed fallback name, reused by every later cycle.
  * Expected filesystem failures are reported, never raised. A report that
    could not be published must not turn an otherwise successful pricing
    cycle into a failure.

Standard library only, no import-time side effects. All code, comments,
docstrings and returned messages are English, matching "hotel rms.py".
"""

from __future__ import annotations

import os
import uuid

FALLBACK_SUFFIX = "_FALLBACK"

# A cell that starts with one of these is executed as a formula by spreadsheet
# software. A leading "+" or "-" is deliberately NOT included: the percentage
# column relies on those signs and Excel reads them as numbers, not formulas.
DANGEROUS_PREFIXES = ("=", "@", "\t", "\r")


def _escape_cell(value):
    if isinstance(value, str) and value.startswith(DANGEROUS_PREFIXES):
        return "'" + value
    return value


def harden_cells(frame):
    """Neutralise spreadsheet formula prefixes without touching other columns.

    A column is only replaced when at least one cell actually changes, so
    numeric columns keep their dtype and every other byte of the report is
    left exactly as the engine produced it.
    """
    hardened = frame.copy()
    for column in hardened.columns:
        original = hardened[column]
        escaped = original.map(_escape_cell)
        if not escaped.equals(original):
            hardened[column] = escaped
    return hardened


def _discard(path):
    """Best-effort removal of a temporary file. Never raises."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def fallback_name(filename):
    """Return the single, stable fallback name for a canonical report name."""
    stem, ext = os.path.splitext(filename)
    return "{}{}{}".format(stem, FALLBACK_SUFFIX, ext or ".csv")


def publish_report(frame, filename):
    """Atomically publish one report.

    Return (published_name, status, message), where status is one of
    'ok', 'fallback', 'failed'. Callers should log the message; 'failed'
    describes a report that could not be published, not a pricing failure,
    and must not change the cycle exit code.
    """
    # The temporary file must live in the SAME folder as the target (so
    # os.replace stays on one volume) but carry only the base name, because
    # a full path inside a file name is not valid on Windows.
    folder = os.path.dirname(filename) or "."
    tmp_name = os.path.join(
        folder,
        ".{}.{}.{}.tmp".format(
            os.path.basename(filename), os.getpid(), uuid.uuid4().hex[:8]
        ),
    )
    alternative = fallback_name(filename)

    try:
        # encoding is stated explicitly instead of inherited from the pandas
        # default, so a locale change cannot alter the report bytes.
        harden_cells(frame).to_csv(tmp_name, index=False, encoding="utf-8")
    except Exception as exc:
        _discard(tmp_name)
        return (None, "failed",
                "could not write report data ({}); no report published.".format(exc))

    try:
        os.replace(tmp_name, filename)
        return (filename, "ok", "written: {}".format(filename))
    except OSError as primary:
        # The canonical file is held open (spreadsheet, antivirus, another
        # process). A second replace into the fixed fallback is still atomic.
        try:
            os.replace(tmp_name, alternative)
            return (alternative, "fallback",
                    "canonical file was unavailable ({}); saved as {}".format(
                        primary, alternative))
        except OSError as secondary:
            _discard(tmp_name)
            return (None, "failed",
                    "could not publish report: {} / {}".format(primary, secondary))
    except Exception as exc:
        _discard(tmp_name)
        return (None, "failed",
                "unexpected error while publishing: {}".format(exc))
