"""Does TSMC's monthly revenue lead the rest of the industry?

TSMC publishes revenue every month, within ten days of month end -- the earliest hard number in
the chain, and the one the industry watches. Test it the same way as the segments: TSMC's y/y
growth aggregated to a calendar quarter, against each company's own y/y revenue growth at leads
and lags of up to three quarters, one pre-specified test per company. A lead only counts if it
beats TSMC's contemporaneous correlation with that company.
"""
import pandas as pd, numpy as np
from scipy import stats
M = pd.read_pickle("out/TSM_monthly.pkl").sort_values("month_end")
M["cq"] = pd.PeriodIndex(M.month_end, freq="Q")
g = M.groupby("cq").agg(rev=("revenue_ntd_m", "sum"), months=("revenue_ntd_m", "size"))
g = g[g.months == 3]
y = g.copy(); y.index = y.index + 4
g = g.join(y.rev.rename("yago"), how="left"); g["tsmc_yoy"] = g.rev / g.yago - 1
T = g[["tsmc_yoy"]].dropna()

S = pd.read_pickle("out/study_signals.pkl").copy()
S["cq"] = pd.PeriodIndex(S.period_end, freq="Q")
S = S.sort_values("period_end").drop_duplicates(["ticker", "cq"], keep="last")
CO = S[["ticker", "cq", "co_yoy"]].dropna()
LAGS = [-3, -2, -1, 0, 1, 2, 3]
rows = []
for t, h in CO.groupby("ticker"):
    h = h.set_index("cq")[["co_yoy"]]
    r = {}
    for k in LAGS:
        a = T.copy(); a.index = a.index + k      # k>0 joins TSMC(q) to the company at q+k: TSMC moved first
        m = a.join(h, how="inner").dropna()
        if len(m) >= 20: r[k] = stats.spearmanr(m.tsmc_yoy, m.co_yoy).statistic
    if 0 not in r or len(r) < 5: continue
    pk = max(r, key=lambda k: r[k])
    rows.append(dict(company=t, n=len(m), tsmc_leads_q=pk, peak_rho=r[pk], rho_at_0=r[0],
                     **{f"tsmc_leads{k:+d}": r.get(k) for k in LAGS}))
D = pd.DataFrame(rows).sort_values("tsmc_leads_q", ascending=False)
D.to_pickle("out/study_tsmc_lead.pkl")
print(f"TSMC monthly revenue: {len(M)} months {M.month_end.min().date()} -> {M.month_end.max().date()}; "
      f"{len(T)} complete quarters with a year-ago comparison, tested against {len(D)} companies")
print("\ntsmc_leads_q > 0 means TSMC's revenue turned that many quarters before the company's.\n")
print(D.round(2).to_string(index=False))
lead = D[(D.tsmc_leads_q >= 1) & (D.peak_rho > 0.4)]
print(f"\ncompanies TSMC leads by a quarter or more (peak correlation above 0.4): {len(lead)} of {len(D)}")
if len(lead): print(lead[["company", "tsmc_leads_q", "peak_rho", "rho_at_0"]].round(2).to_string(index=False))
co = D[D.tsmc_leads_q == 0]; print(f"coincident with TSMC: {len(co)} | TSMC follows: {int((D.tsmc_leads_q < 0).sum())}")
