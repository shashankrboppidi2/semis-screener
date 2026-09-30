"""TXN end-market mix (10-K 'Markets for our products' chart) -> Haiku queue; China share -> regex. Deterministic cut, ~500 tokens per 10-K."""
import re, json, edgar, pandas as pd, llm_fallback as LF
from earnings_docs import to_lines
LF.SYSTEM["endmarkets"] = """You read the 'markets for our products' chart from a Texas Instruments 10-K (table text flattened; a market's percentage may appear next to its first sector). Return ONLY JSON:
{"year":<fiscal year the percentages refer to>,"basis":"TI revenue"|"product revenue"|"other: <as written>","markets":[{"market":"<market name as printed>","pct":<number>}]}
One row per MARKET (e.g. Industrial, Automotive, Personal electronics, Communications equipment, Enterprise systems, Data center, Other, Computing, Education). Never list sectors as markets. Copy numbers exactly; never compute."""
CH = re.compile(r"[^.]*China[^.]*?(\d{1,2})\s?(%|percent) of (our )?revenue[^.]*\.", re.I)
def run():
    j, rows = edgar.submissions(97476)
    ks = sorted([r for r in rows if r["form"] == "10-K" and r["filingDate"] >= "2011-01-01"], key=lambda r: r["filingDate"])
    items, china = [], []
    for r in ks:
        t = re.sub(r"\s+", " ", to_lines(edgar.get(edgar.doc_url(97476, r["accessionNumber"], r["primaryDocument"]))))
        m = re.search(r"(estimated percentage of our \d{4} (product )?revenue|Markets for our products|Market Characteristics|end markets? (and|for) )", t, re.I)
        m2 = [x for x in re.finditer(r"\((\d{1,2})% of (TI|product) revenue\)", t)]
        if m2:
            s = max(0, m2[0].start() - 700); e = m2[-1].end() + 250
            items.append(dict(id=r["accessionNumber"], text=f"[10-K for fiscal year {r['reportDate'][:4]}]\n" + t[s:e][:3500]))
        for c in CH.finditer(t):
            sent = c.group(0).strip()
            for cl in re.split(r";|, while |\. ", sent):          # one measure per clause
                m = re.search(r"(\d{1,2})\s?(%|percent) of (our )?revenue", cl)
                if not m or "China" not in cl: continue
                meas = "shipped into China" if re.search(r"shipped into China|shipments (in)?to China\b", cl) else "customers HQ in China" if re.search(r"headquartered in China", cl) else "shipments to China-based customers" if re.search(r"China-based customers", cl) else None
                if meas: china.append(dict(accn=r["accessionNumber"], filed=r["filingDate"], year=int(r["reportDate"][:4]), pct=float(m.group(1)), measure=meas, text=cl.strip()[:250]))
    LF.enqueue("endmarkets_TXN", items)
    pd.DataFrame(china).drop_duplicates(["year", "measure", "pct"]).to_pickle("out/TXN_china.pkl")
    print(len(ks), "10-Ks |", len(items), "end-market cuts queued (~%d tokens)" % sum(LF.approx_tokens(i["text"]) for i in items), "| China sentences:", len(china))
if __name__ == "__main__": run()
