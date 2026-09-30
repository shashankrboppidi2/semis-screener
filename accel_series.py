"""Every quarterly revenue series a filer discloses, not just reportable segments.

The reportable segment is often too coarse to carry the signal: NVIDIA's segments are 'Compute &
Networking' and 'Graphics', while the line that inflected in 2023 -- Data Center -- is a
product-line disclosure on a different axis. So series are taken from all of them: the segment
axis, the product-or-service axis, product-within-segment (QCOM's Handsets / Automotive / IoT
inside QCT), and geography.

These axes are alternative cuts of the same revenue, NOT additive: NVIDIA tags Data Center and
also Compute, Networking, Hyperscale and Edge Computing, which re-slice it. Each series is scored
on its own and labelled with its axis, and nothing is summed across axes.

Q4 follows the same rule as everywhere else in this pipeline: Q4 = FY - 9M when the filer tags no
separate Q4, first-reported from the first FY printing less the first 9M printing.
"""
import pandas as pd, numpy as np, glob, os, tables as TB

AX = {"segment": "segment", "product_or_service": "product", "product_or_service+segment": "product in segment",
      "geography": "geography"}

def ticker_series(t):
    p = f"out/{t}_seg.pkl"
    if not os.path.exists(p): return pd.DataFrame()
    s = pd.read_pickle(p)
    if "axis" not in s.columns: return pd.DataFrame()
    s = s[(s.metric == "revenue") & s.value.notna()].copy()
    out = []
    for ax, label in AX.items():
        g = s[s.axis == ax].copy()
        if not len(g): continue
        g["series"] = g["name"].fillna(g.members) if ax == "segment" else g.members
        g = g[g.series.notna()]
        # members whose label never resolved past the raw tag ('RSD Member Domain') carry no meaning
        g = g[~g.series.astype(str).str.contains(r"\bMember\b|\bDomain\b", case=False, regex=True)]
        if not len(g): continue
        # a filer can tag the same series twice in one filing (two members, one name): sum them first
        g = g.groupby(["accn", "series", "period_end", "duration_months"], as_index=False).agg(
            value=("value", "sum"), filed=("filed", "first"))
        g["metric"] = "revenue"
        q = TB.dim_quarterly(g, ["series"])
        if not len(q): continue
        out.append(q.assign(ticker=t, axis=label))
    if not out: return pd.DataFrame()
    return pd.concat(out, ignore_index=True)

def company_totals(t, seg=None):
    """Company revenue from the canonical tag; where a filer changed that tag mid-history (Rambus
    in 2018) the series goes stale, so the reconciled segment sum stands in for the missing quarters."""
    f = pd.read_pickle(f"out/{t}_fin.pkl")
    f = f[(f.canonical == "revenue") & (f.duration_months == 3)]
    f = f.sort_values("filed").drop_duplicates("period_end") if len(f) else f
    d = pd.DataFrame(dict(period_end=pd.to_datetime(f.period_end), value=f.value.values,
                          filed=pd.to_datetime(f.filed), source="reported 3M")) if len(f) else pd.DataFrame(columns=["period_end", "value", "filed", "source"])
    if seg is not None and len(seg):
        sg = seg[seg.axis == "segment"]
        if len(sg):
            ssum = sg.groupby("period_end", as_index=False).agg(value=("first", "sum"), filed=("first_filed", "max"))
            ssum["source"] = "sum of reportable segments"
            miss = ssum[~ssum.period_end.isin(d.period_end)] if len(d) else ssum
            d = pd.concat([d, miss], ignore_index=True)
    if not len(d): return pd.DataFrame()
    d = d.sort_values("period_end")
    return pd.DataFrame(dict(ticker=t, axis="company", series="TOTAL COMPANY", period_end=d.period_end.values,
                             first=d.value.values, latest=d.value.values, first_filed=d.filed.values,
                             latest_filed=d.filed.values, source=d.source.values))

if __name__ == "__main__":
    T = sorted({os.path.basename(f).split("_")[0] for f in glob.glob("out/*_seg.pkl")} - {"xcheck"})
    rows = []
    for t in T:
        try:
            a = ticker_series(t)
            if len(a): rows.append(a)
            c = company_totals(t, a if len(a) else None)
            if len(c): rows.append(c)
        except Exception as e:
            print(f"{t}: {type(e).__name__}: {e}")
    D = pd.concat(rows, ignore_index=True)
    D = D.rename(columns={"first": "rev"})[["ticker", "axis", "series", "period_end", "rev", "first_filed", "source"]]
    D["period_end"] = pd.to_datetime(D.period_end)
    D = D[D.period_end >= "2014-01-01"]
    D.to_pickle("out/accel_series.pkl")
    print("series rows:", len(D), "| tickers:", D.ticker.nunique(), "| distinct series:", D.groupby(["ticker", "axis", "series"]).ngroups)
    print(D.groupby("axis").agg(series=("series", "nunique"), rows=("rev", "size")).to_string())
