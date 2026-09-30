"""Name-agnostic segment cross-check vs Fiscal.ai: each Fiscal segment revenue / operating income value for a quarter must appear among
our segment values (any vintage, XBRL + validated model reads) for that quarter end (±10 days). Rollups Fiscal builds itself are reported separately."""
import json, re, pandas as pd, numpy as np
NM = {"Computing & Graphics": "Computing and Graphics", "Enterprise, Embedded & Semi-Custom": "Enterprise, Embedded and Semi-Custom", "Xilinx": "Xilinx", "Other Segment": "Other"}
F = json.load(open("out/fiscal_seg_raw.json")); rows = []
A = json.load(open("queue/s2/accepted.json"))
for key, t in (("NASDAQ_AMD", "AMD"), ("NASDAQ_TXN", "TXN")):
    s = pd.read_pickle(f"out/{t}_seg.pkl"); s = s[(s["axis"] == "segment") & s.name.notna()][["period_end", "duration_months", "metric", "name", "value"]]
    s = s[s.duration_months == 3]
    ps = pd.read_pickle(f"out/{t}_seg.pkl"); ps = ps[(ps["axis"] == "product_or_service+segment") & (ps.duration_months == 3)].copy()   # sub-segment split (AMD 2025+: Client / Gaming inside 'Client and Gaming')
    ps["name"] = ps.members.str.split("+").str[0]; s = pd.concat([s, ps[["period_end", "duration_months", "metric", "name", "value"]]])
    for k, v in A.items():                                   # validated model reads (AMD Q1 2022 Xilinx)
        if k.startswith(f"segments_{t}|"):
            for r in v["output"]["rows"]:
                for m in ("revenue", "operating_income"):
                    if r.get(m) is not None: s = pd.concat([s, pd.DataFrame([dict(period_end=pd.Timestamp(r["period_end"]), duration_months=r["duration_months"], metric=m, name=r["segment"], value=float(r[m]))])])
    # Q4: our segment table carries FY and 9M; derive Q4 = FY - 9M per segment name (same rule as financials)
    q = []
    for (nm, met), g in pd.read_pickle(f"out/{t}_seg.pkl").query("axis == 'segment' and name.notna()", engine="python").groupby(["name", "metric"]):
        for _, fy in g[g.duration_months == 12].iterrows():
            nine = g[(g.duration_months == 9) & ((fy.period_end - g.period_end).dt.days.between(80, 100))]
            if len(nine): q.append(dict(period_end=fy.period_end, duration_months=3, metric=met, name=nm, value=fy.value - nine.value.iloc[-1]))
    s = pd.concat([s, pd.DataFrame(q)]); s["period_end"] = pd.to_datetime(s.period_end)
    names = F[key]["names"]
    for pe, vals in F[key]["rows"]:
        pe = pd.Timestamp(pe)
        for mid, fv in vals.items():
            nm = names[mid]; met = "operating_income" if "Operating Income" in nm else "revenue"
            ours_nm = NM.get(re.sub(r" (Revenue|Operating Income)$", "", nm), re.sub(r" (Revenue|Operating Income)$", "", nm))
            c0 = s[(s.metric == met) & ((s.period_end - pe).abs() <= pd.Timedelta(days=10))]; c = c0[c0.name.str.startswith(ours_nm)]
            ok = ((c.value - fv).abs() <= 1.0).any(); anyname = ((c0.value - fv).abs() <= 1.0).any()
            rollup = nm.startswith("Total ") or (t == "AMD" and nm.startswith("Client and Gaming") and pe < pd.Timestamp("2025-01-01"))
            st = "match" if ok else ("Fiscal rollup (not a reported segment)" if rollup else None) or ("VALUE UNDER OTHER NAME (tag swap)" if anyname else None) or ("Fiscal rollup (not a reported segment)" if nm.startswith("Total ") or (t == "AMD" and nm.startswith("Client and Gaming") and pe < pd.Timestamp("2025-01-01")) else ("no segment data (ours)" if not len(c) else "DIFF"))
            rows.append(dict(t=t, period=pe.date(), fiscal_name=nm, fiscal=fv, status=st, ours_nearest=c.value.iloc[np.argmin((c.value - fv).abs().values)] if len(c) else None))
d = pd.DataFrame(rows); d.to_pickle("out/xcheck_fiscal_seg.pkl")
print(d.groupby(["t", "status"]).size().to_string()); print(d[~d.status.isin(["match", "Fiscal rollup (not a reported segment)"])].to_string())
