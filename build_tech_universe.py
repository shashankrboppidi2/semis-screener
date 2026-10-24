"""Point-in-time chip + tech universe with daily market caps -> results/universe/.

Market cap on day t = split-adjusted close on t x the latest share count *filed* before t (period end + 60 days),
so a name enters the universe only once it was that big at the time -- not because it is big today.

  1. Share counts for every filer from the SEC frames API, 2009 on: diluted weighted-average shares (quarterly,
     all classes together), else the cover-page dei count, else the annual diluted count.
  2. Every filer with a current Nasdaq/NYSE ticker: monthly Yahoo closes -> a rough cap; >= $8B at any month-end
     keeps it as a candidate.
  3. SIC from each candidate's submissions file. Kept: SIC 357x computers, 3661/3663/3669 communications
     equipment, 367x electronic components and semis, 3825 test, 3827 optics (KLAC), 3559 equipment (LRCX), 737x
     software and services; plus config/ chip names and AMZN/TSLA/NFLX (tech by usage, not by SIC). Foreign filers
     (20-F/40-F) only where the ADR ratio is known (ADR below), since their share count is in ordinary shares.
  4. Daily Yahoo closes (split-adjusted and total-return) for the kept names; daily caps.
  5. Survivorship check: filers with no current ticker but a large share count are looked up, and the tech ones
     listed in delisted.csv -- the acquired and failed names Yahoo cannot price.

Needs SEC (SEC_UA) and Yahoo -- run via .github/workflows/universe.yml.
"""
import os, glob, json, time
import numpy as np
import pandas as pd
import yfinance as yf
import edgar
from tech_caps import daily_caps

OUT = "results/universe"
START = "2010-01-01"
TECH_SIC = set(range(3570, 3580)) | {3661, 3663, 3669, 3825, 3827, 3559} | set(range(3670, 3680)) | set(range(7370, 7380))
ALSO = {"AMZN", "TSLA", "NFLX"}
ADR = {"TSM": 5, "UMC": 5, "ASX": 2, "ASML": 1, "STM": 1, "NVMI": 1, "TSEM": 1, "ARM": 1, "SAP": 1, "INFY": 1, "SHOP": 1}
PRE_B = 8.0

def frames():
    rows = []
    now = pd.Timestamp.today()
    for y in range(2009, now.year + 1):
        for q in range(1, 5):
            if pd.Timestamp(y, 3 * q, 1) > now: continue
            for prio, (tax, tag, per) in enumerate([("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", f"CY{y}Q{q}"),
                                                    ("dei", "EntityCommonStockSharesOutstanding", f"CY{y}Q{q}I")]):
                try:
                    j = edgar.getj(f"https://data.sec.gov/api/xbrl/frames/{tax}/{tag}/shares/{per}.json")
                except Exception as e:
                    print("  no frame", tag, per, type(e).__name__, flush=True); continue
                for d in j.get("data", []):
                    rows.append((d["cik"], d.get("entityName"), d["end"], float(d["val"]), prio))
        try:
            j = edgar.getj(f"https://data.sec.gov/api/xbrl/frames/us-gaap/WeightedAverageNumberOfDilutedSharesOutstanding/shares/CY{y}.json")
            rows += [(d["cik"], d.get("entityName"), d["end"], float(d["val"]), 2) for d in j.get("data", [])]
        except Exception:
            pass
        print(f"  frames {y}: {len(rows):,} rows", flush=True)
    f = pd.DataFrame(rows, columns=["cik", "entity", "end", "shares", "prio"])
    f["end"] = pd.to_datetime(f.end)
    f = f[f.shares > 0].sort_values(["cik", "end", "prio"]).drop_duplicates(["cik", "end"])
    return f

def yahoo(tickers, **kw):
    out = {}
    for i in range(0, len(tickers), 200):
        chunk = tickers[i:i + 200]
        for attempt in range(3):
            try:
                d = yf.download(chunk, start=START, auto_adjust=False, actions=True, progress=False, threads=True, group_by="column", **kw)
                break
            except Exception as e:
                print("  yahoo retry", e, flush=True); time.sleep(10); d = None
        if d is None or not len(d): continue
        for fld in ("Close", "Adj Close", "Stock Splits"):
            if fld in d.columns.get_level_values(0):
                x = d[fld]
                if isinstance(x, pd.Series): x = x.to_frame(chunk[0])
                out.setdefault(fld, []).append(x)
        print(f"  yahoo {min(i + 200, len(tickers))}/{len(tickers)}", flush=True)
    return {k: pd.concat(v, axis=1).sort_index() for k, v in out.items()}

def main():
    os.makedirs(OUT, exist_ok=True)
    print("frames ...", flush=True)
    fr = frames()
    tk = edgar.getj("https://www.sec.gov/files/company_tickers_exchange.json")
    t = pd.DataFrame(tk["data"], columns=tk["fields"])
    t = t[t.exchange.isin(["Nasdaq", "NYSE"])].drop_duplicates("cik")          # first listed ticker per filer
    t["ticker"] = t.ticker.str.replace(".", "-", regex=False)
    have = t[t.cik.isin(fr.cik.unique())]
    print(f"{fr.cik.nunique():,} filers with share counts; {len(have):,} with a Nasdaq/NYSE ticker", flush=True)

    config = {os.path.basename(p)[:-5] for p in glob.glob("config/*.json")}
    by = {k: g for k, g in fr.groupby("cik")}
    m = yahoo(sorted(have.ticker), interval="1mo")
    pre = []
    for r in have.itertuples():
        if r.ticker not in m["Close"].columns: continue
        sp = m["Stock Splits"][r.ticker].fillna(0) if "Stock Splits" in m and r.ticker in m["Stock Splits"] else pd.Series(dtype=float)
        c = daily_caps(m["Close"][r.ticker], sp, by[r.cik], ADR.get(r.ticker, 1))
        if len(c) and (c.max() >= PRE_B or r.ticker in config | ALSO): pre.append((r.cik, r.ticker, r.name, c.max()))
    print(f"{len(pre)} candidates with a month-end cap >= ${PRE_B:.0f}bn", flush=True)

    meta = []
    for cik, tick, name, peak in pre:
        try:
            j = edgar.getj(f"https://data.sec.gov/submissions/CIK{edgar.cik10(cik)}.json")
        except Exception as e:
            print("  no submissions", tick, e, flush=True); continue
        forms = set(j["filings"]["recent"]["form"])
        sic = int(j["sic"]) if str(j.get("sic") or "").isdigit() else None
        meta.append(dict(ticker=tick, cik=cik, name=name, sic=sic, sic_desc=j.get("sicDescription"),
                         domestic=bool(forms & {"10-K", "10-Q"}), peak_month_cap_b=round(peak, 1)))
    meta = pd.DataFrame(meta)
    meta["tech"] = meta.sic.isin(TECH_SIC) | meta.ticker.isin(ALSO | config)
    meta["adr_ratio"] = meta.ticker.map(ADR).fillna(1)
    meta["kept"] = meta.tech & (meta.domestic | meta.ticker.isin(ADR))
    meta.sort_values("peak_month_cap_b", ascending=False).to_csv(f"{OUT}/candidates.csv", index=False)
    keep = meta[meta.kept]
    print(f"kept {len(keep)} tech names; dropped {int((meta.tech & ~meta.kept).sum())} foreign tech filers without an ADR ratio", flush=True)

    d = yahoo(sorted(keep.ticker))
    adj = d["Adj Close"].reindex(columns=sorted(keep.ticker))
    cap = pd.DataFrame(index=adj.index)
    for r in keep.itertuples():
        if r.ticker in d["Close"].columns:
            sp = d["Stock Splits"][r.ticker].fillna(0) if "Stock Splits" in d and r.ticker in d["Stock Splits"] else pd.Series(dtype=float)
            cap[r.ticker] = daily_caps(d["Close"][r.ticker], sp, by[r.cik], r.adr_ratio)
    adj.round(4).to_csv(f"{OUT}/tech_adj.csv.gz", index_label="date")
    # raw inputs, so caps can be rebuilt without SEC or Yahoo (tech_caps.daily_caps)
    d["Close"].reindex(columns=sorted(keep.ticker)).round(4).to_csv(f"{OUT}/tech_close.csv.gz", index_label="date")
    spl = d["Stock Splits"].reindex(columns=sorted(keep.ticker)).stack()
    spl[spl > 0].rename("ratio").rename_axis(["date", "ticker"]).reset_index().to_csv(f"{OUT}/tech_splits.csv", index=False)
    fr[fr.cik.isin(keep.cik)].merge(keep[["cik", "ticker"]], on="cik").to_csv(f"{OUT}/tech_shares.csv.gz", index=False)
    cap.round(3).to_csv(f"{OUT}/tech_cap_b.csv.gz", index_label="date")
    keep = keep.assign(first_price=[adj[t].first_valid_index() for t in keep.ticker],
                       last_cap_b=[cap[t].dropna().iloc[-1] if t in cap and cap[t].notna().any() else np.nan for t in keep.ticker],
                       peak_cap_b=[cap[t].max() if t in cap else np.nan for t in keep.ticker])
    keep.to_csv(f"{OUT}/tech_meta.csv", index=False)

    # survivorship: big filers with no current ticker
    gone = fr[~fr.cik.isin(t.cik)].groupby("cik").agg(entity=("entity", "last"), max_shares=("shares", "max"), last_end=("end", "max"))
    gone = gone[gone.max_shares >= 150e6].sort_values("max_shares", ascending=False).head(1500)
    rows = []
    for cik, r in gone.iterrows():
        try:
            j = edgar.getj(f"https://data.sec.gov/submissions/CIK{edgar.cik10(cik)}.json")
        except Exception:
            continue
        sic = int(j["sic"]) if str(j.get("sic") or "").isdigit() else None
        if sic in TECH_SIC:
            rows.append(dict(cik=cik, name=r.entity, sic=sic, sic_desc=j.get("sicDescription"),
                             former_tickers=",".join(j.get("tickers") or []), max_shares_m=round(r.max_shares / 1e6),
                             last_share_report=r.last_end.date()))
    pd.DataFrame(rows).to_csv(f"{OUT}/delisted.csv", index=False)
    print(f"{len(rows)} delisted/no-ticker tech filers with >= 150m shares", flush=True)

    chk = keep.set_index("ticker").last_cap_b.reindex(["AAPL", "MSFT", "NVDA", "AVGO", "AMD", "INTC", "TSM", "ASML", "ORCL", "AMZN"])
    print("sanity, latest cap $bn:", chk.round(0).to_dict(), flush=True)
    print("SEC requests", edgar.STATS, flush=True)

if __name__ == "__main__":
    main()
