"""Daily market caps from SEC share counts and Yahoo split-adjusted closes, robust to split restatements.

Frames return the most recent filing's value for each period, so a share count for a quarter before a split is
often the restated, post-split figure from a later 10-Q's comparative column -- and sometimes the original. Each
count is therefore converted to today's share units by whichever of its candidate split adjustments (the splits
after its period end that the restating filing may already include) lands closest to the next later count, walking
back from the latest. Share counts drift a few percent a quarter; splits jump by 1.5x or more, so the choice is
clear. Counts more than 2.5x off their neighbours' median are dropped as bad tags.

Cap on day t = split-adjusted close x the latest adjusted count available by t (period end + 60 days, <= 500 days
old) / ADR ratio, in $bn.
"""
import numpy as np
import pandas as pd

LAG = pd.Timedelta(days=60)
RESTATE_WINDOW = pd.Timedelta(days=450)

def adjusted_shares(sh, splits):
    """sh: rows (end, shares) for one filer; splits: Series ratio by date (>1 for forward splits).
    Returns Series of shares in today's units, indexed by period end."""
    sh = sh.sort_values("end").drop_duplicates("end", keep="last")
    sp = splits[splits > 0].sort_index()
    ends, vals = pd.DatetimeIndex(sh.end), sh.shares.values.astype(float)
    out = np.empty(len(vals))
    F_now = lambda e: float(np.prod(sp[sp.index > e].values)) if (sp.index > e).any() else 1.0
    ref = [np.median([vals[j] * F_now(ends[j]) for j in range(max(0, len(vals) - 3), len(vals))])]
    for i in range(len(vals) - 1, -1, -1):
        after = sp[sp.index > ends[i]]
        F = float(np.prod(after.values)) if len(after) else 1.0
        within = after[after.index <= ends[i] + RESTATE_WINDOW].values
        cands = [F / float(np.prod(within[:k])) for k in range(len(within) + 1)]
        r = np.median(ref[-3:])
        m = min(cands, key=lambda c: abs(np.log(vals[i] * c / r)))
        out[i] = vals[i] * m
        ref.append(out[i])
    s = pd.Series(out, ends)
    med = s.rolling(5, center=True, min_periods=1).median()
    return s[np.abs(np.log(s / med)) <= np.log(2.5)]

def daily_caps(close, splits, sh, ratio=1.0):
    if not len(sh) or close.dropna().empty: return pd.Series(np.nan, close.index)
    a = adjusted_shares(sh, splits)
    if not len(a): return pd.Series(np.nan, close.index)
    avail = pd.Series(a.values, a.index + LAG)
    avail = avail[~avail.index.duplicated(keep="last")].sort_index()
    pos = avail.index.searchsorted(close.index, side="right") - 1
    v = avail.values[np.maximum(pos, 0)].astype(float)
    age = (close.index - avail.index[np.maximum(pos, 0)]).days
    v[(pos < 0) | (age > 500)] = np.nan
    return close * v / ratio / 1e9
