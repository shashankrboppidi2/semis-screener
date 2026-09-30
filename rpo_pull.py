"""RPO, contract liabilities and backlog for the universe, from SEC companyfacts.

RPO (remaining performance obligation, ASC 606) is the closest thing to a bookings disclosure that
US filers tag consistently. Contract liabilities (deferred revenue) are the cash-collected slice of
it and are tagged far more widely, so both are pulled. companyfacts carries only undimensioned
facts, so a filer that tags RPO solely under the expected-timing axis will show nothing here -- that
is a coverage gap, not a zero, and it is reported as such.
"""
import pandas as pd, numpy as np, json, os, edgar

CONCEPTS = {
    "rpo": ["RevenueRemainingPerformanceObligation"],
    "rpo_next12m": ["RevenueRemainingPerformanceObligationExpectedTimingOfSatisfactionAmount"],
    "deferred_revenue_current": ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"],
    "deferred_revenue_noncurrent": ["ContractWithCustomerLiabilityNoncurrent", "DeferredRevenueNoncurrent"],
    "deferred_revenue_total": ["ContractWithCustomerLiability", "DeferredRevenue"],
}

def facts(cik):
    try: return json.loads(edgar.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"))
    except Exception as e: return None

def series(j, names):
    """-> DataFrame of (period_end, value, filed, accn) keeping the FIRST filing that reported each date."""
    out = []
    for tx in ("us-gaap", "ifrs-full"):
        f = j.get("facts", {}).get(tx, {})
        for n in names:
            if n not in f: continue
            for unit, arr in f[n]["units"].items():
                if not unit.startswith(("USD", "EUR", "TWD", "KRW", "JPY", "CHF")): continue
                for x in arr:
                    d = x.get("end")
                    if not d: continue
                    out.append(dict(period_end=pd.Timestamp(d), value=float(x["val"]), filed=pd.Timestamp(x["filed"]),
                                    accn=x.get("accn"), concept=n, unit=unit, start=x.get("start")))
    if not out: return pd.DataFrame()
    d = pd.DataFrame(out)
    # RPO and contract liabilities are balances: keep the instant fact, not a duration one
    d = d[d.start.isna() | (d.start == "")] if d.start.notna().any() and (d.start.isna()).any() else d
    u = d.unit.value_counts()
    d = d[d.unit == u.index[0]]                        # one currency per filer, the dominant one
    d = d.sort_values(["period_end", "filed"]).drop_duplicates("period_end")
    return d[["period_end", "value", "filed", "accn", "concept", "unit"]]

if __name__ == "__main__":
    T = sorted(open("out/all_tickers.txt").read().split())
    rows, cover = [], []
    for t in T:
        cfg = json.load(open(f"config/{t}.json"))
        for cik in cfg.get("cik_chain", [cfg["cik"]]):
            j = facts(cik)
            if not j: continue
            for metric, names in CONCEPTS.items():
                s = series(j, names)
                if not len(s): continue
                rows.append(s.assign(ticker=t, metric=metric, cik=cik))
    D = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    D = D.sort_values(["ticker", "metric", "period_end", "filed"]).drop_duplicates(["ticker", "metric", "period_end"])
    D = D[D.period_end >= "2015-01-01"]
    D.to_pickle("out/rpo_facts.pkl")
    p = D.pivot_table(index="ticker", columns="metric", values="period_end", aggfunc=["count", "max"])
    print("facts:", len(D), "| tickers:", D.ticker.nunique())
    print(D.groupby(["ticker", "metric"]).agg(n=("value", "size"), first=("period_end", "min"), last=("period_end", "max")).to_string())
