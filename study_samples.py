"""The same tests on three samples, so the reader can see the event-date choice is not driving anything.

  verified release : the earnings release, restricted to quarters where the release itself printed
                    the segment figures. No look-ahead is possible. This is the primary sample.
  all releases     : every earnings release. More power, but for names that publish segment detail
                    only in the 10-Q the short-horizon windows start before the figures were public.
  10-Q filing date : anchored on the filing instead. Conservative by construction, but a median 13
                    days late, so it misses the announcement move and part of any drift.
"""
import pandas as pd, numpy as np, study_run2 as R
HZ = ["reaction", "b5", "b20", "b60", "b120"]
KEY = ["largest_seg_yoy", "wavg_seg_yoy", "best_seg_yoy", "co_yoy", "co_accel"]

def filed_panel():
    S = pd.read_pickle("out/study_signals.pkl")
    Rt = pd.read_csv("out/study_returns.csv", parse_dates=["known_at", "entry_date"])
    d = S.merge(Rt, on=["ticker", "known_at"])
    d = d[(d.known_at - d.period_end).dt.days <= 120].copy()
    d["cq"] = d.known_at.dt.to_period("Q")
    d = d.rename(columns={"r5": "r5", "r20": "r20"})
    return d

rows = []
P = R.panel()
for nm, F in (("verified release", P[P.usable]), ("all releases", P), ("10-Q filing date", filed_panel())):
    for s in KEY:
        for h in HZ:
            if h not in F.columns: continue
            r = R.quarterly_ic(F, s, h)
            if r: rows.append(dict(sample=nm, n_events=len(F), **r))
T = pd.DataFrame(rows); T.to_pickle("out/study_samples.pkl")
print(T.pivot_table(index=["signal"], columns=["sample", "horizon"], values="mean_ic").round(3).to_string())
print("\nt-stats:")
print(T.pivot_table(index=["signal"], columns=["sample", "horizon"], values="t_stat").round(2).to_string())
print("\nevents per sample:", T.groupby("sample").n_events.first().to_dict())
