"""Basket rotation: park in QQQ, rotate into whichever large chip/tech names correct hard.

Question (as asked): $100k plus $4k a month parked in QQQ; rotate into chip or tech names that correct
significantly, restricted to names of at least $10bn, $20bn or $50bn market cap. Does it beat DCA into QQQ?

Fixed before any result was seen:

  Universe (point in time, build_tech_universe.py): a name is eligible on day t if its market cap on t -- close x
  the latest share count filed by then -- is at or above the threshold (10 / 20 / 50 $bn), and it has a year of prices.
  Signal: eligible and its total-return close >= 30% below its 252-day high. An episode starts on the first signal
  day with no episode start for that name in the previous 63 trading days; trade at the next close.
  Rotation: each episode start moves 5% of the account from QQQ into that name; at most 10% in one name and 40%
  across names. Same-day starts that exceed the room share it pro rata.
  Exits: hold (never rotate back), or trip (back to QQQ once the name is within 10% of its 252-day high, or 252
  trading days after its last rotation in). A name whose prices end (acquired, delisted) is sold into QQQ.
  Flows: $100k on day one, $4k on the first trading day of each later month, into QQQ. 10 bp per trade leg.

  Controls:
    DCA QQQ    every dollar into QQQ
    Matched    QQQ plus an equal-weight basket of every eligible name, held at the rotation's average satellite
               weight and rebalanced monthly: owning big tech without the timing
    Random     the same rotations into the same names on random days on which each name was eligible (trip:
               holding periods drawn from the real trips); share of draws the rotation beats

  Hypotheses (last 5 years, each threshold):
    H1  rotation beats DCA QQQ                                                           (the user's)
    H2  rotation beats Matched                                     (timing beats just owning the basket)
    H3  rotation beats 95% of Random                                                     (not luck)
    H4  across 5-year windows starting every 6 months since 2011, it beats Matched and the Random median in most

  Relative triggers (added after the absolute results above were seen, same rules otherwise):
    rel_qqq     the name's price / QQQ is >= 30% below its own 252-day high; trip exit when that ratio is back
                within 10% of its high
    rel_smh     the same against SMH
    rel_sector  SMH for chip names (SIC 3674, 3559, 3827, 3825, or a config/ chip ticker), QQQ for the rest

Reads results/universe/ and results/prices/closes.csv. Writes results/basket_backtest/.
Usage: python basket_backtest.py [trigger ...]   (default: all four)
"""
import os, sys, glob
import numpy as np
import pandas as pd
from dca_backtest import contributions, xirr
from tech_caps import rebuild

UNI = os.environ.get("BASKET_UNI", "results/universe")
OUT = "results/basket_backtest"
THRESH = (10, 20, 50)
DROP, RECOVER, SPACING, MAX_HOLD = 0.30, 0.10, 63, 252
STEP, CAP_NAME, CAP_TOT, FEE = 0.05, 0.10, 0.40, 0.001
BAD_TAGS = ["MRDN", "NXTT", "BLIN", "FIRY"]   # Meridian Holdings, Next Technology, Bridgeline, Firy: never near $10bn
YEARS, DRAWS, ROLL_DRAWS = 5, int(os.environ.get("BASKET_DRAWS", 500)), int(os.environ.get("BASKET_ROLL_DRAWS", 50))

def load():
    """Prices and point-in-time caps. Before a name's first usable share count (a CIK change such as Alphabet's 2015
    holding company, or foreign filers before cover-page tagging in 2018), the cap is estimated from that first count
    and counted at half, so it must clear twice the floor while the share count is unknown. BAD_TAGS are microcaps
    whose SEC share counts are mis-tagged by orders of magnitude (checked by hand); nothing else is removed."""
    q = pd.read_csv("results/prices/closes.csv", index_col=0, parse_dates=True)["QQQ"].dropna()
    adj = pd.read_csv(f"{UNI}/tech_adj.csv.gz", index_col=0, parse_dates=True)
    cap, close = rebuild(UNI)
    for t in cap.columns:
        c = cap[t]; f = c.first_valid_index()
        if f is None: continue
        early = (close.index < f) & close[t].notna().values
        cap.loc[early, t] = (c[f] * close.loc[early, t] / close.at[f, t] / 2).values
    junk = [t for t in BAD_TAGS if t in cap.columns]
    cap = cap.drop(columns=junk)
    adj = adj.reindex(index=q.index, columns=cap.columns)
    cap = cap.reindex(q.index).ffill(limit=5)
    meta = pd.read_csv(f"{UNI}/tech_meta.csv").set_index("ticker")
    print(f"universe: {cap.shape[1]} names after dropping {len(junk)} bad-tag artifacts ({', '.join(junk)})", flush=True)
    return q, adj, cap, meta

# ---------------------------------------------------------------- signals on the full history
TRIGGERS = ("abs", "rel_qqq", "rel_smh", "rel_sector")
CHIP_SIC = {3674, 3559, 3827, 3825}

def prepare(adj, bench=None):
    """Signal inputs. bench: None for the absolute trigger, else a frame of benchmark prices aligned to adj."""
    x = adj if bench is None else adj / bench
    hi = x.rolling(252, min_periods=252).max()
    return dict(down=(x <= (1 - DROP) * hi).values, up=(x >= (1 - RECOVER) * hi).values, hist=hi.notna().values)

def benchmarks(adj, meta, trigger):
    if trigger == "abs": return None
    etf = pd.read_csv("results/prices/closes.csv", index_col=0, parse_dates=True)[["QQQ", "SMH"]].reindex(adj.index)
    if trigger in ("rel_qqq", "rel_smh"):
        col = etf["QQQ" if trigger == "rel_qqq" else "SMH"]
        return pd.DataFrame({t: col for t in adj.columns})
    config = {os.path.basename(p)[:-5] for p in glob.glob("config/*.json")}
    chip = {t for t in adj.columns if t in config or meta.sic.get(t) in CHIP_SIC}
    return pd.DataFrame({t: etf["SMH" if t in chip else "QQQ"] for t in adj.columns})

def episode_starts(sig):
    """sig: T bool for one name -> positions of episode starts (63-day spacing)."""
    out, last = [], -10 ** 9
    for i in np.flatnonzero(sig):
        if i - last >= SPACING: out.append(i); last = i
    return np.array(out, int)

def trip_exits(entries, up):
    """Exit day per trip: first recovered day after an entry, or MAX_HOLD days after the latest entry."""
    ex, last, live = [], None, False
    ent = set(entries.tolist())
    for i in range(len(up)):
        if i in ent: last, live = i, True
        elif live and (up[i] or i - last >= MAX_HOLD):
            ex.append(i); live = False
    return np.array(ex, int)

# ---------------------------------------------------------------- simulation (event-driven)
def simulate(P, q, flows, entries, exits, last_day, matched=None, path=False):
    """P: T x N prices (nan outside a name's life). entries/exits: {day: [names]}. last_day: N last valid day.
    matched: (weight, eligible T x N bool) -> monthly equal-weight rebalance instead of rotation."""
    T, N = P.shape
    pos, amt = flows
    add = dict(zip(pos.tolist(), amt.tolist()))
    dying = {}
    for j, d in enumerate(last_day):
        if d < T - 1: dying.setdefault(int(d), []).append(j)
    rebal = set((pos[1:] - 1).tolist()) | {0} if matched else set()
    days = sorted(set(add) | set(entries) | set(exits) | set(dying) | rebal)
    ns, nq = np.zeros(N), 0.0
    seg = []
    bought = np.zeros(N)
    for d in days:
        p = np.nan_to_num(P[d])
        if d in add: nq += add[d] * (1 - FEE) / q[d]
        for j in set(exits.get(d, [])) | set(dying.get(d, [])):
            if ns[j] > 0: nq += ns[j] * p[j] * (1 - FEE) ** 2 / q[d]; ns[j] = 0.0
        V = nq * q[d] + ns @ p
        if matched and d in rebal:
            w, elig = matched
            E = np.flatnonzero(elig[d] & (p > 0))
            tgt = np.zeros(N)
            if len(E): tgt[E] = w * V / len(E)
            turn = np.abs(tgt - ns * p).sum()
            Vn = V - FEE * turn
            tgt *= Vn / V if V else 0
            ns = np.divide(tgt, p, out=np.zeros(N), where=p > 0)
            nq = (Vn - tgt.sum()) / q[d]
        elif d in entries and V > 0:
            js = [j for j in entries[d] if p[j] > 0]
            if js:
                want = np.array([max(0.0, min(STEP * V, CAP_NAME * V - ns[j] * p[j])) for j in js])
                room = max(0.0, min(CAP_TOT * V - ns @ p, nq * q[d]))
                if want.sum() > room: want *= room / want.sum()
                for j, x in zip(js, want):
                    if x <= 0: continue
                    nq -= x / q[d]; ns[j] += x * (1 - FEE) ** 2 / p[j]; bought[j] += x
        seg.append((d, ns.copy(), nq))
    final = nq * q[-1] + ns @ np.nan_to_num(P[-1])
    if not path: return final, None, None, bought
    val, sat = np.empty(T), np.empty(T)
    bounds = [s[0] for s in seg] + [T]
    for k, (d, s_, q_) in enumerate(seg):
        sl = slice(d, bounds[k + 1])
        sv = np.nan_to_num(P[sl]) @ s_
        sat[sl] = sv; val[sl] = sv + q_ * q[sl]
    return final, val, sat, bought

def twr_drawdown(val, flows):
    add = np.zeros(len(val)); add[flows[0]] = flows[1]
    r = (val[1:] - add[1:]) / val[:-1]
    nav = np.concatenate([[1.0], np.cumprod(r)])
    return (nav / np.maximum.accumulate(nav) - 1).min()

# ---------------------------------------------------------------- one window
def window(q_all, adj, cap, sig, start, end, thr, exit_rule, draws, rng, detail=False):
    k0, k1 = q_all.index.searchsorted(start), q_all.index.searchsorted(end, side="right")
    idx = q_all.index[k0:k1]
    q = q_all.values[k0:k1]
    P = adj.values[k0:k1]
    elig = (cap.values[k0:k1] >= thr) & sig["hist"][k0:k1] & np.isfinite(P)
    down, up = sig["down"][k0:k1], sig["up"][k0:k1]
    T, N = P.shape
    flows = contributions(idx)
    valid = np.isfinite(P)
    last_day = np.array([np.flatnonzero(valid[:, j]).max() if valid[:, j].any() else -1 for j in range(N)])
    entries, exits, ent_list, durs = {}, {}, [], []
    for j in range(N):
        st = episode_starts(down[:, j] & elig[:, j]) + 1
        st = st[st < T]
        if not len(st): continue
        for d in st: entries.setdefault(int(d), []).append(j); ent_list.append((int(d), j))
        if exit_rule == "trip":
            ex = trip_exits(st, up[:, j])
            for d in ex: exits.setdefault(int(d), []).append(j)
            for d in ex:
                prior = st[st < d]
                prev = ex[ex < d]
                prior = prior[prior > (prev.max() if len(prev) else -1)]
                if len(prior): durs.append(d - prior.min())
    final, val, sat, bought = simulate(P, q, flows, entries, exits, last_day, path=True)
    dq, vq, _, _ = simulate(P, q, flows, {}, {}, last_day, path=True)
    wbar = float(np.mean(sat / val))
    fm, vm, _, _ = simulate(P, q, flows, {}, {}, last_day, matched=(wbar, elig), path=True)
    res = dict(threshold=thr, exit=exit_rule, start=idx[0].date(), final=final, dca_qqq=dq, matched=fm, avg_sat=wbar,
               signals=len(ent_list), names_bought=int((bought > 0).sum()), eligible_start=int(elig[0].sum()),
               eligible_end=int(elig[-1].sum()), irr=xirr(*flows, idx, final), irr_qqq=xirr(*flows, idx, dq),
               maxdd=twr_drawdown(val, flows), maxdd_qqq=twr_drawdown(vq, flows), maxdd_matched=twr_drawdown(vm, flows),
               contributed=flows[1].sum())
    if draws and ent_list:
        days_ok = [np.flatnonzero(elig[:, j][:-1]) + 1 for j in range(N)]
        durs = np.array(durs) if durs else np.array([MAX_HOLD])
        sims = []
        for _ in range(draws):
            e2, x2 = {}, {}
            for d, j in ent_list:
                if not len(days_ok[j]): continue
                r = int(rng.choice(days_ok[j]))
                e2.setdefault(r, []).append(j)
                if exit_rule == "trip":
                    x = min(r + int(rng.choice(durs)), T - 1)
                    x2.setdefault(x, []).append(j)
            sims.append(simulate(P, q, flows, e2, x2, last_day)[0])
        sims = np.array(sims)
        res.update(random_pct=(sims < final).mean(), random_median=np.median(sims))
    if detail:
        b = pd.Series(bought, adj.columns); b = b[b > 0].sort_values(ascending=False)
        res["top_bought"] = ", ".join(f"{t} ${v / 1e3:,.0f}k" for t, v in b.head(12).items())
        res["paths"] = pd.DataFrame(dict(rotation=val, dca_qqq=vq, matched=vm, satellite=sat), index=idx)
    return res

def money(x): return f"${x:,.0f}"
def pct(x): return f"{x:+.1%}"

LABEL = {"abs": "30% below own high", "rel_qqq": "30% below high vs QQQ", "rel_smh": "30% below high vs SMH",
         "rel_sector": "30% below high vs own sector ETF"}

def main(triggers=TRIGGERS):
    q, adj, cap, meta = load()
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(31)
    end = q.index[-1]; start = end - pd.DateOffset(years=YEARS)
    sigs = {tr: prepare(adj, benchmarks(adj, meta, tr)) for tr in triggers}
    main_rows = []
    for tr in triggers:
        for thr in THRESH:
            for x in ("hold", "trip"):
                r = window(q, adj, cap, sigs[tr], start, end, thr, x, DRAWS, rng, detail=True)
                r["trigger"] = tr
                r.pop("paths").to_csv(f"{OUT}/curves_{tr}_{thr}b_{x}.csv")
                main_rows.append(r)
                print(f"  {tr} {thr}bn {x}: {money(r['final'])} vs DCA QQQ {money(r['dca_qqq'])}", flush=True)
    m = pd.DataFrame(main_rows); m.to_csv(f"{OUT}/strategies.csv", index=False)

    roll = []
    first = pd.Timestamp("2011-07-01")
    for st in pd.date_range(first, end - pd.DateOffset(years=YEARS), freq="6MS"):
        for tr in triggers:
            for thr in THRESH:
                for x in ("hold", "trip"):
                    r = window(q, adj, cap, sigs[tr], st, st + pd.DateOffset(years=YEARS), thr, x, ROLL_DRAWS, rng)
                    r["trigger"] = tr
                    roll.append(r)
        print(f"  rolling {st.date()}", flush=True)
    roll = pd.DataFrame(roll); roll.to_csv(f"{OUT}/rolling.csv", index=False)

    dl = pd.read_csv(f"{UNI}/delisted.csv") if os.path.exists(f"{UNI}/delisted.csv") else pd.DataFrame()
    L = [f"# Basket rotation: park in QQQ, rotate into large chip/tech names after a 30% fall", "",
         f"Window {start:%Y-%m-%d} .. {end:%Y-%m-%d}. $100,000 then $4,000/month: {money(m.contributed.iloc[0])} contributed. "
         f"{len(meta)} chip/tech names in the point-in-time universe file; {len(dl)} delisted or acquired tech filers with "
         f">= 150m shares could not be priced (survivorship). DCA QQQ ends at {money(m.dca_qqq.iloc[0])} "
         f"({m.irr_qqq.iloc[0]:+.1%}/yr, worst drop {m.maxdd_qqq.iloc[0]:.1%}).", "",
         "| trigger | cap floor | exit | final | vs DCA QQQ | vs matched basket | beats % of random | avg satellite | signals | names bought | money-wtd | worst drop |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in m.itertuples():
        L.append(f"| {LABEL[r.trigger]} | ${r.threshold}bn | {r.exit} | {money(r.final)} | {pct(r.final / r.dca_qqq - 1)} | "
                 f"{pct(r.final / r.matched - 1)} | {r.random_pct:.0%} | {r.avg_sat:.0%} | {r.signals} | {r.names_bought} | "
                 f"{r.irr:+.1%}/yr | {r.maxdd:.1%} |")
    L += ["", "Largest rotations (dollars moved in):", ""]
    for r in m.itertuples():
        L.append(f"- {LABEL[r.trigger]}, ${r.threshold}bn {r.exit}: {r.top_bought}")
    L += ["", f"## Every 5-year window, starts every 6 months {roll.start.min()} .. {roll.start.max()} ({roll.start.nunique()} windows, overlapping)", "",
          "| trigger | cap floor | exit | beats DCA QQQ | median vs DCA QQQ | beats matched | median vs matched | beats random median | median random pct | worst vs DCA QQQ | last 3 windows vs DCA QQQ |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for (tr, thr, x), g in roll.groupby(["trigger", "threshold", "exit"], sort=False):
        v = g.final / g.dca_qqq - 1
        L.append(f"| {LABEL[tr]} | ${thr}bn | {x} | {(v > 0).mean():.0%} | {pct(v.median())} | "
                 f"{(g.final > g.matched).mean():.0%} | {pct((g.final / g.matched).median() - 1)} | "
                 f"{(g.random_pct > 0.5).mean():.0%} | {g.random_pct.median():.0%} | {pct(v.min())} | "
                 f"{', '.join(pct(z) for z in v.tail(3))} |")
    if len(dl):
        L += ["", "## Tech filers the test cannot see (no current ticker, >= 150m shares at some point)", "",
              ", ".join(dl.sort_values("max_shares_m", ascending=False).name.head(40).astype(str))]
    open(f"{OUT}/summary.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main(tuple(sys.argv[1:]) or TRIGGERS)
