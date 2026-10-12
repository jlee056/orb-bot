"""Download the free price data the backtest uses into data/ (git-ignored, ~95 MB).

Run:  python get_data.py          NQ/MNQ futures data (no account needed)
      python get_data.py --qqq    QQQ 1-minute history from Alpaca (needs the paper API keys)

Sources:
  Kaggle  tgtanalytics/nq-futures-1min-bar-2022-2025   NQ 1-minute bars, Dec 2022 to Dec 2025
  GitHub  axb0306/cme-futures-ohlc                     MNQ 1-minute bars, Jan to Apr 2026
The most recent ~60 days come from yfinance and are fetched by the backtest itself.
"""
import os
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

KAGGLE_URL = "https://www.kaggle.com/api/v1/datasets/download/tgtanalytics/nq-futures-1min-bar-2022-2025"
GITHUB_URL = ("https://raw.githubusercontent.com/axb0306/cme-futures-ohlc/HEAD/"
              "MNQ/MNQ_1min_20260120_20260415.csv")


def fetch(url, dest):
    if os.path.isfile(dest):
        print("already have", os.path.relpath(dest, HERE))
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print("downloading", url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def qqq(first_year=2020):
    """1-minute QQQ bars from Alpaca, one CSV per year in data/alpaca/. Needs the paper API keys."""
    import pandas as pd

    import alpaca_io as A
    if not A.have_keys():
        print("Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env first.")
        return
    src = A.AlpacaData()
    os.makedirs(os.path.join(DATA, "alpaca"), exist_ok=True)
    now = pd.Timestamp.now(tz=A.TZ).tz_localize(None)
    for year in range(first_year, now.year + 1):
        dest = os.path.join(DATA, "alpaca", f"QQQ_1min_{year}.csv")
        if os.path.isfile(dest) and year < now.year:
            print("already have", os.path.relpath(dest, HERE))
            continue
        end = min(pd.Timestamp(year + 1, 1, 1), now - pd.Timedelta(minutes=20))
        try:
            df, feed = src.bars(1, pd.Timestamp(year, 1, 1), end, feed="sip"), "sip"
        except Exception as e:   # plan does not include consolidated history: fall back to IEX
            print(f"  {year}: consolidated feed refused ({str(e)[:80]}); using IEX")
            df, feed = src.bars(1, pd.Timestamp(year, 1, 1), end), "iex"
        if len(df):
            df.to_csv(dest)
        print(f"{year}: {len(df):,} bars ({feed})")
    print("done. Next: python backtest.py --qqq")


def main():
    if "--qqq" in sys.argv:
        return qqq()
    zpath = os.path.join(DATA, "kaggle", "nq.zip")
    fetch(KAGGLE_URL, zpath)
    csv = os.path.join(DATA, "kaggle", "Dataset_NQ_1min_2022_2025.csv")
    if not os.path.isfile(csv):
        with zipfile.ZipFile(zpath) as z:
            z.extract("Dataset_NQ_1min_2022_2025.csv", os.path.join(DATA, "kaggle"))
    fetch(GITHUB_URL, os.path.join(DATA, "github", "MNQ_1min_20260120_20260415.csv"))
    print("done. Next: python backtest.py")


if __name__ == "__main__":
    main()
