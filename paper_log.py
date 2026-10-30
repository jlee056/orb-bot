"""Bounded CSV changes between secret-holding trade jobs and clean report jobs.

Only unresolved existing rows may change. Final rows and historical signal facts
are immutable. This module uses only the standard library.
"""
import argparse
import csv
import io
import json
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

HEADER = "date,config_id,source,outcome,shares,entry,stop,target,exit,profit,R,shares_5k,profit_5k,sim_outcome,sim_R,logged_at"
COLUMNS = HEADER.split(",")
PENDING = {"still_open", "order_not_filled"}
FIXED = {"date", "config_id", "source", "shares", "entry", "stop", "target", "sim_outcome", "sim_R"}
OUTCOMES = {"target", "stop", "eod", "late_close", "filtered", "filtered_dir", "no_breakout", "downside_break",
            "no_room", "doji", "missed", "order_not_filled", "still_open", "no_data"}


def parse(text):
    if len(text.encode("utf-8")) > 2_000_000 or any(ord(c) < 32 and c not in "\r\n" or ord(c) > 126 for c in text):
        raise ValueError("log exceeds size limit or contains non-printable bytes")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != COLUMNS:
        raise ValueError("unexpected CSV header")
    rows = list(reader)
    if len({r.get("date") for r in rows}) != len(rows):
        raise ValueError("duplicate dates")
    for row in rows:
        if set(row) != set(COLUMNS) or any(v is None for v in row.values()):
            raise ValueError("incorrect column count")
        date.fromisoformat(row["date"])
        datetime.strptime(row["logged_at"], "%Y-%m-%dT%H:%MZ")
        if not re.fullmatch(r"[0-9a-f]{8}", row["config_id"]) or not re.fullmatch(r"[a-z-]{1,20}/[a-z-]{1,20}", row["source"]):
            raise ValueError("invalid config or source")
        if row["outcome"] not in OUTCOMES or not re.fullmatch(r"[a-z_]{0,24}", row["sim_outcome"]):
            raise ValueError("invalid outcome")
        for key in COLUMNS[4:13] + ["sim_R"]:
            if row[key] and not re.fullmatch(r"-?[0-9]{1,7}(\.[0-9]{1,5})?", row[key]):
                raise ValueError("invalid numeric field")
    return rows


def render(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def validate(new, old):
    before = {r["date"]: r for r in old}
    after = {r["date"]: r for r in new}
    if set(before) - set(after) or len(set(after) - set(before)) > 1:
        raise ValueError("removed dates or more than one new date")
    for day, previous in before.items():
        row = after[day]
        if row == previous:
            continue
        if previous["outcome"] not in PENDING:
            raise ValueError("a final historical row was changed")
        # Previously unfilled entries may acquire their actual fill and bracket values.
        fixed = FIXED if previous["outcome"] == "still_open" else FIXED - {"shares", "entry", "stop", "target"}
        if any(row[k] != previous[k] for k in fixed):
            raise ValueError("historical signal or entry facts were changed")
        if row["outcome"] not in {"still_open", "order_not_filled", "target", "stop", "eod", "late_close"}:
            raise ValueError("invalid reconciliation transition")
        if row["outcome"] in {"target", "stop", "eod", "late_close"} and not all(row[k] for k in ("shares", "entry", "exit", "profit")):
            raise ValueError("settled trade lacks fill evidence")
    if [r["date"] for r in new] != sorted(after):
        raise ValueError("dates must be sorted")
    return new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["emit", "merge", "validate"])
    parser.add_argument("path")
    parser.add_argument("old", nargs="?")
    parser.add_argument("out", nargs="?")
    args = parser.parse_args()
    path = Path(args.path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("log must be a regular file")
    current = parse(path.read_text("utf-8"))
    if args.mode == "emit":
        committed = subprocess.check_output(["git", "show", "HEAD:" + path.as_posix()], text=True)
        old = parse(committed)
        validate(current, old)
        by_date = {r["date"]: r for r in old}
        changed = [r for r in current if by_date.get(r["date"]) != r]
        payload = json.dumps(changed, separators=(",", ":"))
        if len(payload) > 16000:
            raise ValueError("too many row changes")
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("row=" + payload + "\n")
        print(f"Handed on {len(changed)} changed rows")
    elif args.mode == "merge":
        payload = os.getenv("PAPER_ROWS", "") or "[]"
        if len(payload) > 16000:
            raise ValueError("payload too large")
        changed = json.loads(payload)
        if not isinstance(changed, list) or not all(isinstance(r, dict) and set(r) == set(COLUMNS) and
                                                   all(isinstance(v, str) for v in r.values()) for r in changed):
            raise ValueError("unexpected payload schema")
        if len({r["date"] for r in changed}) != len(changed):
            raise ValueError("duplicate payload dates")
        combined = {r["date"]: r for r in current}
        combined.update({r["date"]: r for r in changed})
        text = render([combined[d] for d in sorted(combined)])
        checked = validate(parse(text), current)
        path.write_text(render(checked), "utf-8")
    else:
        old = parse(Path(args.old).read_text("utf-8"))
        Path(args.out).write_text(render(validate(current, old)), "utf-8")


if __name__ == "__main__":
    main()
