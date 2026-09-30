"""Backfill TSMC's monthly revenue for 2010-2013, when the releases were worded differently.

Before mid-2013 the monthly release carried no 'Revenue Report' title and no table: the figure is
in the sentence, 'On a consolidated basis, net sales for March 2011 were approximately NT$ 37.32
billion'. The sentence is rounded to NT$10 million, so these rows are flagged as such; the
consolidated figure is taken, never the unconsolidated one the same release also states.
"""
import pandas as pd, re, edgar, os
from tsmc2 import text, MONTHS
CIK = 1046179
SENT = re.compile(r"consolidated basis,? net (?:sales|revenues?) for (" + "|".join(MONTHS) + r") (\d{4}) (?:was|were) approximately NT\$\s?([\d,.]+) billion", re.I)
j, rows = edgar.submissions(CIK)
have = set()
if os.path.exists("out/TSM_monthly.pkl"):
    M0 = pd.read_pickle("out/TSM_monthly.pkl"); have = set(pd.to_datetime(M0.month_end))
else:
    M0 = pd.DataFrame()
k6 = sorted([r for r in rows if r["form"] == "6-K" and "2010-01-01" <= r["filingDate"] <= "2013-12-31"], key=lambda r: r["filingDate"])
out = []
for r in k6:
    t = text(r["accessionNumber"], r["primaryDocument"])
    m = SENT.search(re.sub(r"\s+", " ", t))
    if not m: continue
    mi = MONTHS.index(m.group(1).lower()); yr = int(m.group(2))
    me = pd.Timestamp(year=yr, month=mi + 1, day=1) + pd.offsets.MonthEnd(0)
    if me in have: continue
    out.append(dict(filed=r["filingDate"], accn=r["accessionNumber"], month_end=me,
                    revenue_ntd_m=float(m.group(3).replace(",", "")) * 1000, source="press-release sentence (rounded to NT$10m)"))
A = pd.DataFrame(out)
print("backfilled months:", len(A), "" if not len(A) else f"{A.month_end.min().date()} -> {A.month_end.max().date()}")
M = pd.concat([M0, A], ignore_index=True).sort_values("month_end").drop_duplicates("month_end")
M.to_pickle("out/TSM_monthly.pkl")
print("monthly series now:", len(M), M.month_end.min().date(), "->", M.month_end.max().date())
print("by source:", M.source.value_counts().to_dict())
# the check that matters: three months must still sum to the quarter
P = pd.read_pickle("out/TSM_q_printings.pkl"); P["period_end"] = pd.to_datetime(P.period_end)
fst = P.sort_values("filed").drop_duplicates("period_end"); fst["q"] = pd.PeriodIndex(fst.period_end, freq="Q")
M["q"] = pd.PeriodIndex(M.month_end, freq="Q")
g = M.groupby("q").agg(months=("revenue_ntd_m", "size"), msum=("revenue_ntd_m", "sum")).reset_index()
g = g[g.months == 3].merge(fst[["q", "revenue"]], on="q"); g["err_pct"] = (g.msum / g.revenue - 1) * 100
print(f"three months vs the quarter: {len(g)} complete quarters | within 0.05%: {int((g.err_pct.abs()<=0.05).sum())} | within 0.5%: {int((g.err_pct.abs()<=0.5).sum())} | max {g.err_pct.abs().max():.3f}%")
print(g[g.err_pct.abs() > 0.05].round(3).to_string(index=False))
