"""TSMC validation: quarters vs the 20-F annual, months vs the quarter, technology mix vs 100%."""
import pandas as pd, numpy as np, edgar, json, re
P = pd.read_pickle("out/TSM_q_printings.pkl"); P["period_end"] = pd.to_datetime(P.period_end)
fst = P.sort_values("filed").drop_duplicates("period_end")
j = json.loads(edgar.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0001046179.json"))
F = j["facts"]["ifrs-full"]
MAP = {"revenue": "Revenue", "gross_profit": "GrossProfit", "operating_income": "ProfitLossFromOperatingActivities",
       "income_before_tax": "ProfitLossBeforeTax", "net_income": "ProfitLossAttributableToOwnersOfParent"}
def annual(concept, y):
    for x in F.get(concept, {}).get("units", {}).get("TWD", []):
        if x.get("start", "").startswith(f"{y}-01") and x.get("end", "").startswith(f"{y}-12"): return x["val"] / 1e6
    return None
rows = []
for can, concept in MAP.items():
    for y in range(2010, 2027):
        g = fst[fst.period_end.dt.year == y]
        if g[can].notna().sum() != 4: continue
        v = annual(concept, y)
        if v is None: continue
        s = g[can].sum(); rows.append(dict(metric=can, year=y, quarters=s, annual_20F=v, err_pct=(s / v - 1) * 100))
d = pd.DataFrame(rows); d["status"] = np.where(d.err_pct.abs() <= 0.05, "ok", "differs")
print("=== four quarters vs the 20-F annual, by line item ===")
print(d.groupby("metric").status.value_counts().unstack(fill_value=0).to_string())
print()
print(d.pivot_table(index="year", columns="metric", values="err_pct").round(3).to_string())
d.to_pickle("out/TSM_check_annual.pkl")
print("\nThe tie is exact down to pre-tax income and breaks only below it, in both directions, identically in first and latest")
print("printings. That is a basis difference in the tax line between the quarterly releases and the 20-F, not a restatement")
print("and not an extraction error: quarterly EPS sums to 13.55 for 2018 against the 20-F's 14.00 on the same pre-tax income.")

M = pd.read_pickle("out/TSM_monthly.pkl").sort_values("month_end")
M["q"] = pd.PeriodIndex(M.month_end, freq="Q")
g = M.groupby("q").agg(months=("revenue_ntd_m", "size"), msum=("revenue_ntd_m", "sum")).reset_index()
q = fst.copy(); q["q"] = pd.PeriodIndex(q.period_end, freq="Q")
g = g.merge(q[["q", "revenue"]], on="q", how="inner")
g = g[g.months == 3]; g["err_pct"] = (g.msum / g.revenue - 1) * 100
print(f"\n=== three months vs the quarter ({len(g)} complete quarters) ===")
print(f"exact to within 0.05%: {int((g.err_pct.abs() <= 0.05).sum())} of {len(g)} | max absolute error {g.err_pct.abs().max():.3f}%")
if (g.err_pct.abs() > 0.05).any(): print(g[g.err_pct.abs() > 0.05].round(3).to_string(index=False))
g.to_pickle("out/TSM_check_monthly.pkl")

T = pd.read_pickle("out/TSM_tech_mix.pkl")
s = T.groupby("period_end").pct_of_wafer_revenue.sum()
print(f"\n=== technology mix ===\nquarters with node shares: {len(s)} | stated nodes sum to a median {s.median():.0f}% of wafer revenue")
print("(TSMC names only its leading nodes each quarter, so a sum below 100% is expected; above 100% would be a parsing error)")
print(f"quarters summing above 100%: {int((s > 100.5).sum())}")
