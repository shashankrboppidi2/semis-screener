"""Earnings-release date per (ticker, fiscal quarter).

The 10-Q filing date is not when the segment figures become public: these companies print
segment revenue in the earnings press release, filed on an 8-K days to weeks earlier. Anchoring
the study on the release date is what makes it a test of information rather than of stale news.
Match rule: the release whose printed revenue equals the quarter's reported revenue (<=0.5%),
else the release filed 10-75 days after the quarter end, nearest first.
"""
import pandas as pd, numpy as np, glob, os, edgar, re

def releases(t):
    p = f"out/{t}_earn.pkl"
    if os.path.exists(p):
        H = pd.read_pickle(p)["H"].copy(); H["filed"] = pd.to_datetime(H.filed); return H[["filed", "revenue"]]
    cfg = __import__("json").load(open(f"config/{t}.json")); j, rows = edgar.submissions(cfg["cik"])
    r = [x for x in rows if x["form"] == "8-K" and x["filingDate"] >= "2010-01-01"]
    return pd.DataFrame(dict(filed=pd.to_datetime([x["filingDate"] for x in r]), revenue=np.nan))

if __name__ == "__main__":
    S = pd.read_pickle("out/study_signals.pkl"); out = []
    for t, g in S.groupby("ticker"):
        R = releases(t).sort_values("filed")
        fin = pd.read_pickle(f"out/{t}_fin.pkl")
        for _, r in g.iterrows():
            pe = pd.Timestamp(r.period_end); rev = r.co_rev
            c = R[(R.filed - pe).dt.days.between(8, 80)].copy()
            if not len(c): out.append(dict(ticker=t, period_end=pe, release=pd.NaT, how="none")); continue
            m = c[np.isclose(c.revenue.astype(float), rev, rtol=0.006)] if rev == rev else c.iloc[0:0]
            # press releases print thousands or millions; try both scalings before falling back to date
            if not len(m):
                for s in (1e3, 1e-3):
                    m = c[np.isclose(c.revenue.astype(float) * s, rev, rtol=0.006)]
                    if len(m): break
            if len(m): out.append(dict(ticker=t, period_end=pe, release=m.filed.iloc[0], how="revenue match"))
            else: out.append(dict(ticker=t, period_end=pe, release=c.filed.iloc[0], how="date proximity"))
    d = pd.DataFrame(out); d.to_pickle("out/study_events.pkl")
    print(d.how.value_counts().to_dict())
    ok = d[d.release.notna()].copy(); ok["lag"] = (ok.release - ok.period_end).dt.days
    print("release lag after quarter end: median %.0f days, p5 %.0f, p95 %.0f" % (ok.lag.median(), ok.lag.quantile(.05), ok.lag.quantile(.95)))
    S2 = S.merge(d, on=["ticker", "period_end"], how="left")
    S2["filing_lag"] = (S2.known_at - S2.release).dt.days
    print("10-Q filing lands a median of %.0f days after the release" % S2.filing_lag.median())
    print("events with a release date:", int(S2.release.notna().sum()), "of", len(S2))
