"""Daily adjusted closes for the semis config tickers plus benchmark ETFs -> results/prices/closes.csv.

Needs Yahoo (yfinance), which the dev container cannot reach -- run via .github/workflows/prices.yml.
relval_backtest.py reads the CSV, so the analysis itself runs anywhere.
"""
import os, glob, time
import pandas as pd
import yfinance as yf

START = os.environ.get("PX_START", "2010-01-01")
ETFS = ["QQQ", "SMH", "SOXX", "SPY", "XLK", "BIL"]
OUT = "results/prices/closes.csv"

def main():
    names = sorted(os.path.basename(p)[:-5] for p in glob.glob("config/*.json"))
    tickers = sorted(set(names) | set(ETFS))
    px = None
    for attempt in range(4):
        try:
            px = yf.download(tickers, start=START, auto_adjust=True, progress=False, threads=True)["Close"]
            break
        except Exception as e:
            print(f"retry {attempt}: {e}", flush=True); time.sleep(5 * (attempt + 1))
    px = px.dropna(axis=1, how="all").sort_index()
    missing = sorted(set(tickers) - set(px.columns))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    px.round(4).to_csv(OUT, index_label="date")
    print(f"{px.shape[1]} tickers, {px.index.min():%Y-%m-%d} .. {px.index.max():%Y-%m-%d}; missing: {missing}")

if __name__ == "__main__":
    main()
