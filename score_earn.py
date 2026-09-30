import pandas as pd, numpy as np, duckdb, json
cfg = json.load(open("config/NVDA.json")); e = pd.read_pickle("nvda_earn.pkl"); x = pd.read_pickle("nvda_xbrl_fin.pkl")
db = duckdb.connect("../nvda/db/nvda.duckdb", read_only=True)
qe = sorted(set(x[(x.canonical == "revenue") & (x.duration_months == 3)].period_end))            # fiscal calendar from XBRL
fye = 1   # NVIDIA fiscal year ends in January (submissions: fiscalYearEnd 0131)
def label_to_pe(q, fy):
    approx = pd.Timestamp(year=fy, month=fye, day=28) - pd.DateOffset(months=3 * (4 - q))
    c = min(qe, key=lambda d: abs((d - approx).days)); return c if abs((c - approx).days) <= 20 else approx.normalize()
P = e["P"].dropna(subset=["fiscal_year"]).copy(); P["period_end"] = [label_to_pe(int(q), int(y)) for q, y in zip(P.fiscal_quarter, P.fiscal_year)]
P = P.sort_values(["filed", "column"]).groupby(["platform", "period_end"]).head(1)                  # first reported
g = db.execute("select platform, period_end, revenue_usd_m from core.fct_platform_revenue where basis='as_first_reported' and duration_months=3 and platform_level like 'market platform%'").df(); g["period_end"] = pd.to_datetime(g.period_end)
m = P.merge(g, on="platform"); m = m[(m.period_end_x - m.period_end_y).dt.days.abs() <= 10]
m["match"] = (m.value - m.revenue_usd_m).abs() < 0.5
print(f"PLATFORM revenue (first reported): {len(m)} paired, match {m.match.mean():.4f}; gold platform-quarters {len(g)}, script covers {len(m)/len(g):.3f}")
print(m[~m.match][["platform", "period_end_x", "value", "revenue_usd_m", "filed"]].to_string())
# headline revenue vs gold results-day revenue
H = e["H"].copy(); H["filed"] = pd.to_datetime(H.filed); H["period_end"] = [max([d for d in qe if d < f and (f - d).days < 70], default=pd.NaT) for f in H.filed]
gh = db.execute("select period_end, value from core.fct_earnings_headline where metric='revenue' and duration_months=3").df(); gh["period_end"] = pd.to_datetime(gh.period_end)
mh = H.merge(gh, on="period_end"); mh["match"] = (mh.revenue - mh.value).abs() < 0.5
print(f"HEADLINE revenue: {len(mh)} paired, match {mh.match.mean():.4f}")
# guidance: script value vs any value printed in the press release or CFO commentary for that target quarter (gold)
G = e["G"].copy(); G["filed"] = pd.to_datetime(G.filed)
G["target"] = [min([d for d in qe if d > pe], default=pe + pd.Timedelta(days=91)) if pd.notna(pe) else pd.NaT for pe in [max([d for d in qe if d < f and (f - d).days < 70], default=pd.NaT) for f in G.filed]]
gg = db.execute("select period_end as target, canonical, coalesce(basis,'n/a') as basis, value from int.earnings_doc_fact_dated where section='guidance'").df(); gg["target"] = pd.to_datetime(gg.target)
MAP = {"revenue_guidance_mid": ("revenue_guidance_mid", "n/a"), "revenue_guidance_plus_minus_pct": ("revenue_guidance_plus_minus_pct", "n/a"), "gm_gaap": ("gross_margin_guidance_mid_pct", "GAAP"),
       "gm_nongaap": ("gross_margin_guidance_mid_pct", "non-GAAP"), "opex_gaap": ("opex_guidance", "GAAP"), "opex_nongaap": ("opex_guidance", "non-GAAP")}
rows = []
for r in G.itertuples(index=False):
    for k, (can, bas) in MAP.items():
        v = getattr(r, k, np.nan)
        if pd.isna(v): continue
        cand = gg[(gg.canonical == can) & (gg.basis == bas) & ((gg.target - r.target).dt.days.abs() <= 10)].value.tolist()
        rows.append(dict(target=r.target, metric=k, script=v, gold_values=sorted(set(cand)), match=any(abs(v - c) < 0.01 for c in cand), gold_has=bool(cand)))
gv = pd.DataFrame(rows); gv2 = gv[gv.gold_has]
print(f"GUIDANCE: {len(gv2)} paired values, match {gv2.match.mean():.4f}"); print(gv2.groupby("metric").match.agg(["size", "mean"]).round(4).to_string())
print(gv2[~gv2.match].to_string())
pd.to_pickle(dict(plat=m, head=mh, guid=gv), "score_earn.pkl")
