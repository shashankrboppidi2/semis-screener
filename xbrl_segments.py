"""Segment / market-platform revenue and operating income from each 10-Q/10-K XBRL instance (dimensional facts). Deterministic."""
import re, pandas as pd, edgar
from lxml import etree
AXES = {"StatementBusinessSegmentsAxis": "segment", "ProductOrServiceAxis": "product_or_service", "StatementGeographicalAxis": "geography", "MajorCustomersAxis": "customer"}
REV = {"Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet"}
OPI = {"OperatingIncomeLoss"}
# Facts whose ONLY dimension is ConsolidationItemsAxis are the corporate / reconciling bucket that completes the segment note.
# Filers use their own member names for it (amat:CorporateReconcilingItemsAndEliminationsMember, nvda:CorporateNonSegment...), so the
# rule is the axis, not a name list. Subtotal members on that axis are excluded.
RECON_EXCLUDE = re.compile(r"^(OperatingSegments|ReportableSegments|SegmentContinuingOperations|ConsolidatedEntities)", re.I)
def instance_name(cik, acc):
    items = edgar.filing_index(cik, acc)["directory"]["item"]; names = [i["name"] for i in items]
    for n in names:
        if n.endswith("_htm.xml"): return n
    xs = [n for n in names if n.endswith(".xml") and not re.search(r"(_cal|_def|_lab|_pre|FilingSummary|MetaLinks)", n, re.I) and re.search(r"\d{8}\.xml$", n)]
    return xs[0] if xs else None
def member_label(m):
    local = m.split(":")[-1]; local = re.sub(r"Member$", "", local)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", local).strip()
GENERIC = {"ReportableSegmentsMember", "SegmentReportingSegmentMember", "OperatingSegmentsMember"}
SUBTOTAL = re.compile(r"^(reportable|reporting|operating|business) segments?$|^segment[s]?$|^total$|^consolidated$|^total (net )?(revenue|sales)$", re.I)
def all_member_labels(cik, acc):
    """{qname: label} for every member in the filing's own label linkbase. The company's label is the authoritative name for a
    member, so no hand-written per-ticker name map is needed ('Datacenter' vs 'Data Center' resolves itself). Role preference:
    terse/verbose label over the standard label, which often carries the '[Member]' suffix."""
    try: items = edgar.filing_index(cik, acc)["directory"]["item"]
    except Exception: return {}
    lab = [i["name"] for i in items if i["name"].endswith("_lab.xml")]
    if not lab: return {}
    try: root = etree.fromstring(edgar.get(edgar.doc_url(cik, acc, lab[0]), binary=True))
    except Exception: return {}
    XL = "http://www.w3.org/1999/xlink"; PREF = {"terseLabel": 0, "verboseLabel": 1, "label": 2}
    best = {}
    for el in root.iter("{http://www.xbrl.org/2003/linkbase}label"):
        key = el.get(f"{{{XL}}}label") or ""
        m = re.match(r"lab_([A-Za-z0-9-]+?)_([A-Za-z0-9]*Member)(?:_|$)", key)
        if not m or not (el.text or "").strip(): continue
        role = (el.get(f"{{{XL}}}role") or "").rsplit("/", 1)[-1]
        if role not in PREF: continue
        q = f"{m.group(1)}:{m.group(2)}"; lbl = re.sub(r"\s*\[(Member|Domain)\]\s*$", "", el.text).strip()
        if not lbl or SUBTOTAL.match(lbl): continue
        if q not in best or PREF[role] < best[q][0]: best[q] = (PREF[role], lbl)
    return {q: v[1] for q, v in best.items()}
def parse(cik, acc):
    n = instance_name(cik, acc)
    if not n: return pd.DataFrame()
    root = etree.fromstring(edgar.get(edgar.doc_url(cik, acc, n), binary=True))
    ns_x = "http://www.xbrl.org/2003/instance"; ns_d = "http://xbrl.org/2006/xbrldi"
    ctx = {}
    for c in root.iter(f"{{{ns_x}}}context"):
        per = c.find(f"{{{ns_x}}}period"); s = per.findtext(f"{{{ns_x}}}startDate"); e = per.findtext(f"{{{ns_x}}}endDate") or per.findtext(f"{{{ns_x}}}instant")
        dims = {d.get("dimension").split(":")[-1]: d.text.strip() for d in c.iter(f"{{{ns_d}}}explicitMember")}
        ctx[c.get("id")] = (s, e, dims)
    rows = []; used = {m for _, _, d in ctx.values() for m in d.values()}
    relabel = all_member_labels(cik, acc)          # covers generic us-gaap members too (TXN tagged Analog as ReportableSegmentsMember)
    for el in root:
        if not isinstance(el.tag, str) or el.get("contextRef") is None: continue
        local = etree.QName(el).localname
        if local not in REV | OPI: continue
        s, e, dims = ctx.get(el.get("contextRef"), (None, None, {}))
        if not dims or not s: continue
        dims = {d: m for d, m in dims.items() if not (d == "ConsolidationItemsAxis" and m.split(":")[-1] == "OperatingSegmentsMember")}  # 'operating segments' qualifier adds no information
        # rule: corporate / reconciling items reported with no segment member (e.g. NVIDIA 'All Other' from FY2019) are a segment-level line of their own
        recon = set(dims) == {"ConsolidationItemsAxis"} and not RECON_EXCLUDE.match(dims["ConsolidationItemsAxis"].split(":")[-1])
        if recon: dims = {"StatementBusinessSegmentsAxis": dims["ConsolidationItemsAxis"]}
        if not dims or any(d not in AXES for d in dims): continue      # skip facts cut by other axes (eliminations, reconciling items)
        try: v = float(el.text) / 1e6
        except (TypeError, ValueError): continue
        dur = int(round((pd.Timestamp(e) - pd.Timestamp(s)).days / 30.44))
        rows.append(dict(accn=acc, concept=local, metric="revenue" if local in REV else "operating_income", period_end=pd.Timestamp(e), duration_months=dur,
                         axis="+".join(sorted(AXES[d] for d in dims)), members="All Other" if recon else "+".join(relabel.get(dims[d]) or member_label(dims[d]) for d in sorted(dims)), raw_members="+".join(dims[d] for d in sorted(dims)), value=v, ctx=el.get("contextRef")))
    return pd.DataFrame(rows).drop_duplicates(subset=[c for c in (rows[0].keys() if rows else []) if c != "ctx"])

import html as _html
def ix_row_labels(cik, acc, primary):
    """rule (tag-swap guard): in an inline-XBRL filing the rendered table is what the company signed. For every tagged revenue /
    operating-income fact, return {(contextRef, value_in_millions): first-cell text of its table row}. Used to overrule a segment member
    whose name disagrees with its row (AMD 10-Qs 2023-24 tag the 'Data Center' row as ClientMember, etc.)."""
    h = edgar.get(edgar.doc_url(cik, acc, primary))
    if "ix:nonFraction" not in h and "ix:nonfraction" not in h: return {}
    out = {}
    for m in re.finditer(r'<ix:nonFraction([^>]*)>([^<]*)<', h, re.I):
        a = m.group(1); nm = re.search(r'name="[^:"]*:([^"]+)"', a); c = re.search(r'contextRef="([^"]+)"', a)
        if not (nm and c) or nm.group(1) not in REV | OPI: continue
        tr = h.rfind("<tr", 0, m.start())
        if tr < 0: continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", h[tr:m.start()], re.S | re.I)
        txt = [re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", x))).strip() for x in cells]
        lab = next((x for x in txt if x and not re.fullmatch(r"[\s$()\d,.—-]*", x)), None)
        sc = re.search(r'scale="(-?\d+)"', a); val = m.group(2).replace(",", "").strip()
        try: v = float(val) * 10 ** int(sc.group(1) if sc else 0) / 1e6
        except ValueError: continue
        if re.search(r'sign="-"', a): v = -v
        if lab: out[(c.group(1), round(v, 3))] = lab
    return out
