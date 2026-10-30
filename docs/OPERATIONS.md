# Paper trading operations

Strategy settings remain frozen. Operational repairs do not change entry rules,
risk sizing, stops or targets. All broker clients remain hard-coded to paper.

## Morning execution

GitHub scheduled workflows are a backup; they have started hours late. The Windows
login helper dispatches workflows over the GitHub REST API using the existing git
credential, without launching gh. It checks every five minutes from 08:45 ET and
checks readiness at 09:20, before the orb5 entry. A queued run older than three
minutes does not suppress recovery.

Install or repair the helper and six scheduled tasks with:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-watchdog.ps1

The installer saves old task XML under LocalAppData/orb-bot-task-backups, creates
the ORB watchdog login shortcut and starts a hidden singleton helper. Scheduler
tasks allow battery operation, catch-up starts, wake and retries. The helper is an
independent path because Windows has refused scheduled starts with 0x800710e0.

The PC must be awake, online and signed in for the helper. Locking the screen is
fine; signing out stops user processes. S4U registration for signed-out execution
requires Windows privileges unavailable in the repair session. Existing cloud
schedules remain enabled, but are not a guarantee of timely execution.

Check watchdog.log for heartbeat and dispatch results. Run `python watchdog.py
probe` for a read-only credential/API check. Credentials are never printed.

## Closing and reconciliation

Close mode always checks the account, even when today has a CSV row. It waits for
order cancellations to release reserved shares, retries reservation conflicts and
verifies the position and open orders. An accepted queued market close is left
alone rather than repeatedly cancelled and resubmitted. An unconfirmed close
fails the job and sends a problem alert.

Pending rows are reconciled against historical broker fills, including next-day
exits. Partial exits remain pending; they are not counted as closed trades. Orders
are deduplicated and a later strategy entry bounds the prior trade's history.
`late_close` explicitly identifies an overnight execution failure.

The trade job hands bounded JSON row changes to a clean report job. The validator
permits updates only to pending rows and at most one new date. Final history and
historical signal facts remain immutable. The write-token publish job reruns the
validator and does not execute installed packages or receive broker secrets.

Run the Paper account audit workflow for read-only checks of all three accounts.
Run Paper trade close and record to verify closure and repair pending records.
Notification retries cannot repeat a trading submission. Missing data, blocked
accounts and missed entry windows fail visibly; a duplicate late run following a
valid morning no-trade decision does not create a false late-start alert.

## Verified October 29, 2026

All three accounts had zero QQQ positions and zero open orders in audit
40986113053 and close/reconciliation run 40986184383. The October 26 orb5 entry
was 42 shares at 707.70; its closing fill arrived October 27 at 09:33 ET at
715.175952. The corrected row records +313.99 gross paper profit, +3.629 R and
`late_close`. The positive profit does not make the overnight hold a valid
same-day strategy result. Account equity can differ from gross logged profit
because of fees.

Tests: `python -m unittest -v test_operations` and `python variants.py --check`.
The operations test workflow repeats both checks without broker secrets.
