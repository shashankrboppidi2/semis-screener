"""Daily Nasdaq new 52-week highs / lows counted from Yahoo -> results/breadth/nasdaq_counts.csv.

A home-grown stand-in for TradingView's INDEX:HIGQ / LOWQ / MAHQ / MALQ feeds (Nasdaq new highs and lows), which
the Nasdaq breadth hedge signal is built on. Universe: today's Nasdaq listing file (nasdaqtrader.com), test issues
dropped, split into common stocks, other issues (warrants, units, rights, preferreds, notes) and ETFs. A new high is a
day whose high is at or above the highest high of the previous 251 sessions (a full year of history required); lows
likewise. Survivorship: delisted issues are missing, so older counts (lows especially) run low.

Needs Yahoo -- run via .github/workflows/breadth.yml.
"""
import io, os, time
import numpy as np
import pandas as pd
import requests
import yfinance as yf

URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OUT = "results/breadth/nasdaq_counts.csv"
START = os.environ.get("BREADTH_START", "2013-01-01")
OTHER = r"Warrant|Unit|Right|Preferred|Depositary Shares|Notes|Debenture|Subordinated"

def universe():
    t = pd.read_csv(io.StringIO(requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"}).text), sep="|")
    t = t[t["Test Issue"].eq("N") & t["Symbol"].notna() & ~t["Symbol"].astype(str).str.startswith("File Creation")]
    name = t["Security Name"].fillna("")
    t["kind"] = np.where(t["ETF"].eq("Y"), "etf", np.where(name.str.contains(OTHER, case=False), "other", "common"))
    t["yahoo"] = t["Symbol"].astype(str).str.replace(".", "-", regex=False)
    return t[["yahoo", "kind"]]

def main():
    u = universe()
    print(u.kind.value_counts().to_dict(), flush=True)
    kinds = dict(zip(u.yahoo, u.kind))
    tick = sorted(kinds)
    acc = None
    for i in range(0, len(tick), 250):
        chunk = tick[i:i + 250]
        d = None
        for attempt in range(3):
            try:
                d = yf.download(chunk, start=START, auto_adjust=False, progress=False, threads=True, group_by="column")
                break
            except Exception as e:
                print("retry", e, flush=True); time.sleep(10)
        if d is None or not len(d): continue
        H, L = d["High"], d["Low"]
        if isinstance(H, pd.Series): H, L = H.to_frame(chunk[0]), L.to_frame(chunk[0])
        prevH = H.shift(1).rolling(251, min_periods=251).max()
        prevL = L.shift(1).rolling(251, min_periods=251).min()
        nh, nl, live = (H >= prevH) & prevH.notna(), (L <= prevL) & prevL.notna(), prevH.notna() & H.notna()
        part = {}
        for k in ("common", "other", "etf"):
            cols = [c for c in H.columns if kinds.get(c) == k]
            part[f"nh_{k}"] = nh[cols].sum(axis=1); part[f"nl_{k}"] = nl[cols].sum(axis=1); part[f"n_{k}"] = live[cols].sum(axis=1)
        part = pd.DataFrame(part)
        acc = part if acc is None else acc.add(part, fill_value=0)
        print(f"{min(i + 250, len(tick))}/{len(tick)}", flush=True)
    acc = acc.sort_index().astype(int)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    acc.to_csv(OUT, index_label="date")
    print(acc.tail(3).to_string())

if __name__ == "__main__":
    main()
