"""Trade blotter for one basket-rotation setup over the last five years (basket_backtest rules).

Every rotation out of QQQ, every signal that found the satellite full, every sale, and where each position
stands at the end. Default: relative to QQQ, $50bn floor, hold.

python basket_trades.py [trigger] [cap floor $bn] [hold|trip]    -> results/basket_backtest/trades_<...>.csv/.md
"""
import sys
import numpy as np
import pandas as pd
import basket_backtest as bb

def main(trigger="rel_qqq", thr=50, exit_rule="hold"):
    thr = float(thr)
    q, adj, cap, meta = bb.load()
    bench = bb.benchmarks(adj, meta, trigger)
    sig = bb.prepare(adj, bench)
    x = adj if bench is None else adj / bench
    rel_dd = x / x.rolling(252, min_periods=252).max() - 1           # how far behind its own high (vs the benchmark)
    own_dd = adj / adj.rolling(252, min_periods=252).max() - 1
    end = q.index[-1]; start = end - pd.DateOffset(years=bb.YEARS)
    log = []
    r = bb.window(q, adj, cap, sig, start, end, thr, exit_rule, 0, np.random.default_rng(0), detail=True, log=log)
    idx = q.index[q.index.searchsorted(start):]
    names = adj.columns
    t = pd.DataFrame(log)
    t["date"] = idx[t.day]; t["ticker"] = names[t.j]
    sday = idx[np.maximum(t.day - 1, 0)]                               # the signal close (trade is the next close)
    t["vs_bench_off_high"] = [rel_dd.at[d, k] for d, k in zip(sday, t.ticker)]
    t["own_off_high"] = [own_dd.at[d, k] for d, k in zip(sday, t.ticker)]
    t["cap_b"] = [cap.at[d, k] for d, k in zip(sday, t.ticker)]
    t["name"] = [meta.name.get(k, "") for k in t.ticker]
    t = t.drop(columns=["day", "j"])
    tag = f"{trigger}_{int(thr)}b_{exit_rule}"
    t.to_csv(f"{bb.OUT}/trades_{tag}.csv", index=False)

    # positions at the end
    last = adj.loc[end]
    buys = t[t.action == "buy"]
    pos = buys.groupby("ticker").agg(first_buy=("date", "min"), buys=("amount", "size"), invested=("amount", "sum"),
                                     shares=("shares", "sum"))
    sold = t[t.action.str.startswith("sell")].groupby("ticker").amount.sum()
    pos["sold_for"] = sold.reindex(pos.index).fillna(0)
    held = ~pos.index.isin(sold.index)
    pos["value_now"] = np.where(held, pos.shares * last.reindex(pos.index).fillna(0), 0.0)
    pos["pnl"] = pos.value_now + pos.sold_for - pos.invested
    pos["return"] = pos.pnl / pos.invested
    # what the same dollars would have done left in QQQ
    qq = q.reindex(idx)
    pos["qqq_alt"] = [sum(a * qq.iloc[-1] / qq.loc[d] for d, a in zip(buys[buys.ticker == k].date, buys[buys.ticker == k].amount))
                      for k in pos.index]
    pos["vs_qqq"] = pos.value_now + pos.sold_for - pos.qqq_alt
    pos = pos.sort_values("pnl", ascending=False)
    pos.to_csv(f"{bb.OUT}/positions_{tag}.csv")

    money = lambda v: f"${v:,.0f}"
    pct = lambda v: f"{v:+.0%}"
    L = [f"# Trades: {bb.LABEL[trigger]}, ${int(thr)}bn floor, {exit_rule}", "",
         f"{idx[0]:%Y-%m-%d} .. {end:%Y-%m-%d}. Final {money(r['final'])} vs DCA QQQ {money(r['dca_qqq'])} "
         f"({pct(r['final'] / r['dca_qqq'] - 1)}); {len(buys)} buys in {buys.ticker.nunique()} names, "
         f"{(t.action == 'skip').sum()} signals skipped for lack of room.", "",
         "| date | ticker | action | amount | price | behind QQQ vs its high | own drop from high | cap $bn | satellite before | note |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for e in t.itertuples():
        L.append(f"| {e.date:%Y-%m-%d} | {e.ticker} | {e.action} | {money(e.amount)} | {e.price:,.2f} | {pct(e.vs_bench_off_high)} | "
                 f"{pct(e.own_off_high)} | {e.cap_b:,.0f} | {'' if pd.isna(e.sat_before) else f'{e.sat_before:.0%}'} | {e.note if isinstance(e.note, str) else ''} |")
    L += ["", "## Positions at the end", "", "| ticker | first buy | buys | invested | value now | P&L | return | vs same $ left in QQQ |",
          "|---|---|---|---|---|---|---|---|"]
    for k, p in pos.iterrows():
        L.append(f"| {k} | {p.first_buy:%Y-%m-%d} | {p.buys} | {money(p.invested)} | {money(p.value_now + p.sold_for)} | "
                 f"{money(p.pnl)} | {pct(p['return'])} | {money(p.vs_qqq)} |")
    L.append(f"| **total** |  | {int(pos.buys.sum())} | {money(pos.invested.sum())} | {money((pos.value_now + pos.sold_for).sum())} | "
             f"{money(pos.pnl.sum())} | {pct(pos.pnl.sum() / pos.invested.sum())} | {money(pos.vs_qqq.sum())} |")
    open(f"{bb.OUT}/trades_{tag}.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main(*sys.argv[1:4])
