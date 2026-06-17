import math
import csv
import os
from datetime import datetime, time
from ib_insync import IB, Future, MarketOrder, LimitOrder, StopOrder, util
import yfinance as yf

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
# Pre-trade market condition checks (via yfinance — no IBKR subscription needed)
# ---------------------------------------------------------------------------

def get_market_conditions():
    """Fetch VIX, NQ 20-day EMA status, and overnight gap before connecting to TWS.
    Returns a dict or None on network failure (soft-fail — don't block on data error)."""
    try:
        vix_data = yf.download("^VIX", period="2d", progress=False)["Close"]
        vix = float(vix_data.iloc[-1])

        nq_daily = yf.download("NQ=F", period="30d", progress=False)["Close"]
        ema20 = nq_daily.ewm(span=20, adjust=False).mean()
        nq_above_ema = float(nq_daily.iloc[-1]) > float(ema20.iloc[-1])

        prev_close = float(nq_daily.iloc[-1])
        nq_intraday = yf.download("NQ=F", period="1d", interval="1m", progress=False)
        today_open = float(nq_intraday["Open"].iloc[0])
        gap_pct = (today_open - prev_close) / prev_close

        print(f"[{ts()}] VIX: {vix:.1f}  NQ above EMA20: {nq_above_ema}  Gap: {gap_pct*100:.2f}%")
        return {"vix": vix, "nq_above_ema": nq_above_ema, "gap_pct": gap_pct}

    except Exception as e:
        print(f"[{ts()}] Market condition fetch failed ({e}) — proceeding without filters")
        return None


# ---------------------------------------------------------------------------
# Daily and monthly loss limit checks
# ---------------------------------------------------------------------------

def check_daily_limits():
    """Read trade_log.csv, check today's P&L and current month's P&L.
    Returns (should_halt, reason) tuple."""
    if not os.path.isfile(config.TRADE_LOG):
        return False, None

    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    daily_loss = 0.0
    monthly_loss = 0.0

    with open(config.TRADE_LOG, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pnl_str = row.get("pnl_usd", "")
            if not pnl_str:
                continue
            try:
                pnl = float(pnl_str)
            except ValueError:
                continue
            if pnl >= 0:
                continue
            if row.get("date", "").startswith(today):
                daily_loss += abs(pnl)
            if row.get("date", "").startswith(month):
                monthly_loss += abs(pnl)

    if daily_loss >= config.DAILY_LOSS_LIMIT:
        return True, f"daily_limit_hit (${daily_loss:.2f} >= ${config.DAILY_LOSS_LIMIT})"
    if monthly_loss >= config.MONTHLY_LOSS_CAP:
        return True, f"monthly_limit_hit (${monthly_loss:.2f} >= ${config.MONTHLY_LOSS_CAP})"
    return False, None


# ---------------------------------------------------------------------------
# Consecutive loss risk reducer
# ---------------------------------------------------------------------------

def get_effective_risk():
    """Check recent trades for consecutive losses.
    If streak >= STREAK_THRESHOLD, halve the dollar risk for this session."""
    base_risk = config.ACCOUNT_SIZE * config.RISK_PERCENT

    if not os.path.isfile(config.TRADE_LOG):
        return base_risk

    rows = []
    with open(config.TRADE_LOG, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    consecutive = 0
    for row in reversed(rows):
        win = row.get("win", "")
        if win == "N":
            consecutive += 1
        elif win == "Y":
            break

    if consecutive >= config.STREAK_THRESHOLD:
        reduced = base_risk * config.STREAK_RISK_MULT
        print(f"[{ts()}] {consecutive} consecutive losses — reducing risk to ${reduced:.0f} (streak mode)")
        return reduced

    return base_risk


# ---------------------------------------------------------------------------
# Opening range
# ---------------------------------------------------------------------------

def collect_opening_range(contract):
    """Request 1-min bars for the first 30 minutes and return (high, low, range_pct)."""
    print(f"[{ts()}] Collecting opening range bars...")

    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr="3600 S",   # 60 min of history to safely cover the 30-min window
        barSizeSetting="1 min",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )

    if not bars:
        raise RuntimeError("No bar data returned. Check market hours and data permissions.")

    # First 30 bars = 9:30–9:59 AM ET
    opening_bars = bars[:config.OPENING_RANGE_MIN]
    orb_high = max(b.high for b in opening_bars)   # top wick
    orb_low  = min(b.low  for b in opening_bars)   # bottom wick
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
            durationStr="300 S",
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

        ib.sleep(300)


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

def calc_contracts(entry, stop, dollar_risk):
    """Size position from dollar_risk. Capped at MAX_CONTRACTS. Minimum 1."""
    risk_per_cont = abs(entry - stop) * 2  # MNQ = $2/point
    if risk_per_cont == 0:
        return 1
    return max(1, min(math.floor(dollar_risk / risk_per_cont), config.MAX_CONTRACTS))


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def place_bracket_order(contract, entry, stop, target, contracts):
    parent = MarketOrder("BUY", contracts)
    parent.orderId  = ib.client.getReqId()
    parent.transmit = False

    take_profit = LimitOrder("SELL", contracts, round(target, 2))
    take_profit.orderId  = ib.client.getReqId()
    take_profit.parentId = parent.orderId
    take_profit.transmit = False

    stop_loss = StopOrder("SELL", contracts, round(stop, 2))
    stop_loss.orderId  = ib.client.getReqId()
    stop_loss.parentId = parent.orderId
    stop_loss.transmit = True

    for order in [parent, take_profit, stop_loss]:
        ib.placeOrder(contract, order)

    print(f"[{ts()}] Buying {contracts} MNQ @ market ~{entry:.2f} | "
          f"Stop: {stop:.2f} | Target: {target:.2f}")
    print(f"[{ts()}] Bracket order placed.")

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
              contracts=0, pnl=None, vix=None):
    file_exists = os.path.isfile(config.TRADE_LOG)
    with open(config.TRADE_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "date", "range_high", "range_low", "range_pct", "skipped",
                "entry", "stop", "target", "exit", "contracts", "pnl_usd", "win", "vix"
            ])
        win = None
        if pnl is not None:
            win = "Y" if pnl > 0 else "N"
        writer.writerow([
            date,
            f"{orb_high:.2f}" if orb_high is not None else "",
            f"{orb_low:.2f}"  if orb_low  is not None else "",
            f"{range_pct:.4f}" if range_pct is not None else "",
            skipped,
            entry, stop, target, exit_price, contracts,
            f"{pnl:.2f}" if pnl is not None else "",
            win or "",
            f"{vix:.1f}" if vix is not None else ""
        ])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts():
    return datetime.now().strftime("%H:%M:%S")


def wait_until(target_time):
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

    # Skip Fridays
    if datetime.now().weekday() == 4:
        print(f"[{ts()}] Friday — skipping. No trades on Fridays.")
        return

    # Check daily and monthly loss limits before doing anything
    should_halt, halt_reason = check_daily_limits()
    if should_halt:
        print(f"[{ts()}] HALTED — {halt_reason}. No trade today.")
        log_trade(today, None, None, None, skipped=halt_reason)
        return

    # Fetch market conditions via yfinance (VIX, NQ EMA, gap)
    conditions = get_market_conditions()
    vix = conditions["vix"] if conditions else None

    if conditions:
        if conditions["vix"] < config.VIX_MIN:
            reason = f"vix_too_low ({conditions['vix']:.1f} < {config.VIX_MIN})"
            print(f"[{ts()}] Skipping — {reason}")
            log_trade(today, None, None, None, skipped=reason, vix=conditions["vix"])
            return

        if conditions["vix"] > config.VIX_MAX:
            reason = f"vix_too_high ({conditions['vix']:.1f} > {config.VIX_MAX})"
            print(f"[{ts()}] Skipping — {reason}")
            log_trade(today, None, None, None, skipped=reason, vix=conditions["vix"])
            return

        if not conditions["nq_above_ema"]:
            reason = "nq_below_20ema"
            print(f"[{ts()}] Skipping — NQ is below its 20-day EMA (bearish regime)")
            log_trade(today, None, None, None, skipped=reason, vix=conditions["vix"])
            return

        if conditions["gap_pct"] > config.GAP_SKIP_PCT:
            reason = f"gap_too_large ({conditions['gap_pct']*100:.2f}% > {config.GAP_SKIP_PCT*100:.1f}%)"
            print(f"[{ts()}] Skipping — {reason}")
            log_trade(today, None, None, None, skipped=reason, vix=conditions["vix"])
            return

    # Get effective risk (reduced automatically if on a losing streak)
    dollar_risk = get_effective_risk()

    connect_tws()
    contract = get_mnq_contract()

    # Wait until 10:00 AM for the 30-minute opening range to complete
    orb_ready = time(10, 0)
    now = datetime.now().time()
    if now < orb_ready:
        print(f"[{ts()}] Waiting until 10:00 AM for 30-min opening range to form...")
        wait_until(orb_ready)

    # Collect and validate opening range
    orb_high, orb_low, range_pct = collect_opening_range(contract)

    if not range_is_valid(range_pct):
        log_trade(today, orb_high, orb_low, range_pct, skipped="range_too_wide", vix=vix)
        ib.disconnect()
        return

    # Watch for breakout
    result = watch_for_breakout(contract, orb_high, orb_low)

    if result is None:
        log_trade(today, orb_high, orb_low, range_pct, skipped="no_breakout", vix=vix)
        ib.disconnect()
        return

    direction, entry = result
    stop   = (orb_high + orb_low) / 2          # midpoint stop — better win rate than range low
    target = orb_high + config.TARGET_RATIO * (orb_high - orb_low)
    qty    = calc_contracts(entry, stop, dollar_risk)

    place_bracket_order(contract, entry, stop, target, qty)

    # Wait for EOD safety close (bracket order handles exits; this is the backstop)
    eod_time = time(config.EOD_CLOSE_HOUR, config.EOD_CLOSE_MINUTE)
    print(f"[{ts()}] Waiting until {eod_time} for EOD close...")
    wait_until(eod_time)
    eod_close(contract)

    ib.sleep(5)

    # Calculate P&L from executions
    fills   = [f for f in ib.fills() if f.contract.symbol == config.SYMBOL]
    exit_px = None
    pnl     = None
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
              exit_price=exit_px, contracts=qty, pnl=pnl, vix=vix)

    ib.disconnect()
    print(f"[{ts()}] Done. See trade_log.csv for record.\n")


if __name__ == "__main__":
    main()
