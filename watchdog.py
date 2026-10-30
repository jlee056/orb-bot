"""Backup trigger for the GitHub jobs, run by Windows Task Scheduler on the always-on PC.

GitHub's own scheduler can start jobs late or skip them. This script checks whether today's
run of each job has started inside its time window and, if not, starts it with the GitHub REST API.
The jobs themselves are safe to start more than once (one order and one push per day).

  python watchdog.py morning   paper-entry + forward-alert   (window 06:00 to 11:55 ET; the task
                               starts at 9:05 so the 9:35 orb5 variant is covered)
  python watchdog.py close     paper-close                   (window 11:00 to 15:45 ET)
  python watchdog.py eod       forward-eod                   (window 16:20 to 23:59 ET)

  python watchdog.py check-morning   after 12:20 ET: phone alert if a morning message is missing
  python watchdog.py check-close     after 16:20 ET: phone alert if the day's result is missing

Uses the stored GitHub git credential (or GH_TOKEN/GITHUB_TOKEN); never launches gh. Writes watchdog.log next to this file.
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
import time
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


def github_token():
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token:
        return token
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    result = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                            capture_output=True, text=True, timeout=30,
                            creationflags=NO_WINDOW, env=env, cwd=HERE)
    if result.returncode:
        raise RuntimeError("Stored GitHub credential unavailable")
    for line in result.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("No token returned by git credential helper")


def github(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request("https://api.github.com/" + path, data=data,
                                 headers={"Authorization": "Bearer " + github_token(),
                                          "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"GitHub API HTTP {exc.code}") from None
        except (OSError, TimeoutError):
            if attempt == 2:
                raise RuntimeError("GitHub API network request failed") from None
        time.sleep(2 ** attempt)


def started_in_window(workflow, lo, hi, today):
    """True if a run of this workflow began today inside the window and is running or succeeded."""
    runs = github(f"repos/{REPO}/actions/workflows/{workflow}/runs?per_page=50")["workflow_runs"]
    for run in runs:
        t = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(ET)
        minute = t.hour * 60 + t.minute
        age = (datetime.now(ET) - t).total_seconds()
        alive = run["status"] == "in_progress" or \
            (run["status"] in ("queued", "requested", "waiting", "pending") and age < 180) or \
            (run["status"] == "completed" and run["conclusion"] == "success")
        if t.date() == today and lo <= minute <= hi and alive:
            return True
    return False


def check(which):
    """Make a silent failure loud: if an expected push is not in today's history, send a problem push."""
    import alpaca_io as A
    from forward_alert import push, sent_titles
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return 0
    try:
        if A.have_keys() and A.AlpacaBroker().hours(now.date()) is None:
            log(f"{which}: market closed today, nothing expected")
            return 0
    except Exception as e:
        log(f"{which}: could not read the market calendar ({e}); checking anyway")
    titles = sent_titles()
    if titles is None:
        log(f"{which}: could not read the push history")
        return 1
    import variants
    day = f"{now:%a %b} {now.day}"
    bots = {v.name: f"ORB QQQ{' ' + v.tag if v.tag else ''} {day}:" for v in variants.ALL.values()}
    if which == "check-morning":
        expected = {"Yahoo alert (NQ)": f"ORB {day}:"}
        expected.update({f"Alpaca bot (QQQ, {name})": prefix for name, prefix in bots.items()})
        missing = [name for name, prefix in expected.items()
                   if not any(t.startswith(prefix) and not t.endswith(": result") for t in titles)]
    else:
        missing = [f"Alpaca end-of-day result ({name})" for name, prefix in bots.items()
                   if f"{prefix} result" not in titles]
    if missing:
        log(f"{which}: MISSING {missing}")
        push(f"ORB PROBLEM {day}: {which.split('-')[1]} message missing",
             "No message today from: " + ", ".join(missing) + ". The job may not have run. Tell Claude to check.",
             "rotating_light")
    else:
        log(f"{which}: all expected messages were sent")
    return 0



def daemon():
    """Independent hidden login helper: Task Scheduler is a second trigger path.

    An OS file lock prevents two login helpers from running together. All dispatch
    decisions still consult GitHub, so the tasks and this helper are idempotent.
    """
    lock = open(os.path.join(HERE, ".watchdog.lock"), "a+b")
    lock.seek(0)
    if not lock.read(1):
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    import msvcrt
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        log("daemon: another helper already holds the lock")
        lock.close()
        return 0
    log(f"daemon: started PID {os.getpid()}")
    last = {}
    while True:
        now = datetime.now(ET)
        minute = now.hour * 60 + now.minute
        due = []
        if now.weekday() < 5:
            if 8 * 60 + 45 <= minute <= 11 * 60 + 55:
                due.append(("morning", 5))
            if 13 * 60 <= minute <= 15 * 60 + 45:
                due.append(("close", 15))
            if 17 * 60 + 30 <= minute <= 23 * 60 + 30:
                due.append(("eod", 30))
            for mode, at in (("check-ready", 9 * 60 + 20), ("check-morning", 12 * 60 + 25),
                             ("check-close", 16 * 60 + 25)):
                if at <= minute < at + 5:
                    due.append((mode, 1440))
        for mode, period in due:
            slot = (now.date(), minute // period)
            if last.get(mode) == slot:
                continue
            try:
                sys.argv = [__file__, mode]
                result = main()
                log(f"daemon: {mode} finished with {result}")
                last[mode] = slot
            except Exception as exc:
                log(f"daemon: {mode} failed: {type(exc).__name__}: {exc}")
        heartbeat = (now.date(), now.hour)
        if last.get("heartbeat") != heartbeat:
            log("daemon: heartbeat")
            last["heartbeat"] = heartbeat
        time.sleep(30)


def main():
    group = sys.argv[1] if len(sys.argv) > 1 else ""
    if group == "daemon":
        return daemon()
    if group == "probe":
        result = github(f"repos/{REPO}/actions/workflows/paper-entry.yml/runs?per_page=1")
        log(f"probe: REST authentication succeeded; {len(result['workflow_runs'])} run returned")
        return 0
    if group == "check-ready":
        now = datetime.now(ET)
        if now.weekday() >= 5 or not 9 * 60 + 15 <= now.hour * 60 + now.minute <= 9 * 60 + 30:
            return 0
        if started_in_window("paper-entry.yml", 6 * 60, 9 * 60 + 25, now.date()):
            log("check-ready: pre-open entry workflow is active or completed")
            return 0
        github(f"repos/{REPO}/actions/workflows/paper-entry.yml/dispatches", {"ref": "main"})
        import config  # loads local alert configuration
        from forward_alert import push
        push(f"ORB PROBLEM {now:%Y-%m-%d}: morning recovery",
             "No timely morning entry run was found. A backup was dispatched before the 9:35 entry.",
             "rotating_light")
        log("check-ready: missing morning run; recovery dispatched")
        return 1
    if group in ("check-morning", "check-close"):
        return check(group)
    if group not in GROUPS:
        print(__doc__)
        return 2
    workflows, (lo, hi) = GROUPS[group]
    now = datetime.now(ET)
    minute = now.hour * 60 + now.minute
    if now.weekday() >= 5 or not lo <= minute <= hi:
        log(f"{group}: outside the window, nothing to do")
        return 0
    failed = False
    for wf in workflows:
        try:
            if started_in_window(wf, lo, hi, now.date()):
                log(f"{group}: {wf} already started today")
                continue
            github(f"repos/{REPO}/actions/workflows/{wf}/dispatches", {"ref": "main"})
            log(f"{group}: STARTED {wf} via REST API")
        except Exception as e:
            failed = True
            log(f"{group}: error checking {wf}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
