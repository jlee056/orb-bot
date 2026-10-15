# ORB Bot Logbook

A running record of how this bot was built, tested and changed, including the parts that did not work. Entries are in date order. Every chart and table in the backtest entries can be regenerated with `python get_data.py` then `python make_charts.py`.

## Where things stand (2026-10-12)

- **The bot works end to end up to the order.** It connects, locks the opening range, detects a breakout and sends a bracket order. No order has filled yet, because the broker account has no futures permission (see the 2026-06-26 entry).
- **The strategy was retuned from a backtest of about 800 trading days.** The new settings are a 60-minute opening range, a stop at the range midpoint, a target of half the range, and one filter (price above its 20-day average).
- **The edge is real but small.** After costs the new settings average +0.13 R per trade (R is the amount risked), a 65% win rate and a profit factor of 1.48, and they were profitable in every period tested, including the two years held back from tuning.
- **Account size is the limiting factor.** One MNQ contract risks about $130 to $310 per trade. A 1.5% risk rule needs an account of roughly $15,000.
- **A forward record is running.** Every weekday the bot's decisions are logged automatically from delayed data, with no broker: see the [forward record](FORWARD.md).
- **Three variants run side by side from 2026-10-15** (see the 2026-10-14 entry): the base rules, a 5-minute long-and-short rule that trades almost every day, and the base rules plus shorts. Each has its own paper account. Results: [VARIANTS.md](VARIANTS.md).

| | Trades | Win rate | Avg R | Profit factor | Profit, 1 contract | Max drawdown |
|---|---|---|---|---|---|---|
| Old settings, no filters | 357 | 54% | +0.04 | 1.09 | $2,332 | $2,510 |
| Old settings, all filters | 126 | 53% | +0.04 | 1.15 | $1,200 | $1,039 |
| **New settings** | **216** | **65%** | **+0.13** | **1.48** | **$4,300** | **$985** |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="charts/equity-dark.png">
  <img src="charts/equity.png" alt="Cumulative profit of the new settings versus the old settings, 2023 to 2026, with the drawdown of the new settings below" width="900">
</picture>

---

## 2026-05-14 — First build

- Wrote the first version: a single Python file that connects to Interactive Brokers (IBKR) Trader Workstation, trades MNQ (Micro Nasdaq-100 futures, $2 per point), and logs each day to a CSV.
- Starting rules: 15-minute opening range, long only, target 1.5 times the range, stop at the range low.
- Applied for an IBKR account with futures permission. IBKR was chosen because it offers free paper trading with a Python API for futures.

## 2026-06-17 — Settings changed from published research

No backtest of my own yet. Every change in this entry came from published statistics and other people's backtests.

| Setting | Before | After | Reason given at the time |
|---|---|---|---|
| Opening range | 15 min | 30 min | Published NQ continuation rates favoured 30 minutes |
| Target | 1.5× range | 1.0× range | Median extension after a breakout was under 1× |
| Stop | Range low | Range midpoint | A third-party backtest showed a higher win rate |
| Risk per trade | 2% | 1.5% | Common professional ceiling |
| Loss limits | None | $150 a day, $300 a month | Prop-firm style limits |
| Filters | None | VIX 13 to 35, above 20-day EMA, gap under 0.7% | Each backed by a separate source |

The repository was made public the same day. The benchmark I set out to match was a 74.6% win rate from a third-party NQ backtest. The 2026-10-12 entry shows why that comparison was wrong.

## 2026-06-19 — Paper account and first bugs

- Paper account approved, Trader Workstation installed, API enabled on port 7497.
- **Bug: contract would not resolve.** The June contract had expired the day before and a generic MNQ request returned six candidates. Fixed by requesting contract details, dropping expired ones and taking the nearest expiry.
- **Bug: yfinance warnings.** A newer yfinance returned a different table shape. Fixed the conversions.

## 2026-06-25 — Paper log-only mode, and the first clean run

- **Problem:** the filters kept skipping every day, so the bot never placed a paper trade and there was nothing to learn from.
- **Change:** added `PAPER_LOG_ONLY`. In paper mode every filter writes the reason it would have skipped into a `would_skip` column and the bot trades anyway. Days with no breakout are still real no-trade days.
- Also added: ATR-based stop, a stop-to-breakeven move, an event-day calendar (`events.py`), a September size cut and an early close on FOMC days.
- **First clean end-to-end run.** The range was 1.76% wide, there was no breakout, and the bot logged a `no_breakout` row. This proved the connect, contract, range, polling and logging steps.

## 2026-06-26 — First breakout, rejected by the broker

The first normal-width day broke out and the order path ran for the first time.

- Range locked at 0.65% (high 29372.75, low 29182.00).
- At 10:10 a 5-minute close of 29443.00 triggered the breakout.
- The bot sent a bracket order: buy 1 MNQ, stop 29182, target 29563.50.
- IBKR rejected it. Neither rejection was a code bug.

| Error | Meaning | Cause |
|---|---|---|
| 460 | No trading permission | The paper account inherits permissions from the live account, which was open but unfunded, so futures were never enabled |
| 162 | No historical data | No CME real-time market data subscription for MNQ |

Still untested after this day: a fill, the breakeven move, the end-of-day close and the profit calculation.

## 2026-08-21 — Resumed on a new machine

- Reinstalled everything on a second computer and confirmed the code matched the repository.
- Confirmed the funding rule: IBKR requires $2,000 of net liquidation value before it will open any futures position. That is an account-level floor and is separate from the per-contract margin.
- Newer Trader Workstation builds replace the "localhost only" checkbox with a Trusted IP list. `127.0.0.1` has to be added there.

## 2026-10-12 — Decision: prove the strategy before funding anything

Funding an account only makes sense if the strategy has an edge, and I had never tested that myself. So the plan changed: backtest first, for free, then run on delayed data, and only then think about a funded account.

### First backtest: 49 days

A quick script on the 60 days of 5-minute data that yfinance keeps, with no trading costs.

| | Trades | Win rate | Profit | Max drawdown |
|---|---|---|---|---|
| No filters | 20 | 45% | +$1,058 | $492 |
| All filters | 10 | 40% | -$30 | $456 |

Two things stood out. The win rate was nowhere near 74.6%. And the average loss was $185 against a $75 risk budget, because the ATR stop was about 170 points wide ($339 per contract) and the bot always trades at least one contract. Twenty trades is far too few to tune anything on, so the next job was finding more data.

### More data

| Source | Instrument | Bars | Period | Trading days used |
|---|---|---|---|---|
| Kaggle `tgtanalytics/nq-futures-1min-bar-2022-2025` | NQ | 1-minute | Dec 2022 to Dec 2025 | 722 |
| GitHub `axb0306/cme-futures-ohlc` | MNQ | 1-minute | Jan to Apr 2026 | 46 |
| yfinance `NQ=F` | NQ | 5-minute | Aug to Oct 2026 | 35 |

Checks before trusting it: I worked out each file's timezone and bar labelling from where the volume peaks (the 9:30 open and the 16:00 close). The Kaggle file is Eastern time labelled by bar end. The GitHub file is UTC labelled by bar start. There are two stretches with no data (mid-Dec 2025 to early Feb 2026, and mid-Apr to mid-Aug 2026), shown hatched in the charts.

### Method

- **Engine:** `orb_engine.py` replays each day bar by bar using the same rules as `orb_bot.py`. `backtest.py` reads `config.py`, so the backtest always tests what the bot would actually do.
- **Costs:** 0.5 point of slippage on every market or stop fill, and $1.24 commission per contract per round trip.
- **Conservative fills:** if the stop and the target are both touched inside one bar, the stop is assumed to have been hit first.
- **No lookahead:** the EMA, ATR and VIX values used for a day come from the previous session.
- **Held-back test:** settings were tuned on 2023 and 2024 only. 2025 and 2026 were not looked at until the candidates were chosen.

### Finding 1: the old settings made almost nothing

Over 357 trades the bot as configured averaged +0.04 R after costs, with a $2,510 drawdown against $2,332 of profit. With all filters on it was no better per trade. It was also risking $170 to $360 per trade on average, depending on the year, against a $75 budget.

### Finding 2: the 74.6% benchmark was never comparable

That figure comes from a backtest using a 15-minute range, a target of half the range, a stop on the far side of the range capped at 50 points, and no trading costs. A small target and a wide stop give a high win rate by construction. Its average win was smaller than its average loss. This bot used a 30-minute range, a full-range target and an ATR stop, so its win rate could never have matched.

### Finding 3: the breakout signal is real, but small

Tested 672 combinations of range length, stop, target, breakeven and direction on 2023 to 2024. Only about 1% looked statistically meaningful, which is what chance alone would give. 82% were slightly positive, but those were bull-market years and the bot only buys.

The useful test was against a benchmark that buys every day at the end of the range, with the same stop and target, whether or not there is a breakout:

| Setup | Breakout entries (avg R) | Buy every day (avg R) |
|---|---|---|
| 30-minute range (the old bot) | +0.06 | +0.01 |
| 60-minute range | +0.09 | +0.05 |
| 5-minute range | +0.17 | -0.03 |

The breakout beat blind buying in every setup, so the signal carries information. Short trades added nothing, so the bot stays long only. Published work points the same way: an independent replication of the best-known ORB paper found about +0.13 R before costs on NQ and roughly zero after them.

### Finding 4: one filter helps, four do not

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="charts/filters-dark.png">
  <img src="charts/filters.png" alt="Average R of trades each filter would block versus keep. Only the 20-day EMA filter blocks trades that lose on average." width="900">
</picture>

- **Trend filter (close above the 20-day EMA): keep.** The trades it blocks lose money on average (-0.06 R). It improved all three setups above, both in the tuning years and in the held-back years.
- **Gap and wide-range filters: remove.** The trades they block were the best ones (+0.37 R and +0.36 R).
- **Low-VIX filter: remove.** The blocked trades were weaker than average but still profitable.
- **Friday skip: remove.** No difference on these settings (+0.13 R either way), and the sign flipped between the tuning years and the held-back years.
- Requiring three closes above the EMA instead of one made no reliable difference, so it is now one.

### Finding 5: the edge is a plateau

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="charts/robustness-dark.png">
  <img src="charts/robustness.png" alt="Heatmap of average R for 25 combinations of opening range length and profit target. All are positive." width="760">
</picture>

All 25 neighbouring settings are positive. Ranges of 45 to 75 minutes with targets of 0.5 to 1.0 times the range all land between +0.09 and +0.15 R. I chose 60 minutes and 0.5× from the middle of that area for its higher win rate and smaller drawdown, and did not tune further. The 60-minute, 1.0× cell scores slightly higher, but the difference is well inside the noise.

### The new settings

| Setting | Before | After |
|---|---|---|
| Opening range | 30 min | 60 min |
| Entry window | 10:00 to 11:00 | 10:30 to 12:00 |
| Stop | Entry minus 0.4 × ATR, floored at the range low | Range midpoint |
| Target | Range high + 1.0 × range | Range high + 0.5 × range |
| Breakeven move | At 75% of the way to target | Off |
| Filters enforced | EMA (3 days), VIX 13 to 35, gap, range, Friday | EMA (1 day), VIX above 35 |
| Monthly loss cap | Sum of losing trades | Net profit and loss |
| Oversized trades | Always trade 1 contract | Skip in live mode if 1 contract exceeds the budget |

### Results by period

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="charts/periods-dark.png">
  <img src="charts/periods.png" alt="Average R per trade by period for old and new settings. The new settings are positive in all five periods." width="900">
</picture>

| Period | Trades | Win rate | Avg R | Profit factor | Profit, 1 contract | Max drawdown |
|---|---|---|---|---|---|---|
| 2023 to 2024 (tuned on) | 140 | 66% | +0.13 | 1.42 | $2,099 | $703 |
| 2025 to 2026 (held back) | 76 | 63% | +0.14 | 1.57 | $2,201 | $985 |
| All | 216 | 65% | +0.13 | 1.48 | $4,300 | $985 |

Stress tests on the new settings:

| Test | Avg R |
|---|---|
| As tested (0.5 pt slippage) | +0.13 |
| Double slippage (1.0 pt) | +0.12 |
| Four times slippage (2.0 pt) | +0.09 |
| Bootstrap 95% range for the true average | +0.02 to +0.23 |

In the bootstrap, fewer than 1% of resamples had an average of zero or below.

### How the trades end

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="charts/exits-dark.png">
  <img src="charts/exits.png" alt="126 trades hit the target, 28 closed at end of day, 62 hit the stop." width="900">
</picture>

A win at the target earns about 0.7 R and a stop costs a full 1 R, so the strategy needs its roughly two-to-one win ratio to stay ahead. The longest losing streak in the data was six trades.

### What a year looks like

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="charts/montecarlo-dark.png">
  <img src="charts/montecarlo.png" alt="Distribution of simulated one-year profit for one contract. Median 1,409 dollars; 8 percent of years lose money." width="900">
</picture>

Resampling the 216 trades into 20,000 simulated years of 70 trades: the median year makes about $1,400 per contract, about 8% of years lose money, and a drawdown of $1,300 is within the normal range.

### Finding 6: the account-size problem

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="charts/risk-dark.png">
  <img src="charts/risk.png" alt="Left: histogram of dollars risked per trade with one contract, mostly above the 75 dollar budget. Right: share of signals tradable by account size at 1.5 percent risk." width="900">
</picture>

One contract risks a median of $133 per trade over the whole period, and about $200 at 2026 price levels. With a 1.5% risk rule:

| Account size | Signals where 1 contract fits the budget |
|---|---|
| $5,000 | 6% |
| $10,000 | 65% |
| $15,000 | 92% |
| $25,000 | 100% |

At $5,000 the choices are to accept about 4% risk per trade, or not to trade MNQ with real money. In live mode the bot now skips trades that exceed the budget. In paper mode it trades one contract and records `over_risk`.

### Code changes made today

- `config.py`: new settings above; `FILTER_FRIDAY`, `FILTER_GAP`, `FILTER_RANGE` switches (off); `MAX_RISK_OVERSHOOT`.
- `orb_bot.py`:
  - Loss caps now use net profit and loss. Before, the cap summed losing trades and ignored wins, so one or two losses stopped the bot for the month.
  - EMA and ATR now use completed sessions only, matching the backtest.
  - The opening range is taken from bars timestamped inside the range window, where before it was the last N bars at the moment of the request.
  - Filters that are switched off still write an `off:` note to the log.
- New files: `orb_engine.py`, `backtest.py`, `make_charts.py`, `get_data.py`.

### Limits of this result

- **It could still be partly luck.** About 800 setups were examined in total. The held-back years and the plateau reduce that risk; they do not remove it.
- **Three and a half years, mostly rising markets.** There is no long bear market in the data, and the bot only buys.
- **Not modelled:** event-day skips (the `events.py` calendar is mostly empty), the losing-streak size cut, the September size cut.
- **Broker path untested.** The changes to the IBKR code could not be run against Trader Workstation without a funded account. The pieces that do not need a connection were checked.
- **Data quality:** the Kaggle and GitHub files are community datasets. The Kaggle file's contract-roll adjustment is undocumented. Intraday ranges are unaffected by that; the overnight gap and daily ATR could be slightly off on roll days.

## 2026-10-12 — Forward run on delayed data

The backtest says what would have happened. The forward run records what does happen, starting from the day the settings were frozen, with no chance to adjust anything afterwards.

**How it works**

- Two jobs run on GitHub's servers every weekday (GitHub Actions), so no computer needs to be on.
- **After the close:** `forward_run.py` downloads the day's NQ futures bars from Yahoo, replays the session with the same engine as the backtest, and appends one row to [`forward/forward_log.csv`](../forward/forward_log.csv). `forward_report.py` then rebuilds the [forward record](FORWARD.md) page and the job commits both.
- **In the morning:** `forward_alert.py` watches the same data from 10:30 to 12:00 ET and sends one phone notification: a breakout with entry, stop and target, or "no trade today" with the reason.
- No orders are placed and no broker is involved.

**About the data delay**

- Yahoo's NQ futures prices run about 10 minutes late (measured: 10.6 minutes).
- The after-close log replays a finished session, so the delay does not affect it.
- The morning alert arrives about 10 minutes after the real breakout. It is a heads-up, not a signal to trade on.
- Yahoo keeps 7 days of 1-minute bars and 60 days of 5-minute bars. A missed run is filled in by the next one, at 1-minute detail if it is within 7 days.

**Rules that keep the record honest**

- The log starts on 2026-10-12 and is append-only. A logged day is never recalculated.
- Every row stores a hash of the strategy settings. If the settings change, the hash changes, and the old rows stay as they were.
- Every trading day gets a row, including days with no trade.
- Nothing will be tuned from this record until it has at least 20 signals.

**Checks before switching it on**

- Replaying 2026-09-28 to 2026-10-09 gave the same four trades, entries and exits as the backtest for those dates.
- Running the log twice adds no rows the second time.
- The alert, stepped minute by minute through last week, decided the same way as the log on all five days.

## 2026-10-12 — Paper trading with real order handling (Alpaca, QQQ)

The forward log records decisions but sends no orders. The next step up is a broker's practice account, where orders are really submitted, filled and cancelled, with practice money.

**Choosing where**

| Option | Result |
|---|---|
| IBKR paper | Needs the $2,000 funded account (the 2026-06-26 problem) |
| MetaTrader 5 demo | US-regulated MT5 brokers leave index CFDs out for US residents, demos included |
| Tradovate demo | Real MNQ, but 14 days only |
| TopstepX practice | Needs a paid account and an API subscription |
| **Alpaca paper** | Free, email signup, no funding, official Python API, free real-time IEX prices |

Alpaca has no futures, so the bot trades **QQQ**, the Nasdaq-100 fund. It follows the same index as MNQ, but it is a different instrument: it only trades in regular hours, and its free price feed comes from one exchange (IEX).

**How it works**

- `alpaca_bot.py entry` watches QQQ from 10:30 to 12:00 ET and, on a breakout, sends one bracket order: market entry, stop at the range midpoint, limit target at half the range above the high.
- `alpaca_bot.py close` flattens anything still open 10 minutes before the close and writes the day to [`paper/alpaca_trades.csv`](../paper/alpaca_trades.csv). The [paper record](PAPER.md) page is rebuilt from that.
- The decision to trade comes from `orb_engine.simulate`, the same function the backtest and the forward log use.
- Each day's row also stores what the engine expected (`sim_outcome`, `sim_R`), so the broker's fills can be checked against it. A day where the engine traded and no order went out is logged as `missed`.

**Sizing, two ways**

One MNQ contract was too big for the risk budget. Shares fix that: the bot buys enough QQQ to risk about $75, which is 30 to 50 shares, roughly $25,000 to $35,000 of stock. That fits the $100,000 practice account but not a real $5,000 one. So every trade is recorded twice: as placed, and as it would have been with $5,000 of cash and no borrowing (about 6 shares, around $10 at risk).

**Safety**

- `alpaca_io.py` always builds the trading client with `paper=True`. There is no live setting to flip.
- One order per day, enforced by a dated order ID that Alpaca rejects if repeated, and by checking for an existing position first.
- Half days are skipped.

**Checks so far (no account yet, so a stand-in broker and Yahoo prices)**

Replaying the week of 2026-10-05:

| Date | Bot | Shares | Result | Engine expected |
|---|---|---|---|---|
| Oct 5 | Order at 10:59 | 30 | Target, +0.97 R | Target, +0.95 R |
| Oct 6 | Order at 10:54 | 48 | Stop, -1.00 R | Stop, -1.01 R |
| Oct 7 | Order at 11:14 | 44 | Target, +0.95 R | Target, +0.94 R |
| Oct 8 | No breakout | | | No breakout |
| Oct 9 | No breakout | | | No breakout |

These are the same three trading days and the same outcomes as NQ futures that week.

**An unflattering first number**

The only QQQ history available without an account is 60 days of 5-minute bars. On those, the frozen settings made 14 trades, won half, and averaged -0.14 R. NQ futures over roughly the same weeks made 8 trades and averaged +0.27 R. Fourteen trades settle nothing either way, but it is a reminder that QQQ is not NQ. The multi-year QQQ backtest (`python get_data.py --qqq`, then `python backtest.py --qqq`) needs the Alpaca keys for data and is the next thing to run.

**Known limits**

- Alpaca's paper fills do not model slippage or market impact, so results will look a little better than real trading.
- Not yet run against the real Alpaca API. Everything above used the stand-in broker.

## 2026-10-12 — First live day: account connected, and a missed morning

**Connected and checked**

- Alpaca paper account connected: active, $100,000 of practice money.
- One-share live test: the bracket order was accepted, the buy filled, the stop and target became active, the flatten closed it, and the account ended flat. A second order with the same ID was refused, which is the one-order-per-day guard working. The fill took 100 seconds, which is slow. It bought 1 share at $747.83 and sold at $747.86, a 3-cent profit, leaving the account at $100,000.03. This was a connection test with its own order ID. It is listed on the [paper record](PAPER.md) page under "Other orders in this account", together with the first test order that was cancelled before filling, and it is kept out of the strategy's win rate and profit figures.
- Multi-year QQQ backtest with the frozen settings, on Alpaca's consolidated 1-minute data:

| Year | Trades | Win rate | Avg R | Profit at $75 risk |
|---|---|---|---|---|
| 2020 | 59 | 59% | +0.02 | $94 |
| 2021 | 67 | 60% | -0.02 | -$82 |
| 2022 | 33 | 76% | +0.29 | $714 |
| 2023 | 74 | 68% | +0.18 | $976 |
| 2024 | 74 | 65% | +0.10 | $516 |
| 2025 | 73 | 58% | +0.05 | $258 |
| 2026 (to Oct 9) | 52 | 60% | +0.05 | $204 |
| All | 432 | 63% | +0.08 | $2,680 |

Positive in six of seven years, with a profit factor of 1.25 and a largest drawdown of $684. 2020 to 2022 were never used to choose the settings, so this is a real out-of-sample check. The edge is smaller than on NQ futures (+0.13 R), and at a $5,000 cash size the dollar amounts are about one sixth of these.

**What went wrong**

GitHub did not start any of the scheduled jobs. The morning alert and the paper-entry job were both due at 9:45 AM ET and never ran; the repository's history shows no scheduled run at all. GitHub's scheduler is documented to start jobs late or drop them under load, and these workflows were new and had been edited several times that morning. By the time it was noticed, the 10:30 to 12:00 entry window had passed.

Replaying the morning afterwards: QQQ had no breakout, so no trade was missed, only the "no trade" notification.

**What changed so it cannot depend on one scheduler again**

- `watchdog.py` runs on an always-on PC through Windows Task Scheduler. Every 15 minutes through the morning (and at intervals before the close and in the evening) it checks whether today's job has started and starts it if not.
- Each workflow now has two or three start times.
- Starting a job twice is harmless. Notifications are send-once, checked against the alert topic's recent history. The entry job exits if today's order ID already exists at the broker. Every checkout uses the newest commit, so a later start sees the row an earlier one logged.

**A difference to watch**

The live bot reads Alpaca's free IEX feed, which is one exchange. The backtest used consolidated data. The opening range can differ by a few cents between the two, so a live day can trigger or size slightly differently from the backtest. Each logged row stores what the engine expected on the same data the bot saw.

## 2026-10-12 — News-day calendar filled in and tested

`events.py` had only eight Fed dates in it. It now holds 532 scheduled-news days from 2020 to 2027.

| What | Source |
|---|---|
| CPI, PPI, jobs report, GDP, PCE release days, 2020 to 2026 | ALFRED (St. Louis Fed) release-date archive; the 2026 CPI, PPI and jobs dates match the BLS schedule exactly |
| Upcoming releases to the end of 2026 | BLS and BEA schedule pages |
| Fed decision days, 2021 to 2027 | Federal Reserve calendar |
| Mag-7 earnings reports | yfinance. Reports come after the close, so the morning tagged is the next trading day. Future dates are estimates. |

**Do news days matter for this strategy?** Average result per trade, frozen settings:

| Day type | QQQ 2020 to 2026 | NQ 2023 to 2026 |
|---|---|---|
| No scheduled news | +0.08 R (312 trades) | +0.16 R (153) |
| Any scheduled news | +0.09 R (120) | +0.06 R (63) |
| CPI | +0.03 R (25) | +0.10 R (15) |
| PPI | -0.03 R (22) | -0.03 R (13) |
| Jobs report | +0.24 R (20) | +0.34 R (7) |
| PCE | +0.38 R (17) | +0.14 R (11) |
| GDP | +0.01 R (22) | -0.20 R (10) |
| Mag-7 earnings morning | +0.28 R (25) | +0.24 R (12) |
| **Fed decision day** | **-0.60 R (8)** | **-0.76 R (6)** |

- **Morning reports and earnings: no reason to skip.** On QQQ, news days did as well as quiet days. The individual categories have 7 to 25 trades each, so their differences are noise.
- **Fed decision days stand out.** Two wins in eight QQQ trades, one in six on NQ. Every one of those trades was already over before 1:30 PM, so the old "close early on Fed days" rule would have changed nothing.
- **How much to trust the Fed result:** it is eight trades, the NQ trades are mostly the same days as the QQQ ones, and it is one of seven categories looked at. There is a plausible reason for it (markets often stall or reverse on the morning of a Fed announcement), but this is a small sample.

**What changed:** the bot no longer skips news days by default (`FILTER_EVENT_DAYS = False`; they are still logged). A separate skip for Fed decision days is under review. It would be a change to the frozen settings, so it has not been made.

## 2026-10-14 — Three variants side by side

**Why.** The base rules made no trade on the first three days (Oct 12 no breakout, Oct 13 no breakout, Oct 14 broke down first). On QQQ they trade about 64 times a year. Telling an average of +0.1 R from zero takes about 312 trades (95% confidence with the spread of results the backtest shows: n = (1.96 × 0.9 / 0.1)²), which is about five years at that rate. The money is practice money, so the plan is to collect data faster without touching the frozen rules: two more versions run next to the base, each in its own Alpaca paper account.

**What the research said**

- This logbook's own backtest (2026-10-12): the 5-minute range had the strongest breakout signal of any range tested (+0.17 R against −0.03 R for buying every day), and short trades added nothing on the 60-minute rules.
- Zarattini & Aziz (2023), "Can Day Trading Really Be Profitable?" (SSRN 4416622): trade QQQ in the direction of the first 5-minute candle, long or short, from the 9:35 open, with the stop at the candle's far side and a 10 R target or the close. About 250 trades a year, no costs beyond commission.
- Their follow-up (Zarattini, Barbon & Aziz, SSRN 4729284, on "stocks in play"): the edge falls off fast with longer ranges. Sharpe 2.81 at 5 minutes, 1.43 at 15, 0.21 at 30, 0.40 at 60.
- An independent replication on QQQ (github.com/giovannibrusco/zarattini-2023-orb-qqq) matched the paper, then found the edge breaks even at about 2.2 cents of slippage per share. So the 5-minute rule is worth testing, not worth trusting.
- Alpaca allows three paper accounts per login, each with its own keys. One account cannot hold a long and a short of the same symbol, so each variant gets its own account.

**The variants** (rules frozen today; first session 2026-10-15)

| Variant | Settings hash (QQQ / NQ) | Rules |
|---|---|---|
| `base` | `e0a01dbd` / `00c5314f` | Unchanged: 60-minute range, long only, stop at the midpoint, target half the range, EMA filter |
| `orb5` | `baa9b9f8` / `961ec940` | First 5-minute candle up: buy; down: sell short; flat: no trade. Market entry at 9:35. Stop at the candle's low (long) or high (short). Target 10 R, otherwise closed at 15:50. No EMA filter |
| `both60` | `f050443e` / `09fbe296` | Base rules plus a short on a downside break. Longs need QQQ above its 20-day average, shorts need it below. Only the first break counts |

**Backtest on QQQ, 2020-01 to 2026-10-09** (Alpaca 1-minute data, $75 risk per trade, 2 cents slippage, `python backtest.py --qqq --variant NAME`)

| Variant | Trades | Per year | Win rate | Avg R | Longs | Shorts | Profit at $75 risk | Max drawdown |
|---|---|---|---|---|---|---|---|---|
| base | 432 | 64 | 63% | +0.084 | +0.084 (432) | none | $2,680 | $684 |
| orb5 | 1,624 | 242 | 25% | +0.081 | +0.088 (818) | +0.073 (806) | $9,819 | $3,411 |
| both60 | 633 | 94 | 62% | +0.053 | +0.084 (432) | −0.012 (201) | $2,493 | $556 |

Slippage stress test:

| Variant | 2 cents | 3 cents | 5 cents |
|---|---|---|---|
| orb5 | +0.081 R | +0.055 R | +0.007 R |
| both60 | +0.053 R | +0.044 R | |

- **orb5** is the data engine: almost one trade every day. It wins only a quarter of the time and lives on the few days that run to the close. Its edge is gone at 5 cents of slippage, which matches the outside replication. Its drawdowns are deep (about 45 R in the backtest).
- **both60** confirms the old finding on a second instrument: the shorts lose slightly (−0.01 R over 201 trades). It runs anyway because it tests that claim live with no extra cost, and every short it takes is a data point on the question.
- The base result is identical to the 2026-10-12 entry (432 trades, +0.084 R), which checks that none of today's code changes moved it.

**Rules for judging, fixed before the first trade**

- Review each variant at 50, 100 and 312 trades. Nothing is retuned from the live record. A change of rules is a new variant with a new settings hash.
- Success means an average above zero at 312 trades.
- A variant stops early if its average is −0.15 R or worse after 100 trades, or if its drawdown passes 1.5 times the largest drawdown in its backtest.

**How it works**

- `variants.py` holds the three variants as small sets of changes to the base settings. `python variants.py --check` fails if the base settings hash moves, and every job runs it first.
- `orb_engine.py` gained two things: a "candle" entry mode and a per-direction trend filter (`f_ema_dir`). New settings fields are left out of the hash while they hold their default, so the base hash did not change.
- `alpaca_bot.py --variant NAME` runs any variant: its own order ids (`orb5-2026-10-15`), log file (`paper/alpaca_trades_orb5.csv`) and notification titles (`ORB QQQ [orb5] ...`). It can now sell short, after checking the account allows it and QQQ is easy to borrow.
- The GitHub jobs run one job per variant, each with only its own account's keys. The after-close job checks each variant's row separately before anything is committed.
- `forward_run.py` logs all three on the NQ forward record, each to its own file. [VARIANTS.md](VARIANTS.md) shows the three side by side and is rebuilt after every close.
- The watchdog on the always-on PC now starts at 9:05, so a skipped GitHub start can still be recovered before the 9:35 entry. It also expects a message from each variant.

**A difference to watch: orb5's entry is about a minute late.** The backtest buys at the 9:35 bar's open. The live bot can only see that bar once it has finished, so its order goes out around 9:36:05. It sizes from the latest price and skips the trade if price is already through the stop. Replaying Oct 5 to 9, the fills differed from the engine's by −0.29 R per trade on average, mostly from one day (Oct 9: engine +1.62 R, fill +0.37 R). The "fill gap" column on [VARIANTS.md](VARIANTS.md) tracks this every day.

## Next

1. Confirm the first full scheduled day (alert, entry, close, log) runs without help, for all three variants.
2. Let the records run. Review each variant at 50, 100 and 312 trades against the rules above.
3. Watch orb5's fill gap. If it stays well below zero, the one-minute delay is eating the edge.
4. Decide whether to skip Fed decision days (next one: 2026-10-28).
5. Revisit funding only if the records hold up.

## Data and sources

- Per-trade and summary tables: [`docs/data/`](data/)
- Kaggle dataset: https://www.kaggle.com/datasets/tgtanalytics/nq-futures-1min-bar-2022-2025
- GitHub dataset: https://github.com/axb0306/cme-futures-ohlc
- Third-party 74.6% benchmark: https://tradethatswing.com/opening-range-breakout-strategy-up-400-this-year
- Replication of the ORB paper net of costs: https://www.mql5.com/en/blogs/post/776235
- Zarattini & Aziz (2023), 5-minute ORB on QQQ: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622
- Zarattini, Barbon & Aziz, ORB on stocks in play: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- Independent QQQ replication with slippage: https://github.com/giovannibrusco/zarattini-2023-orb-qqq
- Alpaca paper accounts and short selling: https://docs.alpaca.markets/us/docs/paper-trading, https://docs.alpaca.markets/us/docs/margin-and-short-selling

Nothing here is investment advice. Futures trading can lose more than the amount deposited.
