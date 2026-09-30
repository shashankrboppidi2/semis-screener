"""Generate a config per ticker from SEC data alone: CIK, fiscal year end, filer type (10-K vs 20-F), earnings form, currency.
Segment names need no config (they come from each filing's own label linkbase)."""
import edgar, json, pandas as pd, collections, sys
U = pd.read_pickle("out/etf_universe_map.pkl")
EX = {"TSM": "NYSE", "STM": "NYSE", "ASX": "NYSE", "UMC": "NYSE"}
CCY = {"TSM": "TWD", "ASX": "TWD", "UMC": "TWD", "ASML": "EUR", "SKHY": "KRW"}
def build(ticker, cik, start="2010-04-01"):
    j, rows = edgar.submissions(int(cik)); forms = collections.Counter(r["form"] for r in rows)
    fpi = forms.get("20-F", 0) > forms.get("10-K", 0)
    fye = j.get("fiscalYearEnd") or "1231"; fye_month = int(fye[:2]) if len(fye) == 4 else 12
    ann = [r for r in rows if r["form"] in ("10-K", "20-F")]
    c = dict(ticker=ticker, cik=int(cik), company_key=f"{EX.get(ticker,'NASDAQ')}_{ticker}", start_period=start, fye_month=fye_month,
             earnings_forms=["6-K"] if fpi else ["8-K"], first_annual=min((r["filingDate"] for r in ann), default=None),
             annual_form="20-F" if fpi else "10-K", sic=j.get("sicDescription"), name=j.get("name"))
    if fpi: c["filer_type"] = "FPI"
    if ticker in CCY: c["currency"] = CCY[ticker]
    return c
if __name__ == "__main__":
    done = {"NVDA", "AMD", "TXN", "ASML"}; out = []
    for _, r in U.iterrows():
        if r.ticker in done or pd.isna(r.cik): continue
        c = build(r.ticker, r.cik)
        json.dump(c, open(f"config/{r.ticker}.json", "w"), indent=1); out.append(c)
    d = pd.DataFrame(out); pd.set_option("display.width", 220)
    print(d[["ticker", "cik", "fye_month", "annual_form", "first_annual", "currency" if "currency" in d else "ticker", "name"]].to_string(index=False))
