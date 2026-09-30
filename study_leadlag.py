"""Cross-company lead-lag: does one company's segment growth lead ANOTHER company's revenue?

The semis chain is supposed to propagate -- an inflection in one link showing up in the next a
quarter or two later. Test: for every (source series, target company) pair, the Spearman
correlation of source y/y at calendar quarter T against the target's total y/y at T, T+1, T+2.
A series only counts as leading if its correlation at +1 or +2 BEATS its own contemporaneous
correlation; co-movement is not a lead. Fiscal calendars differ, so everything is mapped to
calendar quarters. All figures as-first-reported.
"""
import pandas as pd, numpy as np, itertools
from scipy import stats

SQ = pd.read_pickle("out/study_segment_quarters.pkl")
SQ["cq"] = pd.PeriodIndex(SQ.period_end, freq="Q")
# a 52/53-week fiscal calendar can put two fiscal quarters in one calendar quarter; keep the later one
SQ = SQ.sort_values(["ticker", "name", "period_end"]).drop_duplicates(["ticker", "name", "cq"], keep="last")
_y = SQ[["ticker", "name", "cq", "rev"]].copy(); _y["cq"] = _y.cq + 4
SQ = SQ.merge(_y.rename(columns={"rev": "yago"}), on=["ticker", "name", "cq"], how="left")
SQ["yoy"] = pd.to_numeric(SQ.rev, errors="coerce") / pd.to_numeric(SQ.yago, errors="coerce") - 1

S = pd.read_pickle("out/study_signals.pkl").copy()
S["cq"] = pd.PeriodIndex(S.period_end, freq="Q")
S = S.sort_values("period_end").drop_duplicates(["ticker", "cq"], keep="last")
TOT = S[["ticker", "cq", "co_yoy"]].dropna().drop_duplicates(["ticker", "cq"])

# source series: company totals, plus segments big enough to matter (>=10% of revenue on average)
share = SQ.merge(S[["ticker", "cq", "total_rev"]], on=["ticker", "cq"], how="left")
share["sh"] = share.rev / share.total_rev
big = share.groupby(["ticker", "name"]).sh.mean()
keep = big[big >= 0.10].index
src = SQ[pd.MultiIndex.from_arrays([SQ.ticker, SQ["name"]]).isin(keep)]
src = src[src.yoy.notna()][["ticker", "name", "cq", "yoy"]].copy()
src["series"] = src.ticker + " / " + src.name
tot_src = TOT.rename(columns={"co_yoy": "yoy"}).assign(name="TOTAL"); tot_src["series"] = tot_src.ticker + " / TOTAL"
SRC = pd.concat([src, tot_src[["ticker", "name", "cq", "yoy", "series"]]], ignore_index=True)

rows = []
for ser, g in SRC.groupby("series"):
    g = g.dropna(subset=["yoy"]).drop_duplicates("cq")
    if len(g) < 28: continue
    st = g.ticker.iloc[0]
    for tt, h in TOT.groupby("ticker"):
        if tt == st: continue
        for lag in (0, 1, 2):
            a = g[["cq", "yoy"]].copy(); a["cq"] = a.cq + lag
            m = a.merge(h[["cq", "co_yoy"]], on="cq").dropna()
            if len(m) < 24: continue
            r = stats.spearmanr(m.yoy, m.co_yoy)
            rows.append(dict(source=ser, source_ticker=st, target=tt, lag=lag, n=len(m), rho=r.statistic, p=r.pvalue))
L = pd.DataFrame(rows)
piv = L.pivot_table(index=["source", "source_ticker", "target"], columns="lag", values="rho")
piv.columns = [f"rho_lag{c}" for c in piv.columns]
npv = L[L.lag == 1].set_index(["source", "source_ticker", "target"])[["n", "p"]]
piv = piv.join(npv).dropna()
piv["lead_gain"] = piv[["rho_lag1", "rho_lag2"]].max(axis=1) - piv.rho_lag0
piv.to_pickle("out/study_leadlag.pkl")
print(f"pairs tested: {len(piv)} (source series x target company), {L.source.nunique()} source series, {L.target.nunique()} targets")
print(f"\ncontemporaneous correlation is the norm: median rho at lag 0 = {piv.rho_lag0.median():.2f}, at +1 = {piv.rho_lag1.median():.2f}, at +2 = {piv.rho_lag2.median():.2f}")
print(f"pairs where +1 or +2 beats lag 0: {(piv.lead_gain > 0).sum()} of {len(piv)} ({(piv.lead_gain>0).mean():.0%})")
print(f"pairs where the lead beats lag 0 by more than 0.15: {(piv.lead_gain > 0.15).sum()}")
print("\n=== strongest genuine leads (lead correlation minus contemporaneous, min 24 quarters) ===")
print(piv.sort_values("lead_gain", ascending=False).head(20).round(2).to_string())
print("\n=== and the reverse: series that most clearly LAG their peers (for completeness) ===")
print(piv.sort_values("lead_gain").head(8).round(2).to_string())

# ---------------------------------------------------------------------------
# The pair scan above runs 575 tests, so a handful of large lead gains is what chance alone
# would produce. Two disciplines follow: a placebo that destroys any real timing while keeping
# each series' autocorrelation, and one pre-specified test per company instead of per pair.
def placebo(n_shift=(5, 7, 9, 11, 13)):
    out = []
    for k in n_shift:
        rows = []
        for ser, g in SRC.groupby("series"):
            g = g.dropna(subset=["yoy"]).drop_duplicates("cq")
            if len(g) < 28: continue
            st = g.ticker.iloc[0]
            for tt, h in TOT.groupby("ticker"):
                if tt == st: continue
                hh = h.sort_values("cq").copy(); hh["co_yoy"] = np.roll(hh.co_yoy.values, k)   # circular shift: same series, wrong dates
                r = {}
                for lag in (0, 1, 2):
                    a = g[["cq", "yoy"]].copy(); a["cq"] = a.cq + lag
                    m = a.merge(hh[["cq", "co_yoy"]], on="cq").dropna()
                    if len(m) < 24: r = {}; break
                    r[lag] = stats.spearmanr(m.yoy, m.co_yoy).statistic
                if len(r) == 3: rows.append(max(r[1], r[2]) - r[0])
        if rows: out.append(pd.Series(rows))
    return pd.concat(out, ignore_index=True) if out else pd.Series(dtype=float)

def composite():
    """one test per company: does the equal-weight growth of every OTHER name lead this one?"""
    rows = []
    for tt in sorted(TOT.ticker.unique()):
        oth = TOT[TOT.ticker != tt].groupby("cq").co_yoy.agg(["median", "size"])
        oth = oth[oth["size"] >= 8][["median"]].rename(columns={"median": "peers"})
        h = TOT[TOT.ticker == tt].set_index("cq")[["co_yoy"]]
        r = {}
        for lag in (-2, -1, 0, 1, 2):
            a = oth.copy(); a.index = a.index + lag
            m = a.join(h, how="inner").dropna()
            if len(m) < 24: continue
            r[lag] = stats.spearmanr(m.peers, m.co_yoy).statistic
        if 0 in r and 1 in r: rows.append(dict(target=tt, n=len(m), **{f"peers_lead_{k}q": v for k, v in r.items()}))
    return pd.DataFrame(rows)

if __name__ == "__main__":
    pl = placebo()
    if len(pl):
        print(f"\n=== placebo (each target's own series circularly shifted, {len(pl)} pseudo-pairs) ===")
        print(f"lead gain > 0.15 by chance: {(pl > 0.15).mean():.0%} of pseudo-pairs, vs {(piv.lead_gain > 0.15).mean():.0%} in the real data")
        print(f"placebo 95th percentile of lead gain: {pl.quantile(.95):.2f} | real data 95th percentile: {piv.lead_gain.quantile(.95):.2f}")
    C = composite(); C.to_pickle("out/study_leadlag_composite.pkl")
    print("\n=== pre-specified test: peer-group growth (median of all other names) vs each company, by lead ===")
    print("(a positive number at +1 or +2 means the peer group moved first)")
    print(C.round(2).to_string(index=False))
