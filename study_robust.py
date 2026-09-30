import pandas as pd, numpy as np, study_run2 as R
F = R.panel(); F = F[F.usable].copy()
sub = pd.concat([R.subsamples(F, hz=h).assign(horizon=h) for h in ("b20", "b60", "b120")], ignore_index=True)
sub.to_pickle("out/study_subsample.pkl")
print("=== same IC in each half of the sample (a sign flip means it was fitted) ===")
print(sub.round(3).to_string(index=False))
bt = []
for s in ("largest_seg_yoy", "wavg_seg_yoy", "best_seg_yoy", "co_accel", "co_yoy"):
    for h, hold in (("b60", 60), ("b120", 120)):
        q, m = R.backtest(F, s, h, hold=hold)
        if m: bt.append(m)
BT = pd.DataFrame(bt); BT.to_pickle("out/study_backtest.pkl")
print("\n=== long top quintile / short bottom quintile, quarterly, benchmark-relative, before costs ===")
print(BT.round(3).to_string(index=False))
# the residualised version of the one signal that showed incremental content
F["largest_seg_yoy_x"] = R.residualise(F, "largest_seg_yoy", "co_yoy")
rows = [r for h in ("b20", "b60", "b120") if (r := R.quarterly_ic(F, "largest_seg_yoy_x", h))]
print("\n=== largest_seg_yoy net of consolidated growth, by half ===")
print(pd.concat([R.subsamples(F, ["largest_seg_yoy", "largest_seg_yoy_x"], h).assign(horizon=h) for h in ("b20", "b60", "b120")], ignore_index=True).round(3).to_string(index=False))
q, m = R.backtest(F, "largest_seg_yoy_x", "b60", hold=60)
print("\nbacktest on the residualised signal:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()} if m else None)
if q is not None: q.assign(signal="largest_seg_yoy_x").to_pickle("out/study_backtest_series.pkl")
