"""WU SP500 Hedging Signal overlay on DCA QQQ and on the basket rotation (rel_qqq, $50bn floor, hold).

Hedge on at each WU "exit" (Sell Now) close; size 25% or 50% of the account, short QQQ (or SPY), futures-style:
the notional earns T-bill (BIL) returns, so the hedge costs nothing to carry beyond the index's own return;
10 bp per trade. Traded at the close after the signal. Its gain or loss goes into QQQ at the cover.

Exit rules (the request "exit the hedge when the bear market end signal fires" is read three ways):
  reentry   off at WU's own re-entry ("Buy Now")
  bear_end  off only at the next S&P 500 or Nasdaq bear-end flag (literal reading)
  hybrid    off at the re-entry, unless a bear market (S&P -20%, WU bear-start flag) began while hedged;
            then off at the next bear-end flag
  breadth   the public-data core only (HedgingSignals breadth replica): on at its exit, off at its re-entry

The WU [2.2] calendar is the current indicator painted over history (its inputs and rules were revised as late as
2026), not a record of signals published at the time, so its results are in-sample for the author.

The event calendar is read from the private HedgingSignals clone (WU_EVENTS, default
../hedgingsignals/data/master_daily_spx.csv.gz) and is not copied into this repository; only performance is.
python hedge_overlay.py   -> results/hedge_overlay/summary.md
"""
import os
import numpy as np
import pandas as pd
import basket_backtest as bb
from dca_backtest import contributions, xirr

EVENTS = os.environ.get("WU_EVENTS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hedgingsignals",
                                                  "data", "master_daily_spx.csv.gz"))
OUT = "results/hedge_overlay"

def hedge_periods(T, rule):
    """(on dates, off dates) for a rule, from the WU event columns."""
    on, off, hedged, bear = [], [], False, False
    if rule == "breadth":
        for t, r in T.iterrows():
            if not hedged and r.breadth_exit == 1: hedged = True; on.append(t)
            elif hedged and r.breadth_reentry == 1: hedged = False; off.append(t)
        return on, off
    for t, r in T.iterrows():
        if not hedged:
            if r.wu_exit == 1: hedged, bear = True, False; on.append(t)
            continue
        if r.bear_start == 1: bear = True
        bear_end = r.sp_bear_end == 1 or r.nq_bear_end == 1
        if rule == "reentry": done = r.wu_reentry == 1
        elif rule == "bear_end": done = bear_end
        else: done = bear_end if bear else r.wu_reentry == 1
        if done: hedged = False; off.append(t)
    return on, off

def main():
    T = pd.read_csv(EVENTS, index_col=0, parse_dates=True).loc["2010-01-01":]
    q, adj, cap, meta = bb.load()
    px = pd.read_csv("results/prices/closes.csv", index_col=0, parse_dates=True)
    bil, inst = px["BIL"], {"QQQ": px["QQQ"], "SPY": px["SPY"]}
    sig = bb.prepare(adj, bb.benchmarks(adj, meta, "rel_qqq"))
    end = q.index[-1]
    os.makedirs(OUT, exist_ok=True)
    rows, periods = [], {}
    for years in (5, 15):
        start = end - pd.DateOffset(years=years)
        idx = q.index[q.index >= start]
        flows = contributions(idx)
        base = bb.window(q, adj, cap, sig, start, end, 50, "hold", 0, np.random.default_rng(0), detail=True)
        def add(label, r, frac, rule, ins, hedged_days, n):
            pth = r["paths"]
            rows.append(dict(years=years, rule=rule, size=frac, instrument=ins, hedged_share=hedged_days, hedges=n,
                             rot_final=r["final"], rot_irr=r["irr"], rot_dd=r["maxdd"],
                             qqq_final=r["dca_qqq"], qqq_irr=r["irr_qqq"], qqq_dd=r["maxdd_qqq"]))
        add("none", base, 0, "none", "-", 0.0, 0)
        for rule in ("reentry", "bear_end", "hybrid", "breadth"):
            on, off = hedge_periods(T, rule)
            state = pd.Series(0, idx)
            for a in on:
                b = next((x for x in off if x > a), None)
                state[(idx > a) & ((idx <= b) if b is not None else True)] = 1
            n = sum(1 for a in on if a >= start)
            periods[(years, rule)] = [(a.date(), next((x.date() for x in off if x > a), None)) for a in on if a >= start - pd.Timedelta(days=400)]
            for frac in (0.25, 0.50):
                for ins in ("QQQ", "SPY"):
                    r = bb.window(q, adj, cap, sig, start, end, 50, "hold", 0, np.random.default_rng(0), detail=True,
                                  hedge=(on, off, frac, bil, inst[ins]))
                    add(rule, r, frac, rule, ins, state.mean(), n)
    R = pd.DataFrame(rows); R.to_csv(f"{OUT}/results.csv", index=False)

    money = lambda v: f"${v / 1e6:,.2f}M" if v >= 1e6 else f"${v / 1e3:,.0f}k"
    pct = lambda v: f"{v:+.1%}"
    L = ["# WU SP500 Hedging Signal overlay", "",
         "Short QQQ or SPY worth 25% / 50% of the account while the hedge is on, futures-style (notional in T-bills), "
         "10 bp per trade, traded at the next close. Rotation = rel_qqq, $50bn floor, hold.", ""]
    for years in (5, 15):
        g = R[R.years == years]; b = g[g.rule == "none"].iloc[0]
        L += [f"## Last {years} years", "",
              "| exit rule | hedge | via | time hedged | DCA QQQ final | money-wtd | worst drop | rotation final | money-wtd | worst drop |",
              "|---|---|---|---|---|---|---|---|---|---|",
              f"| no hedge |  |  | 0% | {money(b.qqq_final)} | {b.qqq_irr:.1%} | {b.qqq_dd:.1%} | {money(b.rot_final)} | {b.rot_irr:.1%} | {b.rot_dd:.1%} |"]
        for r in g[g.rule != "none"].itertuples():
            L.append(f"| {r.rule} | {r.size:.0%} | {r.instrument} | {r.hedged_share:.0%} | {money(r.qqq_final)} ({pct(r.qqq_final / b.qqq_final - 1)}) | "
                     f"{r.qqq_irr:.1%} | {r.qqq_dd:.1%} | {money(r.rot_final)} ({pct(r.rot_final / b.rot_final - 1)}) | {r.rot_irr:.1%} | {r.rot_dd:.1%} |")
        L.append("")
    open(f"{OUT}/summary.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    for k, v in periods.items():
        if k[0] == 15: print(k[1], len(v), "hedges; days hedged:", sum(((pd.Timestamp(b) if b else end) - pd.Timestamp(a)).days for a, b in v))

if __name__ == "__main__":
    main()
