#!/home/ubuntu/.hermes/hermes-agent/venv/bin/python3
"""
Minimal cron heartbeat — called by system crontab every minute.
Triggers hermes cron scheduler tick, catching any errors gracefully.

Install:
    chmod +x ~/.hermes/skills/trading/trading-infra-troubleshooting/scripts/cron_heartbeat.py
    (crontab -l 2>/dev/null | grep -v cron_heartbeat; echo "* * * * * <path> 2>&1") | crontab -
"""
import os, sys, logging

os.environ.setdefault("HERMES_HOME", os.path.expanduser("~/.hermes"))

logging.basicConfig(
    filename=os.path.expanduser("~/.hermes/logs/cron-fallback.log"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)
logger = logging.getLogger("cron-heartbeat")

try:
    sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent"))
    from cron.scheduler import tick
    count = tick(verbose=False)
    if count > 0:
        logger.info("Tick OK: %d job(s) executed", count)
except Exception as e:
    logger.warning("Heartbeat tick failed: %s", e)
