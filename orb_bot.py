import math
import csv
import os
from datetime import datetime, time
from ib_insync import IB, Future, MarketOrder, LimitOrder, StopOrder, util

import config

util.startLoop()
ib = IB()


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def connect_tws():
    ib.connect(config.TWS_HOST, config.TWS_PORT, clientId=1)
    print(f"[{ts()}] Connected to TWS (port {config.TWS_PORT})")


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

def get_mnq_contract():
    contract = Future(config.SYMBOL, exchange=config.EXCHANGE, currency=config.CURRENCY)
    contracts = ib.qualifyContracts(contract)
    if not contracts:
        raise RuntimeError("Could not resolve MNQ front-month contract. Is TWS running with market data?")
    c = contracts[0]
    print(f"[{ts()}] Contract: {c.localSymbol} exp {c.lastTradeDateOrContractMonth}")
    return c


# ---------------------------------------------------------------------------
# Opening range
# ---------------------------------------------------------------------------

def collect_opening_range(contract):
    """Request 1-min bars for the first 15 minutes and return (high, low, mid_price)."""
    print(f"[{ts()}] Collecting opening range bars...")

    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr="1800 S",   # last 30 min to be safe
        barSizeSetting="1 min",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )

    if not bars:
        raise RuntimeError("No bar data returned. Check market hours and data permissions.")

    # Keep only the first 15 bars (9:30–9:44)
    opening_bars = bars[:config.OPENING_RANGE_MIN]
    orb_high = max(b.high for b in opening_bars)   # top wick, not close
    orb_low  = min(b.low  for b in opening_bars)   # bottom wick, not close
    mid      = (orb_high + orb_low) / 2

    range_pts = orb_high - orb_low
    range_pct = range_pts / mid

    print(f"[{ts()}] ORB locked — High: {orb_high:.2f}  Low: {orb_low:.2f}  "
          f"Range: {range_pts:.2f}pts ({range_pct*100:.2f}%)")

    return orb_high, orb_low, range_pct


def range_is_valid(range_pct):
    if range_pct > config.MAX_RANGE_PCT:
        print(f"[{ts()}] Range {range_pct*100:.2f}% > {config.MAX_RANGE_PCT*100:.1f}% max — skipping today.")
        return False
    return True


# ---------------------------------------------------------------------------
# Breakout detection
# ---------------------------------------------------------------------------

def watch_for_breakout(contract, orb_high, orb_low):
    """Poll every 5 minutes. Return ('long', price) on breakout, or None if cutoff reached."""
    print(f"[{ts()}] Watching for breakout (long only, cutoff 11:00 AM)...")

    while True:
        now = datetime.now().time()
        if now >= time(config.ENTRY_CUTOFF_HOUR, 0):
            print(f"[{ts()}] Entry cutoff reached — no trade today.")
            return None

        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="300 S",   # last 5 minutes
            barSizeSetting="5 mins",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )

        if bars:
            last_close = bars[-1].close
            print(f"[{ts()}] Checking... 5-min close: {last_close:.2f}", end="")

            if last_close > orb_high:
                print(f" — BREAKOUT ABOVE RANGE")
                return ("long", last_close)
            elif last_close < orb_low:
                print(f" — range broken to downside, skipping today.")
                return None
            else:
                print(f" — no breakout")

        ib.sleep(300)  # wait 5 minutes (non-blocking)


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

def calc_contracts(entry, stop):
    """2% of account / dollar risk per contract. Minimum 1."""
    dollar_risk   = config.ACCOUNT_SIZE * config.RISK_PERCENT
    risk_per_cont = abs(entry - stop) * 2  # MNQ = $2/point
    if risk_per_cont == 0:
        return 1
    return max(1, math.floor(dollar_risk / risk_per_cont))


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def place_bracket_order(contract, entry, stop, target, contracts):
    parent = MarketOrder("BUY", contracts)
    parent.orderId      = ib.client.getReqId()
    parent.transmit     = False

    take_profit = LimitOrder("SELL", contracts, round(target, 2))
    take_profit.orderId  = ib.client.getReqId()
    take_profit.parentId = parent.orderId
    take_profit.transmit = False

    stop_loss = StopOrder("SELL", contracts, round(stop, 2))
    stop_loss.orderId  = ib.client.getReqId()
    stop_loss.parentId = parent.orderId
    stop_loss.transmit = True  # transmits all three

    for order in [parent, take_profit, stop_loss]:
        ib.placeOrder(contract, order)

    print(f"[{ts()}] Buying {contracts} MNQ @ market ~{entry:.2f} | "
          f"Stop: {stop:.2f} | Target: {target:.2f}")
    print(f"[{ts()}] Bracket order placed. Done for today.")

    return parent.orderId


# ---------------------------------------------------------------------------
# EOD close
# ---------------------------------------------------------------------------

def eod_close(contract):
    positions = ib.positions()
    for pos in positions:
        if pos.contract.symbol == config.SYMBOL and pos.position != 0:
            qty  = abs(int(pos.position))
            side = "SELL" if pos.position > 0 else "BUY"
            ib.placeOrder(contract, MarketOrder(side, qty))
            print(f"[{ts()}] EOD close — {side} {qty} MNQ @ market")
            return
    print(f"[{ts()}] EOD — no open position to close.")


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------

def log_trade(date, orb_high, orb_low, range_pct, skipped,
              entry=None, stop=None, target=None, exit_price=None,
              contracts=0, pnl=None):
    file_exists = os.path.isfile(config.TRADE_LOG)
    with open(config.TRADE_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "date", "range_high", "range_low", "range_pct", "skipped",
                "entry", "stop", "target", "exit", "contracts", "pnl_usd", "win"
            ])
        win = None
        if pnl is not None:
            win = "Y" if pnl > 0 else "N"
        writer.writerow([
            date, f"{orb_high:.2f}", f"{orb_low:.2f}", f"{range_pct:.4f}", skipped,
            entry, stop, target, exit_price, contracts,
            f"{pnl:.2f}" if pnl is not None else "",
            win or ""
        ])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts():
    return datetime.now().strftime("%H:%M:%S")


def wait_until(target_time):
    """Block (non-blocking sleep) until a specific time()."""
    while datetime.now().time() < target_time:
        ib.sleep(10)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*50}")
    print(f"  ORB Bot — {today}")
    print(f"{'='*50}\n")

    # Skip Fridays — backtests show Fridays are consistently the worst day for ORB
    if datetime.now().weekday() == 4:
        print(f"[{ts()}] Friday — skipping. No trades on Fridays.")
        return

    connect_tws()
    contract = get_mnq_contract()

    # Wait until 9:45 AM for opening range to complete
    orb_ready = time(9, 45)
    now = datetime.now().time()
    if now < orb_ready:
        print(f"[{ts()}] Waiting until 9:45 AM for opening range to form...")
        wait_until(orb_ready)

    # Collect and validate opening range
    orb_high, orb_low, range_pct = collect_opening_range(contract)

    if not range_is_valid(range_pct):
        log_trade(today, orb_high, orb_low, range_pct, skipped="range_too_wide")
        ib.disconnect()
        return

    # Watch for breakout
    result = watch_for_breakout(contract, orb_high, orb_low)

    if result is None:
        log_trade(today, orb_high, orb_low, range_pct, skipped="no_breakout")
        ib.disconnect()
        return

    direction, entry = result
    stop   = orb_low
    target = orb_high + config.TARGET_RATIO * (orb_high - orb_low)
    qty    = calc_contracts(entry, stop)

    place_bracket_order(contract, entry, stop, target, qty)

    # Wait for EOD
    eod_time = time(config.EOD_CLOSE_HOUR, config.EOD_CLOSE_MINUTE)
    print(f"[{ts()}] Waiting until {eod_time} for EOD close...")
    wait_until(eod_time)
    eod_close(contract)

    # Give fill time to process
    ib.sleep(5)

    # Calculate P&L from executions
    fills    = [f for f in ib.fills() if f.contract.symbol == config.SYMBOL]
    exit_px  = None
    pnl      = None
    if len(fills) >= 2:
        buy_fill  = next((f for f in fills if f.execution.side == "BOT"), None)
        sell_fill = next((f for f in reversed(fills) if f.execution.side == "SLD"), None)
        if buy_fill and sell_fill:
            exit_px = sell_fill.execution.avgPrice
            pnl     = (exit_px - buy_fill.execution.avgPrice) * qty * 2
            result_str = f"WIN  +${pnl:.2f}" if pnl > 0 else f"LOSS -${abs(pnl):.2f}"
            print(f"[{ts()}] Exit @ {exit_px:.2f}. P&L: ${pnl:.2f} ({result_str}). Logged.")

    log_trade(today, orb_high, orb_low, range_pct, skipped="N",
              entry=round(entry, 2), stop=round(stop, 2), target=round(target, 2),
              exit_price=exit_px, contracts=qty, pnl=pnl)

    ib.disconnect()
    print(f"[{ts()}] Done. See trade_log.csv for record.\n")


if __name__ == "__main__":
    main()
