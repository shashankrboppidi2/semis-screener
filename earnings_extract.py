"""Deterministic extraction from earnings exhibits: platform revenue table, headline figures, guidance (regex). Anything the regexes can't read is queued for a small model."""
import re, pandas as pd
from earnings_docs import nums
MULT = {"billion": 1000.0, "million": 1.0}
def money(v, unit): return float(v.replace(",", "")) * MULT[unit.lower()]
WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "half a": "0.5", "one-half": "0.5"}
def normalise(t):
    for w, d in WORDS.items(): t = re.sub(rf"plus or minus {w} (percent|%)", f"plus or minus {d}%", t, flags=re.I)
    return re.sub(r"\s*percent\b", "%", t)
QL = re.compile(r"Q([1-4])\s*(?:FY|Fiscal)\s*'?(\d{2,4})", re.I)
def header_periods(line):
    return [(int(q), 2000 + int(y) if len(y) == 2 else int(y)) for q, y in QL.findall(line)]
def platform_table(text, cfg):
    lines = text.splitlines(); out = []
    for i, l in enumerate(lines):
        if not re.search(cfg["platform_table_header"], l, re.I): continue
        hdr = next((h for h in lines[i + 1:i + 4] if header_periods(h)), None); per = header_periods(hdr) if hdr else []
        for r in lines[i + 1:i + 16]:
            cells = [c.strip() for c in r.split("|")]
            if cells[0].lower().startswith("total"): break
            lab = re.sub(r"\s*\(\d\)$", "", cells[0]); name = cfg["platform_labels"].get(lab)
            v = [x for x in (nums(c) for c in cells[1:]) if x]
            if not name or not v: continue
            for k, vals in enumerate(v[:len(per) or 1]):
                fq = per[k] if per else None
                out.append(dict(platform=name, label=lab, value=vals[0], fiscal_quarter=fq[0] if fq else None, fiscal_year=fq[1] if fq else None, column=k))
        if out: break
    return out
def headline(text):
    out = {}; gm = []
    for l in text.splitlines():
        cells = [c.strip() for c in l.split("|")]
        if len(cells) < 2: continue
        m = re.match(r"^(?:Net |Total )?(?:revenues?|net sales)\s*(\((\$B|\$M|\$ in millions|in millions|\$ in billions)\))?\s*$", cells[0], re.I)
        if m and "revenue" not in out:
            v = nums(cells[1])
            if v: out["revenue"] = v[0] * (1000 if m.group(2) and "B" in m.group(2).upper().replace("BILLIONS", "B") and "M" not in m.group(2).upper().replace("BILLIONS", "") else 1)
        if cells[0] == "Gross margin" and len(gm) < 2:
            v = re.findall(r"[\d.]+", cells[1]); gm.append(float(v[0]) if v else None)
    if gm: out["gross_margin_gaap"] = gm[0]
    if len(gm) > 1: out["gross_margin_nongaap"] = gm[1]
    return out
G = [  # (metric, regex, handler) — NVIDIA outlook sentences, 2015-2026 wording variants
 ("revenue", r"Revenue is expected to be \$([\d.,]+)\s*(billion|million),? plus or minus (\d+(?:\.\d+)?)\s*(?:%|percent)", lambda m: {"revenue_guidance_mid": money(m[1], m[2]), "revenue_guidance_plus_minus_pct": float(m[3])}),
 ("gm", r"GAAP and non-GAAP gross margins are expected to be ([\d.]+)\s*(?:%|percent) and ([\d.]+)\s*(?:%|percent),? respectively(?:,? plus or minus (\d+) basis points)?", lambda m: {"gm_gaap": float(m[1]), "gm_nongaap": float(m[2]), **({"gm_pm_bps": float(m[3])} if m[3] else {})}),
 ("gm2", r"GAAP and non-GAAP gross margins are expected to be ([\d.]+)\s*%(?:,? plus or minus (\d+) basis points)?", lambda m: {"gm_gaap": float(m[1]), "gm_nongaap": float(m[1]), **({"gm_pm_bps": float(m[2])} if m[2] else {})}),
 ("gm1", r"GAAP gross margins? (?:is|are) expected to be ([\d.]+)\s*(?:%|percent).{0,80}?non-GAAP gross margins? (?:is|are) expected to be ([\d.]+)\s*(?:%|percent)", lambda m: {"gm_gaap": float(m[1]), "gm_nongaap": float(m[2])}),
 ("opex", r"GAAP and non-GAAP operating expenses are expected to be (?:approximately )?\$([\d.,]+)\s*(billion|million) and \$([\d.,]+)\s*(billion|million)", lambda m: {"opex_gaap": money(m[1], m[2]), "opex_nongaap": money(m[3], m[4])}),
 ("opex1", r"GAAP operating expenses are expected to be (?:approximately )?\$([\d.,]+)\s*(billion|million).{0,120}?non-GAAP operating expenses are expected to be (?:approximately )?\$([\d.,]+)\s*(billion|million)", lambda m: {"opex_gaap": money(m[1], m[2]), "opex_nongaap": money(m[3], m[4])}),
]
def guidance(text):
    L = text.splitlines()
    i = [k for k, l in enumerate(L) if re.search(r"outlook for the .{0,60}? is as follows", l, re.I)] or [k for k, l in enumerate(L) if re.match(r"^\s*(Outlook|[A-Z][\w ]{0,50} Outlook)\s*$", l) and not re.search(r"RECONCILIATION|^Q\d|^FY", l)]
    if not i: return {}, ["NO OUTLOOK SECTION"]
    sec = normalise(re.sub(r"\s+", " ", " ".join(L[i[0]:i[0] + 12])))
    out, got = {}, set()
    for name, rx, fn in G:
        base = name.rstrip("12")
        if base in got: continue
        m = re.search(rx, sec, re.I)
        if m: out.update(fn(m)); got.add(base)
    missing = [b for b in ("revenue", "gm", "opex") if b not in got]
    return out, missing

def outlook_reconciliation(text):
    """Exact figures from the 'RECONCILIATION OF GAAP TO NON-GAAP OUTLOOK' table (the outlook sentence is often rounded)."""
    L = text.splitlines(); i = [k for k, l in enumerate(L) if re.search(r"RECONCILIATION OF GAAP TO NON-GAAP OUTLOOK", l, re.I)]
    if not i: return {}
    out = {}; block = L[i[0]:i[0] + 30]; scale = 1000.0 if any(re.search(r"in billions", b, re.I) for b in block) else 1.0
    for l in block:
        c = [x.strip() for x in l.split("|")]
        if len(c) < 2: continue
        v = nums(c[1])
        if not v: continue
        if re.match(r"^GAAP operating expenses", c[0], re.I) and "opex_gaap" not in out: out["opex_gaap"] = v[0] * scale
        elif re.match(r"^Non-GAAP operating expenses", c[0], re.I) and "opex_nongaap" not in out: out["opex_nongaap"] = v[0] * scale
    return out
