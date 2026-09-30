"""Leading-indicator study, anchored on the earnings release.

Event = the earnings press release that first prints the quarter's segment figures.
  reaction : close(release day + 1) / close(release day - 1) - 1  — spans the release whatever
             the hour it crossed, so it is the market's own response, not a tradable signal.
  entry    : the close one trading day after the release day. Every forward window starts there,
             so a strategy could actually have taken it.
  r / b    : absolute return, and return less an equal-weight index of the same 22 names.
Signals are as-first-reported. Buckets and ICs are cross-sectional within a calendar quarter,
which is what keeps the sector's own cycle from being mistaken for stock selection.
"""
import pandas as pd, numpy as np, os
from scipy import stats

HZ = ["reaction", "b5", "b20", "b60", "b120"]
SIG = ["best_seg_yoy", "worst_seg_yoy", "seg_yoy_disp", "largest_seg_yoy", "wavg_seg_yoy",
       "best_seg_accel", "worst_seg_accel", "wavg_seg_accel", "share_segs_accelerating"]
BASE = ["co_yoy", "co_accel"]

def panel(require_printed=True, min_printed=0.8):
    S = pd.read_pickle("out/study_signals.pkl")
    E = pd.read_pickle("out/study_events.pkl")
    R = pd.read_csv("out/study_returns_rel.csv", parse_dates=["release", "entry_date"])
    d = S.merge(E, on=["ticker", "period_end"]).merge(R, on=["ticker", "release"])
    if require_printed and os.path.exists("out/study_printed.pkl"):
        p = pd.read_pickle("out/study_printed.pkl")
        d = d.merge(p[["ticker", "period_end", "printed"]], on=["ticker", "period_end"], how="left")
        d["usable"] = d.printed >= min_printed
    else:
        d["printed"] = np.nan; d["usable"] = True
    d["cq"] = d.release.dt.to_period("Q")
    return d

def quarterly_ic(df, sig, hz, min_n=6, min_q=8):
    rows = []
    for cq, g in df.groupby("cq"):
        g = g[[sig, hz]].dropna()
        if len(g) < min_n or g[sig].nunique() < 3: continue
        rows.append((cq, stats.spearmanr(g[sig], g[hz]).statistic, len(g)))
    if len(rows) < min_q: return None
    ic = pd.DataFrame(rows, columns=["cq", "ic", "n"]); m, s = ic.ic.mean(), ic.ic.std(ddof=1)
    t = m / (s / np.sqrt(len(ic))) if s > 0 else np.nan
    return dict(signal=sig, horizon=hz, n_quarters=len(ic), n_obs=int(ic.n.sum()), mean_ic=m, t_stat=t,
                p_value=2 * (1 - stats.t.cdf(abs(t), len(ic) - 1)), share_ic_pos=(ic.ic > 0).mean())

def spread(df, sig, hz, nb=5, min_n=10, min_q=8):
    rows = []
    for cq, g in df.groupby("cq"):
        g = g[[sig, hz]].dropna()
        if len(g) < min_n or g[sig].nunique() < nb: continue
        b = pd.qcut(g[sig].rank(method="first"), nb, labels=False)
        rows.append([g[hz][b == i].mean() for i in range(nb)] + [len(g)])
    if len(rows) < min_q: return None
    q = pd.DataFrame(rows, columns=[f"q{i+1}" for i in range(nb)] + ["n"]); sp = q[f"q{nb}"] - q.q1
    t = sp.mean() / (sp.std(ddof=1) / np.sqrt(len(sp)))
    return dict(signal=sig, horizon=hz, n_quarters=len(q), **{f"q{i+1}": q[f"q{i+1}"].mean() for i in range(nb)},
                spread=sp.mean(), t_stat=t, p_value=2 * (1 - stats.t.cdf(abs(t), len(sp) - 1)), hit_rate=(sp > 0).mean())

def residualise(df, sig, ctrl):
    out = pd.Series(np.nan, index=df.index)
    for cq, g in df.groupby("cq"):
        g = g[[sig, ctrl]].dropna()
        if len(g) < 6: continue
        x = g[ctrl].rank(pct=True); y = g[sig].rank(pct=True); b = np.polyfit(x, y, 1)
        out.loc[g.index] = y - (b[0] * x + b[1])
    return out

def table(rows, idx, val):
    return pd.DataFrame(rows).pivot_table(index="signal", columns="horizon", values=val).reindex(idx)[HZ]

if __name__ == "__main__":
    d = panel(); F = d[d.usable].copy()
    print(f"events with prices: {len(d)} | segment figures verified printed in the release: {int(d.usable.sum())}")
    print(f"sample: {len(F)} events, {F.ticker.nunique()} tickers, {F.release.min().date()} -> {F.release.max().date()}")
    print("events per calendar quarter: median %.0f (min %d, max %d)" % (F.groupby('cq').size().median(), F.groupby('cq').size().min(), F.groupby('cq').size().max()))
    print("return coverage:", {h: int(F[h].notna().sum()) for h in HZ})
    F.to_pickle("out/study_panel_rel.pkl")

    ic = [r for s in SIG + BASE for h in HZ if (r := quarterly_ic(F, s, h))]
    pd.DataFrame(ic).to_pickle("out/study_ic_rel.pkl")
    print("\n=== rank IC, mean of quarterly cross-sectional ICs (reaction = same-quarter move, b* = drift from entry) ===")
    print(table(ic, SIG + BASE, "mean_ic").round(3).to_string()); print("\nt-stats:"); print(table(ic, SIG + BASE, "t_stat").round(2).to_string())

    sp = [r for s in SIG + BASE for h in HZ if (r := spread(F, s, h))]
    pd.DataFrame(sp).to_pickle("out/study_spread_rel.pkl")
    print("\n=== quintile spread, top minus bottom, benchmark-relative ===")
    print(table(sp, SIG + BASE, "spread").round(4).to_string()); print("\nt-stats:"); print(table(sp, SIG + BASE, "t_stat").round(2).to_string())

    F2 = F.copy(); inc = []
    for s in SIG:
        F2[s + "_x"] = residualise(F2, s, "co_yoy")
        inc += [r for h in HZ if (r := quarterly_ic(F2, s + "_x", h))]
    pd.DataFrame(inc).to_pickle("out/study_incremental_rel.pkl")
    print("\n=== rank IC after stripping out company total revenue growth ===")
    print(table(inc, [s + "_x" for s in SIG], "mean_ic").round(3).to_string()); print("\nt-stats:"); print(table(inc, [s + "_x" for s in SIG], "t_stat").round(2).to_string())
    n = len(ic); print(f"\ntests run: {n} IC + {len(sp)} spread + {len(inc)} incremental; a 5% threshold after Bonferroni over {n} tests needs |t| > {stats.t.ppf(1-0.025/n, 50):.2f}")

# ---------------------------------------------------------------------------
def subsamples(F, sigs=None, hz="b60"):
    """a signal that only works in one half of the sample is a fitted one."""
    cut = pd.Period("2019Q1")
    rows = []
    for s in (sigs or SIG + BASE):
        a = quarterly_ic(F[F.cq < cut], s, hz, min_q=6); b = quarterly_ic(F[F.cq >= cut], s, hz, min_q=6)
        if a and b: rows.append(dict(signal=s, horizon=hz, ic_2011_2018=a["mean_ic"], t_2011_2018=a["t_stat"],
                                     ic_2019_2026=b["mean_ic"], t_2019_2026=b["t_stat"], same_sign=np.sign(a["mean_ic"]) == np.sign(b["mean_ic"])))
    return pd.DataFrame(rows)

def beyond_reaction(F, hz="b60"):
    """the market's own reaction to the print is the obvious competing signal; does segment detail add to it?"""
    rows = []
    for s in SIG:
        g = F[[s, "reaction", hz, "cq"]].dropna()
        x = residualise(g.assign(**{s: g[s]}), s, "reaction")
        r = quarterly_ic(g.assign(**{s + "_r": x}), s + "_r", hz)
        if r: rows.append(r)
    return pd.DataFrame(rows)

def backtest(F, sig, hz="b60", nb=5, hold=60):
    """quarterly long top quintile / short bottom quintile, held to the horizon, benchmark-relative."""
    rows = []
    for cq, g in F.groupby("cq"):
        g = g[[sig, hz]].dropna()
        if len(g) < 10 or g[sig].nunique() < nb: continue
        b = pd.qcut(g[sig].rank(method="first"), nb, labels=False)
        rows.append(dict(cq=cq, n=len(g), long=g[hz][b == nb - 1].mean(), short=g[hz][b == 0].mean()))
    q = pd.DataFrame(rows)
    if not len(q): return None, None
    q["ls"] = q["long"] - q["short"]
    cum = (1 + q.ls).cumprod()
    dd = (cum / cum.cummax() - 1).min()
    # each book is held `hold` trading days, so 252/hold of them fit in a year (b120 books overlap two quarters)
    return q, dict(signal=sig, horizon=hz, n_books=len(q), mean_per_book=q.ls.mean(), annualised=q.ls.mean() * 252 / hold,
                   t_stat=q.ls.mean() / (q.ls.std(ddof=1) / np.sqrt(len(q))), hit_rate=(q.ls > 0).mean(),
                   worst_quarter=q.ls.min(), best_quarter=q.ls.max(), max_drawdown=dd)
