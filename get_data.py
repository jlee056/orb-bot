"""Download the free price data the backtest uses into data/ (git-ignored, ~95 MB).

Run:  python get_data.py

Sources:
  Kaggle  tgtanalytics/nq-futures-1min-bar-2022-2025   NQ 1-minute bars, Dec 2022 to Dec 2025
  GitHub  axb0306/cme-futures-ohlc                     MNQ 1-minute bars, Jan to Apr 2026
The most recent ~60 days come from yfinance and are fetched by the backtest itself.
"""
import os
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


def main():
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
