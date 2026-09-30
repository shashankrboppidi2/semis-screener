"""ASML operating KPIs from the 6-K results releases (deterministic).
Sources, in priority order, each kept as a separate printing (bitemporal):
  1. EX-99.3 'Quarterly Summary Ratios and other data' - five dated columns (column order varies by year; dates decide)
  2. EX-99.1 headline table '| Qn-1 YYYY | Qn YYYY' (2014+): net bookings value, systems backlog, systems sold (units)
  3. EX-99.1 text (2010-2014): 'Qn YYYY net bookings valued at EUR 1,179 million with 59 systems ... backlog valued at EUR 2,401 million'
Rule: the value for a quarter = its first printing; later printings are kept for restatement tracking."""
import re, json, pandas as pd, earnings_docs as E, fpi_quarterly as F
from earnings_docs import nums
LAB = [  # (regex on normalised label, canonical) - specific (units / ex-EUV) patterns first
    (r"^net bookings,? excluding euv \((in )?units\)$", "bookings_units_ex_euv"),
    (r"^net bookings,? excluding euv$|^value of net bookings,? excluding euv.*$", "bookings_value_ex_euv"),
    (r"^systems backlog,? excluding euv \((in )?units\)$", "backlog_units_ex_euv"),
    (r"^(value of )?systems backlog,? excluding euv.*$", "backlog_value_ex_euv"),
    (r"^number of payroll employees( in|\s*\(in) ftes\)?$", "employees_payroll_fte"),
    (r"^net bookings \((in )?units\)$|^net bookings lithography systems \((in )?units\)$", "bookings_units"),
    (r"^net bookings$|^value of net bookings.*$|^net bookings \(in value\).*$|^net bookings \(eur millions?\)$", "bookings_value"),
    (r"^value of systems backlog.*$|^systems backlog$|^backlog$|^systems backlog \(eur millions?\)$", "backlog_value"),
    (r"^systems backlog \((in )?units\)$", "backlog_units"),
    (r"^(asp|average selling price) of systems backlog.*$", "backlog_asp"),
    (r"^sales of (lithography )?systems \(in units\)$|^total sales of lithography systems \(in units\)$", "systems_sold_units"),
    (r"^new (lithography )?systems sold \(units\)$", "new_systems_sold_units"),
    (r"^used (lithography )?systems sold \(units\)$", "used_systems_sold_units"),
    (r"^(asp|average selling price) of (system|lithography system) sales.*$", "asp_system_sales"),
    (r"^(\.\.\.of which )?installed base management sales$", "installed_base_mgmt_sales"),
]
def norm(lab):
    lab = re.sub(r"\s*(\*|\(\d\))\s*$", "", lab.strip())                       # 'Net bookings(3)', 'Net bookings *'

    lab = re.sub(r"(\s+\d(\s*,\s*\d)*|(?<=[a-z)])\d(,\d)*)$", "", lab)          # footnote markers: 'Net bookings2', '(in units) 1, 2'
    return re.sub(r"\s+", " ", lab).strip().lower()
def canon(lab):
    n = norm(lab)
    for rx, c in LAB:
        if re.match(rx, n): return c
    return None
def ratios_table(exhibits):
    """-> [(column_date, canonical, value)] from every dated Ratios-and-other-data table"""
    out = []
    for n, t in exhibits.items():
        if re.search(r"under IFRS|IFRS-EU|in accordance with IFRS", t[:4000], re.I): continue
        L = t.splitlines()
        for i, l in enumerate(L):
            if not re.search(r"Quarterly Summary.{0,30}Ratios", l, re.I) or re.search("IFRS", l): continue
            ds = F.header_dates(L[i + 1:i + 7])
            if not ds: continue
            for r in L[i + 1:i + 45]:
                cells = [c.strip() for c in r.split("|")]; c = canon(cells[0])
                if not c: continue
                v = [nums(x)[0] for x in cells[1:] if nums(x) and not re.fullmatch(r"\d", x.strip())]   # a lone footnote digit is not a value
                if len(v) == len(ds): out += [(d, c, x) for d, x in zip(ds, v)]
            break
    return out
QL = re.compile(r"^Q([1-4]) ?(\d{4})$")
def headline(exhibits, qend, q, fy):
    """EX-99.1 headline table; columns mapped from the header labels ('Q3 2025 | Q4 2025 | FY 2024 | FY 2025'). Only quarter columns kept.
    Lone footnote digits that appear as extra cells are dropped only when the row has more cells than the header."""
    t = exhibits.get("EX-99.1", ""); L = t.splitlines(); out = []
    for i, l in enumerate(L):
        hdr = [c.strip() for c in l.split("|") if QL.match(c.strip()) or re.match(r"^(FY ?|Full[- ]year )?\d{4}$", c.strip())]   # period columns only
        if not any(QL.match(h) and int(QL.match(h).group(1)) == q and int(QL.match(h).group(2)) == fy for h in hdr): continue
        for r in L[i + 1:i + 30]:
            cells = [c.strip() for c in r.split("|")]; c = canon(cells[0])
            if not c: continue
            v = [x for x in cells[1:] if nums(x)]
            if len(v) > len(hdr): v = [x for x in v if not re.fullmatch(r"\d", x)]
            if len(v) != len(hdr): continue
            for h, x in zip(hdr, v):
                m = QL.match(h)
                if m: out.append((pd.Timestamp(year=int(m.group(2)), month=3 * int(m.group(1)), day=1) + pd.offsets.MonthEnd(0), c, nums(x)[0]))
        break
    return out
TXT = re.compile(r"net bookings (?:valued at|totaled \d+ systems valued at|of) (?:EUR|€) ?([\d,.]+) ?(million|billion)", re.I)
TXT_U = re.compile(r"net bookings[^.]{0,40}?(?:with|totaled|of) (\d+) (?:lithography )?systems", re.I)
TXT_B = re.compile(r"(?:systems )?backlog valued at (?:EUR|€) ?([\d,.]+) ?(million|billion)", re.I)
def text_kpis(exhibits, qend, q, fy):
    t = re.sub(r"\s+", " ", exhibits.get("EX-99.1", "")); out = []
    for s in re.split(r"(?<=[.•])\s", t):
        if not re.search(rf"\bQ{q} ?{fy}\b|this quarter|in the quarter", s): continue
        m = TXT.search(s)
        if m: out.append((qend, "bookings_value", float(m.group(1).replace(",", "")) * (1000 if m.group(2).lower() == "billion" else 1)))
        m = TXT_U.search(s)
        if m: out.append((qend, "bookings_units", float(m.group(1))))
        m = TXT_B.search(s)
        if m: out.append((qend, "backlog_value", float(m.group(1).replace(",", "")) * (1000 if m.group(2).lower() == "billion" else 1)))
        if out: break
    return out
def snap(d):
    return min([pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0) for y in (d.year - 1, d.year, d.year + 1) for m in (3, 6, 9, 12)], key=lambda x: abs((x - d).days))
def run():
    d = pd.read_pickle("out/ASML_q.pkl"); rows = []
    for _, r in d.iterrows():
        x = E.exhibits(937966, r.accn); qend = pd.Timestamp(r.period_end)
        for dt, c, v in ratios_table(x): rows.append(dict(filed=r.filed, accn=r.accn, period_end=snap(dt), metric=c, value=v, source="EX-99.3 ratios table"))
        for dt, vals in F.flat_summary(x, {}, {"Sales of lithography systems (in units)": "systems_sold_units", "Net bookings": "bookings_value",
                                               "Number of payroll employees (in FTEs)": "employees_payroll_fte"}):
            for c, v in vals.items(): rows.append(dict(filed=r.filed, accn=r.accn, period_end=dt, metric=c, value=v, source="EX-99.3 ratios (PDF-flattened)"))
        for dt, c, v in headline(x, qend, r.q, r.fy): rows.append(dict(filed=r.filed, accn=r.accn, period_end=dt, metric=c, value=v, source="EX-99.1 headline table"))
        have = {(p["period_end"], p["metric"]) for p in rows if p["accn"] == r.accn}
        for dt, c, v in text_kpis(x, qend, r.q, r.fy):          # text is rounded: used only when the release has no table value
            if (dt, c) not in have: rows.append(dict(filed=r.filed, accn=r.accn, period_end=dt, metric=c, value=v, source="EX-99.1 text"))
    k = pd.DataFrame(rows); k["filed"] = pd.to_datetime(k.filed)
    k.to_pickle("out/ASML_kpi_printings.pkl")
    # first printing per quarter & metric; conflicts between sources in the SAME release are reported
    same = k.groupby(["accn", "period_end", "metric"]).value.agg(lambda s: s.round(1).nunique())
    first = k.sort_values(["filed", "source"]).drop_duplicates(["period_end", "metric"])
    latest = k.sort_values(["filed", "source"]).drop_duplicates(["period_end", "metric"], keep="last")
    q = first.merge(latest[["period_end", "metric", "value", "filed"]], on=["period_end", "metric"], suffixes=("_first", "_latest"))
    q.to_pickle("out/ASML_kpi_q.pkl")
    cov = q.pivot_table(index="metric", values="period_end", aggfunc=["count", "min", "max"])
    print(cov.to_string()); print("same-release conflicts:", int((same > 1).sum()))
    if (same > 1).any(): print(same[same > 1].head(10))
if __name__ == "__main__": run()
