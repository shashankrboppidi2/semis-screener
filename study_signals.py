"""Signals from quarterly segment revenue, using only what was public at each filing date (as-first-reported values, known_at = the
filing that first carried the figure). One row per ticker x quarter."""
import pandas as pd, numpy as np, json, os
d = pd.read_pickle("out/study_segment_quarters.pkl")
d["fq"] = d.groupby("ticker").period_end.transform(lambda s: s.rank(method="dense").astype(int))   # quarter index per ticker
# y/y growth per segment: the same segment four quarters earlier (a re-segmentation simply leaves no comparison)
prev = d[["ticker", "name", "fq", "rev"]].rename(columns={"fq": "fq4", "rev": "rev_yago"}); prev["fq"] = prev.fq4 + 4
d = d.merge(prev[["ticker", "name", "fq", "rev_yago"]], on=["ticker", "name", "fq"], how="left")
prev1 = d[["ticker", "name", "fq", "rev"]].rename(columns={"rev": "rev_prev_q"}); prev1["fq"] = prev1.fq + 1
d = d.merge(prev1[["ticker", "name", "fq", "rev_prev_q"]], on=["ticker", "name", "fq"], how="left")
d["seg_yoy"] = np.where(d.rev_yago.abs() > 1e-9, d.rev / d.rev_yago - 1, np.nan)
# prior-quarter y/y for the same segment, to measure acceleration
py = d[["ticker", "name", "fq", "seg_yoy"]].rename(columns={"seg_yoy": "seg_yoy_prev"}); py["fq"] = py.fq + 1
d = d.merge(py[["ticker", "name", "fq", "seg_yoy_prev"]], on=["ticker", "name", "fq"], how="left")
d["seg_accel"] = d.seg_yoy - d.seg_yoy_prev
d.to_pickle("out/study_segment_growth.pkl")
# a segment only contributes a growth figure once it is material: at least 2% of the company's revenue a year earlier.
# Without this, a segment going from 1 to 100 produces a 99x "growth" that would dominate every signal.
MIN_SHARE = 0.02
g = []
for (t, pe), x in d.groupby(["ticker", "period_end"]):
    x = x[x.rev.notna()]
    if not len(x): continue
    base = x.rev_yago.sum()
    small = x.rev_yago.notna() & (base > 0) & (x.rev_yago < MIN_SHARE * base)
    x = x.assign(seg_yoy=x.seg_yoy.mask(small), seg_accel=x.seg_accel.mask(small))
    tot = x.rev.sum(); w = x.rev / tot if tot else np.nan
    ok = x[x.seg_yoy.notna()]
    tot_yago = ok.rev_yago.sum() if len(ok) == len(x) and x.rev_yago.notna().all() else np.nan
    row = dict(ticker=t, period_end=pe, known_at=x.known_at.max(), n_segments=len(x), total_rev=tot,
               total_yoy=(tot / tot_yago - 1) if tot_yago and tot_yago > 0 else np.nan,
               largest_seg=x.loc[x.rev.idxmax(), "name"], largest_share=x.rev.max() / tot if tot else np.nan)
    if len(ok):
        row.update(best_seg_yoy=ok.seg_yoy.max(), worst_seg_yoy=ok.seg_yoy.min(), seg_yoy_disp=ok.seg_yoy.std(),
                   largest_seg_yoy=ok.set_index("name").seg_yoy.get(row["largest_seg"], np.nan),
                   wavg_seg_yoy=float((ok.seg_yoy * (ok.rev / ok.rev.sum())).sum()))
    acc = x[x.seg_accel.notna()]
    if len(acc):
        row.update(best_seg_accel=acc.seg_accel.max(), worst_seg_accel=acc.seg_accel.min(),
                   wavg_seg_accel=float((acc.seg_accel * (acc.rev / acc.rev.sum())).sum()),
                   n_segs_accelerating=int((acc.seg_accel > 0).sum()), share_segs_accelerating=float((acc.seg_accel > 0).mean()))
    g.append(row)
S = pd.DataFrame(g)
# company total-revenue growth from the financials (the baseline signal the segment detail must beat)
fins = []
for t in S.ticker.unique():
    f = pd.read_pickle(f"out/{t}_fin.pkl"); f = f[(f.canonical == "revenue") & (f.duration_months == 3) & (f.basis == "as_first_reported")]
    f = f.sort_values("filed").drop_duplicates("period_end")[["period_end", "value", "filed"]].rename(columns={"value": "co_rev", "filed": "co_known_at"})
    f["ticker"] = t; f["period_end"] = pd.to_datetime(f.period_end); fins.append(f)
F = pd.concat(fins, ignore_index=True).sort_values(["ticker", "period_end"])
F["co_rev_yago"] = F.groupby("ticker").co_rev.shift(4); F["co_yoy"] = F.co_rev / F.co_rev_yago - 1
F["co_yoy_prev"] = F.groupby("ticker").co_yoy.shift(1); F["co_accel"] = F.co_yoy - F.co_yoy_prev
S = S.merge(F[["ticker", "period_end", "co_rev", "co_yoy", "co_accel", "co_known_at"]], on=["ticker", "period_end"], how="left")
S["known_at"] = pd.to_datetime(S[["known_at", "co_known_at"]].max(axis=1))     # public only once both the total and the segments are filed
S["segments_sum_to_total"] = (S.total_rev - S.co_rev).abs() <= (0.005 * S.co_rev.abs() + 1)
# winsorise each signal at the 1st/99th percentile so one extreme quarter cannot drive a result
SIG = ["total_yoy", "best_seg_yoy", "worst_seg_yoy", "seg_yoy_disp", "largest_seg_yoy", "wavg_seg_yoy", "best_seg_accel",
       "worst_seg_accel", "wavg_seg_accel", "share_segs_accelerating", "co_yoy", "co_accel", "largest_share"]
for c in SIG:
    if c in S: S[c] = S[c].clip(S[c].quantile(0.01), S[c].quantile(0.99))
S.to_pickle("out/study_signals.pkl")
print(len(S), "ticker-quarters |", S.ticker.nunique(), "tickers |", S.period_end.min().date(), "->", S.period_end.max().date())
print("with segment y/y:", int(S.best_seg_yoy.notna().sum()), "| with acceleration:", int(S.wavg_seg_accel.notna().sum()),
      "| segments tie to total:", int(S.segments_sum_to_total.sum()), "of", len(S))
print(S[["total_yoy", "best_seg_yoy", "wavg_seg_yoy", "wavg_seg_accel", "seg_yoy_disp", "co_yoy"]].describe().round(3).to_string())
