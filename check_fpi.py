"""ASML-type validator: 4 quarters (6-K) must sum to the 20-F annual figure — compared only against a 20-F filed within 4 months of year end (later 20-Fs may be restated)."""
import pandas as pd, sys
t = sys.argv[1]; fin = pd.read_pickle(f"out/{t}_fin.pkl"); allf = pd.read_pickle(f"cache/../all_facts_{__import__('json').load(open(f'config/{t}.json'))['cik']}.pkl")
d = pd.read_pickle(f"out/{t}_q.pkl"); d["year"] = pd.to_datetime(d.period_end).dt.year; rows = []
P = pd.read_pickle(f"out/{t}_q_printings.pkl"); P["filed"] = pd.to_datetime(P.filed); P["period_end"] = pd.to_datetime(P.period_end)
def asof(can, pe, when):
    """value of a quarter as printed most recently on or before `when` (restated prior quarters included); else first reported"""
    p = P[(P.period_end == pe) & (P.filed <= when)].dropna(subset=[can]).sort_values("filed")
    return p[can].iloc[-1] if len(p) else d.loc[pd.to_datetime(d.period_end) == pe, can].iloc[0]
for can in ["revenue", "net_income", "gross_profit"]:
    a = allf[(allf.canonical == can) & (allf.duration_months == 12)]
    for y, r in d.groupby("year")[can].agg(["sum", "count"]).iterrows():
        orig = a[(a.period_end.dt.year == y) & ((a.filed - a.period_end).dt.days <= 125)]
        if r["count"] != 4: continue
        if len(orig): r["sum"] = sum(asof(can, pe, orig.filed.iloc[0]) for pe in pd.to_datetime(d[d.year == y].period_end))
        if not len(orig): rows.append(dict(metric=can, year=y, quarters=r["sum"], annual_20F=None, status="no original 20-F in XBRL (later 20-F may be restated) — not compared")); continue
        v = orig.value.iloc[0]; ok = abs(r["sum"] - v) <= 0.002 * abs(v) + 1.0
        rows.append(dict(metric=can, year=y, quarters=r["sum"], annual_20F=v, status="ok" if ok else f"MISMATCH {r['sum'] - v:+.1f}"))
c = pd.DataFrame(rows); print(c.status.str.split().str[0].value_counts().to_dict()); print(c[c.status != "ok"].to_string())
