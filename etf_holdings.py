"""ETF holdings from SEC Form N-PORT (full portfolio, as of the report date). Deterministic XML parse."""
import edgar, re, pandas as pd
from lxml import etree
SERIES = {"SOXX": (1100663, "S000004354"), "SMH": (1137360, "S000034411")}
def latest(sid, n=1):
    t = edgar.get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={sid}&type=NPORT-P&dateb=&owner=include&count=10&output=atom")
    return [(re.search(r"<filing-date>([^<]+)", e).group(1), re.search(r"<accession-number>([^<]+)", e).group(1)) for e in re.findall(r"<entry>(.*?)</entry>", t, re.S)][:n]
def parse(cik, acc):
    x = edgar.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/primary_doc.xml", binary=True)
    root = etree.fromstring(x); ns = {"n": root.nsmap.get(None, "http://www.sec.gov/edgar/nport")}
    g = lambda el, p: (el.findtext(p, namespaces=ns) or "").strip()
    rep = g(root, ".//n:genInfo/n:repPdDate"); series = g(root, ".//n:genInfo/n:seriesName"); net = float(g(root, ".//n:fundInfo/n:netAssets") or "nan")
    rows = []
    for s in root.iterfind(".//n:invstOrSec", ns):
        isin = s.find(".//n:identifiers/n:isin", ns); tick = s.find(".//n:identifiers/n:ticker", ns)
        rows.append(dict(name=g(s, "n:name"), title=g(s, "n:title"), cusip=g(s, "n:cusip"), isin=isin.get("value") if isin is not None else None,
                         ticker_nport=tick.get("value") if tick is not None else None, shares=float(g(s, "n:balance") or "nan"), units=g(s, "n:units"),
                         value_usd=float(g(s, "n:valUSD") or "nan"), weight_pct=float(g(s, "n:pctVal") or "nan"), asset_cat=g(s, "n:assetCat"),
                         issuer_cat=g(s, "n:issuerCat"), country=g(s, "n:invCountry")))
    return dict(series=series, report_date=rep, net_assets=net), pd.DataFrame(rows)
if __name__ == "__main__":
    out = []
    for etf, (cik, sid) in SERIES.items():
        filed, acc = latest(sid)[0]; meta, d = parse(cik, acc)
        d.insert(0, "etf", etf); d["report_date"] = meta["report_date"]; d["filed"] = filed; d["accn"] = acc; out.append(d)
        print(etf, meta, "filed", filed, "|", len(d), "positions | weight sum", round(d.weight_pct.sum(), 2), "| asset cats", d.asset_cat.value_counts().to_dict())
    pd.concat(out).to_pickle("out/etf_holdings_nport.pkl")
