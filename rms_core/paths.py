# -*- coding: utf-8 -*-
"""Single source of truth for every path the tool reads or writes.

Before this module existed, three files each derived ``APP_DIR`` from their
own ``__file__``. That worked while they all sat in one folder, but it breaks
the moment a module moves into a sub-package: the derived directory silently
becomes the package folder. Every path is therefore computed here, once, from
the package location.

Layout
------
    <app>/                        entry points, staff calendar, docs
        Public holidays.csv
        hotel rms.py
        rms_gui.py
        scheduler.py
        rms_core/                 this package
        output/                   everything the tool generates
            archive/              reports moved out of the retention window
            rms_run.log           engine log
            rms_scheduler.log     scheduler log
            hotel_name_*.csv      the two reports

Nothing is ever deleted: old artefacts are moved, and a name collision is
reported instead of overwritten.
"""

from __future__ import annotations

import os
import re

# The package lives one level below the program folder. Deriving APP_DIR from
# this file rather than from an entry point keeps it correct no matter which
# script (or which working directory) starts the run.
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIRNAME = "output"
ARCHIVE_DIRNAME = "archive"
OUTPUT_DIR = os.path.join(APP_DIR, OUTPUT_DIRNAME)
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, ARCHIVE_DIRNAME)

CALENDAR_FILE = os.path.join(APP_DIR, "Public holidays.csv")
TIMEZONE_SETTINGS_FILE = os.path.join(APP_DIR, "timezone_settings.json")

RUN_LOG_FILE = os.path.join(OUTPUT_DIR, "rms_run.log")
SCHEDULER_LOG_FILE = os.path.join(OUTPUT_DIR, "rms_scheduler.log")

# Anything the engine generates. Used to recognise its own files when moving
# pre-output/ artefacts and when scanning a folder for reports.
REPORT_NAME_PATTERN = re.compile(
    r"^hotel_name_(Live_Dashboard|RMS_Manager_View)_"
    r"\d{4}-\d{2}-\d{2}(_\d{6})?(_FALLBACK)?\.csv$"
)
LOG_NAMES = ("rms_run.log", "rms_scheduler.log")


def is_report_name(name):
    """True for a file this tool generated, False for staff input."""
    return bool(REPORT_NAME_PATTERN.match(name))


def ensure_output_dir():
    """Create output/ on demand. Returns the directory path."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return OUTPUT_DIR


def report_path(filename):
    """Absolute path for a report inside output/, creating the folder."""
    ensure_output_dir()
    return os.path.join(OUTPUT_DIR, filename)


def migrate_legacy_output():
    """Move artefacts written before output/ existed into output/.

    Returns ``(moved, skipped)`` as human-readable English sentences so the
    caller can log them. It never deletes and never overwrites: an existing
    file of the same name in output/ wins and the older one is left alone with
    a note, so nothing silently disappears.
    """
    moved = []
    skipped = []
    ensure_output_dir()

    candidates = []
    try:
        names = sorted(os.listdir(APP_DIR))
    except OSError as exc:
        return moved, ["could not inspect {} ({})".format(APP_DIR, exc)]

    for name in names:
        full = os.path.join(APP_DIR, name)
        if not os.path.isfile(full):
            continue
        if is_report_name(name) or name in LOG_NAMES:
            candidates.append(name)

    for name in candidates:
        source = os.path.join(APP_DIR, name)
        target = os.path.join(OUTPUT_DIR, name)
        if os.path.exists(target):
            skipped.append(
                "{} already exists in output/; the copy in the program folder "
                "was left untouched.".format(name)
            )
            continue
        try:
            os.replace(source, target)
        except OSError as exc:
            skipped.append("could not move {} into output/ ({})".format(name, exc))
        else:
            moved.append(name)

    legacy_archive = os.path.join(APP_DIR, ARCHIVE_DIRNAME)
    if os.path.isdir(legacy_archive):
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        try:
            archive_names = sorted(os.listdir(legacy_archive))
        except OSError as exc:
            archive_names = []
            skipped.append(
                "could not inspect the old archive/ folder ({})".format(exc))
        for name in archive_names:
            source = os.path.join(legacy_archive, name)
            if not os.path.isfile(source):
                continue
            target = os.path.join(ARCHIVE_DIR, name)
            if os.path.exists(target):
                skipped.append(
                    "archive/{} already exists in output/archive/; the old copy "
                    "was left untouched.".format(name)
                )
                continue
            try:
                os.replace(source, target)
            except OSError as exc:
                skipped.append(
                    "could not move archive/{} into output/archive/ ({})".format(
                        name, exc))
            else:
                moved.append("archive/" + name)
        # Only removes the folder when it is empty, so nothing can be lost.
        try:
            os.rmdir(legacy_archive)
        except OSError:
            skipped.append(
                "the old archive/ folder still contains files and was left in "
                "place; move its contents into output/archive/ by hand."
            )

    return moved, skipped
