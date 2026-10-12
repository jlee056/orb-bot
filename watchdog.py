"""Backup trigger for the GitHub jobs, run by Windows Task Scheduler on the always-on PC.

GitHub's own scheduler can start jobs late or skip them. This script checks whether today's
run of each job has started inside its time window and, if not, starts it with `gh workflow run`.
The jobs themselves are safe to start more than once (one order and one push per day).

  python watchdog.py morning   paper-entry + forward-alert   (window 06:00 to 11:55 ET)
  python watchdog.py close     paper-close                   (window 11:00 to 15:45 ET)
  python watchdog.py eod       forward-eod                   (window 16:20 to 23:59 ET)

Needs the GitHub CLI (`gh`) logged in on this PC. Writes watchdog.log next to this file.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

REPO = "jlee056/orb-bot"
ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
GROUPS = {
    "morning": (("paper-entry.yml", "forward-alert.yml"), (6 * 60, 11 * 60 + 55)),
    "close": (("paper-close.yml",), (11 * 60, 15 * 60 + 45)),
    "eod": (("forward-eod.yml",), (16 * 60 + 20, 23 * 60 + 59)),
}
NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # no console flash when run by Task Scheduler


def log(msg):
    line = f"{datetime.now(ET):%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    with open(os.path.join(HERE, "watchdog.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=120)


def started_in_window(workflow, lo, hi, today):
    """True if a run of this workflow began today inside the window and is running or succeeded."""
    r = gh("run", "list", "--repo", REPO, "--workflow", workflow, "--limit", "20",
           "--json", "status,conclusion,createdAt,event")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    for run in json.loads(r.stdout or "[]"):
        t = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00")).astimezone(ET)
        minute = t.hour * 60 + t.minute
        alive = run["status"] in ("in_progress", "queued", "requested", "waiting", "pending") or \
            (run["status"] == "completed" and run["conclusion"] == "success")
        if t.date() == today and lo <= minute <= hi and alive:
            return True
    return False


def main():
    group = sys.argv[1] if len(sys.argv) > 1 else ""
    if group not in GROUPS:
        print(__doc__)
        return 2
    workflows, (lo, hi) = GROUPS[group]
    now = datetime.now(ET)
    minute = now.hour * 60 + now.minute
    if now.weekday() >= 5 or not lo <= minute <= hi:
        log(f"{group}: outside the window, nothing to do")
        return 0
    for wf in workflows:
        try:
            if started_in_window(wf, lo, hi, now.date()):
                log(f"{group}: {wf} already started today")
                continue
            r = gh("workflow", "run", wf, "--repo", REPO)
            log(f"{group}: STARTED {wf}" if r.returncode == 0 else f"{group}: FAILED to start {wf}: {r.stderr.strip()[:200]}")
        except Exception as e:
            log(f"{group}: error checking {wf}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
