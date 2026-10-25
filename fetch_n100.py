"""Point-in-time Nasdaq-100 membership (quarterly) and prices for every member since 2006, for the momentum test.

Membership: the Wikipedia "Nasdaq-100" article as it stood at each quarter end (MediaWiki revision history), saved raw
so the parsing can be checked; cross-checked against the n100tickers package (2016 onwards). Prices: Yahoo adjusted
closes for the union of members from 2006 (names Yahoo cannot price are listed as missing). Writes results/n100/.
Needs Wikipedia and Yahoo -- run via .github/workflows/n100.yml.
"""
import gzip, json, os, re, time
import pandas as pd
import requests

OUT = "results/n100"
API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "semis-screener research (github.com/shashankrboppidi2/semis-screener)"}
TICK = re.compile(r"\{\{\s*(?:NASDAQ|Nasdaq|nasdaq)\s*\|\s*([A-Z.]{1,6})\s*\}\}")

def revision(at):
    p = dict(action="query", prop="revisions", titles="Nasdaq-100", redirects=1, rvlimit=1, rvdir="older",
             rvstart=at, rvprop="content|timestamp|ids", rvslots="main", format="json", formatversion=2)
    for attempt in range(4):
        try:
            j = requests.get(API, params=p, headers=UA, timeout=60).json()
            rv = j["query"]["pages"][0]["revisions"][0]
            return rv["timestamp"], rv["slots"]["main"]["content"]
        except Exception as e:
            print("  retry", at, str(e)[:80], flush=True); time.sleep(5)
    return None, ""

def main():
    os.makedirs(OUT, exist_ok=True)
    qs = pd.date_range("2006-12-31", pd.Timestamp.today(), freq="QE")
    raw, rows = {}, []
    for q in qs:
        ts, text = revision(q.strftime("%Y-%m-%dT23:59:59Z"))
        raw[str(q.date())] = dict(ts=ts, text=text)
        tick = sorted(set(TICK.findall(text)))
        rows += [dict(quarter=str(q.date()), revision=ts, ticker=t) for t in tick]
        print(q.date(), ts, len(tick), flush=True); time.sleep(1)
    with gzip.open(f"{OUT}/wiki_revisions.json.gz", "wt") as f: json.dump(raw, f)
    mem = pd.DataFrame(rows); mem.to_csv(f"{OUT}/members_wiki.csv", index=False)
    try:                                                              # cross-check, 2016 onwards
        from n100tickers import tickers_as_of
        cx = [dict(quarter=str(q.date()), ticker=t) for q in qs if q.year >= 2016 for t in sorted(tickers_as_of(q.year, q.month, q.day))]
        pd.DataFrame(cx).to_csv(f"{OUT}/members_n100tickers.csv", index=False)
    except Exception as e:
        print("n100tickers unavailable:", str(e)[:120], flush=True)
    import yfinance as yf
    allt = sorted(set(mem.ticker))
    if os.path.exists(f"{OUT}/members_n100tickers.csv"):
        allt = sorted(set(allt) | set(pd.read_csv(f"{OUT}/members_n100tickers.csv").ticker))
    parts = []
    for i in range(0, len(allt), 100):
        ch = [t.replace(".", "-") for t in allt[i:i + 100]]
        d = yf.download(ch, start="2006-01-01", auto_adjust=False, progress=False, threads=True, group_by="column")
        if d is None or not len(d): continue
        a = d["Adj Close"]; a = a.to_frame(ch[0]) if isinstance(a, pd.Series) else a
        parts.append(a)
    px = pd.concat(parts, axis=1).sort_index().dropna(how="all", axis=1)
    px.to_csv(f"{OUT}/adj.csv.gz", float_format="%.6g", index_label="date")
    miss = sorted(set(t.replace(".", "-") for t in allt) - set(px.columns))
    pd.Series(miss, name="ticker").to_csv(f"{OUT}/missing_prices.csv", index=False)
    print(f"{len(allt)} members ever, {px.shape[1]} priced, {len(miss)} missing", flush=True)

if __name__ == "__main__":
    main()
