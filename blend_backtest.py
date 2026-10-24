"""Two-sleeve book: a QQQ sleeve and an SMH sleeve, each parking in its ETF and rotating into its own laggards,
with an optional inverse-ETF hedge per sleeve and three portfolio rules.

  Sleeve rotation (as basket_backtest): an episode start of a name's signal buys STEP of that sleeve's value from the
  sleeve's ETF, capped at CAP_NAME per name and CAP_TOT across names in the sleeve; held, no exit.
  Rules (each optional):
    displace   a signal that finds no room sells the sleeve's smallest-cap holdings, smaller than the new name, until
               the new name fits (largest cap first among same-day signals)
    rebalance  first trading day of each year: move money between the two ETFs so the sleeves are equal
    trim       on the schedule given ("Y" or "Q"): cut any name above CAP_NAME of its sleeve to CAP_NAME, then scale the
               sleeve's names down to CAP_TOT if they exceed it
  Hedge: on each on-day, each sleeve sells `frac` of its value from its ETF into the hedge instrument (e.g. PSQ);
  on the off-day the hedge is sold back into the ETF.

Deposits are split equally between the sleeves' ETFs. FEE per trade leg. Pure functions; the caller supplies prices,
signals and hedge dates (see the module's caller in the scratchpad, which reads the private WU calendar).
"""
import numpy as np
import pandas as pd
from basket_backtest import episode_starts

FEE = 0.001

def simulate(idx, cores, hedge_px, sleeves, flows, step, cap_name=0.10, cap_tot=0.40, hedge=None,
             displace=False, rebalance=False, trim=None, log=None):
    """idx: trading days. cores: [ETF price array per sleeve]. sleeves: list of dict(P=T x N prices, elig=T x N bool,
    down=T x N bool, cap=T x N market caps). flows: (positions, amounts). hedge: (on day set, off day set, [frac per
    sleeve]) or None. Returns daily value, daily stock value, and per-name end values per sleeve."""
    T = len(idx)
    pos, amt = flows
    add = dict(zip(pos.tolist(), amt.tolist()))
    S = len(sleeves)
    ent = []
    for s in sleeves:
        e = {}
        for j in range(s["P"].shape[1]):
            st = episode_starts(s["down"][:, j] & s["elig"][:, j]) + 1
            for d in st[st < T]: e.setdefault(int(d), []).append(j)
        ent.append(e)
        valid = np.isfinite(s["P"])
        s["last"] = np.array([np.flatnonzero(valid[:, j]).max() if valid[:, j].any() else -1 for j in range(s["P"].shape[1])])
    years = {i for i in range(1, T) if idx[i].year != idx[i - 1].year}
    quarters = {i for i in range(1, T) if idx[i].quarter != idx[i - 1].quarter}
    trim_days = years if trim == "Y" else quarters if trim == "Q" else set()
    h_on, h_off, h_frac = hedge if hedge else (set(), set(), [0.0] * S)
    dying = [{int(d): [] for d in s["last"] if 0 <= d < T - 1} for s in sleeves]
    for k, s in enumerate(sleeves):
        for j, d in enumerate(s["last"]):
            if 0 <= d < T - 1: dying[k][int(d)].append(j)
    days = set(add) | set(h_on) | set(h_off) | trim_days | (years if rebalance else set())
    for k in range(S): days |= set(ent[k]) | set(dying[k])
    days = sorted(days)
    core = np.zeros(S)                                    # ETF units per sleeve
    hu = np.zeros(S)                                      # hedge-instrument units per sleeve
    ns = [np.zeros(s["P"].shape[1]) for s in sleeves]
    seg = []

    def price(k, d): return np.nan_to_num(sleeves[k]["P"][d])
    def sleeve_val(k, d): return core[k] * cores[k][d] + ns[k] @ price(k, d) + hu[k] * hedge_px[d]
    def to_core(k, d, dollars): core[k] += dollars * (1 - FEE) / cores[k][d]
    def from_core(k, d, dollars):
        x = min(dollars, core[k] * cores[k][d]); core[k] -= x / cores[k][d]; return x

    for d in days:
        if d in add:
            for k in range(S): to_core(k, d, add[d] / S)
        for k in range(S):
            for j in dying[k].get(d, []):
                if ns[k][j] > 0: to_core(k, d, ns[k][j] * price(k, d)[j] * (1 - FEE)); ns[k][j] = 0.0
        if d in h_off:
            for k in range(S):
                if hu[k] > 0: to_core(k, d, hu[k] * hedge_px[d] * (1 - FEE)); hu[k] = 0.0
        if d in trim_days:
            for k in range(S):
                p = price(k, d); V = sleeve_val(k, d)
                over = np.maximum(ns[k] * p - cap_name * V, 0)
                for j in np.flatnonzero(over > 0):
                    ns[k][j] -= over[j] / p[j]; to_core(k, d, over[j] * (1 - FEE))
                sat = ns[k] @ p
                if sat > cap_tot * V:
                    cut = 1 - cap_tot * V / sat
                    to_core(k, d, sat * cut * (1 - FEE)); ns[k] *= (1 - cut)
        if rebalance and d in years and S == 2:
            V = [sleeve_val(k, d) for k in range(S)]
            gap = (V[0] - V[1]) / 2
            rich, poor = (0, 1) if gap > 0 else (1, 0)
            x = from_core(rich, d, abs(gap)); to_core(poor, d, x * (1 - FEE))
        if d in h_on:
            for k in range(S):
                if hu[k] == 0 and h_frac[k] > 0:
                    x = from_core(k, d, h_frac[k] * sleeve_val(k, d)); hu[k] = x * (1 - FEE) ** 2 / hedge_px[d]
        for k in range(S):
            js = [j for j in ent[k].get(d, []) if price(k, d)[j] > 0]
            if not js: continue
            p = price(k, d); capd = np.nan_to_num(sleeves[k]["cap"][d])
            if displace: js.sort(key=lambda j: -capd[j])
            V = sleeve_val(k, d)
            want = [max(0.0, min(step * V, cap_name * V - ns[k][j] * p[j])) for j in js]
            room = max(0.0, min(cap_tot * V - ns[k] @ p, core[k] * cores[k][d]))
            if not displace and sum(want) > room:
                want = [w * room / sum(want) for w in want]
            for j, w in zip(js, want):
                if w <= 0: continue
                room = max(0.0, min(cap_tot * V - ns[k] @ p, core[k] * cores[k][d]))
                if displace and w > room:
                    held = [h for h in np.flatnonzero(ns[k] > 0) if h != j and capd[h] < capd[j]]
                    for h in sorted(held, key=lambda h: capd[h]):
                        if room >= w: break
                        v = ns[k][h] * p[h]; ns[k][h] = 0.0; to_core(k, d, v * (1 - FEE))
                        if log is not None: log.append(dict(day=d, sleeve=k, j=h, action="displaced", amount=v))
                        room = max(0.0, min(cap_tot * V - ns[k] @ p, core[k] * cores[k][d]))
                x = min(w, room)
                if x <= 0: continue
                x = from_core(k, d, x); ns[k][j] += x * (1 - FEE) ** 2 / p[j]
                if log is not None: log.append(dict(day=d, sleeve=k, j=j, action="buy", amount=x))
        seg.append((d, core.copy(), hu.copy(), [n.copy() for n in ns]))
    val, stock = np.zeros(T), np.zeros(T)
    bounds = [s_[0] for s_ in seg] + [T]
    for i, (d, c_, h_, n_) in enumerate(seg):
        sl = slice(d, bounds[i + 1])
        sv = sum(np.nan_to_num(sleeves[k]["P"][sl]) @ n_[k] for k in range(S))
        stock[sl] = sv
        val[sl] = sv + sum(c_[k] * cores[k][sl] for k in range(S)) + h_.sum() * hedge_px[sl]
    end_names = [ns[k] * price(k, T - 1) for k in range(S)]
    return val, stock, end_names
