"""Contribution backtest: hold new cash in T-bills and buy a stock only when it lags a composite of ETFs badly,
versus simply dollar-cost averaging into QQQ.

Question (as asked): start with $100k, add $4k a month. Compare AMD against several ETFs at once, buy only on
"massive deltas", and see whether that beats DCA into QQQ.

Fixed before any result was seen:

  Composite delta: for each of QQQ, SMH, SOXX, XLK, SPY, the stock's 63-day residual after a trailing 252-day
  beta, divided by its residual vol (relval_backtest.features -> resid_z). Composite = the mean of the five.
  Signal = composite <= -2.0 at a close; buy at the next close. Sensitivity: -1.0, -1.5, -2.5.

  Flows: $100k on the first day, $4k on the first trading day of every later month. 10 bp on every stock/ETF
  buy. Cash waiting for a signal sits in BIL (T-bills), so waiting is not penalised by a zero yield.

  Strategies:
    DCA QQQ          every dollar into QQQ on arrival                                      (the benchmark asked for)
    DCA AMD          every dollar into the stock on arrival             (separates "the stock rose" from timing)
    Timed AMD        every dollar to BIL; all cash into the stock at the close after a signal day
    Random AMD       Timed AMD with the same number of deployments on random days, 1,000 draws      (placebo)
    Core+reserve     75% of each dollar into QQQ on arrival, 25% to BIL and into the stock on signals
    Core+DCA         75% QQQ / 25% stock, both on arrival                         (Core+reserve's no-timing twin)

  Hypotheses:
    H1  Timed AMD ends above DCA QQQ over the last 5 years.                                      (the user's)
    H2  Timed AMD ends above DCA AMD.                                         (the timing itself adds value)
    H3  Timed AMD ends above the 95th percentile of Random AMD.                (the signal beats luck, 5% one-sided)
    H4  Across every 5-year window starting quarterly since 2011, Timed AMD beats DCA AMD in most windows.
    H5  Across the config chip stocks, Timed beats DCA-same-stock for most names over the last 5 years.

Reads results/prices/closes.csv. Writes results/dca_backtest/.
"""
import os, sys
import numpy as np
import pandas as pd
from relval_backtest import features

PX = "results/prices/closes.csv"
OUT = "results/dca_backtest"
COMP = ["QQQ", "SMH", "SOXX", "XLK", "SPY"]
YEARS, INIT, MONTHLY, FEE = 5, 100_000, 4_000, 0.001
Z_ON = -2.0
CORE = 0.75
DRAWS = 1000

# ---------------------------------------------------------------- signal
def composite(px, name):
    a = px[name].dropna()
    zs = pd.DataFrame({e: features(a, px[e].reindex(a.index).ffill()).resid_z for e in COMP})
    return zs.mean(axis=1, skipna=False), zs

# ---------------------------------------------------------------- flows and simulation
def contributions(idx):
    """$INIT on day 0, $MONTHLY on the first trading day of each later month. Returns positions in idx."""
    m = idx.to_period("M")
    pos = [0] + [i for i in range(1, len(idx)) if m[i] != m[i - 1]]
    amt = np.array([INIT] + [MONTHLY] * (len(pos) - 1), float)
    return np.array(pos), amt

def simulate(s, q, bil, flows, deploy, core):
    """Daily account value. s, q, bil: price arrays on one index. flows: (positions, amounts).
    core: share of each dollar bought into QQQ on arrival; the rest goes to BIL and is moved into the stock on
    every day in `deploy` (a boolean array, already lagged to the trade day)."""
    pos, amt = flows
    add = np.zeros(len(s)); add[pos] = amt
    ns = nq = nb = 0.0
    val, units, nav = np.empty(len(s)), np.empty(len(s)), 1.0
    for i in range(len(s)):
        if i:
            before = ns * s[i] + nq * q[i] + nb * bil[i]
            nav *= before / val[i - 1]
        if add[i]:
            nq += add[i] * core * (1 - FEE) / q[i]
            nb += add[i] * (1 - core) / bil[i]
        if deploy[i] and nb > 0:
            ns += nb * bil[i] * (1 - FEE) / s[i]; nb = 0.0
        val[i] = ns * s[i] + nq * q[i] + nb * bil[i]
        units[i] = nav
    return val, units

def final_fast(s, q, bil, flows, deploy_pos, core):
    """Closed-form final value for the reserve leg: each contribution waits in BIL until the next deploy day."""
    pos, amt = flows
    k = np.searchsorted(deploy_pos, pos, side="left")           # first deploy day at or after the contribution
    d = np.where(k < len(deploy_pos), deploy_pos[np.minimum(k, len(deploy_pos) - 1)], -1)
    res = amt * (1 - core)
    grown = np.where(d >= 0, res * bil[np.maximum(d, 0)] / bil[pos] * (1 - FEE) * s[-1] / s[np.maximum(d, 0)],
                     res * bil[-1] / bil[pos])
    return grown.sum() + (amt * core * (1 - FEE) * q[-1] / q[pos]).sum()

def xirr(flows_pos, amt, idx, final):
    t = np.array([(idx[p] - idx[0]).days / 365.25 for p in flows_pos]); T = (idx[-1] - idx[0]).days / 365.25
    f = lambda r: (amt * (1 + r) ** (T - t)).sum() - final
    lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return mid

def robustness(px, name, sig, start, end, rng, sigs):
    """Per threshold: last window for the stock, every rolling 5-year window, and every chip name."""
    rows = []
    first = sig.dropna().index[0]
    starts = pd.date_range(first, end - pd.DateOffset(years=YEARS), freq="QS")
    for z in (-1.0, -1.5, -2.0, -2.5):
        last, _, _ = run_window(px, name, sig, start, end, z_on=z, placebo=True, rng=rng)
        roll = [run_window(px, name, sig, st, st + pd.DateOffset(years=YEARS), z_on=z)[0] for st in starts]
        rr = np.array([r["Timed " + name]["final"] / r["DCA " + name]["final"] for r in roll])
        rq = np.array([r["Timed " + name]["final"] / r["DCA QQQ"]["final"] for r in roll])
        uni = []
        for t, ts in sigs.items():
            u, _, _ = run_window(px, t, ts, start, end, z_on=z, placebo=True, rng=rng)
            uni.append((u["Timed " + t]["final"] / u["DCA " + t]["final"], u.get("placebo", {}).get("timed_pct", np.nan)))
        uni = np.array(uni)
        rows.append(dict(threshold=z, last5_vs_dca_stock=last["Timed " + name]["final"] / last["DCA " + name]["final"] - 1,
                         last5_placebo_pct=last.get("placebo", {}).get("timed_pct", np.nan),
                         windows=len(rr), roll_beats_dca_stock=(rr > 1).mean(), roll_median_vs_dca_stock=np.median(rr) - 1,
                         roll_beats_dca_qqq=(rq > 1).mean(),
                         names=len(uni), uni_beats_dca_stock=(uni[:, 0] > 1).mean(), uni_median_vs_dca_stock=np.median(uni[:, 0]) - 1,
                         uni_above_placebo_median=np.nanmean(uni[:, 1] > 0.5)))
    return pd.DataFrame(rows)

def run_window(px, name, sig, start, end, z_on=Z_ON, placebo=False, rng=None, curves=False):
    idx = px.index[(px.index >= start) & (px.index <= end)]
    idx = idx[px[[name, "QQQ", "BIL"]].reindex(idx).notna().all(axis=1).values]
    s, q, bil = (px[c].reindex(idx).values for c in (name, "QQQ", "BIL"))
    flows = contributions(idx)
    on = (sig.reindex(idx) <= z_on).shift(1, fill_value=False).values   # signal at t-1 close -> trade at t close
    every = np.zeros(len(idx), bool); every[flows[0]] = True
    out, paths = {}, {}
    plans = {"DCA QQQ": (every, 1.0), "DCA " + name: (every, 0.0), "Timed " + name: (on, 0.0),
             "Core+DCA": (every, CORE), "Core+reserve": (on, CORE)}
    for k, (dep, core) in plans.items():
        val, units = simulate(s, q, bil, flows, dep, core)
        dd = (units / np.maximum.accumulate(units) - 1).min()
        out[k] = dict(final=val[-1], irr=xirr(*flows, idx, val[-1]), maxdd=dd)
        if curves: paths[k] = val
    # how the timed book actually behaved
    pos, amt = flows
    tv, _ = simulate(s, q, bil, flows, on, 0.0)
    ns_track = np.zeros(len(idx)); nb = 0.0; ns = 0.0; add = np.zeros(len(idx)); add[pos] = amt
    deploys = 0
    for i in range(len(idx)):
        if add[i]: nb += add[i] / bil[i]
        if on[i] and nb > 0: ns += nb * bil[i] / s[i]; nb = 0.0; deploys += 1
        ns_track[i] = nb * bil[i] / (ns * s[i] + nb * bil[i])
    out["Timed " + name].update(deploys=deploys, avg_cash=ns_track.mean(), signal_days=int(on.sum()))
    dep_pos = np.flatnonzero(on)
    if len(dep_pos):
        assert abs(final_fast(s, q, bil, flows, dep_pos, 0.0) / out["Timed " + name]["final"] - 1) < 1e-9
    if placebo and deploys:
        r = []
        for _ in range(DRAWS):
            rp = np.sort(rng.choice(len(idx), deploys, replace=False))
            r.append((final_fast(s, q, bil, flows, rp, 0.0), final_fast(s, q, bil, flows, rp, CORE)))
        r = np.array(r)
        out["placebo"] = dict(timed_pct=(r[:, 0] < out["Timed " + name]["final"]).mean(),
                              core_pct=(r[:, 1] < out["Core+reserve"]["final"]).mean(),
                              timed_p50=np.median(r[:, 0]), timed_p05=np.percentile(r[:, 0], 5), timed_p95=np.percentile(r[:, 0], 95),
                              core_p50=np.median(r[:, 1]))
    out["_contrib"] = flows[1].sum()
    return out, (pd.DataFrame(paths, index=idx) if curves else None), on

# ---------------------------------------------------------------- main
def money(x): return f"${x:,.0f}"
def pct(x): return f"{x:+.1%}"

def main(name="AMD"):
    px = pd.read_csv(PX, index_col=0, parse_dates=True)
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(11)
    sig, zs = composite(px, name)
    end = px[name].dropna().index[-1]; start = end - pd.DateOffset(years=YEARS)
    corr = zs[zs.index >= start].corr().values; pair = corr[np.triu_indices(len(COMP), 1)].mean()

    res, paths, on = run_window(px, name, sig, start, end, placebo=True, rng=rng, curves=True)
    paths.to_csv(f"{OUT}/curves.csv")
    pd.DataFrame({"composite_z": sig, **{f"z_{c}": zs[c] for c in COMP}})[lambda d: d.index >= start].round(3).to_csv(f"{OUT}/signal.csv")
    buys = paths.index[on]
    sens = []
    for z in (-1.0, -1.5, -2.0, -2.5):
        r, _, _ = run_window(px, name, sig, start, end, z_on=z, placebo=True, rng=rng)
        t = r["Timed " + name]
        sens.append(dict(threshold=z, deploys=t["deploys"], avg_cash=t["avg_cash"], timed=t["final"],
                         vs_dca_qqq=t["final"] / r["DCA QQQ"]["final"] - 1, vs_dca_stock=t["final"] / r["DCA " + name]["final"] - 1,
                         placebo_pct=r.get("placebo", {}).get("timed_pct", np.nan),
                         core_reserve=r["Core+reserve"]["final"], core_vs_twin=r["Core+reserve"]["final"] / r["Core+DCA"]["final"] - 1))
    sens = pd.DataFrame(sens); sens.to_csv(f"{OUT}/sensitivity.csv", index=False)

    roll = []
    first = sig.dropna().index[0]
    for st in pd.date_range(first, end - pd.DateOffset(years=YEARS), freq="QS"):
        r, _, _ = run_window(px, name, sig, st, st + pd.DateOffset(years=YEARS))
        roll.append(dict(start=st.date(), dca_qqq=r["DCA QQQ"]["final"], dca_stock=r["DCA " + name]["final"],
                         timed=r["Timed " + name]["final"], deploys=r["Timed " + name]["deploys"],
                         core_reserve=r["Core+reserve"]["final"], core_dca=r["Core+DCA"]["final"]))
    roll = pd.DataFrame(roll); roll.to_csv(f"{OUT}/rolling.csv", index=False)

    sigs = {t: composite(px, t)[0] for t in sorted(c for c in px.columns if c not in set(COMP) | {"BIL", "PSQ", "SOXS", "SH"})
            if px[t].dropna().index[0] <= start - pd.DateOffset(days=550)}   # a year of beta + 63 days before start
    rob = robustness(px, name, sig, start, end, rng, sigs); rob.to_csv(f"{OUT}/robustness.csv", index=False)
    uni = []
    for t, st_sig in sigs.items():
        r, _, _ = run_window(px, t, st_sig, start, end, placebo=True, rng=rng)
        tm = r["Timed " + t]
        uni.append(dict(ticker=t, deploys=tm["deploys"], dca_qqq=r["DCA QQQ"]["final"], dca_stock=r["DCA " + t]["final"],
                        timed=tm["final"], timed_vs_dca_stock=tm["final"] / r["DCA " + t]["final"] - 1,
                        timed_vs_dca_qqq=tm["final"] / r["DCA QQQ"]["final"] - 1,
                        placebo_pct=r.get("placebo", {}).get("timed_pct", np.nan)))
    uni = pd.DataFrame(uni).set_index("ticker"); uni.to_csv(f"{OUT}/universe.csv")

    rows = [dict(strategy=k, **v) for k, v in res.items() if not k.startswith(("_", "placebo"))]
    summ = pd.DataFrame(rows).set_index("strategy"); summ.to_csv(f"{OUT}/strategies.csv")
    pl = res.get("placebo", {})
    pd.DataFrame([pl]).to_csv(f"{OUT}/placebo.csv", index=False)
    pd.DataFrame({"date": buys.date}).to_csv(f"{OUT}/buys.csv", index=False)

    L = [f"# {name}: buy only on composite deltas vs DCA", "",
         f"Window {paths.index[0]:%Y-%m-%d} .. {paths.index[-1]:%Y-%m-%d}. {money(INIT)} then {money(MONTHLY)}/month: "
         f"{money(res['_contrib'])} contributed. Composite = mean beta-adjusted 63-day z vs {', '.join(COMP)}; "
         f"signal <= {Z_ON}. Average pairwise correlation of the five z-series: {pair:.2f}.", "",
         "| strategy | final value | profit | money-weighted return | worst drop (time-weighted) |", "|---|---|---|---|---|"]
    for k, r in summ.iterrows():
        L.append(f"| {k} | {money(r.final)} | {money(r.final - res['_contrib'])} | {r.irr:+.1%}/yr | {r.maxdd:.1%} |")
    t = res["Timed " + name]
    L += ["", f"Timed {name}: {t['deploys']} deployments, {t['signal_days']} signal days, average {t['avg_cash']:.0%} of the account in T-bills.",
          f"Buy days: {', '.join(str(d.date()) for d in buys[:40])}{' ...' if len(buys) > 40 else ''}", "",
          f"Placebo (same {t['deploys']} deployments on random days, {DRAWS} draws): timed beats {pl.get('timed_pct', np.nan):.0%} of draws "
          f"(median {money(pl.get('timed_p50', np.nan))}, 5-95% {money(pl.get('timed_p05', np.nan))} .. {money(pl.get('timed_p95', np.nan))}); "
          f"core+reserve beats {pl.get('core_pct', np.nan):.0%} of its draws.", "",
          "## Threshold sensitivity", "",
          "| threshold | deploys | avg in T-bills | timed final | vs DCA QQQ | vs DCA stock | beats % of random | core+reserve vs core+DCA |",
          "|---|---|---|---|---|---|---|---|"]
    for r in sens.itertuples():
        L.append(f"| {r.threshold} | {r.deploys} | {r.avg_cash:.0%} | {money(r.timed)} | {pct(r.vs_dca_qqq)} | {pct(r.vs_dca_stock)} | "
                 f"{r.placebo_pct:.0%} | {pct(r.core_vs_twin)} |")
    L += ["", "## Robustness by threshold", "",
          "| threshold | AMD last 5y vs DCA AMD | beats % of random | 5y windows timed > DCA AMD | median vs DCA AMD | timed > DCA QQQ | chip names timed > DCA same stock | median | names above placebo median |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rob.itertuples():
        L.append(f"| {r.threshold} | {pct(r.last5_vs_dca_stock)} | {r.last5_placebo_pct:.0%} | {r.roll_beats_dca_stock:.0%} of {r.windows} | "
                 f"{pct(r.roll_median_vs_dca_stock)} | {r.roll_beats_dca_qqq:.0%} | {r.uni_beats_dca_stock:.0%} of {r.names} | "
                 f"{pct(r.uni_median_vs_dca_stock)} | {r.uni_above_placebo_median:.0%} |")
    L += ["", f"## Every 5-year window, quarterly starts {roll.start.iloc[0]} .. {roll.start.iloc[-1]} ({len(roll)} windows, overlapping)", "",
          f"- Timed beats DCA QQQ in {(roll.timed > roll.dca_qqq).mean():.0%} of windows",
          f"- Timed beats DCA {name} in {(roll.timed > roll.dca_stock).mean():.0%} of windows; median ratio {pct((roll.timed / roll.dca_stock).median() - 1)}",
          f"- DCA {name} beats DCA QQQ in {(roll.dca_stock > roll.dca_qqq).mean():.0%} of windows",
          f"- Core+reserve beats Core+DCA in {(roll.core_reserve > roll.core_dca).mean():.0%} of windows; median {pct((roll.core_reserve / roll.core_dca).median() - 1)}", "",
          "| start | DCA QQQ | DCA stock | timed | deploys |", "|---|---|---|---|---|"]
    for r in roll.itertuples():
        L.append(f"| {r.start} | {money(r.dca_qqq)} | {money(r.dca_stock)} | {money(r.timed)} | {r.deploys} |")
    L += ["", "## Chip universe, last 5 years", "",
          f"- Timed beats DCA-same-stock for {(uni.timed_vs_dca_stock > 0).mean():.0%} of {len(uni)} names; median {pct(uni.timed_vs_dca_stock.median())}",
          f"- Timed beats DCA QQQ for {(uni.timed_vs_dca_qqq > 0).mean():.0%}; DCA-same-stock beats DCA QQQ for {(uni.dca_stock > uni.dca_qqq).mean():.0%}",
          f"- Timed beats the median random draw for {(uni.placebo_pct > 0.5).mean():.0%}; above the 95th percentile for {(uni.placebo_pct > 0.95).mean():.0%}", "",
          "| ticker | deploys | DCA QQQ | DCA stock | timed | timed vs DCA stock | beats % of random |", "|---|---|---|---|---|---|---|"]
    for k, r in uni.iterrows():
        L.append(f"| {k} | {r.deploys} | {money(r.dca_qqq)} | {money(r.dca_stock)} | {money(r.timed)} | {pct(r.timed_vs_dca_stock)} | {r.placebo_pct:.0%} |")
    open(f"{OUT}/summary.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main(*sys.argv[1:2])
