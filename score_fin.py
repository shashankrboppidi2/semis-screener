import pandas as pd, duckdb, numpy as np
x = pd.read_pickle("nvda_xbrl_fin.pkl"); x = x[~x.concept.str.contains("FY-9M")]
g = duckdb.connect("../nvda/db/nvda.duckdb", read_only=True).execute("""select canonical_metric as canonical, cast(period_end as date) as period_end, duration_months, value, filing_id as accn from int.filing_value_vintages
   where section in ('income_statement','balance_sheet')""").df()
g["period_end"] = pd.to_datetime(g.period_end)
# every (metric, period, duration) printed in a given filing, both sides
xa = x.drop_duplicates(["canonical", "period_end", "duration_months", "accn"])
m = xa.merge(g, on=["canonical", "duration_months", "accn"], suffixes=("_x", "_g"))
m = m[(m.period_end_x - m.period_end_g).dt.days.abs() <= 7]
m["tol"] = np.where(m.canonical.str.startswith("eps"), 0.0051, np.maximum(0.0015, 0.0005 * m.value_g.abs()))
m["match"] = (m.value_x - m.value_g).abs() <= m.tol
print("paired values (same filing, metric, period, duration):", len(m), "match:", round(m.match.mean(), 4))
print(m.groupby("canonical").match.agg(["size", "mean"]).round(4).to_string())
bad = m[~m.match][["canonical", "concept", "period_end_x", "duration_months", "value_x", "value_g", "accn"]].sort_values(["canonical", "period_end_x"])
print(bad.head(40).to_string()); m.to_pickle("score_fin.pkl")
