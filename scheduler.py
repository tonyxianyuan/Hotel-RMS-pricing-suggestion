import schedule
import time
import subprocess
import logging
import sys
import argparse
import traceback
from datetime import datetime

# ==========================================
# 1. LOGGING CONFIGURATION
# ==========================================
# Configured to log both to the console and to rms_scheduler.log
log_formatter = logging.Formatter('%(asctime)s\n%(message)s\n', datefmt='%Y-%m-%d %H:%M')
logger = logging.getLogger("RMSScheduler")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler("rms_scheduler.log", mode='a')
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)



# ==========================================
# 1.4 RUN TIME / TIMEZONE (configurable)
# ==========================================
# Daily 06:00 run, using the machine's local time by default - no region is
# named and no external timezone database is required.
# To pin the run to a specific timezone, set PROPERTY_TIMEZONE to an IANA name
# (e.g. "Europe/London"); that needs tzdata / pytz installed.
# TODO: expose this in the staff UI so it can be picked there.
PROPERTY_TIMEZONE = None

# ==========================================
# 1.5 PYTHON INTERPRETER RESOLVER
# ==========================================
def resolve_python_interpreter():
    """Prefer an interpreter that can import pandas, so the scheduler works
    even if it was started with a different Python on PATH."""
    candidates = [sys.executable,
                  "py"]  # generic Python launcher; no machine-specific paths
    for exe in candidates:
        try:
            check = subprocess.run([exe, "-c", "import pandas"],
                                   capture_output=True, timeout=60)
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
    
    try:
        # Pick a Python interpreter that actually has pandas installed
        interpreter = resolve_python_interpreter()
        result = subprocess.run(
            [interpreter, "hotel rms.py"], 
            capture_output=True, 
            text=True, 
            check=True
        )
        logger.info("Hotel RMS Finished Successfully")
        
    except subprocess.CalledProcessError as e:
        error_msg = f"ERROR: RMS execution failed with return code {e.returncode}\n"
        error_msg += f"Standard Output:\n{e.stdout}\n"
        error_msg += f"Standard Error:\n{e.stderr}"
        logger.error(error_msg)
        
    except Exception as e:
        error_msg = "ERROR: An unexpected exception occurred.\n"
        error_msg += traceback.format_exc()
        logger.error(error_msg)

# ==========================================
# 3. MAIN SCHEDULER LOOP
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="RMS Unattended Automated Scheduler")
    parser.add_argument("--run-now", action="store_true", help="Execute the RMS script immediately, then begin scheduling.")
    args = parser.parse_args()

    if args.run_now:
        print("🚀 '--run-now' flag detected. Executing initial run...")
        run_rms_job()

    # Schedule the job daily at 06:00 (property / local time)
    # Note: a named timezone requires schedule >= 1.2.0
    try:
        if PROPERTY_TIMEZONE:
            schedule.every().day.at("06:00", PROPERTY_TIMEZONE).do(run_rms_job)
        else:
            schedule.every().day.at("06:00").do(run_rms_job)
        print("✅ Scheduled RMS to run daily at 06:00 (local / property time).")
    except schedule.ScheduleValueError:
        # Fallback if timezone parsing fails (e.g., older schedule version)
        print("⚠️ Timezone parsing failed. Defaulting to local system time. Please ensure the system clock matches the property timezone.")
        schedule.every().day.at("06:00").do(run_rms_job)

    print("⏳ Scheduler is now running in the background. Press Ctrl+C to exit.")

    # Infinite loop to keep the scheduler running
    while True:
        schedule.run_pending()
        time.sleep(60) # Check every 60 seconds to save CPU cycles

if __name__ == "__main__":
    main()