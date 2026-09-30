"""Tier 1: market-wide RPO / bookings panel from the SEC XBRL frames API.

The frames endpoint returns every filer that reported a concept for a calendar period in ONE
request, so the whole US market costs a few hundred requests instead of one companyfacts pull per
filer. Off-calendar fiscal quarters are handled by the SEC, which snaps each fact to the nearest
calendar frame (AAR Corp's 31 May balance lands in CY2026Q2I).

KNOWN LIMITATION, deliberate: frames return ONE observation per filer per period -- the most
recently filed one. So this panel is latest-reported, not as-first-reported. That is correct for a
current screen ("what is inflecting now") but carries restatement bias, so any backtest of these
signals has to go back through the per-filer path that records filing dates.

Revenue concepts differ by filer, so several are fetched and coalesced in priority order. Q4 is
derived as FY less the first three quarters wherever a filer tags only the annual figure.
"""
import edgar, json, pandas as pd, numpy as np, os, sys, time

_NOW = pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("Q")          # through the current calendar quarter (off-calendar filers land there early)
Q = [(y, q) for y in range(2017, _NOW.year + 1) for q in (1, 2, 3, 4) if pd.Period(f"{y}Q{q}", "Q") <= _NOW]

INSTANT = {                                    # balances -> the 'I' frames
    "rpo": ["RevenueRemainingPerformanceObligation"],
    "dr_cur": ["ContractWithCustomerLiabilityCurrent"],
    "dr_tot": ["ContractWithCustomerLiability"],
}
DURATION = {                                   # flows -> plain frames
    "rev": ["RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTaxAndOtherRevenue"],
}

def frame(tag, period, taxonomy="us-gaap", unit="USD"):
    u = f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json"
    try:
        j = json.loads(edgar.get(u))
    except Exception as e:
        return pd.DataFrame(), f"{type(e).__name__}"
    d = pd.DataFrame(j.get("data", []))
    if not len(d): return pd.DataFrame(), "empty"
    d = d[["cik", "entityName", "end", "val", "accn"] + (["start"] if "start" in d.columns else [])]
    return d, "ok"

def pull():
    rows, log = [], []
    for name, tags in INSTANT.items():
        for y, q in Q:
            for k, tag in enumerate(tags):
                d, st = frame(tag, f"CY{y}Q{q}I")
                log.append((name, tag, f"CY{y}Q{q}I", st, len(d)))
                if len(d):
                    rows.append(d.assign(metric=name, tag=tag, cy=y, cq=q, prio=k)); break
    for name, tags in DURATION.items():
        for y, q in Q:
            for k, tag in enumerate(tags):
                d, st = frame(tag, f"CY{y}Q{q}")
                log.append((name, tag, f"CY{y}Q{q}", st, len(d)))
                if len(d): rows.append(d.assign(metric=name, tag=tag, cy=y, cq=q, prio=k))
        for y in range(2017, _NOW.year):       # annual (completed years), for deriving Q4
            for k, tag in enumerate(tags):
                d, st = frame(tag, f"CY{y}")
                log.append((name, tag, f"CY{y}", st, len(d)))
                if len(d): rows.append(d.assign(metric="rev_fy", tag=tag, cy=y, cq=0, prio=k))
    D = pd.concat(rows, ignore_index=True)
    L = pd.DataFrame(log, columns=["metric", "tag", "period", "status", "n"])
    D.to_pickle("out/tier1_raw.pkl"); L.to_pickle("out/tier1_fetchlog.pkl")
    print(f"requests: {len(L)} | rows: {len(D):,} | filers touched: {D.cik.nunique():,}")
    print(L.groupby(["metric", "status"]).agg(requests=("n", "size"), rows=("n", "sum")).to_string())
    return D

if __name__ == "__main__":
    t0 = time.time(); D = pull(); print(f"elapsed {time.time()-t0:.0f}s | {edgar.STATS}")
