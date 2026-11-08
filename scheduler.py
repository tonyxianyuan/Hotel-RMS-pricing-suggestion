import argparse
import logging
import os
import subprocess
import sys
import time
import traceback

import schedule

# ==========================================
# 1. LOGGING CONFIGURATION
# ==========================================
# Resolve every path from this file so the scheduler works no matter which
# directory it was started from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RMS_SCRIPT = os.path.join(SCRIPT_DIR, "hotel rms.py")
LOG_FILE = os.path.join(SCRIPT_DIR, "rms_scheduler.log")

log_formatter = logging.Formatter("%(asctime)s\n%(message)s\n", datefmt="%Y-%m-%d %H:%M")
logger = logging.getLogger("RMSScheduler")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# ==========================================
# 1.4 RUN TIME / TIMEZONE (configurable)
# ==========================================
# Daily 06:00 run, using the machine's local time by default. No region is
# named and no external timezone database is required.
# To pin the run to a specific timezone, set PROPERTY_TIMEZONE to an IANA name
# (for example "Asia/Singapore"); that needs schedule >= 1.2.0 and tzdata or
# pytz. With None the run time is machine local time, NOT automatically SGT.
PROPERTY_TIMEZONE = None

# ==========================================
# 1.5 PYTHON INTERPRETER RESOLVER
# ==========================================
def resolve_python_interpreter():
    """Prefer an interpreter that can import pandas, so the scheduler works
    even if it was started with a different Python on PATH."""
    candidates = [sys.executable, "py"]  # generic Python launcher
    for exe in candidates:
        try:
            check = subprocess.run(
                [exe, "-c", "import pandas"], capture_output=True, timeout=60
            )
            if check.returncode == 0:
                return exe
        except Exception:
            continue
    return sys.executable  # last resort: whatever started this scheduler


# ==========================================
# 2. JOB DEFINITION
# ==========================================
def run_rms_job():
    logger.info("Hotel RMS Started")
    if not os.path.isfile(RMS_SCRIPT):
        logger.error("ERROR: Pricing engine not found: %s", RMS_SCRIPT)
        return
    try:
        interpreter = resolve_python_interpreter()
        result = subprocess.run(
            [interpreter, RMS_SCRIPT],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        if result.stdout:
            logger.info(result.stdout.strip())
        logger.info("Hotel RMS Finished Successfully")
    except subprocess.CalledProcessError as exc:
        error_msg = "ERROR: RMS execution failed with return code {}\n".format(
            exc.returncode
        )
        error_msg += "Standard Output:\n{}\n".format(exc.stdout or "")
        error_msg += "Standard Error:\n{}".format(exc.stderr or "")
        logger.error(error_msg)
    except Exception:
        logger.error("ERROR: An unexpected exception occurred.\n%s", traceback.format_exc())


# ==========================================
# 3. MAIN SCHEDULER LOOP
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="RMS Unattended Automated Scheduler")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Execute the RMS script immediately, then begin scheduling.",
    )
    args = parser.parse_args()

    if args.run_now:
        print("[INFO] '--run-now' flag detected. Executing initial run...")
        run_rms_job()

    # Daily 06:00 run. A named timezone requires schedule >= 1.2.0.
    try:
        if PROPERTY_TIMEZONE:
            schedule.every().day.at("06:00", PROPERTY_TIMEZONE).do(run_rms_job)
        else:
            schedule.every().day.at("06:00").do(run_rms_job)
        print("[INFO] Scheduled RMS to run daily at 06:00 (local / property time).")
    except schedule.ScheduleValueError:
        print(
            "[WARN] Timezone parsing failed. Defaulting to local system time. "
            "Please ensure the system clock matches the property timezone."
        )
        schedule.every().day.at("06:00").do(run_rms_job)

    print("[INFO] Scheduler is running in the background. Press Ctrl+C to exit.")

    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every 60 seconds to save CPU cycles.


if __name__ == "__main__":
    main()
