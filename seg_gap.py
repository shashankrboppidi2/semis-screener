"""Segment-gap fallback. For a filing x period whose XBRL segments fail the add-up, cut the segment table from the filing text
(rows around the mapped segment names, ~40 lines) and queue it for Haiku. Answers are accepted only if every number appears in the
text AND the segments sum to the XBRL consolidated revenue; otherwise escalated to Sonnet."""
import re, json, sys, pandas as pd, edgar, llm_fallback as LF
from earnings_docs import to_lines
LF.SYSTEM["segments"] = """You read a segment table from a company's 10-Q/10-K. Return ONLY JSON:
{"rows":[{"segment":"<name as printed>","period_end":"YYYY-MM-DD","duration_months":3|6|9|12,"revenue":<number or null>,"operating_income":<number or null>}],"units":"millions"|"thousands"}
One row per reportable segment (and 'All Other' if printed) per column. Skip total rows. Parentheses = negative. Copy numbers exactly; never compute."""
def cut(cik, acc, primary, names):
    L = [l for l in to_lines(edgar.get(edgar.doc_url(cik, acc, primary))).splitlines() if l.strip()]
    pat = re.compile(r"^(" + "|".join(re.escape(n) for n in names) + r")\b", re.I)
    for i, l in enumerate(L):                          # first block where >= 2 segment names head table rows within 12 lines
        if "|" in l and pat.match(l) and sum(bool(pat.match(x)) and "|" in x for x in L[i:i + 12]) >= 2 \
           and re.search(r"net revenue|revenue:|net sales|revenue by segment", " ".join(L[max(0, i - 4):i + 1]), re.I) and len(" ".join(L[max(0, i - 4):i])) < 1500:
            s = max(0, i - 4); e = i + 1
            while e < len(L) and e < i + 30 and ("|" in L[e] or len(L[e]) < 60): e += 1
            return "\n".join(L[s:e])
    return ""
if __name__ == "__main__":
    t = sys.argv[1]; cfg = json.load(open(f"config/{t}.json")); cik = cfg["cik"]; j, rows = edgar.submissions(cik); prim = {r["accessionNumber"]: r for r in rows}
    rep = pd.read_pickle(f"out/{t}_addup.pkl"); bad = rep[rep.issue.str.startswith("sum ") & (rep.issue != "sum ok")]
    names = sorted(set(cfg["member_map"].values()) | set(cfg["member_map"]), key=len, reverse=True); items = []
    for acc, g in bad.groupby("accn"):
        r = prim[acc]; txt = cut(cik, acc, r["primaryDocument"], names)
        items.append(dict(id=acc, text=f"[{r['form']} for period ending {r['reportDate']}]\n{txt}"))
    LF.enqueue(f"segments_{t}", items); print(t, len(items), "segment-gap reads queued, ~%d tokens" % sum(LF.approx_tokens(i["text"]) for i in items))
