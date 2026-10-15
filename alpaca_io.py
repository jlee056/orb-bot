"""Everything that talks to Alpaca lives here. PAPER TRADING ONLY.

There is deliberately no live-account switch: the trading client is always built
with paper=True. Keys come from the environment (.env locally, repository
secrets in GitHub Actions): ALPACA_API_KEY and ALPACA_SECRET_KEY.

Also holds two stand-ins used before keys exist and in tests:
  YahooData   - same bars() shape, from yfinance
  FakeBroker  - same order methods, fills simulated from bars
"""
import os
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

import config  # noqa: F401  (loads .env)

SYMBOL = "QQQ"
TZ = "America/New_York"
RTH_OPEN, RTH_CLOSE = 9 * 60 + 30, 16 * 60


def have_keys():
    return bool(os.getenv("ALPACA_API_KEY", "").strip() and os.getenv("ALPACA_SECRET_KEY", "").strip())


def _keys():
    return os.environ["ALPACA_API_KEY"].strip(), os.environ["ALPACA_SECRET_KEY"].strip()


def fill_minutes(df, bar):
    """Give every regular-hours minute a bar. IEX is one exchange, so a quiet minute can have
    no trade; such a minute is filled flat at the previous close with zero volume."""
    if not len(df):
        return df
    out = []
    for d, b in df.groupby(df.index.normalize()):
        mod = b.index.hour * 60 + b.index.minute
        b = b[(mod >= RTH_OPEN) & (mod < RTH_CLOSE)]
        if not len(b):
            continue
        grid = pd.date_range(d + pd.Timedelta(minutes=RTH_OPEN), b.index[-1], freq=f"{bar}min")
        b = b.reindex(grid)
        close = b["close"].ffill()
        for col in ("open", "high", "low"):
            b[col] = b[col].fillna(close)
        b["close"] = close
        b["volume"] = b["volume"].fillna(0)
        out.append(b.dropna(subset=["close"]))
    res = pd.concat(out) if out else df.iloc[:0]
    res.index.name = "ts"
    return res


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

class AlpacaData:
    """QQQ bars from Alpaca's free IEX feed, as a naive Eastern-time frame."""
    name = "alpaca-iex"

    def __init__(self):
        from alpaca.data.historical import StockHistoricalDataClient
        self.client = StockHistoricalDataClient(*_keys())

    def bars(self, bar, start, end=None, symbol=SYMBOL, feed="iex"):
        """feed="iex" is the free real-time feed. feed="sip" (all exchanges) is only free for
        history older than 15 minutes, so it is used for backtest downloads, never live."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        s = pd.Timestamp(start, tz=TZ).tz_convert("UTC").to_pydatetime()
        e = pd.Timestamp(end, tz=TZ).tz_convert("UTC").to_pydatetime() if end is not None else None
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame(bar, TimeFrameUnit.Minute),
                               start=s, end=e, feed=DataFeed.SIP if feed == "sip" else DataFeed.IEX)
        df = self.client.get_stock_bars(req).df
        if not len(df):
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = df.xs(symbol, level=0)
        df.index = df.index.tz_convert(TZ).tz_localize(None)
        return fill_minutes(df[["open", "high", "low", "close", "volume"]].astype(float), bar)


class YahooData:
    """Same shape from yfinance. Keeps 7 days of 1-minute and 60 days of 5-minute bars."""
    name = "yahoo"

    def bars(self, bar, start, end=None, symbol=SYMBOL):
        import yfinance as yf
        period = "7d" if bar == 1 else "60d"
        d = yf.download(symbol, period=period, interval=f"{bar}m", progress=False, multi_level_index=False)
        d.index = d.index.tz_convert(TZ).tz_localize(None)
        d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].astype(float)
        d = d[d.index >= pd.Timestamp(start)]
        if end is not None:
            d = d[d.index < pd.Timestamp(end)]
        return fill_minutes(d, bar)


def data_source():
    return AlpacaData() if have_keys() else YahooData()


# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------

def _f(x):
    return float(x) if x is not None else None


class AlpacaBroker:
    name = "alpaca-paper"

    def __init__(self):
        from alpaca.trading.client import TradingClient
        self.client = TradingClient(*_keys(), paper=True)   # paper only, by design

    def account(self):
        a = self.client.get_account()
        return SimpleNamespace(number=a.account_number, status=str(a.status), equity=float(a.equity),
                               buying_power=float(a.buying_power))

    def hours(self, day):
        """(open, close) as naive Eastern datetimes, or None if the market is closed that day."""
        from alpaca.trading.requests import GetCalendarRequest
        cal = self.client.get_calendar(GetCalendarRequest(start=day, end=day))
        for c in cal:
            if c.date == day:
                return pd.Timestamp(c.open).tz_localize(None), pd.Timestamp(c.close).tz_localize(None)
        return None

    def position_qty(self, symbol=SYMBOL):
        from alpaca.common.exceptions import APIError
        try:
            return float(self.client.get_open_position(symbol).qty)
        except APIError:
            return 0.0

    def has_order(self, client_order_id):
        """True if an order with this client id was ever submitted (filled, open or cancelled)."""
        from alpaca.common.exceptions import APIError
        try:
            self.client.get_order_by_client_id(client_order_id)
            return True
        except APIError:
            return False

    def open_orders(self, symbol=SYMBOL):
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        return self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol]))

    def can_short(self, symbol=SYMBOL):
        """(ok, reason): the account may short and the symbol is shortable and easy to borrow."""
        a = self.client.get_account()
        if not getattr(a, "shorting_enabled", False):
            return False, "shorting is not enabled on this account"
        s = self.client.get_asset(symbol)
        if not s.shortable or not s.easy_to_borrow:
            return False, f"{symbol} is not shortable / easy to borrow today"
        return True, ""

    def place_bracket(self, qty, stop, target, client_order_id, symbol=SYMBOL, side="buy"):
        """Market entry with a take-profit limit and a stop. side="sell" opens a short (target below, stop above)."""
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
        req = MarketOrderRequest(symbol=symbol, qty=int(qty), side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                                 time_in_force=TimeInForce.DAY,
                                 order_class=OrderClass.BRACKET, client_order_id=client_order_id,
                                 take_profit=TakeProfitRequest(limit_price=round(float(target), 2)),
                                 stop_loss=StopLossRequest(stop_price=round(float(stop), 2)))
        return str(self.client.submit_order(req).id)

    def flatten(self, symbol=SYMBOL):
        """Cancel open orders for the symbol, then close any position at market."""
        for o in self.open_orders(symbol):
            self.client.cancel_order_by_id(o.id)
        if self.position_qty(symbol) != 0:
            self.client.close_position(symbol)

    def day_orders(self, day, symbol=SYMBOL):
        """All of the day's orders for the symbol, bracket legs flattened in, as plain records."""
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        after = pd.Timestamp(day, tz=TZ).tz_convert("UTC").to_pydatetime()
        raw = self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, symbols=[symbol], after=after,
                                                      nested=True, limit=200))
        out = []

        def add(o, parent=None):
            out.append(SimpleNamespace(
                id=str(o.id), parent=parent, client_order_id=o.client_order_id,
                side=str(getattr(o.side, "value", o.side)), type=str(getattr(o.type, "value", o.type)),
                status=str(getattr(o.status, "value", o.status)), filled_qty=_f(o.filled_qty) or 0.0,
                filled_at=getattr(o, "filled_at", None),
                filled_avg_price=_f(o.filled_avg_price), limit_price=_f(o.limit_price), stop_price=_f(o.stop_price)))
            for leg in (o.legs or []):
                add(leg, str(o.id))
        for o in raw:
            add(o)
        return out


class FakeBroker:
    """In-memory stand-in. settle() fills a bracket from bars the way the backtest would."""
    name = "fake"

    def __init__(self, equity=100000.0):
        self.equity, self.orders, self.qty = equity, [], 0.0

    def account(self):
        return SimpleNamespace(number="FAKE", status="ACTIVE", equity=self.equity, buying_power=self.equity * 2)

    def hours(self, day):
        if day.weekday() >= 5:
            return None
        d = pd.Timestamp(day)
        return d + pd.Timedelta(minutes=RTH_OPEN), d + pd.Timedelta(minutes=RTH_CLOSE)

    def position_qty(self, symbol=SYMBOL):
        return self.qty

    def has_order(self, client_order_id):
        return any(o.client_order_id == client_order_id for o in self.orders)

    def open_orders(self, symbol=SYMBOL):
        return [o for o in self.orders if o.status in ("new", "held")]

    def _order(self, **k):
        o = SimpleNamespace(id=str(len(self.orders) + 1), parent=None, client_order_id=None, side="buy",
                            type="market", status="new", filled_qty=0.0, filled_avg_price=None, filled_at=None,
                            limit_price=None, stop_price=None, placed_at=None)
        o.__dict__.update(k)
        self.orders.append(o)
        return o

    def can_short(self, symbol=SYMBOL):
        return True, ""

    def place_bracket(self, qty, stop, target, client_order_id, symbol=SYMBOL, side="buy", placed_at=None):
        if any(o.client_order_id == client_order_id for o in self.orders):
            raise RuntimeError("client_order_id must be unique")
        out = "sell" if side == "buy" else "buy"
        p = self._order(client_order_id=client_order_id, side=side, placed_at=placed_at, want=float(qty))
        self._order(parent=p.id, side=out, type="limit", status="held", limit_price=round(float(target), 2))
        self._order(parent=p.id, side=out, type="stop", status="held", stop_price=round(float(stop), 2))
        return p.id

    def settle(self, bars, close_at):
        """Fill the open bracket from 1-minute bars: entry at the next bar's open, then the first of
        stop (checked first), target, or a market close at `close_at`. Shorts are mirrored."""
        for p in [o for o in self.orders if o.parent is None and o.type == "market" and o.status == "new"]:
            tp = next(o for o in self.orders if o.parent == p.id and o.type == "limit")
            sl = next(o for o in self.orders if o.parent == p.id and o.type == "stop")
            long = p.side == "buy"
            after = bars[bars.index > p.placed_at]
            if not len(after):
                continue
            p.status, p.filled_qty, p.filled_avg_price = "filled", p.want, float(after["open"].iloc[0])
            done = False
            for ts, b in after.iterrows():
                if ts >= close_at:
                    break
                if (b["low"] <= sl.stop_price) if long else (b["high"] >= sl.stop_price):
                    px = min(sl.stop_price, b["open"]) if long else max(sl.stop_price, b["open"])
                    sl.status, sl.filled_qty, sl.filled_avg_price = "filled", p.want, px
                    tp.status, done = "canceled", True
                    break
                if (b["high"] >= tp.limit_price) if long else (b["low"] <= tp.limit_price):
                    tp.status, tp.filled_qty, tp.filled_avg_price = "filled", p.want, tp.limit_price
                    sl.status, done = "canceled", True
                    break
            if not done:
                tp.status = sl.status = "canceled"
                late = bars[bars.index >= close_at]
                px = float(late["open"].iloc[0]) if len(late) else float(bars["close"].iloc[-1])
                self._order(side="sell" if long else "buy", status="filled", filled_qty=p.want, filled_avg_price=px)

    def flatten(self, symbol=SYMBOL):
        pass

    def day_orders(self, day, symbol=SYMBOL):
        return list(self.orders)
