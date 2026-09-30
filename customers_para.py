"""Cut the customer-concentration paragraph(s) out of each 10-Q/10-K (deterministic) so the model sees ~400 tokens, not the filing."""
import re, edgar
from earnings_docs import to_lines
KEY = re.compile(r"(customers?|Customer [A-Z])\b.{0,200}?\b\d{1,2}(?:\.\d)?\s?%.{0,120}?total revenue|No (single |direct )?customer (represented|accounted for) 10% or more of (our )?total revenue|significant customers", re.I)
def paragraphs(cik, acc, primary):
    L = [l for l in to_lines(edgar.get(edgar.doc_url(cik, acc, primary))).splitlines() if l.strip()]
    keep = []
    for i, l in enumerate(L):
        if KEY.search(l) and not re.search(r"outside (of )?the United States|headquarter", l, re.I):
            keep.append(l)
            if re.match(r"^(Direct |Indirect )?Customers?\b", l) or l.rstrip().endswith(":"):   # table follows
                keep += [x for x in L[i + 1:i + 8] if "|" in x]
    seen, out = set(), []
    for k in keep:
        if k not in seen: seen.add(k); out.append(k)
    return "\n".join(out)[:4000]
