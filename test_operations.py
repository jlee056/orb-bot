"""Regression tests for order handling, record reconciliation and backup startup."""
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pandas as pd
from alpaca.common.exceptions import APIError

import alpaca_bot as bot
import alpaca_io as A
import forward_alert
import paper_log
import watchdog


def api_error(code, status):
    return APIError(json.dumps({"code": code, "message": "test"}),
                    NS(response=NS(status_code=status)))


def row(outcome="still_open"):
    record = {c: "" for c in paper_log.COLUMNS}
    record.update(date="2026-10-26", config_id="baa9b9f8", source="alpaca-paper/alpaca-iex",
                  outcome=outcome, shares="10", entry="10.00", stop="9.00", target="20.00",
                  sim_outcome="eod", sim_R="3.790", logged_at="2026-10-26T21:18Z")
    return record


def order(id, **kwargs):
    fields = dict(id=id, parent=None, client_order_id=None, side="sell", type="market", status="filled",
                  filled_qty=0, filled_avg_price=None, filled_at=pd.Timestamp("2026-10-26T15:00Z"),
                  limit_price=None, stop_price=None, order_class="simple", legs=[])
    fields.update(kwargs)
    return NS(**fields)


class CloseTests(unittest.TestCase):
    def broker(self):
        broker = A.AlpacaBroker.__new__(A.AlpacaBroker)
        broker.client = Mock()
        return broker

    @patch.object(A.clock, "sleep")
    def test_waits_for_cancellation_and_retries_reservation(self, sleep):
        broker = self.broker()
        bracket = order("stop", type="stop", order_class="bracket")
        broker.open_orders = Mock(side_effect=[[bracket], [bracket], [], []])
        broker.position_qty = Mock(side_effect=[42, 42, 0])
        broker.client.close_position.side_effect = [api_error(40310000, 403), NS()]
        self.assertTrue(broker.flatten())
        broker.client.cancel_order_by_id.assert_called_once_with("stop")
        self.assertEqual(broker.client.close_position.call_count, 2)
        self.assertEqual(sleep.call_count, 2)

    @patch.object(A.clock, "sleep")
    def test_existing_queued_close_is_not_cancelled_or_duplicated(self, sleep):
        broker = self.broker()
        broker.open_orders = Mock(return_value=[order("queued-close")])
        broker.position_qty = Mock(return_value=42)
        self.assertFalse(broker.flatten(timeout=0))
        broker.client.cancel_order_by_id.assert_not_called()
        broker.client.close_position.assert_not_called()

    def test_only_missing_position_is_zero(self):
        broker = self.broker()
        broker.client.get_open_position.side_effect = api_error(40410000, 404)
        self.assertEqual(broker.position_qty(), 0)
        broker.client.get_open_position.side_effect = api_error(40310000, 403)
        with self.assertRaises(APIError):
            broker.position_qty()

    def test_order_lookup_does_not_hide_auth_failure(self):
        broker = self.broker()
        broker.client.get_order_by_client_id.side_effect = api_error(40110000, 401)
        with self.assertRaises(APIError):
            broker.has_order("orb5-2026-10-26")

    def test_cancel_timeout_does_not_submit_close(self):
        broker = self.broker()
        broker.open_orders = Mock(return_value=[order("stop", type="stop")])
        with self.assertRaisesRegex(RuntimeError, "cancellations"):
            broker.flatten(timeout=0)
        broker.client.close_position.assert_not_called()


class RecordTests(unittest.TestCase):
    def test_later_trade_exit_is_excluded_from_reconciliation(self):
        broker = A.AlpacaBroker.__new__(A.AlpacaBroker)
        parent = order("parent", client_order_id="orb5-2026-10-26", side="buy")
        later = order("later", client_order_id="orb5-2026-10-28", side="buy",
                      filled_at=pd.Timestamp("2026-10-28T13:36Z"))
        exit_order = order("exit", filled_at=pd.Timestamp("2026-10-27T13:33Z"))
        later_exit = order("later-exit", filled_at=pd.Timestamp("2026-10-28T16:00Z"))
        broker.day_orders = Mock(return_value=[parent, exit_order, later, later_exit])
        self.assertEqual([o.id for o in broker.trade_orders(parent.filled_at.date(), parent.client_order_id)],
                         ["parent", "exit"])

    def test_duplicate_nested_leg_keeps_parent_link(self):
        broker = A.AlpacaBroker.__new__(A.AlpacaBroker)
        leg = order("leg", stop_price=9)
        parent = order("parent", legs=[leg])
        broker.client = Mock()
        broker.client.get_orders.return_value = [parent, leg]
        orders = broker.day_orders(datetime(2026, 10, 26).date())
        self.assertEqual(len(orders), 2)
        self.assertEqual(next(o.parent for o in orders if o.id == "leg"), "parent")

    def make_row(self, sold):
        parent = order("entry", side="buy", client_order_id="orb-2026-10-26", filled_qty=10,
                       filled_avg_price=10)
        stop = order("stop", parent="entry", type="stop", stop_price=9)
        target = order("target", parent="entry", type="limit", limit_price=20)
        exit_order = order("close", filled_qty=sold, filled_avg_price=11,
                           filled_at=pd.Timestamp("2026-10-27T13:30Z"))
        broker = NS(name="alpaca-paper", day_orders=lambda day: [parent, stop, target, exit_order])
        return bot.build_row(broker, NS(name="alpaca-iex"), datetime(2026, 10, 26).date(), bot.qqq_params(), None, row())

    def test_partial_exit_is_not_a_closed_trade(self):
        result = self.make_row(4)
        self.assertEqual(result["outcome"], "still_open")
        self.assertEqual(result["profit"], "")

    def test_next_day_exit_reconciles_actual_profit(self):
        result = self.make_row(10)
        self.assertEqual(result["outcome"], "late_close")
        self.assertEqual(result["profit"], "10.00")
        self.assertEqual(result["sim_R"], "3.790")

    def test_excess_exit_requires_review(self):
        with self.assertRaisesRegex(RuntimeError, "exceeds"):
            self.make_row(11)

    def test_upsert_replaces_one_date(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "log.csv")
            bot.upsert_row(path, row())
            settled = row("eod")
            settled.update(exit="11.00", profit="10.00")
            bot.upsert_row(path, settled)
            self.assertEqual(bot.read_rows(path), [settled])

    def test_today_logged_does_not_bypass_broker_flatten(self):
        today = pd.Timestamp.now(tz=bot.TZ).date()
        broker = Mock()
        broker.hours.return_value = (pd.Timestamp(today), pd.Timestamp(today))
        broker.position_qty.return_value = 0
        broker.open_orders.return_value = []
        broker.flatten.return_value = True
        previous = {**row("eod"), "date": today.isoformat(), "profit": "10.00", "profit_5k": "1.00"}
        with patch.object(A, "have_keys", return_value=True), patch.object(A, "AlpacaBroker", return_value=broker), \
             patch.object(A, "AlpacaData"), patch.object(bot, "read_rows", return_value=[previous]), \
             patch.object(bot, "reconcile_pending"), patch.object(bot, "push"):
            self.assertEqual(bot.mode_close(), 0)
        broker.flatten.assert_called_once()


class ValidationTests(unittest.TestCase):
    def test_pending_can_settle_without_rewriting_signal(self):
        old = row()
        new = {**old, "outcome": "late_close", "exit": "11.00", "profit": "10.00"}
        parsed = paper_log.parse(paper_log.render([new]))
        self.assertEqual(paper_log.validate(parsed, [old]), [new])
        new["entry"] = "12.00"
        with self.assertRaisesRegex(ValueError, "facts"):
            paper_log.validate([new], [old])

    def test_final_history_cannot_be_rewritten(self):
        old = row("stop")
        with self.assertRaisesRegex(ValueError, "final"):
            paper_log.validate([{**old, "profit": "99.00"}], [old])

    def test_control_bytes_and_duplicate_dates_rejected(self):
        with self.assertRaises(ValueError):
            paper_log.parse(paper_log.render([row()]) + "\x00")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            paper_log.parse(paper_log.render([row(), row()]))

    def test_no_deleted_dates_or_multiple_new_dates(self):
        with self.assertRaises(ValueError):
            paper_log.validate([], [row()])
        with self.assertRaises(ValueError):
            paper_log.validate([row(), {**row(), "date": "2026-10-27"}], [])


class BackupTests(unittest.TestCase):
    def test_late_duplicate_after_timely_no_trade_does_not_alarm(self):
        now = pd.Timestamp("2026-10-29 14:00", tz=bot.TZ)
        broker = Mock()
        broker.hours.return_value = (pd.Timestamp("2026-10-29 09:30"), pd.Timestamp("2026-10-29 16:00"))
        broker.has_order.return_value = False
        broker.position_qty.return_value = 0
        broker.open_orders.return_value = []
        with patch.object(A, "have_keys", return_value=True), patch.object(A, "AlpacaBroker", return_value=broker), \
             patch.object(A, "AlpacaData"), patch.object(bot.pd, "Timestamp", wraps=pd.Timestamp) as timestamp, \
             patch.object(bot, "already_sent", return_value=True), patch.object(bot, "push") as push:
            timestamp.now.return_value = now
            self.assertEqual(bot.mode_entry(), 0)
            push.assert_not_called()

    def test_old_queued_run_does_not_suppress_recovery(self):
        now = datetime.now(watchdog.ET)
        run = dict(created_at=(now - timedelta(minutes=5)).isoformat(), status="queued", conclusion=None)
        with patch.object(watchdog, "github", return_value={"workflow_runs": [run]}):
            self.assertFalse(watchdog.started_in_window("paper-entry.yml", 0, 1439, now.date()))
        run["status"] = "in_progress"
        with patch.object(watchdog, "github", return_value={"workflow_runs": [run]}):
            self.assertTrue(watchdog.started_in_window("paper-entry.yml", 0, 1439, now.date()))

    def test_notification_outage_does_not_raise_into_trading(self):
        with patch.dict(os.environ, NTFY_TOPIC="test-topic"), \
             patch.object(forward_alert, "already_sent", return_value=False), \
             patch.object(forward_alert.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")), \
             patch.object(forward_alert.time, "sleep"):
            self.assertFalse(forward_alert.push("Test", "Test"))


if __name__ == "__main__":
    unittest.main()
