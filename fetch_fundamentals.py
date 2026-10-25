"""Point-in-time revenue and operating income for the software names (SIC 73xx) of the tech universe.

Reads results/universe/tech_meta.csv, pulls each company's SEC companyfacts through xbrl_financials.load, and keeps the
first-reported value of every quarter and fiscal year with the date it was filed (Q4 derived as FY minus 9M YTD), so a
backtest can use only what was public on a given day. Output: results/universe/fundamentals.csv.gz.
Needs SEC (SEC_UA) -- run via .github/workflows/fundamentals.yml.
"""
import copy
import pandas as pd
import xbrl_financials as xf

OUT = "results/universe/fundamentals.csv.gz"
KEEP = ("revenue", "operating_income")
GAAP = copy.deepcopy(xf.CONCEPTS)          # load() swaps CONCEPTS to the IFRS names for IFRS filers; restore per company

meta = pd.read_csv("results/universe/tech_meta.csv")
sw = meta[meta.sic.fillna(0).astype(int).astype(str).str.startswith("73")]
rows, missing = [], []
for t, cik in zip(sw.ticker, sw.cik):
    xf.CONCEPTS.clear(); xf.CONCEPTS.update(copy.deepcopy(GAAP))
    try:
        df, _ = xf.load(int(cik))
    except Exception as e:
        missing.append(t); print(t, "failed:", str(e)[:100], flush=True); continue
    df = df[(df.basis == "as_first_reported") & df.canonical.isin(KEEP) & df.duration_months.isin([3, 12])]
    if not len(df): missing.append(t); continue
    rows.append(df.assign(ticker=t)[["ticker", "canonical", "period_end", "duration_months", "value", "filed", "form"]])
out = pd.concat(rows).sort_values(["ticker", "canonical", "period_end", "duration_months"])
out.to_csv(OUT, index=False, float_format="%.3f")
print(f"{out.ticker.nunique()} of {len(sw)} software names, {len(out)} rows; no data: {missing}", flush=True)
