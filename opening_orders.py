"""Opening book for the 50/50 QQQ/SMH plan, split across a TFSA and a taxable account.

Sizes the book as if every name that is behind today had just alerted once (STEP of its sleeve), plus the PSQ hedge
when it is on, then places it: the TFSA takes the rotation names first (later rotations and trims trade there
tax-free), then core ETF; the taxable account takes the hedge and the rest of the core.

python opening_orders.py --plan 93450 --tfsa 43550 --hedge on      # US$; prints one order table per account
"""
import argparse, glob, os
import numpy as np
import pandas as pd
import basket_backtest as bb
import plan_alerts as pa

ap = argparse.ArgumentParser()
ap.add_argument("--plan", type=float, required=True, help="total plan dollars (both accounts)")
ap.add_argument("--tfsa", type=float, default=0.0, help="plan dollars held in the TFSA")
ap.add_argument("--hedge", choices=["on", "off"], required=True)
a = ap.parse_args()

q, adj, cap, meta = bb.load()
px = pd.read_csv("results/prices/closes.csv", index_col=0, parse_dates=True).reindex(q.index).ffill()
config = {os.path.basename(p)[:-5] for p in glob.glob("config/*.json")}
chips = [t for t in adj.columns if t in config or meta.sic.get(t) in pa.CHIP_SIC]
d = q.index[-1]
def behind(P, b): x = P / b.values[:, None]; return (x / x.rolling(252, min_periods=252).max() - 1).loc[d]
rq, rs, capd = behind(adj, px.QQQ), behind(adj[chips], px.SMH), cap.loc[d]
top = capd[chips].sort_values(ascending=False).head(pa.TOP_N).index
qq = rq[(capd >= pa.FLOOR_B) & (rq <= -pa.DROP)].index
ss = rs[rs.index.isin(top) & (rs <= -pa.DROP)].index
r = np.log(px[["QQQ", "SMH"]]).diff().iloc[-1260:]
beta = r.SMH.cov(r.QQQ) / r.QQQ.var()
SLV = a.plan / 2
frac = {"QQQ": 0.25, "SMH": 0.5 * beta / (1 + beta)} if a.hedge == "on" else {"QQQ": 0.0, "SMH": 0.0}
names = pd.Series(0.0, index=sorted(set(qq) | set(ss)))
for sleeve in (qq, ss):
    for t in capd[list(sleeve)].sort_values(ascending=False).index[:int(pa.CAP_TOT / pa.STEP)]:   # 40% cap, largest first
        names[t] += pa.STEP * SLV
nmax = int(pa.CAP_TOT / pa.STEP)
core = {"QQQ": SLV * (1 - pa.STEP * min(len(qq), nmax) - frac["QQQ"]),
        "SMH": SLV * (1 - pa.STEP * min(len(ss), nmax) - frac["SMH"])}
psq = (frac["QQQ"] + frac["SMH"]) * SLV

tfsa, taxable = {}, {}
room = a.tfsa
for t in names.sort_values(ascending=False).index:
    x = min(names[t], room); room -= x
    if x > 0: tfsa[t] = x
    if names[t] - x > 0: taxable[t] = names[t] - x
ctot = sum(core.values())
for e in ("QQQ", "SMH"):
    x = min(core[e], room * core[e] / ctot) if ctot > 0 else 0.0
    if x > 0: tfsa[e] = x
    if core[e] - x > 0: taxable[e] = core[e] - x
if psq > 0: taxable["PSQ"] = psq

price = {**{t: adj.at[d, t] for t in names.index}, "QQQ": px.QQQ[d], "SMH": px.SMH[d], "PSQ": px.PSQ[d]}
print(f"prices as of {d.date()}; SMH beta {beta:.2f}; hedge {a.hedge}; sleeves ${SLV:,.0f} each")
for label, book in (("TFSA", tfsa), ("Taxable", taxable)):
    if not book: continue
    print(f"\n{label}\n| ticker | amount | close | shares |\n|---|---|---|---|")
    for t in sorted(book, key=lambda t: (t not in ("QQQ", "SMH", "PSQ"), -book[t])):
        print(f"| {t} | ${book[t]:,.0f} | {price[t]:,.2f} | {book[t] / price[t]:,.2f} |")
    print(f"| total | ${sum(book.values()):,.0f} | | |")
