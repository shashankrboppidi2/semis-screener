"""Generic earnings stage: headline revenue + guidance (pattern library; misses queued for Haiku). Usage: python3 run_earnings2.py TICKER"""
import edgar, earnings_docs as E, earnings_extract as X, guidance_generic as GG, llm_fallback as LF, json, pandas as pd, sys, re
t = sys.argv[1]; cfg = json.load(open(f"config/{t}.json")); cik = cfg["cik"]; start = cfg.get("start_period", "2010-04-01")
j, rows = edgar.submissions(cik)
CHAIN = cfg.get("cik_chain", [cik])
if len(CHAIN) > 1:
    rows = []
    for _c in CHAIN: rows += [dict(x, cik=_c) for x in edgar.submissions(_c)[1]]
rows = [dict(x) if isinstance(x, dict) else x for x in rows]
for x in rows: x.setdefault("cik", cik)
forms = cfg.get("earnings_forms", ["8-K"])
er = sorted([r for r in rows if r["form"] in forms and (r["form"] != "8-K" or "2.02" in r.get("items", "")) and r["filingDate"] >= start], key=lambda r: r["filingDate"])
H, G, Q, skipped = [], [], [], []
for r in er:
    x = E.exhibits(r.get("cik", cik), r["accessionNumber"]); keys = sorted(k for k in x if k.startswith("EX-99"))
    pr = x.get("EX-99.1") or x.get("EX-99") or (x[keys[0]] if keys else ""); cfo = x.get("EX-99.2", "")
    if not pr or not re.search(cfg.get("results_marker", r"(quarter|results)"), pr[:3000], re.I): skipped.append(r["filingDate"]); continue
    h = X.headline(pr) or X.headline(cfo)
    g, otext, has_rev = GG.read(pr)
    if not has_rev and cfo: g2, ot2, hr2 = GG.read(cfo); g, otext, has_rev = (g2, ot2, hr2) if hr2 else (g, otext, has_rev)
    H.append(dict(filed=r["filingDate"], accn=r["accessionNumber"], **h)); G.append(dict(filed=r["filingDate"], accn=r["accessionNumber"], outlook=otext, **g))
    if not has_rev: Q.append(dict(id=r["accessionNumber"], text=GG.model_text(pr + "\n" + (cfo or ""))))
pd.to_pickle(dict(H=pd.DataFrame(H), G=pd.DataFrame(G)), f"out/{t}_earn.pkl")
LF.enqueue(f"guidance_{t}", Q)
print(t, len(er), "releases;", len(skipped), "skipped (no results text);", len(H), "parsed |", sum(1 for h in H if h.get("revenue")), "headline revenues |",
      sum(1 for g in G if any(k.startswith("revenue_") for k in g)), "revenue guides by regex |", len(Q), "queued for Haiku (~", sum(LF.approx_tokens(q["text"]) for q in Q), "tokens)")
print(pd.DataFrame(G).drop(columns=["outlook"]).tail(6).to_string())
