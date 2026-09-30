"""Backtest of book-to-bill on AS-FIRST-REPORTED data (BACKLOG task 7).

Question: does a company's book-to-bill, known on the day its 10-Q/10-K is filed, predict its stock's
return over the following quarter or two, relative to the market?

Pre-registered before any result was seen (so the multiple-testing count is fixed at 4):
  H1 (primary)  b2b level            rank IC with 63-day excess return > 0
  H2            b2b trend            b2b minus the mean of the three prior quarters' b2b
  H3            RPO growth y/y
  H4 (event)    'backlog building ahead' gate (b2b > 1.05, trend > 0, revenue y/y < 15%, as in tier1_screen)
                -> gated names beat the rest of the same cohort over 63 days
  Significance: Bonferroni over 4 tests, alpha 0.05/4 = 0.0125, on the permutation (placebo) p-value.
  126-day horizon is reported for every test but is NOT a separate test.

Point-in-time rules -- the reason this uses companyfacts per filer rather than the frames panel:
  * every value is the FIRST filing that reported it (restatements ignored), so nothing is used that
    was not public at the time;
  * information date = the filing date of the 10-Q/10-K that first carried the RPO figure (RPO is
    rarely in the earnings press release, so the filing, not the release, is when it becomes known);
  * entry = close of the first trading day AFTER the filing date (filings land after the close too);
  * return = adjusted close, excess over SPY across the same window.
Same eligibility as the live screen: revenue >= $25m a quarter, RPO >= 1 quarter of revenue, and
RPO steps (x1.5 or /1.5 in one quarter, mostly disclosure changes) and implausible cover (> 40 quarters)
dropped.

Known bias, stated rather than hidden: the universe is filers that disclose RPO TODAY with a CURRENT
ticker, so companies that were delisted or acquired are missing (survivorship). That tends to flatter
long-only results; the rank IC / long-short spread is less exposed but not immune.

Needs SEC (companyfacts) and Yahoo (prices) -- run via .github/workflows/backtest.yml.
Writes results/backtest_b2b/: summary.md, cohorts.csv, events.csv.
"""
import json, os, sys, time
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
OUT = os.path.join(ROOT, "results", "backtest_b2b")
REV = ["RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
       "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTaxAndOtherRevenue"]
RPO = ["RevenueRemainingPerformanceObligation"]
H = (63, 126)
MIN_REV, MIN_COVER, MAX_COVER, STEP = 25e6, 1.0, 40.0, 1.5
MIN_COHORT = 20
N_PERM = 2000
TESTS = {"H1 b2b level": "b2b", "H2 b2b trend": "b2b_trend", "H3 RPO growth y/y": "rpo_yoy"}

# ---------------------------------------------------------------- facts -> point-in-time panel
def first_reported(arr, duration=None):
    """companyfacts unit array -> one row per (start, end), the FIRST filing's value. Only 10-Q/10-K family."""
    rows = [x for x in arr if str(x.get("form", "")).startswith("10-") and x.get("end") and x.get("filed")]
    if not rows: return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["end"] = pd.to_datetime(d.end); d["filed"] = pd.to_datetime(d.filed)
    if "start" not in d: d["start"] = pd.NaT
    d["start"] = pd.to_datetime(d.start)
    if duration == "instant":
        d = d[d.start.isna()]
    elif duration is not None:
        days = (d.end - d.start).dt.days
        d = d[days.between(*duration)]
    return d.sort_values("filed").drop_duplicates(["start", "end"] if duration != "instant" else ["end"], keep="first")

def quarterly_revenue(f):
    """First-reported quarterly revenue from the concept with the most quarters (pinned per filer, as the
    live panel does, so the series cannot switch concept mid-stream). Q4 = FY - the three quarters
    inside it, dated to the 10-K."""
    best = None
    for c in REV:
        units = f.get(c, {}).get("units", {}).get("USD")
        if not units: continue
        q = first_reported(units, (80, 100))
        if best is None or len(q) > len(best[1]): best = (c, q, units)
    if best is None: return pd.DataFrame()
    c, q, units = best
    fy = first_reported(units, (350, 380))
    q = q[["start", "end", "val", "filed"]].copy()
    add = []
    for r in fy.itertuples():
        inside = q[(q.start >= r.start - pd.Timedelta(days=7)) & (q.end < r.end - pd.Timedelta(days=30))]
        if len(inside) == 3 and not ((q.end - r.end).abs().dt.days <= 7).any():
            add.append(dict(start=inside.end.max() + pd.Timedelta(days=1), end=r.end, val=r.val - inside.val.sum(), filed=r.filed))
    if add: q = pd.concat([q, pd.DataFrame(add)], ignore_index=True)
    return q.sort_values("end").reset_index(drop=True)

def panel_for(cik, j):
    f = j.get("facts", {}).get("us-gaap", {})
    units = f.get(RPO[0], {}).get("units", {}).get("USD")
    if not units: return pd.DataFrame()
    rpo = first_reported(units, "instant")[["end", "val", "filed"]].rename(columns={"val": "rpo", "filed": "rpo_filed"})
    rev = quarterly_revenue(f)
    if not len(rpo) or not len(rev): return pd.DataFrame()
    rev = rev.rename(columns={"val": "rev", "filed": "rev_filed"})
    # match each RPO balance to the revenue quarter ending on (about) the same date
    rpo = rpo.sort_values("end"); rev = rev.sort_values("end")
    d = pd.merge_asof(rpo, rev[["end", "rev", "rev_filed"]], on="end", direction="nearest", tolerance=pd.Timedelta(days=6))
    d = d.dropna(subset=["rev"]).reset_index(drop=True)
    if len(d) < 2: return pd.DataFrame()
    prev = d[["end", "rpo", "rpo_filed"]].shift(1)
    gap = (d.end - prev.end).dt.days
    d["rpo_prev"] = np.where(gap.between(75, 105), prev.rpo, np.nan)      # consecutive quarter only, never across a gap
    d["prev_filed"] = prev.rpo_filed
    d["bookings"] = d.rev + d.rpo - d.rpo_prev
    d["b2b"] = d.bookings / d.rev
    d["cover"] = d.rpo / d.rev
    d["step"] = (d.rpo / d.rpo_prev).where(d.rpo_prev > 0)
    # history-based features: only quarters strictly before, all first-reported, so all public by the filing date
    d["b2b_trend"] = d.b2b - d.b2b.shift(1).rolling(3, min_periods=3).mean()
    yago = d[["end", "rev", "rpo"]].copy(); yago["end"] = yago.end + pd.DateOffset(years=1)
    d = pd.merge_asof(d.sort_values("end"), yago.rename(columns={"rev": "rev_yago", "rpo": "rpo_yago"}).sort_values("end"),
                      on="end", direction="nearest", tolerance=pd.Timedelta(days=10))
    d["rev_yoy"] = d.rev / d.rev_yago - 1
    d["rpo_yoy"] = d.rpo / d.rpo_yago - 1
    # information date: when every input was public
    d["known"] = d[["rpo_filed", "rev_filed", "prev_filed"]].max(axis=1)
    d["cik"] = int(cik)
    return d

def build_panel(ciks):
    import edgar
    P, t0 = [], time.time()
    for i, cik in enumerate(ciks):
        try:
            j = json.loads(edgar.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"))
            p = panel_for(cik, j)
            if len(p): P.append(p)
        except Exception as e:
            print(f"  {cik}: {type(e).__name__} {str(e)[:80]}", flush=True)
        if (i + 1) % 100 == 0: print(f"  companyfacts {i+1}/{len(ciks)} | {time.time()-t0:.0f}s | {edgar.STATS}", flush=True)
    return pd.concat(P, ignore_index=True)

def eligible(d):
    d = d.dropna(subset=["b2b", "known"])
    d = d[(d.rev >= MIN_REV) & (d.cover >= MIN_COVER) & (d.cover <= MAX_COVER)]
    d = d[d.step.between(1 / STEP, STEP)]
    d = d[(d.known - d.end).dt.days.between(0, 120)]                    # late or amended filings are not the signal
    d = d.copy()
    d["gate"] = (d.b2b > 1.05) & (d.b2b_trend > 0) & (d.rev_yoy < 0.15)
    return d

# ---------------------------------------------------------------- prices
def prices(tickers, start):
    import yfinance as yf
    out = []
    tickers = sorted(set(tickers) | {"SPY"})
    for i in range(0, len(tickers), 80):
        chunk = tickers[i:i + 80]
        for attempt in range(3):
            try:
                px = yf.download(chunk, start=start, auto_adjust=True, progress=False, threads=True)["Close"]
                break
            except Exception as e:
                print(f"  prices retry {attempt}: {e}", flush=True); time.sleep(5 * (attempt + 1)); px = None
        if px is None: continue
        if isinstance(px, pd.Series): px = px.to_frame(chunk[0])
        out.append(px)
        print(f"  prices {min(i+80, len(tickers))}/{len(tickers)}", flush=True)
    return pd.concat(out, axis=1).sort_index()

def forward_returns(ev, px):
    idx = px.index; spy = px["SPY"]
    rows = []
    for r in ev.itertuples():
        if r.ticker not in px.columns: rows.append({}); continue
        s = px[r.ticker]
        k = idx.searchsorted(r.known, side="right")                        # first trading day strictly after filing
        if k >= len(idx) or pd.isna(s.iloc[k]): rows.append({}); continue
        o = dict(entry_date=idx[k])
        for h in H:
            if k + h < len(idx) and pd.notna(s.iloc[k + h]):
                o[f"ret{h}"] = s.iloc[k + h] / s.iloc[k] - 1
                o[f"xs{h}"] = o[f"ret{h}"] - (spy.iloc[k + h] / spy.iloc[k] - 1)
        rows.append(o)
    return pd.concat([ev.reset_index(drop=True), pd.DataFrame(rows)], axis=1)

# ---------------------------------------------------------------- statistics
def nw_t(x, lag):
    """t-stat of the mean with Newey-West errors (overlapping 126-day windows on quarterly cohorts)."""
    x = np.asarray(x, float); x = x[~np.isnan(x)]; n = len(x)
    if n < 4: return np.nan
    e = x - x.mean(); v = e @ e / n
    for l in range(1, lag + 1): v += 2 * (1 - l / (lag + 1)) * (e[l:] @ e[:-l]) / n
    return x.mean() / np.sqrt(v / n) if v > 0 else np.nan

def cohort_ic(d, sig, ret):
    out = []
    for q, g in d.dropna(subset=[sig, ret]).groupby("cohort"):
        if len(g) < MIN_COHORT: continue
        a, b = g[sig].rank(), g[ret].rank()
        qn = pd.qcut(g[sig].rank(method="first"), 5, labels=False)
        out.append(dict(cohort=q, n=len(g), ic=np.corrcoef(a, b)[0, 1],
                        q5_q1=g[ret][qn == 4].mean() - g[ret][qn == 0].mean()))
    return pd.DataFrame(out)

def perm_p(d, sig, ret, rng, stat="ic"):
    """Placebo: shuffle the signal WITHIN each cohort (keeps cohort composition and return dispersion), N_PERM
    times. p = share of shuffles whose mean statistic is at least the real one (one-sided, H: positive)."""
    g = d.dropna(subset=[sig, ret]); g = g[g.groupby("cohort")[sig].transform("size") >= MIN_COHORT]
    if not len(g): return np.nan, np.nan
    real = cohort_ic(g, sig, ret)
    if not len(real): return np.nan, np.nan
    obs = real.ic.mean() if stat == "ic" else real.q5_q1.mean()
    grp = [(c.index.values, c[ret].rank().values) for _, c in g.groupby("cohort")]
    sv = g[sig].values; pos = {ix: n for n, ix in enumerate(g.index)}
    cnt = 0
    for _ in range(N_PERM):
        ics = []
        for ix, rr in grp:
            s = pd.Series(rng.permutation(sv[[pos[i] for i in ix]])).rank().values
            ics.append(np.corrcoef(s, rr)[0, 1])
        cnt += np.mean(ics) >= obs
    return obs, (cnt + 1) / (N_PERM + 1)

def event_test(d, ret, rng):
    """H4: gated names vs the rest of their own cohort. Per-cohort difference in mean excess return, averaged;
    placebo shuffles the gate flag within cohort."""
    g = d.dropna(subset=[ret]); rows = []
    for q, c in g.groupby("cohort"):
        if c.gate.sum() >= 2 and (~c.gate).sum() >= 5:
            rows.append(dict(cohort=q, n_gate=int(c.gate.sum()), n_rest=int((~c.gate).sum()),
                             diff=c[ret][c.gate].mean() - c[ret][~c.gate].mean()))
    R = pd.DataFrame(rows)
    if not len(R): return R, np.nan, np.nan
    obs = R["diff"].mean(); use = g[g.cohort.isin(R.cohort)]
    cnt = 0
    for _ in range(N_PERM):
        ds = []
        for _, c in use.groupby("cohort"):
            f = rng.permutation(c.gate.values); v = c[ret].values
            ds.append(v[f].mean() - v[~f].mean())
        cnt += np.mean(ds) >= obs
    return R, obs, (cnt + 1) / (N_PERM + 1)

def analyse(d):
    rng = np.random.default_rng(7)
    lines, table = [], []
    for name, sig in TESTS.items():
        for h in H:
            ret = f"xs{h}"; C = cohort_ic(d, sig, ret)
            if not len(C): continue
            obs, p = perm_p(d, sig, ret, rng)
            table.append(dict(test=name, horizon=h, cohorts=len(C), events=int(C.n.sum()), mean_ic=C.ic.mean(),
                              ic_t_nw=nw_t(C.ic, h // 63), ic_positive_share=(C.ic > 0).mean(),
                              q5_minus_q1=C.q5_q1.mean(), q5q1_t_nw=nw_t(C.q5_q1, h // 63), placebo_p=p,
                              significant=bool(h == 63 and p < 0.0125)))
    for h in H:
        R, obs, p = event_test(d, f"xs{h}", rng)
        if len(R):
            table.append(dict(test="H4 backlog-building gate", horizon=h, cohorts=len(R), events=int(R.n_gate.sum()),
                              mean_ic=np.nan, ic_t_nw=np.nan, ic_positive_share=(R["diff"] > 0).mean(),
                              q5_minus_q1=obs, q5q1_t_nw=nw_t(R["diff"], h // 63), placebo_p=p,
                              significant=bool(h == 63 and p < 0.0125)))
    return pd.DataFrame(table)

def robustness(d):
    """Primary test (H1, 63d) on halves of the sample and by size -- a real effect should not live in one slice."""
    rows = []
    mid = d.cohort.sort_values().iloc[len(d) // 2]
    med = d.rev.median()
    for lab, s in [("first half", d[d.cohort < mid]), ("second half", d[d.cohort >= mid]),
                   ("revenue above median", d[d.rev >= med]), ("revenue below median", d[d.rev < med])]:
        C = cohort_ic(s, "b2b", "xs63")
        if len(C): rows.append(dict(slice=lab, cohorts=len(C), mean_ic=C.ic.mean(), ic_t=nw_t(C.ic, 1), q5_minus_q1=C.q5_q1.mean()))
    return pd.DataFrame(rows)

def write(d, T, Rb):
    os.makedirs(OUT, exist_ok=True)
    keep = ["cik", "ticker", "end", "known", "entry_date", "cohort", "rev", "rpo", "b2b", "b2b_trend", "rev_yoy", "rpo_yoy", "gate",
            "ret63", "xs63", "ret126", "xs126"]
    d[[c for c in keep if c in d]].to_csv(f"{OUT}/events.csv", index=False, float_format="%.5g")
    T.to_csv(f"{OUT}/tests.csv", index=False, float_format="%.4g")
    f = lambda x: "" if pd.isna(x) else f"{x:+.3f}"
    md = [f"# Book-to-bill backtest (as first reported)\n",
          f"Run {time.strftime('%Y-%m-%d', time.gmtime())}. {len(d):,} filer-quarters with prices, {d.cik.nunique():,} companies, "
          f"entries {d.entry_date.min():%Y-%m} to {d.entry_date.max():%Y-%m}. Returns are excess over SPY from the first close after "
          f"the 10-Q/10-K filing. Pre-registered: 4 tests at 63 days, Bonferroni alpha 0.0125 on the placebo p-value.\n",
          "| test | horizon | cohorts | events | mean rank IC | IC t (NW) | share of cohorts IC>0 | top-minus-bottom quintile / gate minus rest | t (NW) | placebo p | passes |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in T.itertuples():
        md.append(f"| {r.test} | {r.horizon}d | {r.cohorts} | {r.events:,} | {f(r.mean_ic)} | {'' if pd.isna(r.ic_t_nw) else f'{r.ic_t_nw:.2f}'} | "
                  f"{r.ic_positive_share:.0%} | {r.q5_minus_q1:+.2%} | {'' if pd.isna(r.q5q1_t_nw) else f'{r.q5q1_t_nw:.2f}'} | {r.placebo_p:.3f} | "
                  f"{'**yes**' if r.significant else ('n/a (126d not a test)' if r.horizon != 63 else 'no')} |")
    md += ["\n## Robustness of H1 (b2b level, 63 days)\n", "| slice | cohorts | mean IC | IC t | top-minus-bottom quintile |", "|---|---|---|---|---|"]
    for r in Rb.itertuples(): md.append(f"| {r.slice} | {r.cohorts} | {r.mean_ic:+.3f} | {r.ic_t:.2f} | {r.q5_minus_q1:+.2%} |")
    md += ["\n## How to read it\n",
           "* **Rank IC**: correlation, within each quarterly cohort, between the signal's rank and the next-63-day excess return's rank. "
           "Around +0.02 to +0.05 is what usable single factors look like; 0 is no information.",
           "* **Placebo p**: the signal is shuffled among the same cohort's names 2,000 times; p is how often chance did as well. "
           "This is the number the pass/fail uses.",
           "* **Survivorship**: only companies with a current ticker are in the universe, so failed and acquired companies are missing.",
           "* **Not tested**: transaction costs, and anything intraday. The 126-day rows overlap across cohorts; their t-stats use Newey-West errors."]
    open(f"{OUT}/summary.md", "w").write("\n".join(md) + "\n")
    print("\n".join(md))

if __name__ == "__main__":
    if "--selftest" in sys.argv: sys.exit(0)
    L = pd.read_pickle("out/tier1_latest.pkl")
    ciks = sorted(L.cik.astype(int).unique())
    T = pd.read_pickle("out/cik_tickers.pkl").drop_duplicates("cik")
    tick = dict(zip(T.cik.astype(int), T.ticker))
    ciks = [c for c in ciks if c in tick]
    lim = int(os.environ.get("BT_LIMIT", "0"))
    if lim: ciks = ciks[:lim]
    print(f"universe: {len(ciks)} RPO filers with a current ticker", flush=True)
    P = build_panel(ciks)
    P.to_pickle("out/bt_panel.pkl")
    d = eligible(P); d["ticker"] = d.cik.map(tick).str.replace(".", "-", regex=False)
    print(f"panel {len(P):,} filer-quarters | eligible {len(d):,} | companies {d.cik.nunique():,}", flush=True)
    px = prices(d.ticker.unique(), str((d.known.min() - pd.Timedelta(days=10)).date()))
    d = forward_returns(d, px).dropna(subset=["xs63"])
    d["cohort"] = pd.PeriodIndex(d.entry_date, freq="Q").astype(str)
    print(f"with prices and a 63-day window: {len(d):,} | cohorts {d.cohort.nunique()}", flush=True)
    Tab = analyse(d); Rb = robustness(d)
    write(d, Tab, Rb)
