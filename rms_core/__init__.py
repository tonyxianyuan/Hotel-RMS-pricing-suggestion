# -*- coding: utf-8 -*-
"""Reusable modules for the Hotel RMS pricing tool.

Nothing in this package is a program: every module is imported by one of the
three entry points that stay in the folder above.

    hotel rms.py   one pricing cycle (also started by Run_Pricing_Now.bat and
                   by scheduler.py)
    rms_gui.py     the staff UI (started by Start_Pricing_UI.bat)
    scheduler.py   the resident daily scheduler

Modules
-------
event_calendar      loads and validates Public holidays.csv
timezone_config     property timezone settings and IANA availability
report_writer       atomic report publishing
report_retention    soft-delete archiving of old reports
price_guard         pre-publish price sanity checks

All identifiers, comments and messages are English.
"""
