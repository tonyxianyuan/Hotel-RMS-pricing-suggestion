BEHAVIOUR CONTRACTS
===================

These are not unit tests and they do not need pytest. Each file is a small
program that copies the project into a temporary sandbox, runs the real entry
points, and then asserts things a hotelier could check by hand: "this date has
no booking history, so the rate must not be discounted for weak pace", "a
published rate must sit inside its own floor and ceiling", "a failed run must
not look successful".

Nothing here writes to the repository. Every scenario runs against a sandbox in
the system temp folder, so a contract can be run at any time, on a machine with
no data in it, without touching `output/`.

HOW TO RUN

  py tests/run_all.py                 every contract, one summary
  py tests/run_all.py --only step7    one or more, comma separated
  py tests/run_all.py --list          names only
  py tests/contract_step7.py          a single contract, full output

Use `py`, not `python`: on a machine with several interpreters the `py`
launcher is usually the one carrying pandas / numpy / requests. The runner
passes `RMS_NO_PAUSE=1` and strips any `RMS_*` variable inherited from your
shell, so a leftover back-test setting cannot bias a run.

WHAT EACH CONTRACT PROTECTS

  layout    Only three entry points live beside the code; reusable modules are
            inside `rms_core/`; the engine still runs when launched from a
            different working directory.
  output    Generated files land in `output/` and never beside the code; old
            files are moved there once, never deleted or overwritten; a second
            cycle does not duplicate or re-move anything.
  step1     Data provenance: `Data_Mode` is decided from what the adapters
            actually returned, not from whether credentials exist. A live PMS
            that fails is labelled as a fallback, never as live.
  step2     Report publishing: one `Run_Timestamp` per cycle in both files,
            formula-injection escaping that does not corrupt `+`/`-` percentage
            columns, and a mismatched pair is detectable.
  step3     Audit trail: every factor column needed to rebuild a rate by hand is
            exported, the run log survives closing the window, and the manager
            `Action` agrees with the percentage it displays.
  step4     The staff UI: exit codes are translated into plain language, a
            failed run marks the visible results as stale instead of looking
            successful, results load at startup, and cancelling or closing the
            window kills the child process.
  step5     Launchers: the `.bat` files probe interpreters by really importing
            the dependencies, report every attempt when none works, and never
            hang on `pause` unattended.
  step6     Guard rails: an absurd event factor cannot raise the ceiling to
            Base x 24, a NaN/inf factor stops the run with a calendar line
            number, and a forgotten movable holiday is warned about.
  step7     Pricing semantics: no invented booking history, one occupancy per
            row, whole-unit rates inside their own band, a same-day guest
            signal that cannot reprice next month, and dirty PMS rows that are
            skipped instead of killing the cycle.

THE BASELINE

`golden/v7/` is the current frozen output of one pricing cycle under fixed
inputs. Contracts use it as the reference for "prices must not change" checks,
and `golden/diff_reports.py` compares a fresh run against it:

  py golden/diff_reports.py --baseline golden/v7/reports --candidate output --strict

`golden/v0/` is the pre-correction reference; it is kept so the step 7 price
change stays auditable. Do not refresh either snapshot to make a diff disappear.

REQUIREMENTS

  Python 3.9+ with pandas, numpy and requests. `schedule` and `tzdata` are only
  needed by the resident scheduler and by named timezones.
