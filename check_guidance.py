"""Plausibility validator for regex-read guidance: the guided quarter's actual revenue (reported ~3 months later) must lie
within ±20% of the implied guide midpoint. Misses are listed for a model read / spot check — a big miss can also be a real surprise."""
import pandas as pd, numpy as np, sys, json
def actuals(t):
    cfg = json.load(open(f"config/{t}.json"))
    if cfg.get("filer_type") == "FPI":
        q = pd.read_pickle(f"out/{t}_q.pkl"); return pd.Series(q.revenue.values, index=pd.to_datetime(q.period_end)).sort_index()
    f = pd.read_pickle(f"out/{t}_fin.pkl"); f = f[(f.canonical == "revenue") & (f.duration_months == 3)].sort_values("filed").drop_duplicates("period_end")
    return pd.Series(f.value.values, index=pd.to_datetime(f.period_end)).sort_index()
def guides(t):
    import os
    if os.path.exists(f"out/{t}_guid_final.pkl"): return pd.read_pickle(f"out/{t}_guid_final.pkl")   # regex + validated model answers
    cfg = json.load(open(f"config/{t}.json"))
    return pd.read_pickle(f"out/{t}_guid.pkl") if cfg.get("filer_type") == "FPI" else pd.read_pickle(f"out/{t}_earn.pkl")["G"]
def run(t, tol=0.20):
    A = actuals(t); G = guides(t).copy(); G["filed"] = pd.to_datetime(G.filed); rows = []
    for _, g in G.iterrows():
        prev = A[A.index < g.filed - pd.Timedelta(days=5)]; nxt = A[(A.index > g.filed) & (A.index <= g.filed + pd.Timedelta(days=120))]
        if not len(prev): continue
        p = prev.iloc[-1]; a = nxt.iloc[0] if len(nxt) else np.nan; get = lambda k: g[k] if k in g and pd.notna(g[k]) else None
        if get("revenue_mid"): mid, how = get("revenue_mid"), "mid"
        elif get("revenue_low") and get("revenue_high"): mid, how = (get("revenue_low") + get("revenue_high")) / 2, "range"
        elif get("revenue_qoq_pct") is not None: mid, how = p * (1 + get("revenue_qoq_pct") / 100), "q/q %"
        elif get("revenue_qoq_low_pct") is not None: mid, how = p * (1 + (get("revenue_qoq_low_pct") + get("revenue_qoq_high_pct")) / 200), "q/q range"
        elif get("revenue_direction"): mid, how = np.nan, "direction only"
        else: continue
        r = a / mid if pd.notna(a) and pd.notna(mid) else np.nan
        rows.append(dict(filed=g.filed.date(), accn=g.accn, how=how, prior=p, guide_mid=mid, actual=a, ratio=r,
                         status="no actual yet" if pd.isna(a) else ("direction" if pd.isna(mid) else ("ok" if abs(r - 1) <= tol else "CHECK"))))
    return pd.DataFrame(rows, columns=["filed", "accn", "how", "prior", "guide_mid", "actual", "ratio", "status"])
if __name__ == "__main__":
    for t in sys.argv[1:]:
        d = run(t); d.to_pickle(f"out/{t}_guid_check.pkl")
        print(t, d.status.value_counts().to_dict(), "| median |actual/guide-1| = %.1f%%" % (100 * (d.ratio - 1).abs().median()))
        print(d[d.status == "CHECK"].to_string() if (d.status == "CHECK").any() else "  none flagged")
