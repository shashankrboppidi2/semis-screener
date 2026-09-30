"""Independent cross-check vs Fiscal.ai quarterly (revenue, gross profit, net income). Match if our first-reported OR any later printing
agrees within 0.5% (+1 unit, Fiscal rounds to 0.1M). Fiscal serves latest (restated) values, so first-reported can differ legitimately."""
import json, pandas as pd, numpy as np
F = json.load(open("out/fiscal_q.json")); rows = []
for t, data in F.items():
    cfg = json.load(open(f"config/{t}.json"))
    if cfg.get("filer_type") == "FPI":
        P = pd.read_pickle(f"out/{t}_q_printings.pkl"); Q = pd.read_pickle(f"out/{t}_q.pkl")
        V = pd.concat([Q.assign(src="first")[["period_end", "revenue", "gross_profit", "net_income", "src"]], P.assign(src="later")[["period_end", "revenue", "gross_profit", "net_income", "src"]]])
        V = V.melt(["period_end", "src"], var_name="canonical").dropna(); V["period_end"] = pd.to_datetime(V.period_end)
    else:
        a = pd.read_pickle(f"cache/../all_facts_{cfg['cik']}.pkl"); a = a[(a.duration_months == 3) & a.canonical.isin(["revenue", "gross_profit", "net_income"])]
        f = pd.read_pickle(f"out/{t}_fin.pkl"); f = f[(f.duration_months == 3) & f.canonical.isin(["revenue", "gross_profit", "net_income"])]   # includes derived Q4 (FY - 9M)
        V = pd.concat([a, f])[["period_end", "canonical", "value"]].assign(src="any"); V["period_end"] = pd.to_datetime(V.period_end)
    for pe, rev, gp, ni in data:
        pe = pd.Timestamp(pe)
        for can, fv in (("revenue", rev), ("gross_profit", gp), ("net_income", ni)):
            if fv is None: continue
            c = V[(V.canonical == can) & ((V.period_end - pe).abs() <= pd.Timedelta(days=10))]
            if not len(c): rows.append(dict(t=t, period=pe.date(), metric=can, fiscal=fv, ours=None, status="missing in ours")); continue
            ok = ((c.value - fv).abs() <= 0.005 * abs(fv) + 1).any()
            rows.append(dict(t=t, period=pe.date(), metric=can, fiscal=fv, ours=c.value.iloc[np.argmin((c.value - fv).abs().values)], status="match" if ok else "DIFF"))
d = pd.DataFrame(rows)
# explained differences (verified by reading the filings / Fiscal's own line items):
d.loc[(d.t == "ASML") & (d.status == "DIFF"), "status"] = "basis: Fiscal=IFRS, ours=US GAAP"
d.loc[(d.t == "AMD") & (d.status == "DIFF") & (pd.to_datetime(d.period) < "2018-01-01"), "status"] = "restated: AMD ASC 606 full retrospective (ours first-reported)"
d.loc[(d.t == "TXN") & (d.status == "DIFF") & (d.period.astype(str) == "2015-12-31") & (d.metric == "gross_profit"), "status"] = "restated: TXN 2018 10-K restated FY2015 GP 7,560 -> 7,575 (ours first-reported)"
d.to_pickle("out/xcheck_fiscal.pkl")
print(d.groupby(["t", "metric"]).status.value_counts().unstack(fill_value=0).to_string())
print(d[d.status != "match"].to_string())
