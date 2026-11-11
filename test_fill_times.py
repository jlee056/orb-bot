import io
import unittest
from contextlib import redirect_stdout
from datetime import date
from types import SimpleNamespace

import pandas as pd

import alpaca_bot as B


class Broker:
    def __init__(self, orders):
        self.orders = orders

    def day_orders(self, day):
        return self.orders


def run(broker, day):
    out = io.StringIO()
    with redirect_stdout(out):
        B.print_fill_times(broker, day)
    return out.getvalue()


class FillTimes(unittest.TestCase):
    day = date(2026, 11, 10)

    def test_prints_times_and_delay(self):
        o = SimpleNamespace(client_order_id=B.order_id(self.day),
                            submitted_at=pd.Timestamp("2026-11-10T14:36:05Z"),
                            filled_at=pd.Timestamp("2026-11-10T14:37:45Z"))
        text = run(Broker([o]), self.day)
        self.assertIn("FILLTIMES 2026-11-10", text)
        self.assertIn("submitted=2026-11-10T14:36:05", text)
        self.assertIn("delay_s=100.0", text)

    def test_no_order_prints_nothing(self):
        self.assertEqual(run(Broker([]), self.day), "")

    def test_broker_error_is_swallowed(self):
        class Broken:
            def day_orders(self, day):
                raise RuntimeError("boom")
        self.assertIn("unavailable", run(Broken(), self.day))


if __name__ == "__main__":
    unittest.main()
