"""Live Nasdaq breadth hedge signal for plan_alerts.py.

update_counts()  refreshes the latest days of results/breadth/nasdaq_counts.csv from Yahoo: about 14 months of daily
                 highs and lows for today's Nasdaq common stocks and other issues (ETFs skipped), so the last couple of
                 months have a full year of look-back. Same rule as breadth_counts.py.
signal()         the two breadth lines from those counts -- 5 x EMA10 of the share of issues at new 52-week lows minus
                 new highs, mapped by a linear calibration -- and the hedge state machine: on when either line closes
                 above its exit level, off when both close below their re-entry levels.

The calibration and the levels are read from the BREADTH_PARAMS secret (JSON) and are not kept in this public
repository:  {"orange": [a, b], "blue": [a, b], "exit": [orange, blue], "reentry": [orange, blue]}
"""
import json, os
import numpy as np
import pandas as pd

COUNTS = "results/breadth/nasdaq_counts.csv"
KINDS = ("common", "other")

def params():
    raw = os.getenv("BREADTH_PARAMS", "").strip()
    return json.loads(raw) if raw else None

def update_counts(days=430, path=COUNTS):
    import yfinance as yf
    from breadth_counts import universe
    u = universe(); u = u[u.kind.isin(KINDS)]
    kinds = dict(zip(u.yahoo, u.kind)); tick = sorted(kinds)
    start = (pd.Timestamp.today().normalize() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    acc = None
    for i in range(0, len(tick), 250):
        chunk = tick[i:i + 250]
        try:
            d = yf.download(chunk, start=start, auto_adjust=False, progress=False, threads=True, group_by="column")
        except Exception as e:
            print("breadth download failed for a chunk:", str(e)[:120], flush=True); continue
        if d is None or not len(d): continue
        H, L = d["High"], d["Low"]
        if isinstance(H, pd.Series): H, L = H.to_frame(chunk[0]), L.to_frame(chunk[0])
        prevH = H.shift(1).rolling(251, min_periods=251).max()
        prevL = L.shift(1).rolling(251, min_periods=251).min()
        nh, nl, live = (H >= prevH) & prevH.notna(), (L <= prevL) & prevL.notna(), prevH.notna() & H.notna()
        part = {}
        for k in KINDS:
            cols = [c for c in H.columns if kinds.get(c) == k]
            part[f"nh_{k}"] = nh[cols].sum(axis=1); part[f"nl_{k}"] = nl[cols].sum(axis=1); part[f"n_{k}"] = live[cols].sum(axis=1)
        part = pd.DataFrame(part)
        acc = part if acc is None else acc.add(part, fill_value=0)
    if acc is None: return pd.read_csv(path, index_col=0, parse_dates=True)
    new = acc[acc.n_common > 0].astype(int)
    old = pd.read_csv(path, index_col=0, parse_dates=True) if os.path.exists(path) else pd.DataFrame()
    keep = old.drop(index=old.index.intersection(new.index)) if len(old) else old
    out = pd.concat([keep, new]).sort_index()
    out.to_csv(path, index_label="date", float_format="%.0f")
    print(f"breadth counts refreshed: {len(new)} days, last {new.index.max().date()}", flush=True)
    return out

def lines(counts, p):
    nl = sum(counts[f"nl_{k}"] for k in KINDS); nh = sum(counts[f"nh_{k}"] for k in KINDS)
    n = sum(counts[f"n_{k}"] for k in KINDS)
    share = ((nl - nh) / n.where(n > 200)).dropna()
    base = 5 * share.ewm(span=10, adjust=False).mean()
    return p["orange"][0] * base + p["orange"][1], p["blue"][0] * base + p["blue"][1]

def signal(counts=None, p=None):
    p = p or params()
    if p is None: return None
    counts = counts if counts is not None else pd.read_csv(COUNTS, index_col=0, parse_dates=True)
    o, b = lines(counts, p)
    (eo, eb), (ro, rb) = p["exit"], p["reentry"]
    on, since, events = False, None, []
    for t in o.index:
        if not on and (o[t] > eo or b[t] > eb): on, since = True, t; events.append((t, "on"))
        elif on and o[t] < ro and b[t] < rb: on, since = False, t; events.append((t, "off"))
    return dict(on=on, since=since, date=o.index[-1], orange=float(o.iloc[-1]), blue=float(b.iloc[-1]), events=events[-6:])
