"""Tier-1 screens over the market-wide RPO panel.

Four cuts, each answering a different question:

  backlog_ahead   book-to-bill above 1 and rising while revenue growth is still soft. This is the
                  pre-inflection state -- contracted work is piling up before it shows in the P&L,
                  which is where a leading indicator should be if it is anywhere.
  accelerating    RPO growth accelerating with book-to-bill above 1: already inflecting, confirmed.
  borrowing       revenue growing while book-to-bill is below 1. Revenue is being met out of
                  backlog rather than new orders -- ON Semi's pattern, and invisible on revenue alone.
  rpo_step        the largest single-quarter jumps in RPO. These are often disclosure events (a
                  scope change, a first-time disclosure) rather than organic orders, and are
                  flagged as such rather than scored with the rest.
"""
import pandas as pd, numpy as np, os

MIN_REV_Q, MIN_COVER = 25.0, 1.0
# a filer must have reported this recently to be ranked: three quarters before the current calendar quarter
# (2025Q4 when this was built in 2026Q3). SEMIS_CURRENT_Q=2026Q1 pins it.
CURRENT = pd.Period(os.environ.get("SEMIS_CURRENT_Q") or pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("Q") - 3, "Q")

def latest():
    P = pd.read_pickle("out/tier1_panel.pkl")
    T = pd.read_pickle("out/cik_tickers.pkl")[["cik", "ticker"]]
    L = P.dropna(subset=["b2b"]).sort_values("cqp").groupby("cik").tail(1).copy()
    P4 = P.sort_values("cqp").groupby("cik").b2b.apply(lambda s: s.dropna().tail(4))
    L = L.merge(T, on="cik", how="left")
    if os.path.exists("out/tier1_sic.pkl"):
        S = pd.read_pickle("out/tier1_sic.pkl")
        L = L.merge(S[["cik", "sic_desc"]].rename(columns={"sic_desc": "industry"}), on="cik", how="left")
        L["ticker"] = L.ticker.fillna(pd.Series(S.set_index("cik").ticker.reindex(L.cik).values, index=L.index))
    else:
        L["industry"] = None
    # trend in book-to-bill: latest minus the mean of the three before it
    prev = P.sort_values("cqp").groupby("cik").b2b.apply(lambda s: s.dropna().iloc[-4:-1].mean())
    L["b2b_prev3"] = L.cik.map(prev)
    L["b2b_trend"] = L.b2b - L.b2b_prev3
    L["gated"] = ((L.rpo_cover_q >= MIN_COVER) & (L.rev >= MIN_REV_Q) & (L.cqp >= CURRENT)
                  & L.clean & (L.rpo_quarters >= 5))          # 5 quarters of RPO so y/y means something
    return P, L

COLS = ["ticker", "name", "industry", "cqp", "rev", "rpo", "rpo_cover_q", "b2b", "b2b_4q", "b2b_prev3",
        "b2b_trend", "rpo_yoy", "rpo_yoy_accel", "rev_yoy", "d_rpo"]

def screens(L):
    G = L[L.gated].copy()
    out = {}
    out["backlog_ahead"] = G[(G.b2b > 1.05) & (G.b2b_trend > 0) & (G.rev_yoy < 0.15) & ~G.flag_rpo_step].sort_values("b2b", ascending=False)
    # step events are disclosure changes, not orders, so they are excluded here and reported on their own
    out["accelerating"] = G[(G.rpo_yoy_accel > 0) & (G.b2b > 1.0) & (G.rpo_yoy > 0) & ~G.flag_rpo_step].sort_values("rpo_yoy_accel", ascending=False)
    out["borrowing"] = G[(G.rev_yoy > 0.02) & (G.b2b < 0.95)].sort_values("b2b")
    s = G.dropna(subset=["d_rpo"]).copy()
    s["rpo_step_x"] = s.rpo / (s.rpo - s.d_rpo)
    out["rpo_step"] = s[(s.rpo_step_x > 1.5) & (s.d_rpo > 100)].sort_values("rpo_step_x", ascending=False)
    return out

if __name__ == "__main__":
    P, L = latest(); L.to_pickle("out/tier1_latest.pkl")
    S = screens(L)
    print(f"panel {len(P):,} filer-quarters | {L.cik.nunique():,} filers with a book-to-bill | gated: {int(L.gated.sum()):,}")
    print(f"gate: RPO cover >= {MIN_COVER}q, revenue >= ${MIN_REV_Q:.0f}m/q, reported {CURRENT} or later\n")
    for k, d in S.items():
        print(f"=== {k}: {len(d)} names ===")
        print(d.head(18)[COLS].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
        print()
