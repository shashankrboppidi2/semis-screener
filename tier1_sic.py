"""Industry (SIC) for the filers that clear the tier-1 gate. One submissions request each, so it
runs only over the gated shortlist rather than all 8,447 filers in the panel."""
import edgar, json, pandas as pd, numpy as np
from tier1_screen import CURRENT
P = pd.read_pickle("out/tier1_panel.pkl")
L = P.dropna(subset=["b2b"]).sort_values("cqp").groupby("cik").tail(1)
L = L[(L.rpo_cover_q >= 1.0) & (L.rev >= 25) & (L.cqp >= CURRENT)]
rows = []
for cik in L.cik.unique():
    try:
        j, _ = edgar.submissions(int(cik))
        rows.append(dict(cik=cik, sic=j.get("sic"), sic_desc=j.get("sicDescription"),
                         ticker=(j.get("tickers") or [None])[0], name=j.get("name"),
                         fy_end=j.get("fiscalYearEnd")))
    except Exception as e:
        rows.append(dict(cik=cik, sic=None, sic_desc=f"{type(e).__name__}"))
d = pd.DataFrame(rows); d.to_pickle("out/tier1_sic.pkl")
print("fetched", len(d), "| with SIC:", d.sic.notna().sum(), "| with ticker:", d.ticker.notna().sum())
print(d.sic_desc.value_counts().head(15).to_string())
