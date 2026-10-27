"""1993-2010 daily prices for the 1990s stress test: Yahoo for the tech universe and every Nasdaq-100 member since 2006,
Tiingo (TIINGO_KEY) for acquired names Yahoo cannot price. Writes results/history/y1993_adj.csv.gz and tiingo_extra.csv.gz."""
import os, time
import pandas as pd, requests, yfinance as yf
OUT = "results/history"; os.makedirs(OUT, exist_ok=True)
RENAME = {"FB": "META", "PCLN": "BKNG", "RIMM": "BB", "ERTS": "EA", "SYMC": "GEN", "FISV": "FI", "MYL": "VTRS", "JDSU": "VIAV", "KRFT": "KHC"}
tech = list(pd.read_csv("results/universe/tech_adj.csv.gz", index_col=0, nrows=1).columns)
n100 = sorted({RENAME.get(t, t).replace(".", "-") for t in pd.read_csv("results/n100/members_wiki.csv").ticker})
tick = sorted(set(tech) | set(n100) | {"MSI", "NOK", "ERIC", "GLW", "TXN", "HPQ", "IBM", "ORCL", "CSCO", "MSFT", "INTC", "DELL", "AAPL"})
parts = []
for i in range(0, len(tick), 100):
    ch = tick[i:i + 100]
    d = yf.download(ch, start="1993-01-01", end="2010-04-01", auto_adjust=False, progress=False, threads=True, group_by="column")
    if d is None or not len(d): continue
    a = d["Adj Close"]; a = a.to_frame(ch[0]) if isinstance(a, pd.Series) else a
    parts.append(a); print(f"yahoo {min(i + 100, len(tick))}/{len(tick)}", flush=True)
px = pd.concat(parts, axis=1).sort_index().dropna(how="all", axis=1)
px.to_csv(f"{OUT}/y1993_adj.csv.gz", float_format="%.6g", index_label="date")
print(f"yahoo: {px.shape[1]} tickers, {int(px.loc[:'1995-01-31'].notna().any().sum())} priced in Jan 1995", flush=True)
KEY = os.environ.get("TIINGO_KEY", "").strip(); ex = {}
for t in ("XLNX", "MXIM", "YHOO", "JDSU", "ALTR", "LLTC", "BRCM", "NSM", "LSI", "NVLS", "SNDK", "CNXT", "AMCC", "PMCS", "VTSS", "EMC", "SUNW", "PALM"):
    if not KEY: break
    try:
        r = requests.get(f"https://api.tiingo.com/tiingo/daily/{t.lower()}/prices", params=dict(startDate="1993-01-01", endDate="2010-03-31", token=KEY), timeout=60)
        if r.status_code == 200 and r.text.startswith("["):
            d = pd.DataFrame(r.json())
            if len(d): ex[t] = pd.Series(d.adjClose.values, index=pd.to_datetime(d.date.str[:10]))
        print(t, "rows", len(ex.get(t, [])), flush=True)
    except Exception as e:
        print(t, "error", type(e).__name__, flush=True)
    time.sleep(4)
if ex: pd.DataFrame(ex).sort_index().to_csv(f"{OUT}/tiingo_extra.csv.gz", float_format="%.6g", index_label="date")
