"""Rank every disclosed KPI series by how hard it is accelerating right now.

Scored per series, on the latest quarter each filer has reported:
  yoy        y/y growth now
  accel      y/y now less y/y a quarter ago -- the second difference, which is the signal
  streak     consecutive quarters of positive acceleration ending in the latest
  cum_accel  how far y/y has travelled over that streak
  qoq_3q     three-quarter compound q/q, which turns before y/y clears its base

Materiality guards, so a rounding-sized line cannot top the screen: a revenue series must be at
least 5% of company revenue and have a year-ago base over $20m; a balance series (RPO, contract
liabilities) at least 10% of trailing revenue. Series whose last report predates the filer's own
latest quarter are marked stale and excluded from the ranking.
"""
import pandas as pd, numpy as np, os

MIN_SHARE, MIN_BASE, MIN_BAL = 0.05, 20.0, 0.03

def snap_cq(pe):
    """A 52/53-week quarter can end a few days either side of the calendar quarter (ON Semi's
    quarters end Apr 4, Jul 3, Oct 3, Dec 31). Taking the calendar quarter of the raw date would
    push two of them into one quarter and leave another empty, so dates snap to the nearest month
    end first -- the same rule the rest of this pipeline uses."""
    pe = pd.to_datetime(pe)
    a = pe + pd.offsets.MonthEnd(0); b = pe - pd.offsets.MonthEnd(1)
    me = np.where((a - pe).dt.days.values <= (pe - b).dt.days.values, a.values, b.values)
    return pd.PeriodIndex(pd.DatetimeIndex(me), freq="Q")

def metrics(d, keys=("ticker", "axis", "series")):
    d = d.dropna(subset=["value"]).copy()
    d["cq"] = snap_cq(d.period_end)
    d = d.sort_values(list(keys) + ["period_end"]).drop_duplicates(list(keys) + ["cq"], keep="last")
    out = []
    for k, g in d.groupby(list(keys)):
        g = g.set_index("cq").sort_index()
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        v = pd.to_numeric(g.value, errors="coerce")
        v = v.where(v != 0)                       # a zero base makes y/y meaningless, not infinite
        yoy = v / v.shift(4) - 1
        r = pd.DataFrame({**dict(zip(keys, k)), "cq": full, "value": pd.to_numeric(g.value, errors="coerce").values, "yago": v.shift(4).values,
                          "yoy": yoy.values, "accel": yoy.diff().values, "qoq": (v / v.shift(1) - 1).values,
                          "qoq_3q": (v / v.shift(3) - 1).values})
        s, run = [], 0
        for a in r.accel:
            run = run + 1 if (a == a and a is not None and a > 0) else 0
            s.append(run)
        r["streak"] = s
        r["cum_accel"] = [r.yoy.iloc[i] - r.yoy.iloc[i - r.streak.iloc[i]] if r.streak.iloc[i] > 0 and i - r.streak.iloc[i] >= 0 else np.nan for i in range(len(r))]
        out.append(r)
    return pd.concat(out, ignore_index=True)

def build():
    R = pd.read_pickle("out/accel_series.pkl").rename(columns={"rev": "value"})
    R["kind"] = np.where(R.axis == "company", "company revenue", "segment revenue")
    parts = [R[["ticker", "axis", "series", "period_end", "value", "kind"]]]

    B = pd.read_pickle("out/rpo_facts.pkl").copy()
    B = B[B.metric.isin(["rpo", "deferred_revenue_total", "deferred_revenue_current"])]
    NAME = {"rpo": "RPO (remaining performance obligation)", "deferred_revenue_total": "Contract liabilities (total)",
            "deferred_revenue_current": "Contract liabilities (current)"}
    B["series"] = B.metric.map(NAME); B["axis"] = "balance"; B["kind"] = "bookings / backlog"
    B["value"] = B.value / 1e6          # companyfacts reports raw currency units; revenue series are in millions
    parts.append(B[["ticker", "axis", "series", "period_end", "value", "kind"]])

    if os.path.exists("out/ASML_kpi_q.pkl"):
        A = pd.read_pickle("out/ASML_kpi_q.pkl")
        A = A[A.metric.isin(["bookings_value", "backlog_value"])].copy()
        A["series"] = A.metric.map({"bookings_value": "Bookings (EUR m)", "backlog_value": "Backlog (EUR m)"})
        A = A.rename(columns={"value_first": "value"}).assign(ticker="ASML", axis="disclosed KPI", kind="bookings / backlog")
        parts.append(A[["ticker", "axis", "series", "period_end", "value", "kind"]])

    D = pd.concat(parts, ignore_index=True)
    D["period_end"] = pd.to_datetime(D.period_end)
    D = D[D.period_end >= "2014-01-01"]
    M = metrics(D)
    kind = D.drop_duplicates(["ticker", "axis", "series"]).set_index(["ticker", "axis", "series"]).kind
    M["kind"] = M.set_index(["ticker", "axis", "series"]).index.map(kind)

    hist = M.dropna(subset=["value"]).groupby(["ticker", "axis", "series"]).cq.agg(["min", "size"]).rename(columns={"size": "quarters_history"})
    M = M.merge(hist[["quarters_history"]], left_on=["ticker", "axis", "series"], right_index=True, how="left")
    co = M[M.axis == "company"][["ticker", "cq", "value"]].rename(columns={"value": "co_rev"})
    M = M.merge(co, on=["ticker", "cq"], how="left")
    M["ttm_rev"] = M.groupby("ticker").co_rev.transform(lambda s: s.rolling(4, min_periods=3).sum() * 4 / s.rolling(4, min_periods=3).count())
    M["share"] = np.where(M.kind == "bookings / backlog", M.value / M.ttm_rev, M.value / M.co_rev)
    M.to_pickle("out/accel_metrics.pkl")
    return M

def rank(M):
    last_q = M[M.axis == "company"].dropna(subset=["value"]).groupby("ticker").cq.max()
    L = M.dropna(subset=["value"]).sort_values("cq").groupby(["ticker", "axis", "series"]).tail(1).copy()
    L["latest_co_q"] = L.ticker.map(last_q)
    L["stale_q"] = [np.nan if (a != a or b != b) else (a.ordinal - b.ordinal) for a, b in zip(L.latest_co_q, L.cq)]
    L["material"] = np.where(L.kind == "bookings / backlog", L.share >= MIN_BAL,
                             (L.share >= MIN_SHARE) & (L.yago >= MIN_BASE))
    L.loc[L.axis == "company", "material"] = True
    ok = L[(L.stale_q <= 1) & L.material & L.accel.notna()].copy()
    # a run of acceleration is worth more than one big quarter, but not linearly; cap so one outlier cannot dominate
    ok["score"] = ok.accel.clip(-2, 5) * np.maximum(np.minimum(ok.streak, 4), 1) ** 0.5
    ok["short_history"] = ok.quarters_history < 8      # a segment redefined recently has no clean year-ago base
    return L, ok.sort_values("score", ascending=False)

if __name__ == "__main__":
    M = build(); L, ok = rank(M)
    M.to_pickle("out/accel_metrics.pkl"); L.to_pickle("out/accel_latest.pkl"); ok.to_pickle("out/accel_ranked.pkl")
    print(f"series scored: {len(L)} | current and material: {len(ok)} | tickers: {ok.ticker.nunique()}")
    cols = ["ticker", "axis", "series", "cq", "value", "yoy", "accel", "streak", "cum_accel", "qoq_3q", "share"]
    print("\n=== accelerating hardest in the latest reported quarter ===")
    print(ok[ok.accel > 0].head(30)[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print("\n=== bookings / backlog series only ===")
    b = ok[ok.kind == "bookings / backlog"]
    print(b.head(25)[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
