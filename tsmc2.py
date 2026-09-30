"""TSMC (CIK 1046179) quarterly figures and KPIs from its 6-K filings.

TSMC is a foreign private issuer: no 10-Qs, and its XBRL carries annual figures only, so the
quarterly history lives in the 6-K earnings releases. Every release prints the same five-column
table -- current quarter, year-ago quarter, YoY %, prior quarter, QoQ % -- but the header cells
change shape over the years ('4Q20', '4Q18Amounta', '4Q12Amount*') and footnote letters land in
their own cells, so column position cannot be trusted. Instead each row's numeric values are
read in order and the three quarter columns are taken by ordinal position (0, 1, 3), then
CHECKED against the YoY and QoQ percentages the filer printed in columns 2 and 4. A row whose
arithmetic does not reproduce those percentages is dropped rather than guessed at.

Streams: quarterly income statement (3 vintages per release) | next-quarter guidance |
technology-node mix | platform mix | monthly revenue.
"""
import re, sys, pandas as pd, edgar, earnings_docs as E
from earnings_docs import to_lines, nums

CIK = 1046179
ROWS = {"net sales": "revenue", "gross profit": "gross_profit", "income from operations": "operating_income",
        "income before tax": "income_before_tax", "net income": "net_income",
        "eps (nt$)": "eps_diluted", "eps(nt$)": "eps_diluted", "eps (nt$)*": "eps_diluted"}
QL = re.compile(r"^([1-4])Q(\d{2})(?!\d)")   # header cells run the label into text: '4Q23', '4Q18Amounta', '4Q12Amount*'
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]

def qend(q, yy):
    return pd.Timestamp(year=2000 + int(yy), month=3 * int(q), day=1) + pd.offsets.MonthEnd(0)

def text(acc, prim):
    x = E.exhibits(CIK, acc)
    return "\n".join(x[k] for k in sorted(x)) if x else to_lines(edgar.get(edgar.doc_url(CIK, acc, prim)))

def results_table(t):
    """-> ([(period_end, {metric: value})], n_checked, n_dropped) for the three quarters each release prints."""
    L = [l for l in t.splitlines() if l.strip()]
    for i, l in enumerate(L):
        cells = [c.strip() for c in l.split("|")]
        qs = [QL.match(c) for c in cells if QL.match(c)]
        if len(qs) != 3: continue                      # current, year-ago, prior quarter
        pes = [qend(m.group(1), m.group(2)) for m in qs]
        if not (pes[0] > pes[1] and pes[0] > pes[2]): continue
        out, ok, bad = {}, 0, 0
        for r in L[i + 1:i + 16]:
            rc = [c.strip() for c in r.split("|")]
            can = ROWS.get(re.sub(r"\s*[*a-z]?$", "", rc[0].lower()).strip()) or ROWS.get(rc[0].lower().strip())
            if not can: continue
            v = [x for c in rc[1:] for x in nums(c)[:1]]
            if len(v) < 5: continue
            v = v[:5]
            # the filer's own YoY and QoQ percentages are the check on the column mapping
            def pct(a, b): return None if not b else (a / b - 1) * 100
            c1, c2 = pct(v[0], v[1]), pct(v[0], v[3])
            if c1 is None or c2 is None: bad += 1; continue
            if abs(abs(c1) - abs(v[2])) > max(0.35, 0.02 * abs(v[2])) or abs(abs(c2) - abs(v[4])) > max(0.35, 0.02 * abs(v[4])):
                bad += 1; continue
            ok += 1
            for pe, val in zip(pes, (v[0], v[1], v[3])): out.setdefault(pe, {})[can] = val
        if out: return sorted(out.items()), ok, bad
    return [], 0, 0

WAFER = re.compile(r"of total wafer revenue")
NODE = re.compile(r"(\d+(?:/\d+)?(?:\.\d+)?)[\s-]?(nanometer|nm|micron|micrometer)\b[^.;]{0,70}?(\d+(?:\.\d+)?)\s?(?:percent|%)", re.I)
NODE2 = re.compile(r"(\d+(?:\.\d+)?)\s?(?:percent|%)[^.;]{0,50}?(\d+(?:/\d+)?(?:\.\d+)?)[\s-]?(nanometer|nm)\b", re.I)
def tech_mix(t, pe):
    """node shares from the press-release sentence that states them 'of total wafer revenue'."""
    flat = re.sub(r"\s+", " ", t)
    out = []
    for s in re.split(r"(?<=[.])\s", flat[:6000]):
        if not WAFER.search(s): continue
        for m in NODE.finditer(s):
            p = float(m.group(3))
            if 0 < p <= 100: out.append((f"{m.group(1)}{'nm' if m.group(2).lower().startswith('n') else 'um'}", p))
        for m in NODE2.finditer(s):
            p = float(m.group(1))
            if 0 < p <= 100: out.append((f"{m.group(2)}nm", p))
        break
    d = pd.DataFrame([dict(period_end=pe, node=n, pct_of_wafer_revenue=p) for n, p in out])
    return d.drop_duplicates(["period_end", "node"]) if len(d) else d

PLAT = ("Smartphone", "HPC", "IoT", "Automotive", "DCE", "Others")
def platform_mix(t, pe):
    """platform shares from the earnings-presentation slide; kept only when they sum to ~100%."""
    flat = re.sub(r"\s+", " ", t)
    m = re.search(r"[1-4]Q\d\d Revenue by Platform(.{0,400}?)(?:Unleash Innovation|Growth)", flat)
    if not m: return pd.DataFrame()
    seg = m.group(1); got = {}
    for p in PLAT:
        mm = re.search(rf"{p}\s*(\d+(?:\.\d+)?)\s?%", seg)
        if mm: got[p] = float(mm.group(1))
    if len(got) < 4 or not 97 <= sum(got.values()) <= 103: return pd.DataFrame()
    return pd.DataFrame([dict(period_end=pe, platform=k, pct_of_revenue=v) for k, v in got.items()])

GUID_NT = re.compile(r"revenue .{0,40}?between NT\$\s?([\d,.]+) billion and NT\$\s?([\d,.]+) billion", re.I)
GUID_US = re.compile(r"[Rr]evenue .{0,40}?between US\$\s?([\d,.]+) billion and US\$\s?([\d,.]+) billion")
GM = re.compile(r"[Gg]ross (?:profit )?margin .{0,25}?between ([\d.]+)\s?% and ([\d.]+)\s?%")
OM = re.compile(r"[Oo]perating (?:profit )?margin .{0,25}?between ([\d.]+)\s?% and ([\d.]+)\s?%")
CAPEX = re.compile(r"capital (?:budget|expenditure).{0,40}?between US\$\s?([\d,.]+) billion and US\$\s?([\d,.]+) billion", re.I)
def guidance(t, cur_pe):
    flat = re.sub(r"\s+", " ", t); g = dict(period_end=cur_pe + pd.offsets.QuarterEnd(1), guided_at=cur_pe)
    for rx, unit in ((GUID_US, "USD_bn"), (GUID_NT, "NTD_bn")):
        m = rx.search(flat)
        if m: g.update(rev_low=float(m.group(1).replace(",", "")), rev_high=float(m.group(2).replace(",", "")), rev_unit=unit); break
    for rx, lo, hi in ((GM, "gm_low", "gm_high"), (OM, "om_low", "om_high"), (CAPEX, "capex_low_usd_bn", "capex_high_usd_bn")):
        m = rx.search(flat)
        if m: g[lo], g[hi] = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
    return g if len(g) > 2 else None

TITLE = re.compile(r"TSMC (" + "|".join(MONTHS) + r") (\d{4}) Revenue Report", re.I)
def monthly(t):
    """TSMC reports revenue every month. The month comes from the release title; the figure from the
    'Net Revenue(s)' row, whose eight columns are month, year-ago month, YoY %, prior month, MoM %,
    year to date, year-ago year to date, YoY % -- so the row checks itself against its own percentages."""
    L = [l for l in t.splitlines() if l.strip()]
    m = TITLE.search("\n".join(L[:60]))
    if not m: return None
    mi = MONTHS.index(m.group(1).lower()); yr = int(m.group(2))
    me = pd.Timestamp(year=yr, month=mi + 1, day=1) + pd.offsets.MonthEnd(0)
    for l in L:
        rc = [c.strip() for c in l.split("|")]
        if not re.match(r"^net revenues?$", rc[0].strip().lower()): continue
        v = [x for c in rc[1:] for x in nums(c)[:1]]
        if len(v) < 5: continue
        chk = []
        for a, b, p in ((v[0], v[1], v[2]), (v[0], v[3], v[4])):
            chk.append(b and abs(abs(a / b - 1) * 100 - abs(p)) <= max(0.35, 0.02 * abs(p)))
        if not all(chk): continue
        out = dict(month_end=me, revenue_ntd_m=v[0], source="monthly release table (NT$ million)")
        if len(v) >= 6: out["ytd_ntd_m"] = v[5]
        return out
    f = re.sub(r"\s+", " ", "\n".join(L))
    mm = re.search(rf"revenues? for {MONTHS[mi]} {yr} (?:was|were) approximately NT\$\s?([\d,.]+) billion", f, re.I)
    if mm: return dict(month_end=me, revenue_ntd_m=float(mm.group(1).replace(",", "")) * 1000, source="press-release sentence (rounded)")
    return None

def run():
    j, rows = edgar.submissions(CIK)
    k6 = sorted([r for r in rows if r["form"] == "6-K" and r["filingDate"] >= "2010-01-01"], key=lambda r: r["filingDate"])
    P, G, TK, PL, M = [], [], [], [], []
    nq = nok = nbad = 0
    for r in k6:
        t = text(r["accessionNumber"], r["primaryDocument"])
        mo = monthly(t)
        if mo: M.append(dict(filed=r["filingDate"], accn=r["accessionNumber"], **mo)); continue
        tab, ok, bad = results_table(t)
        nok += ok; nbad += bad
        if not tab: continue
        nq += 1; cur = max(pe for pe, _ in tab)
        for pe, vals in tab: P.append(dict(filed=r["filingDate"], accn=r["accessionNumber"], period_end=pe, **vals))
        g = guidance(t, cur)
        if g: G.append(dict(filed=r["filingDate"], accn=r["accessionNumber"], **g))
        tm = tech_mix(t, cur)
        if len(tm): TK.append(tm.assign(filed=r["filingDate"], accn=r["accessionNumber"]))
        pm = platform_mix(t, cur)
        if len(pm): PL.append(pm.assign(filed=r["filingDate"], accn=r["accessionNumber"]))
    P = pd.DataFrame(P); P["filed"] = pd.to_datetime(P.filed)
    P.to_pickle("out/TSM_q_printings.pkl")
    first = P.sort_values("filed").drop_duplicates("period_end"); latest = P.sort_values("filed").drop_duplicates("period_end", keep="last")
    first.assign(method="6-K quarterly results table").to_pickle("out/TSM_q.pkl"); latest.to_pickle("out/TSM_q_latest.pkl")
    Gd = pd.DataFrame(G); Gd.to_pickle("out/TSM_guid.pkl")
    tk = pd.concat(TK, ignore_index=True).sort_values("filed").drop_duplicates(["period_end", "node"]) if TK else pd.DataFrame()
    pl = pd.concat(PL, ignore_index=True).sort_values("filed").drop_duplicates(["period_end", "platform"]) if PL else pd.DataFrame()
    if len(tk): tk.to_pickle("out/TSM_tech_mix.pkl")
    if len(pl): pl.to_pickle("out/TSM_platform_mix.pkl")
    M = pd.DataFrame(M).sort_values("filed").drop_duplicates("month_end") if M else pd.DataFrame()
    if len(M): M.to_pickle("out/TSM_monthly.pkl")
    print(f"TSM: {len(k6)} 6-K filings | {nq} quarterly releases | rows checked ok {nok}, dropped on the YoY/QoQ check {nbad}")
    print(f"quarters {len(first)}: {first.period_end.min().date()} -> {first.period_end.max().date()} | printings {len(P)}")
    print("coverage:", {c: int(first[c].notna().sum()) for c in ("revenue", "gross_profit", "operating_income", "income_before_tax", "net_income", "eps_diluted") if c in first})
    print(f"guidance {len(Gd)} | tech-mix rows {len(tk)} ({tk.period_end.nunique() if len(tk) else 0} quarters) | platform-mix rows {len(pl)} ({pl.period_end.nunique() if len(pl) else 0} quarters) | months {len(M)}")
    if len(M): print(f"months {M.month_end.min().date()} -> {M.month_end.max().date()} | by source: {M.source.value_counts().to_dict()}")
if __name__ == "__main__": run()
