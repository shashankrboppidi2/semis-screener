import pandas as pd, duckdb, json, numpy as np
x = pd.read_pickle("out/NVDA_seg.pkl")   # names resolved from each filing's own label linkbase
x = x[x.name.notna() & x["axis"].isin(["segment", "product_or_service"])].copy()
x["section"] = np.where(x["axis"] == "segment", "segment", "market_platform")
x["canonical"] = np.where(x.section == "market_platform", "platform_revenue", np.where(x.metric == "revenue", "segment_revenue", "segment_operating_income"))
g = duckdb.connect("../nvda/db/nvda.duckdb", read_only=True).execute("""select segment as name, canonical_metric as canonical, cast(period_end as date) as period_end, duration_months, value, filing_id as accn
  from int.filing_value_vintages where section in ('segment','market_platform') and segment <> ''""").df(); g["period_end"] = pd.to_datetime(g.period_end)
m = x.drop_duplicates(["name", "canonical", "period_end", "duration_months", "accn"]).merge(g, on=["name", "canonical", "duration_months", "accn"], suffixes=("_x", "_g"))
m = m[(m.period_end_x - m.period_end_g).dt.days.abs() <= 7]
m["match"] = (m.value_x - m.value_g).abs() <= np.maximum(0.0015, 0.0005 * m.value_g.abs())
print("paired:", len(m), "match:", round(m.match.mean(), 4)); print(m.groupby(["canonical", "name"]).match.agg(["size", "mean"]).round(3).to_string())
print(m[~m.match][["canonical", "name", "period_end_x", "duration_months", "value_x", "value_g", "accn"]].head(20).to_string())
# coverage: gold values (first reported, 3-month) that XBRL can't supply at all
gf = duckdb.connect("../nvda/db/nvda.duckdb", read_only=True).execute("""select segment_name as name, metric as canonical, period_end, section from core.fct_segment_value where source='sec_filing_extraction' and duration_months=3 and method='printed'""").df()
gf["period_end"] = pd.to_datetime(gf.period_end); have = set(zip(x.name, x.canonical, x.period_end.dt.to_period("M")))
gf["xbrl_has"] = [((n, c, p.to_period("M")) in have) or ((n, c, (p + pd.Timedelta(days=5)).to_period("M")) in have) or ((n, c, (p - pd.Timedelta(days=5)).to_period("M")) in have) for n, c, p in zip(gf.name, gf.canonical, gf.period_end)]
gf["era"] = np.where(gf.period_end < "2010-07-01", "pre-FY2011", "FY2011+")
print(gf.groupby(["section", "era"]).xbrl_has.agg(["size", "mean"]).round(3))
