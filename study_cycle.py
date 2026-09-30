"""Which quarterly segment KPIs lead the semiconductor cycle?

One pre-specified test per segment, not a pair scan: correlate the segment's y/y growth against
the cycle itself -- the median y/y of every company in the universe except the segment's own
parent -- at leads and lags of up to three quarters. The lag at which the correlation peaks is
that segment's position in the cycle: a segment peaking at a NEGATIVE peer lag moved first.
Reported alongside the peak correlation, so a segment that simply does not track the cycle
(low peak) is not mistaken for a leading one.
"""
import pandas as pd, numpy as np
from scipy import stats
LAGS = [-3, -2, -1, 0, 1, 2, 3]

SQ = pd.read_pickle("out/study_segment_quarters.pkl")
SQ["cq"] = pd.PeriodIndex(SQ.period_end, freq="Q")
SQ = SQ.sort_values(["ticker", "name", "period_end"]).drop_duplicates(["ticker", "name", "cq"], keep="last")
_y = SQ[["ticker", "name", "cq", "rev"]].copy(); _y["cq"] = _y.cq + 4
SQ = SQ.merge(_y.rename(columns={"rev": "yago"}), on=["ticker", "name", "cq"], how="left")
SQ["yoy"] = pd.to_numeric(SQ.rev, errors="coerce") / pd.to_numeric(SQ.yago, errors="coerce") - 1

S = pd.read_pickle("out/study_signals.pkl").copy()
S["cq"] = pd.PeriodIndex(S.period_end, freq="Q")
S = S.sort_values("period_end").drop_duplicates(["ticker", "cq"], keep="last")
TOT = S[["ticker", "cq", "co_yoy"]].dropna()
sh = SQ.merge(S[["ticker", "cq", "total_rev"]], on=["ticker", "cq"], how="left")
sh["s"] = sh.rev / sh.total_rev
avg_share = sh.groupby(["ticker", "name"]).s.mean()

def cycle_ex(parent):
    o = TOT[TOT.ticker != parent].groupby("cq").co_yoy.agg(["median", "size"])
    return o[o["size"] >= 8][["median"]].rename(columns={"median": "cyc"})

rows = []
for (t, nm), g in SQ.groupby(["ticker", "name"]):
    g = g.dropna(subset=["yoy"])
    if len(g) < 28 or avg_share.get((t, nm), 0) < 0.08: continue
    cyc = cycle_ex(t); h = g.set_index("cq")[["yoy"]]
    r = {}
    for k in LAGS:
        a = cyc.copy(); a.index = a.index + k          # joins cycle(T) to segment(T+k): a peak at k>0 means the cycle moved first
        m = a.join(h, how="inner").dropna()
        if len(m) >= 24: r[k] = stats.spearmanr(m.cyc, m.yoy).statistic
    if 0 not in r or len(r) < 5: continue
    pk = max(r, key=lambda k: r[k])
    # report it the way an analyst would read it: quarters the SEGMENT leads the industry (so -k)
    rows.append(dict(ticker=t, segment=nm, avg_share=avg_share[(t, nm)], n=len(m), segment_leads_q=-pk, peak_rho=r[pk],
                     rho_at_0=r[0], **{f"seg_leads{-k:+d}": r.get(k) for k in LAGS}))
C = pd.DataFrame(rows).sort_values(["segment_leads_q", "peak_rho"], ascending=[False, False])
C.to_pickle("out/study_cycle.pkl")
print(f"segments tested: {len(C)} (>=8% of company revenue, >=24 overlapping quarters), {C.ticker.nunique()} companies")
print("\nsegment_leads_q > 0: the segment turns this many quarters BEFORE the rest of the industry. < 0: it follows.\n")
COLS = [f"seg_leads{k:+d}" for k in sorted([-k for k in LAGS], reverse=True)]
print(C[["ticker", "segment", "avg_share", "n", "segment_leads_q", "peak_rho", "rho_at_0"] + COLS].round(2).to_string(index=False))
print("\n=== segments that LEAD the industry by a quarter or more (peak correlation above 0.45) ===")
L = C[(C.segment_leads_q >= 1) & (C.peak_rho > 0.45)]
print(L[["ticker", "segment", "avg_share", "n", "segment_leads_q", "peak_rho", "rho_at_0"]].round(2).to_string(index=False) if len(L) else "none")
print("\n=== segments that FOLLOW the industry (peak correlation above 0.45) ===")
G = C[(C.segment_leads_q <= -1) & (C.peak_rho > 0.45)]
print(G[["ticker", "segment", "avg_share", "n", "segment_leads_q", "peak_rho", "rho_at_0"]].round(2).to_string(index=False) if len(G) else "none")
print("\n=== segments that barely track the cycle at all (peak correlation below 0.3) ===")
print(C[C.peak_rho < 0.3][["ticker", "segment", "avg_share", "peak_rho"]].round(2).to_string(index=False))
