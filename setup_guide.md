# ORB Bot Setup Guide

## Step 1 — Open an IBKR Account

1. Go to **interactivebrokers.com** → click "Open Account"
2. Select **Individual** account
3. When asked about trading permissions, add **Futures**
4. Takes 1–3 business days to get approved

## Step 2 — Activate Paper Trading

1. Log in to Client Portal (interactivebrokers.com/portal)
2. Go to **Settings → Paper Trading** → click "Create Paper Trading Account"
3. Your paper account starts with $1,000,000 by default — ignore that, the bot uses $5,000 for position sizing

## Step 3 — Download TWS

1. Go to **interactivebrokers.com/en/trading/tws.php**
2. Download **Trader Workstation (TWS)** — the full version, not IBKR Mobile
3. Install it

## Step 4 — Enable the API in TWS

1. Open TWS → log in to your **paper** account (switch at login screen)
2. Go to **Edit → Global Configuration → API → Settings**
3. Check: **Enable ActiveX and Socket Clients**
4. Set **Socket port** to `7497`
5. Check: **Allow connections from localhost only**
6. Uncheck: **Read-Only API** (bot needs to place orders)
7. Click **OK** and restart TWS

## Step 5 — Install Python Dependencies

Open a terminal in `C:\orb-bot\` and run:

```
pip install -r requirements.txt
```

## Step 6 — Run the Bot

**Every trading morning:**

1. Open TWS
2. Log in to your **paper** account (not live)
3. Open a terminal in `C:\orb-bot\`
4. Run:

```
python orb_bot.py
```

The bot will wait until 9:45 AM ET, lock the opening range, and handle everything automatically.

## Going Live (When Ready)

1. Open `config.py`
2. Change `TWS_PORT = 7497` to `TWS_PORT = 7496`
3. Fund your real IBKR account (recommended minimum: $2,000–$5,000)
4. Log into your **live** account in TWS before running the bot

---

## Troubleshooting

| Error | Fix |
|---|---|
| `Connection refused` | TWS isn't running or API isn't enabled |
| `No contract found` | Market is closed or data permissions missing |
| `No bar data returned` | Market not open yet — run after 9:30 AM ET |
| Bot places no trade | Range was too wide, or no breakout before 11 AM (normal) |
