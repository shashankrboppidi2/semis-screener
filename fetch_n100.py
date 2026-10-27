"""Point-in-time Nasdaq-100 membership (quarterly) and prices for every member since 2006, for the momentum test.

Membership: the Components section of the Wikipedia "Nasdaq-100" article as it stood at each quarter end (MediaWiki
revision history), saved raw so the parsing can be checked; a quarter whose fetch fails carries the previous list; cross-checked against the n100tickers package (2016 onwards). Prices: Yahoo adjusted
closes for the union of members from 2006 (names Yahoo cannot price are listed as missing). Writes results/n100/.
Needs Wikipedia and Yahoo -- run via .github/workflows/n100.yml.
"""
import gzip, json, os, re, time
import pandas as pd
import requests

OUT = "results/n100"
API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "semis-screener research (github.com/shashankrboppidi2/semis-screener)"}
LIST = re.compile(r"^[*#][^\n]*?\(\s*(?:\[\[)?([A-Z][A-Z.]{0,5})(?:\]\])?\s*\)", re.M)
CELL = re.compile(r"^\|(?!-)(.*)$", re.M)
RENAME = {"FB": "META", "PCLN": "BKNG", "RIMM": "BB", "ERTS": "EA", "SYMC": "GEN", "FISV": "FI", "MYL": "VTRS",
          "JDSU": "VIAV", "KRFT": "KHC"}

def components(text):
    """Tickers in the article's Components section (bullet lists of 2006-2018, tables after)."""
    m = re.search(r"^==\s*Components\s*==\s*$", text, re.M)
    if not m: return set()
    rest = text[m.end():]
    e = re.search(r"^==[^=].*?==\s*$|^===[^=].*?===\s*$", rest, re.M)
    sec = rest[:e.start()] if e else rest
    out = set(LIST.findall(sec))
    for line in CELL.findall(sec):
        for c in [c.strip() for c in line.split("||")][:3]:
            c = re.sub(r"\{\{\s*(?:NASDAQ|Nasdaq|nasdaq)\s*\|\s*([A-Z.]+)\s*\}\}", r"\1", c)
            if re.fullmatch(r"[A-Z][A-Z.]{0,5}", c): out.add(c); break
    return out

def revision(at):
    p = dict(action="query", prop="revisions", titles="Nasdaq-100", redirects=1, rvlimit=1, rvdir="older",
             rvstart=at, rvprop="content|timestamp|ids", rvslots="main", format="json", formatversion=2)
    for attempt in range(6):
        try:
            j = requests.get(API, params=p, headers=UA, timeout=60).json()
            rv = j["query"]["pages"][0]["revisions"][0]
            return rv["timestamp"], rv["slots"]["main"]["content"]
        except Exception as e:
            print("  retry", at, str(e)[:80], flush=True); time.sleep(10 * (attempt + 1))
    return None, ""

def main():
    os.makedirs(OUT, exist_ok=True)
    qs = pd.date_range("2006-12-31", pd.Timestamp.today(), freq="QE")
    raw, rows, prev = {}, [], set()
    for q in qs:
        ts, text = revision(q.strftime("%Y-%m-%dT23:59:59Z"))
        raw[str(q.date())] = dict(ts=ts, text=text)
        tick, src = components(text), "wiki"
        if len(tick) < 90: tick, src = prev, "carried"           # failed fetch or a list moved off the page
        prev = tick
        rows += [dict(quarter=str(q.date()), revision=ts, ticker=t, source=src) for t in sorted(tick)]
        print(q.date(), ts, len(tick), src, flush=True); time.sleep(2)
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
        ch = [RENAME.get(t, t).replace(".", "-") for t in allt[i:i + 100]]
        d = yf.download(ch, start="2006-01-01", auto_adjust=False, progress=False, threads=True, group_by="column")
        if d is None or not len(d): continue
        a = d["Adj Close"]; a = a.to_frame(ch[0]) if isinstance(a, pd.Series) else a
        parts.append(a)
    px = pd.concat(parts, axis=1).sort_index().dropna(how="all", axis=1)
    px.to_csv(f"{OUT}/adj.csv.gz", float_format="%.6g", index_label="date")
    miss = sorted(set(RENAME.get(t, t).replace(".", "-") for t in allt) - set(px.columns))
    pd.Series(miss, name="ticker").to_csv(f"{OUT}/missing_prices.csv", index=False)
    print(f"{len(allt)} members ever, {px.shape[1]} priced, {len(miss)} missing", flush=True)

if __name__ == "__main__":
    main()
