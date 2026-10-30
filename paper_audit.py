"""Read-only broker audit. No order mutations, no credentials printed."""
import json
from datetime import date, timedelta

import pandas as pd

import alpaca_bot as bot
import alpaca_io as A
import variants


def main(name):
    variant = variants.get(name)
    broker = A.AlpacaBroker()
    account = broker.account()
    today = pd.Timestamp.now(tz=A.TZ).date()
    summary = dict(variant=name, status=account.status, equity=account.equity,
                   position_qty=broker.position_qty(), open_order_count=len(broker.open_orders()))
    print(json.dumps(summary))
    for old in bot.read_rows(variant.path("paper_log")):
        if old["outcome"] != "still_open":
            continue
        orders = broker.day_orders(date.fromisoformat(old["date"]), through=today + timedelta(days=1))
        print("Historical order evidence", old["date"])
        for order in orders:
            print(json.dumps(vars(order), default=str))


if __name__ == "__main__":
    import sys
    main(sys.argv[1])
