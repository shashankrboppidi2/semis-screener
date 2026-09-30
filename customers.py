"""Customer concentration (customers >= 10% of revenue) from the 10-Q/10-K text, regex only."""
import re, edgar
from earnings_docs import to_lines
SENT = re.compile(r"[^.]*?\b(customers?|Customer [A-Z])\b[^.]*?\b\d{1,2}(?:\.\d)?%[^.]*?(?:of (?:our )?total revenue|total revenue)[^.]*\.", re.I)
TABLE = re.compile(r"^(Direct |Indirect )?Customer [A-Z]\s*\|(.*)$", re.I)
def extract(cik, acc, primary):
    t = to_lines(edgar.get(edgar.doc_url(cik, acc, primary))); flat = re.sub(r"\s+", " ", t)
    pct, none = set(), False
    for m in SENT.finditer(flat):
        s = m.group(0)
        if re.search(r"accounts receivable", s, re.I) and not re.search(r"revenue from", s, re.I): continue
        if re.search(r"outside (of )?the United States|geographic|headquarter|located in|billing location", s, re.I): continue
        s2 = re.sub(r"(represent(ing|ed)?|accounted for) (\d+% or more|more than \d+%)|10% or more|more than 10%", " ", s, flags=re.I)
        pct |= {float(x) for x in re.findall(r"(\d{1,2}(?:\.\d)?)\s?%", s2) if 10 <= float(x) <= 60}
        if re.search(r"no (single )?customer (represented|accounted for) 10% or more", s, re.I): none = True
    if re.search(r"no (single |direct )?customer (represented|accounted for) 10% or more of (our )?total revenue", flat, re.I): none = True
    for l in t.splitlines():                                   # 'Customer A | 13% | *' style tables
        m = TABLE.match(l.strip())
        if m: pct |= {float(x) for x in re.findall(r"(\d{1,2}(?:\.\d)?)\s*%", m.group(2)) if 10 <= float(x) <= 60}
    return sorted(pct), none
