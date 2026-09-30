"""Does quarterly segment KPI growth lead the company's OWN next-quarter revenue growth?

This is the leading-indicator question stripped of the market: if segment detail carries
information, a segment inflecting this quarter should show up in the consolidated line next
quarter, over and above what this quarter's consolidated growth already says.
All figures as-first-reported. Target = next quarter's y/y total revenue growth.
"""
import pandas as pd, numpy as np
from scipy import stats
S = pd.read_pickle("out/study_signals.pkl").sort_values(["ticker", "period_end"]).reset_index(drop=True)
S["q"] = S.groupby("ticker").cumcount()
# next quarter's y/y growth, only when the next row really is the next quarter
nxt = S.groupby("ticker").shift(-1)
gap = (nxt.period_end - S.period_end).dt.days
S["fwd_yoy"] = np.where(gap.between(60, 130), nxt.co_yoy, np.nan)
S["fwd_accel"] = S.fwd_yoy - S.co_yoy          # does growth speed up next quarter?
SIG = ["best_seg_yoy", "worst_seg_yoy", "seg_yoy_disp", "largest_seg_yoy", "wavg_seg_yoy",
       "best_seg_accel", "worst_seg_accel", "wavg_seg_accel", "share_segs_accelerating"]
d = S[S.fwd_yoy.notna()].copy()
rows = []
for s in SIG + ["co_yoy", "co_accel"]:
    cols = list(dict.fromkeys([s, "fwd_yoy", "fwd_accel", "co_yoy", "co_accel"]))  # s may itself be co_yoy/co_accel
    g = d[cols].dropna(subset=[s, "fwd_yoy"])
    if len(g) < 100: continue
    r1 = stats.spearmanr(g[s], g.fwd_yoy)
    r2 = stats.spearmanr(g[s], g.fwd_accel)
    # partial: rank-residualise both sides on this quarter's consolidated growth
    def resid(y, x):
        x = stats.rankdata(x); y = stats.rankdata(y); b = np.polyfit(x, y, 1); return y - (b[0] * x + b[1])
    gp = g.dropna(subset=["co_yoy"])
    pr = stats.spearmanr(resid(gp[s], gp.co_yoy), resid(gp.fwd_yoy, gp.co_yoy)) if s != "co_yoy" and len(gp) > 50 else (np.nan, np.nan)
    rows.append(dict(signal=s, n=len(g), rho_next_yoy=r1.statistic, p_next_yoy=r1.pvalue,
                     rho_next_accel=r2.statistic, p_next_accel=r2.pvalue,
                     rho_partial=pr[0] if s != "co_yoy" else np.nan, p_partial=pr[1] if s != "co_yoy" else np.nan))
F = pd.DataFrame(rows); F.to_pickle("out/study_fundamental.pkl")
print("sample:", len(d), "quarter pairs,", d.ticker.nunique(), "tickers")
print(F.round(3).to_string(index=False))
# how much of next-quarter growth does each add in a pooled OLS on top of consolidated growth?
import itertools
y = d.fwd_yoy
base = d[["co_yoy", "co_accel"]].copy()
def r2(X, y):
    m = X.notna().all(axis=1) & y.notna(); X = X[m]; yy = y[m]
    X = np.column_stack([np.ones(len(X)), X.values])
    b, *_ = np.linalg.lstsq(X, yy, rcond=None); p = X @ b
    return 1 - ((yy - p) ** 2).sum() / ((yy - yy.mean()) ** 2).sum(), m.sum()
b0, n0 = r2(base, y)
print(f"\npooled R^2 of next-quarter y/y on consolidated growth + acceleration alone: {b0:.3f} (n={n0})")
for s in SIG:
    r, n = r2(pd.concat([base, d[[s]]], axis=1), y)
    bb, _ = r2(base.loc[d[[s]].dropna().index.intersection(base.dropna().index)], y)
    print(f"  + {s:26s} R^2 {r:.3f}  (vs {bb:.3f} on the same rows: {r-bb:+.3f})")
