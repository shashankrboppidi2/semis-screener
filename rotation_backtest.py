"""Rotation backtest: park every dollar in QQQ, rotate part of it into a stock when the stock corrects hard.

Question (as asked): start with $100k, add $4k a month, keep the money in QQQ, and rotate into a risk-on name
like AMD when it corrects significantly. Does that beat plain DCA into QQQ?

Fixed before any result was seen:

  Signals (known at a close, traded at the next close; an episode starts on the first signal day with no episode
  start in the previous 63 trading days, relval_backtest.episodes):
    rel   composite delta <= -2.0: mean beta-adjusted 63-day z vs QQQ, SMH, SOXX, XLK, SPY (dca_backtest.composite)
    abs   the stock >= 30% below its own 252-day closing high
  Rotation: at each episode start move 10% of the account from QQQ into the stock, never above 40% in the stock.
  Exits:
    hold   never rotate back (the cap only stops further buys)
    trip   rotate the whole stock position back into QQQ when it has recovered (rel: composite >= 0;
           abs: within 10% of its 252-day high) or 252 trading days after the last rotation in
  Flows: $100k on day one, $4k on the first trading day of each later month, all into QQQ. 10 bp per trade leg.

  Controls:
    DCA QQQ    every dollar into QQQ
    Matched    every dollar into a fixed mix at the strategy's time-average stock weight, rebalanced monthly
    Random     the same number of episode starts on random days, same step, cap and (for trip) the same holding
               periods shuffled; 1,000 draws, reported as the share of draws the strategy beats

  Hypotheses (last 5 years, AMD):
    H1  the rotation ends above DCA QQQ                                                         (the user's)
    H2  the rotation ends above Matched                                           (timing, not more AMD)
    H3  the rotation beats 95% of Random                                                   (not luck)
    H4  across quarterly-start 5-year windows since 2012, the rotation beats Matched in most windows
    H5  across the config chip names, the rotation beats Matched for most names

Taxes are not deducted; realized gains (average-cost basis) are reported so the drag can be judged.
Reads results/prices/closes.csv. Writes results/rotation_backtest/.
"""
import os, sys
import numpy as np
import pandas as pd
from relval_backtest import episodes
from dca_backtest import composite, contributions, xirr, COMP

PX = "results/prices/closes.csv"
OUT = "results/rotation_backtest"
YEARS, FEE = 5, 0.001
STEP, CAP, MAX_HOLD = 0.10, 0.40, 252
DRAWS = 1000

# ---------------------------------------------------------------- signals
def signals(px, name, kind):
    """(entry flags, recovered flags) on the stock's own index, both known at the close."""
    a = px[name].dropna()
    if kind == "rel":
        z, _ = composite(px, name)
        return (z <= -2.0), (z >= 0)
    dd = a / a.rolling(252, min_periods=252).max() - 1
    return (dd <= -0.30), (dd >= -0.10)

# ---------------------------------------------------------------- simulation
def simulate(s, q, flows, entry, exitd, fixed=None):
    """Daily book of QQQ (q) and the stock (s). entry/exitd: boolean arrays of trade days (already lagged).
    fixed: a constant stock weight instead (new money split, monthly rebalance) for the Matched control.
    Returns value path, time-weighted unit path, stock weight path, realized gains, trades."""
    pos, amt = flows
    add = np.zeros(len(s)); add[pos] = amt
    month_end = np.zeros(len(s), bool); month_end[pos[1:] - 1] = True
    ns = nq = 0.0; bs = bq = 0.0                                     # shares and cost basis (total $)
    val, unit, wt = np.empty(len(s)), np.empty(len(s)), np.empty(len(s))
    nav, gains, trades = 1.0, 0.0, 0

    def sell_q(x):
        nonlocal nq, bq, gains
        sh = min(nq, x / q[i]); gains += sh * q[i] - bq * sh / nq; bq -= bq * sh / nq; nq -= sh
        return sh * q[i]
    def sell_s(x):
        nonlocal ns, bs, gains
        sh = min(ns, x / s[i]); gains += sh * s[i] - bs * sh / ns; bs -= bs * sh / ns; ns -= sh
        return sh * s[i]

    for i in range(len(s)):
        if i:
            nav *= (ns * s[i] + nq * q[i]) / val[i - 1]
        if add[i]:
            w = 0.0 if fixed is None else fixed
            c = add[i] * (1 - FEE)
            nq += c * (1 - w) / q[i]; bq += c * (1 - w)
            ns += c * w / s[i]; bs += c * w
        V = ns * s[i] + nq * q[i]
        if fixed is not None:
            if month_end[i] and V > 0:
                d = fixed * V - ns * s[i]
                if d > 0 and nq > 0:
                    x = sell_q(d) * (1 - FEE); ns += x * (1 - FEE) / s[i]; bs += x * (1 - FEE)
                elif d < 0 and ns > 0:
                    x = sell_s(-d) * (1 - FEE); nq += x * (1 - FEE) / q[i]; bq += x * (1 - FEE)
        else:
            if exitd[i] and ns > 0:
                x = sell_s(ns * s[i]) * (1 - FEE); nq += x * (1 - FEE) / q[i]; bq += x * (1 - FEE); trades += 1
            if entry[i] and nq > 0:
                room = CAP * V - ns * s[i]
                if room > 0:
                    x = sell_q(min(STEP * V, room)) * (1 - FEE); ns += x * (1 - FEE) / s[i]; bs += x * (1 - FEE); trades += 1
        val[i] = ns * s[i] + nq * q[i]
        unit[i] = nav
        wt[i] = ns * s[i] / val[i]
    return val, unit, wt, gains, trades

def exits_for(entry_days, recovered, n, trip):
    """Round-trip exit days: the first recovered day after an entry, or MAX_HOLD days after the latest entry."""
    out = np.zeros(n, bool)
    if not trip or not len(entry_days): return out
    last, live = None, False
    ent = np.zeros(n, bool); ent[entry_days] = True
    for i in range(n):
        if ent[i]: last, live = i, True
        elif live and (recovered[i] or i - last >= MAX_HOLD):
            out[i] = True; live = False
    return out

def trips(entry_days, exitd):
    """Holding period of each round trip: first entry since the previous exit, to the exit."""
    d, prev = [], -1
    for x in np.flatnonzero(exitd):
        e = entry_days[(entry_days > prev) & (entry_days < x)]
        if len(e): d.append(x - e[0])
        prev = x
    return np.array(d) if d else np.array([MAX_HOLD])

# ---------------------------------------------------------------- one window
def run(px, name, kind, exit_rule, start, end, placebo=0, rng=None, sig_cache=None):
    sig_on, sig_rec = sig_cache[(name, kind)] if sig_cache is not None else signals(px, name, kind)
    idx = px.index[(px.index >= start) & (px.index <= end)]
    idx = idx[px[[name, "QQQ"]].reindex(idx).notna().all(axis=1).values]
    s, q = px[name].reindex(idx).values, px["QQQ"].reindex(idx).values
    flows = contributions(idx)
    on = sig_on.reindex(idx).fillna(False)
    starts = episodes(on)                                           # episode-start dates (signal days)
    ent = np.zeros(len(idx), bool)
    k = idx.get_indexer(starts) + 1; k = k[k < len(idx)]; ent[k] = True   # trade at the next close
    rec = sig_rec.reindex(idx).fillna(False).shift(1, fill_value=False).values
    trip = exit_rule == "trip"
    ex = exits_for(np.flatnonzero(ent), rec, len(idx), trip)
    val, unit, wt, gains, trades = simulate(s, q, flows, ent, ex)
    every = np.zeros(len(idx), bool)
    dq = simulate(s, q, flows, every, every, fixed=0.0)
    wbar = float(wt.mean())
    mt = simulate(s, q, flows, every, every, fixed=round(wbar, 4))
    res = dict(final=val[-1], dca_qqq=dq[0][-1], matched=mt[0][-1], avg_w=wbar, episodes=int(ent.sum()), trades=trades,
               gains=gains, matched_gains=mt[3], irr=xirr(*flows, idx, val[-1]), irr_qqq=xirr(*flows, idx, dq[0][-1]),
               maxdd=(unit / np.maximum.accumulate(unit) - 1).min(), maxdd_qqq=(dq[1] / np.maximum.accumulate(dq[1]) - 1).min(),
               contributed=flows[1].sum())
    if placebo and ent.sum():
        durs = trips(np.flatnonzero(ent), ex)
        beats = []
        for _ in range(placebo):
            e = np.sort(rng.choice(len(idx) - 1, int(ent.sum()), replace=False)) + 1
            pe = np.zeros(len(idx), bool); pe[e] = True
            px_ = np.zeros(len(idx), bool)
            if trip:
                xs = np.minimum(e + rng.choice(durs, len(e)), len(idx) - 1); px_[xs] = True
            beats.append(simulate(s, q, flows, pe, px_)[0][-1])
        beats = np.array(beats)
        res.update(placebo_pct=(beats < val[-1]).mean(), placebo_median=np.median(beats))
    paths = pd.DataFrame(dict(rotation=val, dca_qqq=dq[0], matched=mt[0], weight=wt), index=idx)
    return res, paths

# ---------------------------------------------------------------- main
def money(x): return f"${x:,.0f}"
def pct(x): return f"{x:+.1%}"

def main(name="AMD"):
    px = pd.read_csv(PX, index_col=0, parse_dates=True)
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(23)
    end = px[name].dropna().index[-1]; start = end - pd.DateOffset(years=YEARS)
    names = sorted(c for c in px.columns if c not in set(COMP) | {"BIL", "PSQ", "SOXS", "SH"} and px[c].dropna().index[0] <= start - pd.DateOffset(days=550))
    cache = {(t, k): signals(px, t, k) for t in names for k in ("rel", "abs")}
    configs = [(k, x) for k in ("rel", "abs") for x in ("hold", "trip")]
    label = {("rel", "hold"): "Relative delta, hold", ("rel", "trip"): "Relative delta, round trip",
             ("abs", "hold"): "30% correction, hold", ("abs", "trip"): "30% correction, round trip"}

    main_rows, curves = [], {}
    for k, x in configs:
        r, p = run(px, name, k, x, start, end, placebo=DRAWS, rng=rng, sig_cache=cache)
        main_rows.append(dict(config=label[(k, x)], **r)); curves[label[(k, x)]] = p
    mr = pd.DataFrame(main_rows).set_index("config"); mr.to_csv(f"{OUT}/strategies.csv")
    pd.concat({k: v for k, v in curves.items()}, axis=1).to_csv(f"{OUT}/curves.csv")

    roll = []
    first = max(cache[(name, "rel")][0].dropna().index[0], px[name].dropna().index[0] + pd.DateOffset(years=1))
    for st in pd.date_range(first, end - pd.DateOffset(years=YEARS), freq="QS"):
        for k, x in configs:
            r, _ = run(px, name, k, x, st, st + pd.DateOffset(years=YEARS), sig_cache=cache)
            roll.append(dict(start=st.date(), config=label[(k, x)], **{c: r[c] for c in ("final", "dca_qqq", "matched", "avg_w", "episodes")}))
    roll = pd.DataFrame(roll); roll.to_csv(f"{OUT}/rolling.csv", index=False)

    rp = []                                                         # the placebo in every window, for the abs signal
    for x in ("hold", "trip"):
        for st in pd.date_range(first, end - pd.DateOffset(years=YEARS), freq="QS"):
            r, _ = run(px, name, "abs", x, st, st + pd.DateOffset(years=YEARS), placebo=200, rng=rng, sig_cache=cache)
            rp.append(dict(config=label[("abs", x)], start=st.date(), placebo_pct=r.get("placebo_pct", np.nan),
                           vs_random_median=r["final"] / r["placebo_median"] - 1 if "placebo_median" in r else np.nan))
    rp = pd.DataFrame(rp); rp.to_csv(f"{OUT}/rolling_placebo.csv", index=False)

    uni = []
    for t in names:
        for k, x in configs:
            r, _ = run(px, t, k, x, start, end, placebo=100, rng=rng, sig_cache=cache)
            uni.append(dict(ticker=t, config=label[(k, x)], **{c: r.get(c, np.nan) for c in
                       ("final", "dca_qqq", "matched", "avg_w", "episodes", "placebo_pct")}))
    uni = pd.DataFrame(uni); uni.to_csv(f"{OUT}/universe.csv", index=False)

    c0 = mr.contributed.iloc[0]
    L = [f"# {name}: park in QQQ, rotate on corrections", "",
         f"Window {start:%Y-%m-%d} .. {end:%Y-%m-%d}. $100,000 then $4,000/month into QQQ: {money(c0)} contributed. "
         f"Each correction episode moves {STEP:.0%} of the account into {name}, capped at {CAP:.0%}.", "",
         "| strategy | final | vs DCA QQQ | vs matched | avg stock weight | episodes | money-wtd return | worst drop | realized gains | beats % of random |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    q = mr.iloc[0]
    L.append(f"| DCA QQQ | {money(q.dca_qqq)} |  |  | 0% |  | {q.irr_qqq:+.1%}/yr | {q.maxdd_qqq:.1%} | $0 |  |")
    for k, r in mr.iterrows():
        L.append(f"| {k} | {money(r.final)} | {pct(r.final / r.dca_qqq - 1)} | {pct(r.final / r.matched - 1)} | {r.avg_w:.0%} | "
                 f"{r.episodes} | {r.irr:+.1%}/yr | {r.maxdd:.1%} | {money(r.gains)} | {r.get('placebo_pct', np.nan):.0%} |")
        L.append(f"|   matched {r.avg_w:.1%} {name}, no timing | {money(r.matched)} | {pct(r.matched / r.dca_qqq - 1)} |  |  |  |  |  | {money(r.matched_gains)} |  |")
    L += ["", f"## Every 5-year window, quarterly starts {roll.start.min()} .. {roll.start.max()} ({roll.start.nunique()} windows, overlapping)", "",
          "| strategy | beats DCA QQQ | median vs DCA QQQ | beats matched | median vs matched |", "|---|---|---|---|---|"]
    for k, g in roll.groupby("config", sort=False):
        L.append(f"| {k} | {(g.final > g.dca_qqq).mean():.0%} | {pct((g.final / g.dca_qqq).median() - 1)} | "
                 f"{(g.final > g.matched).mean():.0%} | {pct((g.final / g.matched).median() - 1)} |")
    L += ["", "### Same windows against random rotation dates (200 draws per window)", "",
          "| strategy | beats random median | above random 95th | median vs random median |", "|---|---|---|---|"]
    for k, g in rp.groupby("config", sort=False):
        L.append(f"| {k} | {(g.placebo_pct > 0.5).mean():.0%} | {(g.placebo_pct > 0.95).mean():.0%} | {pct(g.vs_random_median.median())} |")
    L += ["", f"## Chip names, last 5 years ({uni.ticker.nunique()} names)", "",
          "| strategy | beats DCA QQQ | median vs DCA QQQ | beats matched | median vs matched | above random median | above random 95th |",
          "|---|---|---|---|---|---|---|"]
    for k, g in uni.groupby("config", sort=False):
        L.append(f"| {k} | {(g.final > g.dca_qqq).mean():.0%} | {pct((g.final / g.dca_qqq).median() - 1)} | "
                 f"{(g.final > g.matched).mean():.0%} | {pct((g.final / g.matched).median() - 1)} | "
                 f"{(g.placebo_pct > 0.5).mean():.0%} | {(g.placebo_pct > 0.95).mean():.0%} |")
    piv = uni.assign(v=uni.final / uni.dca_qqq - 1).pivot(index="ticker", columns="config", values="v")[list(label.values())]
    L += ["", "### Per name: rotation vs DCA QQQ", "", "| ticker | " + " | ".join(piv.columns) + " |", "|---" * (len(piv.columns) + 1) + "|"]
    for t, r in piv.iterrows():
        L.append(f"| {t} | " + " | ".join(pct(v) for v in r.values) + " |")
    open(f"{OUT}/summary.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main(*sys.argv[1:2])
