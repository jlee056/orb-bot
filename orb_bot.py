import math
import csv
import os
from datetime import datetime, time
from ib_insync import IB, Future, MarketOrder, LimitOrder, StopOrder, util
import yfinance as yf

import config
import events

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
    details = ib.reqContractDetails(contract)
    if not details:
        raise RuntimeError("Could not resolve MNQ front-month contract. Is TWS running with market data?")
    today = datetime.now().strftime("%Y%m%d")
    valid = sorted(
        [d for d in details if d.contract.lastTradeDateOrContractMonth >= today],
        key=lambda d: d.contract.lastTradeDateOrContractMonth,
    )
    if not valid:
        raise RuntimeError("No active MNQ contracts found.")
    c = valid[0].contract
    ib.qualifyContracts(c)
    print(f"[{ts()}] Contract: {c.localSymbol} exp {c.lastTradeDateOrContractMonth}")
    return c


# ---------------------------------------------------------------------------
# Pre-trade market condition checks (via yfinance — no IBKR subscription needed)
# ---------------------------------------------------------------------------

def get_market_conditions():
    """Fetch VIX, NQ 20-day EMA status, and overnight gap before connecting to TWS.
    Returns a dict or None on network failure (soft-fail — don't block on data error)."""
    try:
        vix_data = yf.download("^VIX", period="2d", progress=False, multi_level_index=False)["Close"]
        vix = float(vix_data.iloc[-1])

        # 90 days of daily bars — a 20-EMA needs ~60-90 bars to stabilize (30d was a bug).
        nq_ohlc = yf.download("NQ=F", period="90d", progress=False, multi_level_index=False)
        nq_daily = nq_ohlc["Close"]
        ema20 = nq_daily.ewm(span=20, adjust=False).mean()
        nq_above_ema = float(nq_daily.iloc[-1]) > float(ema20.iloc[-1])

        # How many of the most recent consecutive sessions closed above the EMA
        # (anti-whipsaw: research wants 3+ before taking a long).
        days_above_ema = 0
        for close_v, ema_v in zip(reversed(nq_daily.tolist()), reversed(ema20.tolist())):
            if close_v > ema_v:
                days_above_ema += 1
            else:
                break

        # ATR(N) on the daily bars (NQ index points ≈ MNQ price points) for the stop.
        atr = None
        try:
            high = nq_ohlc["High"]
            low = nq_ohlc["Low"]
            prev_c = nq_daily.shift(1)
            tr = (high - low).combine((high - prev_c).abs(), max).combine((low - prev_c).abs(), max)
            atr = float(tr.rolling(config.ATR_PERIOD).mean().iloc[-1])
        except Exception:
            atr = None

        prev_close = float(nq_daily.iloc[-2])  # yesterday's close, not today's partial bar
        nq_intraday = yf.download("NQ=F", period="1d", interval="1m", progress=False, multi_level_index=False)
        today_open = float(nq_intraday["Open"].iloc[0])
        gap_pct = (today_open - prev_close) / prev_close

        atr_str = f"{atr:.1f}" if atr is not None else "n/a"
        print(f"[{ts()}] VIX: {vix:.1f}  NQ above EMA20: {nq_above_ema} ({days_above_ema}d)  "
              f"Gap: {gap_pct*100:.2f}%  ATR: {atr_str}")
        return {"vix": vix, "nq_above_ema": nq_above_ema, "days_above_ema": days_above_ema,
                "gap_pct": gap_pct, "atr": atr}

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
        useRTH=False,
        formatDate=1,
    )

    if not bars:
        raise RuntimeError("No bar data returned. Check market hours and data permissions.")

    # Last 30 bars of the 60-min window = 9:30–9:59 AM ET
    opening_bars = bars[-config.OPENING_RANGE_MIN:]
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
    """Poll every 5 minutes. Returns one of:
       ("long", price)   — upside breakout (the only tradable signal),
       "downside_break"  — range broke down first (long-only: no trade),
       "no_breakout"     — entry cutoff reached with no breakout.
    Both no-trade outcomes are genuine signal-absence, not filter skips —
    there is no valid long entry, so paper mode does not override them."""
    print(f"[{ts()}] Watching for breakout (long only, cutoff 11:00 AM)...")

    while True:
        now = datetime.now().time()
        if now >= time(config.ENTRY_CUTOFF_HOUR, 0):
            print(f"[{ts()}] Entry cutoff reached — no trade today.")
            return "no_breakout"

        ib.sleep(2)  # prevent IBKR pacing violations (~6 req/10s limit)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1800 S",
            barSizeSetting="5 mins",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
        )

        if bars:
            last_close = bars[-1].close
            print(f"[{ts()}] Checking... 5-min close: {last_close:.2f}", end="")

            if last_close > orb_high:
                print(f" — BREAKOUT ABOVE RANGE")
                return ("long", last_close)
            elif last_close < orb_low:
                print(f" — range broken to downside, no long entry today.")
                return "downside_break"
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


def compute_stop(entry, orb_high, orb_low, atr):
    """Stop price per config.STOP_MODE.
       'atr'      => max(orb_low, entry - ATR_STOP_MULT*ATR)  (research-preferred)
       'midpoint' => (orb_high + orb_low) / 2                 (validated fallback)
    Falls back to midpoint if ATR is unavailable (e.g. yfinance failed)."""
    midpoint = (orb_high + orb_low) / 2
    if config.STOP_MODE == "atr" and atr:
        return max(orb_low, entry - config.ATR_STOP_MULT * atr)
    return midpoint


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def place_bracket_order(contract, entry, stop, target, contracts):
    parent = MarketOrder("BUY", contracts)
    parent.orderId  = ib.client.getReqId()
    parent.transmit = False
    parent.tif      = "DAY"

    take_profit = LimitOrder("SELL", contracts, round(target, 2))
    take_profit.orderId  = ib.client.getReqId()
    take_profit.parentId = parent.orderId
    take_profit.transmit = False
    take_profit.tif      = "DAY"

    stop_loss = StopOrder("SELL", contracts, round(stop, 2))
    stop_loss.orderId  = ib.client.getReqId()
    stop_loss.parentId = parent.orderId
    stop_loss.transmit = True
    stop_loss.tif      = "DAY"

    for order in [parent, take_profit, stop_loss]:
        ib.placeOrder(contract, order)

    print(f"[{ts()}] Buying {contracts} MNQ @ market ~{entry:.2f} | "
          f"Stop: {stop:.2f} | Target: {target:.2f}")
    print(f"[{ts()}] Bracket order placed.")

    return parent.orderId, stop_loss


def manage_position(contract, stop_order, entry, target, eod_time):
    """Poll until EOD. Once price reaches BREAKEVEN_TRIGGER_RATIO of the way to
    target, move the stop to entry (breakeven) — exactly once. No trailing
    afterward (QuantCrawler: trailing reduced PnL)."""
    trigger = entry + config.BREAKEVEN_TRIGGER_RATIO * (target - entry)
    moved_to_breakeven = False
    print(f"[{ts()}] Managing position — breakeven trigger at {trigger:.2f} (stop->entry)...")

    while datetime.now().time() < eod_time:
        ib.sleep(2)
        bars = ib.reqHistoricalData(
            contract, endDateTime="", durationStr="600 S",
            barSizeSetting="1 min", whatToShow="TRADES", useRTH=False, formatDate=1,
        )
        if bars and not moved_to_breakeven:
            last_close = bars[-1].close
            if last_close >= trigger:
                try:
                    stop_order.auxPrice = round(entry, 2)
                    ib.placeOrder(contract, stop_order)
                    moved_to_breakeven = True
                    print(f"[{ts()}] Price {last_close:.2f} >= {trigger:.2f} — stop moved to breakeven {entry:.2f}.")
                except Exception as e:
                    print(f"[{ts()}] Breakeven move failed ({e}) — leaving original stop.")
        ib.sleep(30)


# ---------------------------------------------------------------------------
# EOD close
# ---------------------------------------------------------------------------

def eod_close(contract):
    open_trades = [t for t in ib.openTrades() if t.contract.symbol == config.SYMBOL]
    for trade in open_trades:
        ib.cancelOrder(trade.order)
    if open_trades:
        ib.sleep(2)

    positions = ib.positions()
    for pos in positions:
        if pos.contract.symbol == config.SYMBOL and pos.position != 0:
            qty  = abs(int(pos.position))
            side = "SELL" if pos.position > 0 else "BUY"
            ib.placeOrder(contract, MarketOrder(side, qty))
            print(f"[{ts()}] EOD close — cancelled {len(open_trades)} bracket leg(s), {side} {qty} MNQ @ market")
            return
    print(f"[{ts()}] EOD — no open position to close.")


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------

def log_trade(date, orb_high, orb_low, range_pct, skipped,
              entry=None, stop=None, target=None, exit_price=None,
              contracts=0, pnl=None, vix=None, would_skip=""):
    """Append a row. `skipped` is the ACTUAL outcome ("N" traded, or a no-trade
    reason). `would_skip` is a ";"-joined list of filters that fired but were
    overridden in paper mode — the data we use to validate the filters later."""
    file_exists = os.path.isfile(config.TRADE_LOG)
    with open(config.TRADE_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "date", "range_high", "range_low", "range_pct", "skipped",
                "entry", "stop", "target", "exit", "contracts", "pnl_usd", "win", "vix",
                "would_skip"
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
            f"{vix:.1f}" if vix is not None else "",
            would_skip
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
    if config.PAPER_LOG_ONLY:
        print("  PAPER LOG-ONLY MODE — filters log but never skip")
    print(f"{'='*50}\n")

    # Per-day accumulator of filters that fired. In paper mode the bot keeps
    # trading and records these in the 'would_skip' column; in live mode the
    # first failing filter skips immediately (and this stays empty).
    would_skip = []

    def gate(reason):
        """Return True if the bot must STOP for this reason (live mode),
        False to CONTINUE (paper log-only mode — reason recorded)."""
        if config.PAPER_LOG_ONLY:
            would_skip.append(reason)
            print(f"[{ts()}] [PAPER] would skip — {reason}  (continuing)")
            return False
        print(f"[{ts()}] Skipping — {reason}")
        return True

    # --- Filter: Friday ---
    if datetime.now().weekday() == 4:
        if gate("friday"):
            return

    # --- Filter: daily / monthly loss limit ---
    should_halt, halt_reason = check_daily_limits()
    if should_halt:
        if gate(halt_reason):
            log_trade(today, None, None, None, skipped=halt_reason, would_skip=";".join(would_skip))
            return

    # --- Filter: high-impact event day (CPI/NFP/PCE/GDP/FOMC/earnings) ---
    todays_events = events.get_events_today(today)
    if todays_events:
        if gate(f"event_day({','.join(todays_events)})"):
            log_trade(today, None, None, None, skipped=f"event_day({','.join(todays_events)})",
                      would_skip=";".join(would_skip))
            return

    # Fetch market conditions via yfinance (VIX, NQ EMA + days above, gap, ATR)
    conditions = get_market_conditions()
    vix = conditions["vix"] if conditions else None
    atr = conditions["atr"] if conditions else None

    if conditions:
        # --- Filter: VIX too low ---
        if conditions["vix"] < config.VIX_MIN:
            reason = f"vix_too_low ({conditions['vix']:.1f} < {config.VIX_MIN})"
            if gate(reason):
                log_trade(today, None, None, None, skipped=reason, vix=vix, would_skip=";".join(would_skip))
                return

        # --- Filter: VIX too high ---
        if conditions["vix"] > config.VIX_MAX:
            reason = f"vix_too_high ({conditions['vix']:.1f} > {config.VIX_MAX})"
            if gate(reason):
                log_trade(today, None, None, None, skipped=reason, vix=vix, would_skip=";".join(would_skip))
                return

        # --- Filter: EMA trend (below EMA, or not yet confirmed 3+ days above) ---
        if not conditions["nq_above_ema"]:
            if gate("below_ema"):
                log_trade(today, None, None, None, skipped="below_ema", vix=vix, would_skip=";".join(would_skip))
                return
        elif conditions["days_above_ema"] < config.EMA_DAYS_ABOVE_REQUIRED:
            reason = f"ema_whipsaw ({conditions['days_above_ema']}d < {config.EMA_DAYS_ABOVE_REQUIRED}d above)"
            if gate(reason):
                log_trade(today, None, None, None, skipped=reason, vix=vix, would_skip=";".join(would_skip))
                return

        # --- Filter: gap too large ---
        if conditions["gap_pct"] > config.GAP_SKIP_PCT:
            reason = f"gap_too_large ({conditions['gap_pct']*100:.2f}% > {config.GAP_SKIP_PCT*100:.1f}%)"
            if gate(reason):
                log_trade(today, None, None, None, skipped=reason, vix=vix, would_skip=";".join(would_skip))
                return

    # --- Monitor (never skips, even live): historically weak weekday ---
    if datetime.now().weekday() in config.WEAK_WEEKDAYS:
        would_skip.append("weak_weekday")
        print(f"[{ts()}] NOTE: today is a flagged weak weekday — monitoring only.")

    # Get effective risk (reduced automatically if on a losing streak)
    dollar_risk = get_effective_risk()

    # September size reducer (NOT a skip)
    if datetime.now().month == 9:
        dollar_risk *= config.SEPTEMBER_SIZE_MULT
        would_skip.append("september_half_size")
        print(f"[{ts()}] September — halving size to ${dollar_risk:.0f}.")

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

    # --- Filter: range too wide (choppy day) ---
    if not range_is_valid(range_pct):
        if gate("range_too_wide"):
            log_trade(today, orb_high, orb_low, range_pct, skipped="range_too_wide", vix=vix,
                      would_skip=";".join(would_skip))
            ib.disconnect()
            return

    # Watch for breakout — "long" trades; downside_break / no_breakout are
    # genuine signal-absence (no valid long entry), logged as no-trade.
    result = watch_for_breakout(contract, orb_high, orb_low)

    if result in ("no_breakout", "downside_break"):
        log_trade(today, orb_high, orb_low, range_pct, skipped=result, vix=vix,
                  would_skip=";".join(would_skip))
        ib.disconnect()
        return

    direction, entry = result
    stop   = compute_stop(entry, orb_high, orb_low, atr)
    target = orb_high + config.TARGET_RATIO * (orb_high - orb_low)
    qty    = calc_contracts(entry, stop, dollar_risk)

    parent_id, stop_order = place_bracket_order(contract, entry, stop, target, qty)

    # Manage the position to EOD: move stop to breakeven at 0.75x to target.
    # FOMC days force-close early (1:30 PM) to dodge the announcement whipsaw.
    if events.is_fomc(today):
        eod_time = time(config.FOMC_CLOSE_HOUR, config.FOMC_CLOSE_MINUTE)
        print(f"[{ts()}] FOMC day — forcing early close at {eod_time}.")
    else:
        eod_time = time(config.EOD_CLOSE_HOUR, config.EOD_CLOSE_MINUTE)

    manage_position(contract, stop_order, entry, target, eod_time)
    print(f"[{ts()}] EOD reached — closing any open position...")
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
              exit_price=exit_px, contracts=qty, pnl=pnl, vix=vix,
              would_skip=";".join(would_skip))

    ib.disconnect()
    print(f"[{ts()}] Done. See trade_log.csv for record.\n")


if __name__ == "__main__":
    main()
