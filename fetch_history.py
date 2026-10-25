"""Pre-2010 daily prices for the tech universe and the plan's ETFs, from Yahoo, to extend the backtests to 2007.

The universe files (results/universe/) start in 2010. This fetches 2006-01 to 2010-03 (a quarter of overlap) for
every universe ticker plus QQQ, SMH, PSQ, SPY, BIL and the 13-week T-bill yield (^IRX, the cash rate before BIL
listed in 2007). Writes results/history/pre2010_{adj,close}.csv.gz. Names Yahoo cannot price (acquired or failed
before today) stay missing, as in the universe itself. Needs Yahoo -- run via .github/workflows/history.yml.
"""
import os
import pandas as pd
import yfinance as yf

OUT, START, END = "results/history", "2006-01-01", "2010-04-01"
ETFS = ["QQQ", "SMH", "PSQ", "SPY", "BIL", "^IRX"]

def main():
    os.makedirs(OUT, exist_ok=True)
    tick = list(pd.read_csv("results/universe/tech_adj.csv.gz", index_col=0, nrows=1).columns) + ETFS
    adj, close = [], []
    for i in range(0, len(tick), 100):
        chunk = tick[i:i + 100]
        d = yf.download(chunk, start=START, end=END, auto_adjust=False, progress=False, threads=True, group_by="column")
        if d is None or not len(d): continue
        a, c = d["Adj Close"], d["Close"]
        if isinstance(a, pd.Series): a, c = a.to_frame(chunk[0]), c.to_frame(chunk[0])
        adj.append(a); close.append(c)
        print(f"yahoo {min(i + 100, len(tick))}/{len(tick)}", flush=True)
    for name, parts in (("adj", adj), ("close", close)):
        x = pd.concat(parts, axis=1).sort_index().dropna(how="all", axis=1)
        x.to_csv(f"{OUT}/pre2010_{name}.csv.gz", float_format="%.6g", index_label="date")
    have = pd.concat(adj, axis=1).loc[:"2007-01-31"].notna().any()
    print(f"{int(have.sum())} of {len(tick)} tickers priced in Jan 2007", flush=True)

if __name__ == "__main__":
    main()
