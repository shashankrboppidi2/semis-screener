"""Generic customer-concentration step: cut the paragraph(s) from each 10-Q/10-K (regex, no model), queue them for Haiku.
Filings with no concentration wording are skipped entirely (0 tokens)."""
import re, json, sys, edgar, llm_fallback as LF
from earnings_docs import to_lines
REV = r"(?:total |net |consolidated )?(?:net )?(?:revenue|revenues|sales)"
KEY = re.compile(rf"(customers?|Customer [A-Z]|distributors?)\b.{{0,250}}?\b\d{{1,2}}(?:\.\d)?\s?%.{{0,160}}?\b{REV}\b"
                 rf"|\b\d{{1,2}}(?:\.\d)?\s?% of (?:our )?{REV}.{{0,120}}?\b(customers?|Customer [A-Z])\b"
                 rf"|No (single |one |direct )?(customer|end customer)s? (represented|accounted for|exceeded) (10%|ten percent)"
                 , re.I)
HEAD = re.compile(r"^(Major|Significant) customers?\s*$", re.I)
SKIP = re.compile(r"outside (of )?the United States|headquarter|billing location|shipments to|shipped to|[A-Z][a-z]+-based customers|revenue was direct|through distributors|loss of a significant customer", re.I)
def paragraphs(cik, acc, primary):
    L = [l for l in to_lines(edgar.get(edgar.doc_url(cik, acc, primary))).splitlines() if l.strip()]
    keep = []
    for i, l in enumerate(L):
        if HEAD.match(l.strip()): keep += L[i:i + 2]; continue
        if KEY.search(l) and not SKIP.search(l) and len(l) < 3000:
            keep.append(l)
            if l.rstrip().endswith(":") or re.match(r"^(Direct |Indirect )?Customers?\b", l):
                keep += [x for x in L[i + 1:i + 8] if "|" in x]
    seen, out = set(), []
    for k in keep:
        if k not in seen: seen.add(k); out.append(k)
    return "\n".join(out)[:4000]
if __name__ == "__main__":
    t = sys.argv[1]; cfg = json.load(open(f"config/{t}.json")); cik = cfg["cik"]; j, rows = edgar.submissions(cik)
    CHAIN = cfg.get("cik_chain", [cik])                      # predecessor registrants keep their own filings
    if len(CHAIN) > 1:
        rows = [dict(x, cik=_c) for _c in CHAIN for x in edgar.submissions(_c)[1]]
    for x in rows: x.setdefault("cik", cik)
    fs = sorted([r for r in rows if r["form"] in ("10-Q", "10-K") and r["filingDate"] >= "2011-01-01"], key=lambda r: r["filingDate"])
    items, empty = [], []
    for r in fs:
        p = paragraphs(r.get("cik", cik), r["accessionNumber"], r["primaryDocument"])
        hdr = f"[{r['form']} for period ending {r['reportDate']}]\n"
        (items.append(dict(id=r["accessionNumber"], text=hdr + p)) if p else empty.append(r["accessionNumber"]))
    LF.enqueue(f"customers_{t}", items)
    tok = sum(LF.approx_tokens(i["text"]) for i in items)
    print(t, len(fs), "filings |", len(items), "with concentration text queued (~%d input tokens) |" % tok, len(empty), "with none (skipped)")
