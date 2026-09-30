"""Foreign private issuers (20-F + 6-K): quarterly figures from the results release. Deterministic rules:
   - the reported quarter is the calendar/fiscal quarter that ended just before the 6-K filing date;
   - values come from the US-GAAP 'Quarterly Summary' (quarters in date order -> last column = reported quarter),
     else from any table whose header ends with that quarter's label (e.g. '| Q1 2026 | Q2 2026')."""
import re, pandas as pd
from earnings_docs import nums
def reported_quarter(filed, fye_month=12):
    f = pd.Timestamp(filed); qe = [pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0) for y in (f.year - 1, f.year) for m in (3, 6, 9, 12)]
    qe = [q for q in qe if q < f - pd.Timedelta(days=5)]; q = max(qe)
    return q, ((q.month - fye_month - 1) % 12) // 3 + 1, q.year if q.month <= fye_month else q.year + 1
def _rows(lines, row_labels, ncols=None, from_right=0):
    vals = {}
    for r in lines:
        cells = [c.strip() for c in r.split("|")]; lab = re.sub(r"\s*[\d,]+$", "", cells[0]).strip(); can = row_labels.get(lab)
        v = [nums(c)[0] for c in cells[1:] if nums(c)]
        if can and len(v) > from_right and can not in vals and (ncols is None or len(v) >= ncols): vals[can] = v[-1 - from_right]
    return vals
MD = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? ?(\d{1,2})", re.I)
def header_dates(lines):
    """Column dates from a header split over two rows ('Mar 27, | Dec 31, | ...' then '... | 2011 | 2010 | ...'), or one row."""
    for i, l in enumerate(lines[:6]):
        md = MD.findall(l)
        if len(md) >= 2:
            yrs = re.findall(r"(20\d\d)(?!\d)", l)  # footnote digits can be glued on: "Jun 30, 42013"
            if len(yrs) < len(md) and i + 1 < len(lines): yrs = re.findall(r"(20\d\d)(?!\d)", lines[i + 1])
            if len(yrs) >= len(md):
                yrs = yrs[-len(md):]
                try: return [pd.Timestamp(f"{m[:3]} {d} {y}") for (m, d), y in zip(md, yrs)]
                except Exception: return None
    return None
def _strict(lines, row_labels, ncol, idx):
    """Only rows with exactly ncol values are used, so a column can never shift."""
    vals = {}
    for r in lines:
        cells = [c.strip() for c in r.split("|")]; can = row_labels.get(re.sub(r"\s*[\d,]+$", "", cells[0]).strip())
        v = [nums(c)[0] for c in cells[1:] if nums(c)]
        if can and len(v) == ncol and can not in vals: vals[can] = v[idx]
    return vals
def extract(exhibits, cfg, filed):
    qend, q, fy = reported_quarter(filed, cfg.get("fye_month", 12))
    gaap = [t for k, t in sorted(exhibits.items()) if not re.search(r"under IFRS|IFRS-EU|IFRS Consolidated|in accordance with IFRS", t[:4000], re.I)] or list(exhibits.values())
    for t in gaap:                                             # 1) Quarterly Summary statement of operations
        L = t.splitlines()
        for i, l in enumerate(L):
            if re.search(r"Quarterly Summary.{0,40}(Statements? of Operations|Income Statement)", l, re.I) and not re.search(r"IFRS", l):
                ds = header_dates(L[i + 1:i + 7])
                if not ds: continue
                k = min(range(len(ds)), key=lambda j: abs((ds[j] - qend).days))
                if abs((ds[k] - qend).days) > 10: continue
                v = _rows(L[i + 1:i + 45], cfg["row_labels"], ncols=len(ds), from_right=len(ds) - 1 - k)
                if "revenue" in v: return (qend, q, fy), v, "quarterly summary (dated columns)"
    for dq, v in flat_summary(gaap, cfg["row_labels"]) if False else flat_summary(dict(enumerate(gaap)), cfg["row_labels"]):   # 1b) PDF-flattened summary (2025+)
        if abs((dq - qend).days) <= 10 and "revenue" in v: return (qend, q, fy), v, "flattened quarterly summary (PDF exhibit)"
    lab = re.compile(rf"\bQ{q}\s?'?(?:{fy}|{str(fy)[2:]})\b")      # 2) table whose last header column is the reported quarter
    for t in gaap:
        L = t.splitlines()
        for i, l in enumerate(L):
            hc = [c.strip() for c in l.split("|")]
            hit = [k for k, c in enumerate(hc) if lab.search(c)]
            ncol = sum(1 for c in hc if re.search(r"\bQ[1-4]\b|\b20\d\d\b|FY|Full year", c, re.I))
            if "|" in l and hit and ncol >= 2:
                v = _strict(L[i + 1:i + 40], cfg["row_labels"], ncol, [k for k, c in enumerate([c for c in hc if re.search(r"\bQ[1-4]\b|\b20\d\d\b|FY|Full year", c, re.I)]) if lab.search(c)][-1])
                if "revenue" in v: return (qend, q, fy), v, "quarter-column table"
    return (qend, q, fy), {}, "not found"

def printings(exhibits, cfg):
    flat = flat_summary(exhibits, cfg["row_labels"])
    if flat: return [(d, v) for d, v in flat if "revenue" in v]
    return _printings_tables(exhibits, cfg)
def _printings_tables(exhibits, cfg):
    """Every dated column of the US-GAAP Quarterly Summary -> [(quarter_end, values)]. A release prints the last 5 quarters,
    so later releases carry restated prior quarters (bitemporal: first reported vs latest)."""
    gaap = [t for k, t in sorted(exhibits.items()) if not re.search(r"under IFRS|IFRS-EU|IFRS Consolidated|in accordance with IFRS", t[:4000], re.I)]
    for t in gaap:
        L = t.splitlines()
        for i, l in enumerate(L):
            if re.search(r"Quarterly Summary.{0,40}(Statements? of Operations|Income Statement)", l, re.I) and not re.search(r"IFRS", l):
                ds = header_dates(L[i + 1:i + 7])
                if not ds: continue
                out = []
                for k, dt in enumerate(ds):
                    qe = min([pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0) for y in (dt.year - 1, dt.year, dt.year + 1) for m in (3, 6, 9, 12)], key=lambda x: abs((x - dt).days))
                    v = _rows(L[i + 1:i + 45], cfg["row_labels"], ncols=len(ds), from_right=len(ds) - 1 - k)
                    if "revenue" in v: out.append((qe, v))
                return out
    return []

NUMTOK = r"\(?-?[\d,]*\d(?:\.\d+)?\)?\s?%?"
def flat_summary(exhibits, row_labels, extra_labels=None):
    """PDF-derived exhibits (ASML 2025+) flatten each table onto one line: 'Three months ended Jun 29, Sep 28, Dec 31, Mar 29, Jun 28,
    (Unaudited, €, in millions ...) 2025 2025 2025 2026 2026 Net system sales 5,596.1 ...'. Only 5-column quarterly lines are read;
    a label counts only if followed by exactly n numbers. Returns [(quarter_end, {canonical: value})]."""
    labs = dict(row_labels); labs.update(extra_labels or {}); out = {}
    for t in exhibits.values():
        for l in dict.fromkeys(t.splitlines()):
            m = re.match(r"\s*Three months ended\s+((?:[A-Z][a-z]{2,4}\.? \d{1,2},\s*){3,})(\([^)]*\))?\s*((?:20\d\d\s+){3,})(.*)", l)
            if not m: continue
            md = MD.findall(m.group(1)); yrs = re.findall(r"20\d\d", m.group(3))
            if len(md) != len(yrs): continue
            try: ds = [pd.Timestamp(f"{a[:3]} {d} {y}") for (a, d), y in zip(md, yrs)]
            except Exception: continue
            n = len(ds); body = m.group(4)
            for lab in sorted(labs, key=len, reverse=True):
                mm = re.search(rf"(?<![A-Za-z]){re.escape(lab)}\s*\d?\s+((?:{NUMTOK}\s+){{{n - 1}}}{NUMTOK})(?=\s|$)", body)
                if not mm: continue
                vals = re.findall(NUMTOK, mm.group(1))
                if len(vals) != n: continue
                can = labs[lab]
                for d, v in zip(ds, vals):
                    x = float(v.replace(",", "").replace("(", "-").replace(")", "").replace("%", "").strip())
                    qe = min([pd.Timestamp(year=y, month=mo, day=1) + pd.offsets.MonthEnd(0) for y in (d.year - 1, d.year, d.year + 1) for mo in (3, 6, 9, 12)], key=lambda z: abs((z - d).days))
                    out.setdefault(qe, {}).setdefault(can, x)
    return sorted(out.items())
