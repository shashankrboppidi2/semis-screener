"""Validator: results-day revenue must equal the 10-Q/10-K revenue (XBRL, first reported) for the same quarter."""
import pandas as pd, sys
t = sys.argv[1]; H = pd.read_pickle(f"out/{t}_earn.pkl")["H"]; fin = pd.read_pickle(f"out/{t}_fin.pkl")
q = fin[(fin.canonical == "revenue") & (fin.duration_months == 3) & (fin.basis == "as_first_reported")].drop_duplicates("period_end").set_index("period_end").value
H["filed"] = pd.to_datetime(H.filed); cal = sorted(q.index)
H["period_end"] = [max([d for d in cal if d < f and (f - d).days < 75], default=pd.NaT) for f in H.filed]
H["xbrl_rev"] = H.period_end.map(q)
r = H.revenue / H.xbrl_rev; H.loc[(r > 0.0009) & (r < 0.0011), "revenue"] = H.revenue * 1000     # printed in billions without a unit label
h = H.dropna(subset=["revenue", "xbrl_rev"]).copy()
h["ok"] = (h.revenue - h.xbrl_rev).abs() <= h.xbrl_rev * 0.003 + 0.5     # tolerance covers $1.93B-style rounding
print(f"{t}: results-day revenue vs 10-Q revenue: {int(h.ok.sum())}/{len(h)} agree; {int(H.revenue.isna().sum())} releases without a readable revenue row")
H["revenue_verified"] = H.index.isin(h[h.ok].index); H.to_pickle(f"out/{t}_headline_checked.pkl")
print(h[~h.ok][["filed", "period_end", "revenue", "xbrl_rev"]].to_string() if (~h.ok).any() else "")
