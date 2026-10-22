"""Relative-value "buy the laggard" overlay: add to a stock when it has fallen hard against a benchmark.

Question (as asked): alert when AMD's price relative to QQQ drops severely, and use the alert to raise AMD
exposure. How would that have done over the last five years?

Fixed before any result was seen:

  Signals, all from closes known at t, traded at the close of t+1:
    S1 ratio_dd   AMD/QQQ price ratio >= 30% below its trailing 252-day high          (the rule as asked)
    S2 rel_z      63-day log return of AMD minus QQQ, divided by its own trailing vol, <= -1.5
    S3 resid_z    63-day residual of AMD after a trailing 252-day beta to QQQ, / resid vol, <= -1.5
    S4 resid_smh  S3 against SMH, so semis-wide drawdowns do not count as AMD-specific
  An episode starts on the first signal day with no episode start in the previous 63 trading days.

  Portfolio: 10% AMD / 90% QQQ core, rebalanced monthly. Overlay: 20% AMD for 126 trading days after
  the latest signal, funded from QQQ. 10 bp per unit of turnover. Judged against a static mix holding the
  overlay's *average* AMD weight -- otherwise a rule that adds AMD looks good just because AMD went up.

  Hypotheses (pass = beats the exposure-matched static mix on the stated measure):
    H1  AMD, last 5 years: S1 overlay beats its exposure-matched mix on total return.
    H2  Same for S3 (beta-adjusted), the version a risk desk would run.
    H3  Generalises: across the config semis universe, mean 126-day forward excess return (vs QQQ) after
        S3 episodes beats a placebo of the same number of random dates per name (1,000 draws, one-sided 5%).
    H4  Shape: forward 63-day relative return rises from the bottom to the top quintile of rel_z
        (momentum) rather than falls (reversal).  Informative either way; reported as the quintile table.

Reads results/prices/closes.csv (fetch_prices.py). Writes results/relval_backtest/.
"""
import os, sys
import numpy as np
import pandas as pd

PX = "results/prices/closes.csv"
OUT = "results/relval_backtest"
YEARS = 5
LB, H, BETA_W = 63, 126, 252
Z_ON, DD_ON = -1.5, np.log(0.70)
BASE_W, OVER_W, COST = 0.10, 0.20, 0.001
HORIZONS = (21, 63, 126, 252)

# ---------------------------------------------------------------- signals
def features(a, b):
    """a, b: price series (same index). Returns the signal inputs, all known at the close of each day."""
    la, lb = np.log(a), np.log(b)
    ra, rb = la.diff(), lb.diff()
    rel = la - lb
    out = pd.DataFrame(index=a.index)
    out["ratio_dd"] = rel - rel.rolling(BETA_W, min_periods=BETA_W).max()
    rr = ra - rb
    out["rel_z"] = (rel - rel.shift(LB)) / (rr.rolling(BETA_W).std() * np.sqrt(LB))
    beta = ra.rolling(BETA_W).cov(rb) / rb.rolling(BETA_W).var()
    res = ra - beta.shift(1) * rb                                   # yesterday's beta: no look-ahead
    out["resid_z"] = res.rolling(LB).sum() / (res.rolling(BETA_W).std() * np.sqrt(LB))
    out["beta"] = beta
    # S5 (added after S1-S4 were seen): armed by a 30% ratio drawdown in the last 126 days, fires when the
    # ratio closes back above its 50-day average -- buy the laggard once it stops lagging, not on the way down
    armed = (out.ratio_dd <= DD_ON).astype(float).rolling(H, min_periods=1).max().astype(bool)
    above = rel > rel.rolling(50).mean()
    out["turn"] = armed & above & ~above.shift(1, fill_value=False)
    return out

def fire(f, kind, z_on=Z_ON, dd_on=DD_ON):
    if kind == "ratio_dd": return f.ratio_dd <= dd_on
    if kind == "turn": return f.turn
    return f[kind] <= z_on

def episodes(on):
    """First signal day with no episode start in the previous LB days."""
    starts, last = [], None
    for i, (d, v) in enumerate(on.items()):
        if v and (last is None or i - last >= LB):
            starts.append(d); last = i
    return pd.DatetimeIndex(starts)

# ---------------------------------------------------------------- portfolio
def simulate(ra, rb, target):
    """Daily NAV of a two-asset book. target = desired weight in asset a, already lagged to be tradable.
    Rebalance to target when it changes or at month end; COST per unit of turnover."""
    nav, wa = 1.0, target.iloc[0]
    xa, xb = nav * wa, nav * (1 - wa)
    navs, wts, turn = [], [], 0.0
    month = target.index.to_period("M")
    for i, d in enumerate(target.index):
        if i:
            xa *= np.exp(ra.iloc[i]); xb *= np.exp(rb.iloc[i])
        nav = xa + xb
        t = target.iloc[i]
        month_end = i + 1 < len(target) and month[i + 1] != month[i]
        if i == 0 or t != target.iloc[i - 1] or month_end:
            tr = abs(nav * t - xa)
            nav -= 2 * tr * COST                                     # buy one leg, sell the other
            xa, xb = nav * t, nav * (1 - t)
            turn += 2 * tr / max(nav, 1e-12)
        navs.append(nav); wts.append(xa / nav)
    return pd.Series(navs, target.index), pd.Series(wts, target.index), turn

def stats(nav, years):
    r = np.log(nav).diff().dropna()
    dd = nav / nav.cummax() - 1
    return dict(total=nav.iloc[-1] / nav.iloc[0] - 1, cagr=(nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1,
                vol=r.std() * np.sqrt(252), sharpe=r.mean() / r.std() * np.sqrt(252), maxdd=dd.min())

def overlay_target(on, idx, hold=H):
    """OVER_W for `hold` days after the latest signal day, else BASE_W; lagged one day (signal at t, trade t+1)."""
    last = pd.Series(np.where(on.reindex(idx).fillna(False), np.arange(len(idx)), np.nan), idx).ffill()
    since = np.arange(len(idx)) - last
    tgt = pd.Series(np.where(since < hold, OVER_W, BASE_W), idx)
    return tgt.shift(1).fillna(BASE_W)

def run_portfolio(px, name, bench, start):
    a, b = px[name].dropna(), px[bench].dropna()
    idx = a.index.intersection(b.index)
    a, b = a[idx], b[idx]
    f = features(a, b)
    f_smh = features(a, px["SMH"].reindex(idx).ffill())
    ra, rb = np.log(a).diff().fillna(0), np.log(b).diff().fillna(0)
    win = idx[idx >= start]
    years = (win[-1] - win[0]).days / 365.25
    rows, curves = [], {}
    def book(label, tgt, on=None):
        nav, w, turn = simulate(ra[win], rb[win], tgt[win])
        s = stats(nav, years); s.update(strategy=label, avg_amd_w=w.mean(), turnover_per_yr=turn / years)
        if on is not None:
            ep = episodes(on[win]); s.update(episodes=len(ep), days_overweight=int((tgt[win] > BASE_W).sum()))
        rows.append(s); curves[label] = nav
        return s
    base = book(f"static {BASE_W:.0%} {name}", pd.Series(BASE_W, idx))
    for kind, lab, ff in [("ratio_dd", "S1 ratio drawdown", f), ("rel_z", "S2 vol-adj rel", f),
                          ("resid_z", "S3 beta-adj resid", f), ("resid_z", "S4 resid vs SMH", f_smh),
                          ("turn", "S5 drawdown then turn (post hoc)", f)]:
        on = fire(ff, kind)
        s = book(lab, overlay_target(on, idx), on)
        m = book(f"  matched static {s['avg_amd_w']:.1%}", pd.Series(round(s["avg_amd_w"], 4), idx))
        rows[-2]["vs_matched"] = (1 + s["total"]) / (1 + m["total"]) - 1
    return pd.DataFrame(rows).set_index("strategy"), pd.DataFrame(curves), f.loc[win], f_smh.loc[win]

def sensitivity(px, name, bench, start):
    """vs-matched total return across thresholds and hold periods: how fragile is any one setting."""
    a, b = px[name].dropna(), px[bench].dropna()
    idx = a.index.intersection(b.index); a, b = a[idx], b[idx]
    ra, rb = np.log(a).diff().fillna(0), np.log(b).diff().fillna(0)
    win = idx[idx >= start]
    feats = {bench: features(a, b), "SMH": features(a, px["SMH"].reindex(idx).ffill())}
    grid = [("ratio_dd", bench, dict(dd_on=np.log(1 - x)), f"ratio {x:.0%} off 1y high") for x in (0.2, 0.3, 0.4)]
    grid += [(k, bb, dict(z_on=z), f"{k} vs {bb} <= {z}") for k, bb in (("rel_z", bench), ("resid_z", bench), ("resid_z", "SMH"))
             for z in (-1.0, -1.5, -2.0)]
    grid += [("turn", bench, {}, "drawdown then turn (post hoc)")]
    rows = []
    for kind, bb, kw, lab in grid:
        on = fire(feats[bb], kind, **kw)
        row = dict(rule=lab, episodes=len(episodes(on[win])))
        for hold in (63, 126, 252):
            tgt = overlay_target(on, idx, hold)
            nav, w, _ = simulate(ra[win], rb[win], tgt[win])
            m, _, _ = simulate(ra[win], rb[win], pd.Series(round(w.mean(), 4), win))
            row[f"hold {hold}d"] = nav.iloc[-1] / m.iloc[-1] - 1
        rows.append(row)
    return pd.DataFrame(rows).set_index("rule")

def episode_list(px, name, bench, start):
    a = px[name].dropna(); rows = []
    for bb in (bench, "SMH"):
        b = px[bb].reindex(a.index).ffill(); f = features(a, b)
        for kind in (("ratio_dd", "resid_z", "turn") if bb == bench else ("resid_z",)):
            for d in episodes(fire(f, kind)[f.index >= start]):
                r = {h: forward(a, b, f.beta, d, h) for h in (63, 126, 252)}
                rows.append(dict(signal=f"{kind} vs {bb}", date=d.date(), px=a.loc[d], ratio_dd=f.ratio_dd.loc[d],
                                 z=f.resid_z.loc[d],
                                 **{f"rel_{h}": (r[h] or {}).get("rel") for h in r}))
    return pd.DataFrame(rows)

# ---------------------------------------------------------------- event study
def forward(a, b, beta, d, h):
    """Log return of a, of a minus b, and beta-adjusted (beta frozen at d), from the close after d over h days."""
    i = a.index.get_loc(d) + 1
    if i + h >= len(a): return None
    la, lb = np.log(a.iloc[i + h] / a.iloc[i]), np.log(b.iloc[i + h] / b.iloc[i])
    path = np.log(a.iloc[i:i + h + 1] / a.iloc[i]).values - np.log(b.iloc[i:i + h + 1] / b.iloc[i]).values
    return dict(raw=la, rel=la - lb, resid=la - beta.loc[d] * lb, worst_rel=path.min())

def event_table(px, name, bench, start, kinds=("ratio_dd", "rel_z", "resid_z", "turn")):
    a, b = px[name].dropna(), px[bench].reindex(px[name].dropna().index).ffill()
    f = features(a, b)
    rows = []
    for kind in kinds:
        ep = episodes(fire(f, kind)[f.index >= start])
        for d in ep:
            for h in HORIZONS:
                r = forward(a, b, f.beta, d, h)
                if r: rows.append(dict(signal=kind, date=d, h=h, **r))
    # unconditional: every day in the window
    for d in f.index[(f.index >= start)][::5]:
        if pd.isna(f.beta.loc[d]): continue
        for h in HORIZONS:
            r = forward(a, b, f.beta, d, h)
            if r: rows.append(dict(signal="all days", date=d, h=h, **r))
    return pd.DataFrame(rows)

def quintiles(px, name, bench, start, h=63):
    a, b = px[name].dropna(), px[bench].reindex(px[name].dropna().index).ffill()
    f = features(a, b)
    fwd = (np.log(a).shift(-h - 1) - np.log(a).shift(-1)) - (np.log(b).shift(-h - 1) - np.log(b).shift(-1))
    d = pd.DataFrame(dict(z=f.rel_z, fwd=fwd))[f.index >= start].dropna()
    d["q"] = pd.qcut(d.z, 5, labels=["Q1 worst", "Q2", "Q3", "Q4", "Q5 best"])
    return d.groupby("q", observed=True).agg(z_mean=("z", "mean"), fwd_rel_mean=("fwd", "mean"),
                                             fwd_rel_median=("fwd", "median"), hit=("fwd", lambda x: (x > 0).mean()),
                                             days=("fwd", "size"))

# ---------------------------------------------------------------- universe + placebo
def universe(px, bench, start, kind="resid_z", h=H, draws=1000, seed=7):
    """Pooled forward excess after episodes across every name, against random dates drawn per name."""
    rng = np.random.default_rng(seed)
    skip = {"QQQ", "SMH", "SOXX", "SPY", "XLK"}
    per, actual, pools = [], [], []
    for t in sorted(c for c in px.columns if c not in skip):
        a = px[t].dropna()
        if len(a[a.index >= start]) < 2 * BETA_W: continue
        b = px[bench].reindex(a.index).ffill()
        f = features(a, b)
        fwd = (np.log(a).shift(-h - 1) - np.log(a).shift(-1)) - (np.log(b).shift(-h - 1) - np.log(b).shift(-1))
        ok = (f.index >= start) & fwd.notna() & f[kind].notna()
        ep = episodes(fire(f, kind) & ok)
        vals = fwd.reindex(ep).dropna()
        pool = fwd[ok]
        per.append(dict(ticker=t, episodes=len(vals), fwd_mean=vals.mean() if len(vals) else np.nan,
                        uncond_mean=pool.mean(), edge=(vals.mean() - pool.mean()) if len(vals) else np.nan))
        actual += list(vals.values); pools.append((pool.values, len(vals)))
    act = np.mean(actual)
    sims = np.array([np.mean(np.concatenate([rng.choice(p, n) for p, n in pools if n])) for _ in range(draws)])
    return pd.DataFrame(per).set_index("ticker"), dict(episodes=len(actual), mean=act, placebo_mean=sims.mean(),
                                                       p_one_sided=(sims >= act).mean())

# ---------------------------------------------------------------- main
def pct(x): return f"{x:+.1%}" if pd.notna(x) else ""

def main(name="AMD", bench="QQQ"):
    px = pd.read_csv(PX, index_col=0, parse_dates=True)
    end = px[name].dropna().index[-1]
    start = end - pd.DateOffset(years=YEARS)
    os.makedirs(OUT, exist_ok=True)

    port, curves, f, f_smh = run_portfolio(px, name, bench, start)
    curves.to_csv(f"{OUT}/curves.csv")
    pd.concat([f.add_prefix("qqq_"), f_smh.add_prefix("smh_")], axis=1).to_csv(f"{OUT}/signals.csv")
    port.to_csv(f"{OUT}/portfolio.csv")

    ev5 = event_table(px, name, bench, start)
    evlong = event_table(px, name, bench, px[name].dropna().index[0] + pd.DateOffset(years=1))
    ev5.to_csv(f"{OUT}/events_5y.csv", index=False); evlong.to_csv(f"{OUT}/events_full.csv", index=False)
    q5 = quintiles(px, name, bench, start)
    qlong = quintiles(px, name, bench, px[name].dropna().index[0] + pd.DateOffset(years=1))

    uni5, plc5 = universe(px, bench, start)
    unil, plcl = universe(px, bench, px.index[0] + pd.DateOffset(years=1))
    uni5.to_csv(f"{OUT}/universe_5y.csv"); unil.to_csv(f"{OUT}/universe_full.csv")
    _, plc5_turn = universe(px, bench, start, kind="turn")
    _, plcl_turn = universe(px, bench, px.index[0] + pd.DateOffset(years=1), kind="turn")
    _, plc5_smh = universe(px, "SMH", start)
    _, plcl_smh = universe(px, "SMH", px.index[0] + pd.DateOffset(years=1))
    sens = sensitivity(px, name, bench, start); sens.to_csv(f"{OUT}/sensitivity.csv")
    eps = episode_list(px, name, bench, start); eps.to_csv(f"{OUT}/episodes.csv", index=False)

    def evsum(ev):
        g = ev.groupby(["signal", "h"]).agg(n=("rel", "size"), raw=("raw", "mean"), rel=("rel", "mean"),
                                           rel_med=("rel", "median"), resid=("resid", "mean"),
                                           hit=("rel", lambda x: (x > 0).mean()), worst=("worst_rel", "median"))
        return g
    s5, sl = evsum(ev5), evsum(evlong)

    L = [f"# {name} vs {bench}: buy-the-relative-laggard overlay",
         f"Window {start:%Y-%m-%d} .. {end:%Y-%m-%d}. Log returns throughout; 'rel' = {name} minus {bench}.", "",
         "## Portfolio (10% core, 20% for 126 days after a signal; vs the static mix at the same average weight)", "",
         "| strategy | total | CAGR | vol | Sharpe | max DD | avg AMD w | episodes | vs matched (end value) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for k, r in port.iterrows():
        L.append(f"| {k} | {pct(r.total)} | {pct(r.cagr)} | {r.vol:.1%} | {r.sharpe:.2f} | {pct(r.maxdd)} | "
                 f"{r.avg_amd_w:.1%} | {'' if pd.isna(r.get('episodes')) else int(r.episodes)} | {pct(r.get('vs_matched'))} |")
    L += ["", "## Sensitivity: overlay minus exposure-matched static, total return over the window", "",
          "| rule | episodes | hold 63d | hold 126d | hold 252d |", "|---|---|---|---|---|"]
    for k, r in sens.iterrows():
        L.append(f"| {k} | {r.episodes} | {pct(r['hold 63d'])} | {pct(r['hold 126d'])} | {pct(r['hold 252d'])} |")
    L += ["", "## Episodes in the window (rel = log return of AMD minus benchmark from the next close)", "",
          "| signal | date | price | ratio vs 1y high | resid z | rel 63d | rel 126d | rel 252d |", "|---|---|---|---|---|---|---|---|"]
    for r in eps.itertuples():
        L.append(f"| {r.signal} | {r.date} | {r.px:.2f} | {pct(np.exp(r.ratio_dd) - 1)} | {r.z:+.2f} | "
                 f"{pct(r.rel_63)} | {pct(r.rel_126)} | {pct(r.rel_252)} |")
    for lab, s in [("last 5 years", s5), ("full history", sl)]:
        L += ["", f"## Event study, {lab}: mean forward log return after an episode start", "",
              "| signal | h | n | raw | rel | rel median | beta-adj | hit (rel>0) | median worst rel on the way |",
              "|---|---|---|---|---|---|---|---|---|"]
        for (sig, h), r in s.iterrows():
            L.append(f"| {sig} | {h} | {r.n} | {pct(r.raw)} | {pct(r.rel)} | {pct(r.rel_med)} | {pct(r.resid)} | {r.hit:.0%} | {pct(r.worst)} |")
    for lab, q in [("last 5 years", q5), ("full history", qlong)]:
        L += ["", f"## Quintiles of 63-day vol-adjusted relative return -> next 63 days, {lab}", "",
              "| quintile | mean z | fwd rel mean | fwd rel median | hit | days |", "|---|---|---|---|---|---|"]
        for k, r in q.iterrows():
            L.append(f"| {k} | {r.z_mean:+.2f} | {pct(r.fwd_rel_mean)} | {pct(r.fwd_rel_median)} | {r.hit:.0%} | {r.days} |")
    pd.DataFrame([dict(test=t, window=w, **p) for t, w, p in [
        ("S3 resid vs QQQ", "5y", plc5), ("S3 resid vs QQQ", "full", plcl), ("S4 resid vs SMH", "5y", plc5_smh),
        ("S4 resid vs SMH", "full", plcl_smh), ("S5 drawdown then turn", "5y", plc5_turn),
        ("S5 drawdown then turn", "full", plcl_turn)]]).to_csv(f"{OUT}/placebo.csv", index=False)
    pd.concat([q5.assign(window="5y"), qlong.assign(window="full")]).to_csv(f"{OUT}/quintiles.csv")
    L += ["", "## Universe placebos, 126-day forward excess", ""]
    for lab, p in [("S4 residual vs SMH, last 5 years", plc5_smh), ("S4 residual vs SMH, full history", plcl_smh),
                   ("S5 drawdown then turn vs QQQ, last 5 years", plc5_turn), ("S5 drawdown then turn vs QQQ, full history", plcl_turn)]:
        L.append(f"- {lab}: {p['episodes']} episodes, mean {pct(p['mean'])}, placebo mean {pct(p['placebo_mean'])}, "
                 f"one-sided p = {p['p_one_sided']:.3f}")
    for lab, u, p in [("last 5 years", uni5, plc5), ("full history", unil, plcl)]:
        L += ["", f"## Universe, {lab}: S3 episodes, 126-day forward excess vs {bench}", "",
              f"{p['episodes']} episodes, mean {pct(p['mean'])}, placebo mean {pct(p['placebo_mean'])}, "
              f"one-sided p = {p['p_one_sided']:.3f}", "",
              "| ticker | episodes | fwd mean | unconditional | edge |", "|---|---|---|---|---|"]
        for k, r in u.iterrows():
            L.append(f"| {k} | {r.episodes} | {pct(r.fwd_mean)} | {pct(r.uncond_mean)} | {pct(r.edge)} |")
    open(f"{OUT}/summary.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main(*sys.argv[1:3])
