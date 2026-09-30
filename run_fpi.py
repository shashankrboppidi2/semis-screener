import edgar, earnings_docs as E, fpi_quarterly as F, guidance_generic as GG, llm_fallback as LF, json, pandas as pd, sys, re
t = sys.argv[1]; cfg = json.load(open(f"config/{t}.json")); cik = cfg["cik"]
if not cfg.get("row_labels"):
    # A foreign private issuer's quarterly figures live in its 6-K results tables, whose row labels differ per filer. Without a
    # row_labels map there is nothing deterministic to read, so that ticker's workbook carries 20-F annual figures only.
    print(f"{t}: no results-table row_labels configured for this filer — quarterly extraction skipped (annual 20-F figures still load)"); sys.exit(0)
j, rows = edgar.submissions(cik)
P = []
k6 = sorted([r for r in rows if r["form"] == "6-K" and r["filingDate"] >= cfg["start_period"]], key=lambda r: r["filingDate"]); out, G, Q = [], [], []
for r in k6:
    x = E.exhibits(cik, r["accessionNumber"]); allt = "\n".join(x.values())
    if not (re.search(r"net sales", allt[:8000], re.I) and re.search(r"(results|reports)", allt[:3000], re.I)): continue
    (qend, q, fy), vals, how = F.extract(x, cfg, r["filingDate"])
    P += [dict(filed=r["filingDate"], accn=r["accessionNumber"], period_end=pe, **pv) for pe, pv in F.printings(x, cfg)]
    out.append(dict(filed=r["filingDate"], accn=r["accessionNumber"], period_end=qend, q=q, fy=fy, method=how, **vals))
    g, ot, has = GG.read(x.get("EX-99.1", allt)); G.append(dict(filed=r["filingDate"], accn=r["accessionNumber"], period_end=qend, outlook=ot, **g))
    if not has: Q.append(dict(id=r["accessionNumber"], text=GG.model_text(x.get("EX-99.1", allt))))
d = pd.DataFrame(out).sort_values("filed").drop_duplicates(["period_end"]); d.to_pickle(f"out/{t}_q.pkl"); pd.DataFrame(P).to_pickle(f"out/{t}_q_printings.pkl"); Gd = pd.DataFrame(G).sort_values("filed").drop_duplicates("period_end"); Gd.to_pickle(f"out/{t}_guid.pkl")
Q = [q for q in Q if q["id"] in set(Gd.accn) and q["id"] in set(Gd[~Gd.filter(regex="^revenue_").notna().any(axis=1)].accn)]; LF.enqueue(f"guidance_{t}", Q, system=LF.SYSTEM["guidance_eur"] if cfg.get("currency") == "EUR" else None)
print(t, len(d), "quarters", d.period_end.min().date(), "->", d.period_end.max().date(), "| method:", d.method.value_counts().to_dict())
print("coverage:", {c: int(d[c].notna().sum()) for c in ["revenue", "system_sales", "gross_profit", "net_income", "bookings", "operating_income"] if c in d})
print("guidance by regex:", int(Gd.filter(regex="^revenue_").notna().any(axis=1).sum()), "of", len(Gd), "quarters | queued for Haiku:", len(Q))
P = pd.DataFrame(P); print("printings:", len(P), "| quarters restated in a later release:", int(P.groupby("period_end").revenue.nunique().gt(1).sum() + P.groupby("period_end").net_income.nunique().gt(1).sum()), "(revenue+NI)")
