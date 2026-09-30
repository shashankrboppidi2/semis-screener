"""Tier 1 panel: implied bookings and book-to-bill for every US filer that discloses RPO.

Most filers never report bookings, but RPO plus revenue backs it out:

    implied gross bookings_t  =  revenue_t + (RPO_t - RPO_t-1)
    book-to-bill_t            =  implied bookings_t / revenue_t

The gate that makes this meaningful: RPO has to represent more than about a quarter of revenue.
Where RPO cover is near zero (NVIDIA, AMD, Lam) the derived book-to-bill pins to 1.00 and carries
no information at all, so including those names would inject noise into any cross-sectional rank.
That gate was discovered empirically on the semis universe, not assumed.

Latest-reported, not as-first-reported -- see tier1_frames.py for why, and what that rules out.
"""
import pandas as pd, numpy as np

MIN_REV_Q = 25.0          # $m per quarter, to keep micro caps out of the rank
MIN_COVER = 1.0           # quarters of revenue sitting in RPO

def build():
    D = pd.read_pickle("out/tier1_raw.pkl")
    D["end"] = pd.to_datetime(D.end)

    # --- quarterly revenue: coalesce concepts by priority, keep only ~3-month periods
    r = D[D.metric == "rev"].copy()
    r["span"] = (r.end - pd.to_datetime(r.start)).dt.days
    r = r[r.span.between(80, 100)]
    # These concepts are NESTED, not alternatives: ASC 606 revenue is a subset of total revenue, so
    # for a lessor like Crown Castle the 606 tag is only ~3% of the top line. But picking the
    # largest per QUARTER lets the concept switch mid-series, which puts a step in the growth rate
    # that the filer never reported. So one concept is pinned PER FILER: the one with the most
    # quarters available, and among equals the one with the larger median value (total, not component).
    pick = (r.groupby(["cik", "tag"]).val.agg(n="size", med="median").reset_index()
              .sort_values(["cik", "n", "med"], ascending=[True, False, False])
              .drop_duplicates("cik")[["cik", "tag"]])
    r = r.merge(pick, on=["cik", "tag"], how="inner")
    r = r.sort_values(["cik", "cy", "cq"]).drop_duplicates(["cik", "cy", "cq"])
    rev = r[["cik", "entityName", "cy", "cq", "val", "tag"]].rename(columns={"val": "rev"})
    PICK = pick.set_index("cik").tag

    # --- Q4 from the annual figure where a filer tags no separate Q4
    fy = D[D.metric == "rev_fy"].copy()
    fy["span"] = (fy.end - pd.to_datetime(fy.start)).dt.days
    fy = fy[fy.span.between(350, 380)].copy()
    fy["pinned"] = fy.cik.map(PICK)                      # derive Q4 from the SAME concept as the quarters
    fy = pd.concat([fy[fy.tag == fy.pinned], fy[fy.pinned.isna()]])
    fy = fy.sort_values(["cik", "cy", "val"], ascending=[True, True, False]).drop_duplicates(["cik", "cy"])
    q123 = rev[rev.cq.isin([1, 2, 3])].groupby(["cik", "cy"]).agg(s=("rev", "sum"), n=("rev", "size"))
    q123 = q123[q123.n == 3]
    d4 = fy.set_index(["cik", "cy"]).join(q123, how="inner")
    d4 = d4[d4.s.notna()].reset_index()
    d4["rev"] = d4.val - d4.s; d4["cq"] = 4
    have4 = set(zip(rev[rev.cq == 4].cik, rev[rev.cq == 4].cy))
    d4 = d4[[(c, y) not in have4 for c, y in zip(d4.cik, d4.cy)]]
    d4 = d4[d4.rev > 0]
    rev = pd.concat([rev, d4[["cik", "entityName", "cy", "cq", "rev", "tag"]].assign(tag="derived Q4 = FY - 9M")], ignore_index=True)

    # --- balances
    bal = []
    for m, nm in (("rpo", "rpo"), ("dr_cur", "dr_cur"), ("dr_tot", "dr_tot")):
        b = D[D.metric == m].sort_values(["cik", "cy", "cq", "prio"]).drop_duplicates(["cik", "cy", "cq"])
        bal.append(b[["cik", "cy", "cq", "val"]].rename(columns={"val": nm}))
    P = rev
    for b in bal: P = P.merge(b, on=["cik", "cy", "cq"], how="outer")

    P["name"] = P.groupby("cik").entityName.transform(lambda s: s.dropna().iloc[-1] if s.notna().any() else None)
    P = P.drop(columns="entityName")
    P["cqp"] = pd.PeriodIndex.from_fields(year=P.cy, quarter=P.cq, freq="Q")
    for c in ("rev", "rpo", "dr_cur", "dr_tot"):
        P[c] = pd.to_numeric(P[c], errors="coerce") / 1e6      # -> $m
    # a zero or negative quarter of revenue makes every ratio below meaningless, not infinite
    P.loc[P.rev.le(0), "rev"] = np.nan
    P = P.sort_values(["cik", "cqp"])

    # --- derived series, computed only across consecutive quarters
    g = P.groupby("cik")
    P["gap"] = g.cqp.diff().apply(lambda x: getattr(x, "n", np.nan))
    P["d_rpo"] = np.where(P.gap == 1, g.rpo.diff(), np.nan)
    P["bookings"] = P.rev + P.d_rpo
    P["b2b"] = P.bookings / P.rev
    P["rpo_cover_q"] = P.rpo / P.rev
    y = P[["cik", "cqp", "rpo", "rev", "b2b"]].copy(); y["cqp"] = y.cqp + 4
    P = P.merge(y.rename(columns={"rpo": "rpo_yago", "rev": "rev_yago", "b2b": "b2b_yago"}), on=["cik", "cqp"], how="left")
    P["rpo_yoy"] = P.rpo / P.rpo_yago - 1
    P["rev_yoy"] = P.rev / P.rev_yago - 1
    P["b2b_chg_yoy"] = P.b2b - P.b2b_yago
    P = P.sort_values(["cik", "cqp"])
    P["b2b_4q"] = P.groupby("cik").b2b.transform(lambda s: s.rolling(4, min_periods=3).mean())
    P["rpo_yoy_accel"] = np.where(P.gap == 1, P.groupby("cik").rpo_yoy.diff(), np.nan)

    # ---- data-quality flags. A market-wide pull has no reconciliation validator behind it, so the
    # checks the semis pipeline got for free have to be explicit here.
    P["rpo_quarters"] = P.groupby("cik").rpo.transform(lambda s: s.notna().cumsum())
    # (a) a source fact that cannot be right: TPI Composites tags $59.6bn of RPO against $72m of
    #     quarterly revenue. No downstream cleverness fixes a wrong fact, so it is excluded.
    P["flag_implausible_rpo"] = P.rpo_cover_q > 40
    # (b) a step that large is a disclosure event -- a scope change or a first-time disclosure --
    #     not a quarter of orders, so it is reported separately instead of scored as acceleration.
    P["flag_rpo_step"] = (P.d_rpo / (P.rpo - P.d_rpo)).abs() > 0.5
    # (c) four quarters that do not add up to the annual figure mean the revenue concept is the
    #     wrong one for this filer. The test is only VALID where the fiscal year ends in December:
    #     for a June-year-end filer the frames annual period does not span the four calendar
    #     quarters, so a mismatch there says nothing about the data. Tested only where valid, and
    #     kept advisory rather than a gate, since a wrong concept is now unlikely after pinning.
    fyv = fy.rename(columns={"val": "fy_rev"})[["cik", "cy", "fy_rev", "end"]].copy(); fyv["fy_rev"] /= 1e6
    fyv["dec_fy"] = pd.to_datetime(fyv.end).dt.month == 12
    ann = P.groupby(["cik", "cy"]).agg(q=("rev", "sum"), n=("rev", "size"), derived=("tag", lambda s: (s == "derived Q4 = FY - 9M").any())).reset_index()
    ann = ann[(ann.n == 4) & ~ann.derived].merge(fyv[fyv.dec_fy], on=["cik", "cy"], how="inner")
    ann["rev_vs_annual"] = ann.q / ann.fy_rev - 1
    bad = ann[ann.rev_vs_annual.abs() > 0.20].groupby("cik").size()
    P["flag_revenue_mismatch"] = P.cik.isin(bad.index)
    P["revenue_check_ran"] = P.cik.isin(ann.cik)
    P["clean"] = ~(P.flag_implausible_rpo | P.flag_revenue_mismatch)
    P.to_pickle("out/tier1_panel.pkl")
    return P

if __name__ == "__main__":
    P = build()
    print(f"panel: {len(P):,} filer-quarters | filers {P.cik.nunique():,} | {P.cqp.min()} to {P.cqp.max()}")
    print(f"with RPO: {P.rpo.notna().sum():,} rows, {P[P.rpo.notna()].cik.nunique():,} filers")
    print(f"with both RPO and revenue: {(P.rpo.notna() & P.rev.notna()).sum():,} rows")
    print(f"Q4 rows derived from the annual: {(P.tag == 'derived Q4 = FY - 9M').sum():,}")
    L = P.dropna(subset=["b2b"]).sort_values("cqp").groupby("cik").tail(1)
    print(f"\nfilers with a computable book-to-bill in their latest quarter: {len(L):,}")
    print(f"  of which RPO cover >= {MIN_COVER} quarter: {(L.rpo_cover_q >= MIN_COVER).sum():,}")
    print(f"  and revenue >= ${MIN_REV_Q:.0f}m/quarter:  {((L.rpo_cover_q >= MIN_COVER) & (L.rev >= MIN_REV_Q)).sum():,}")
    print("\nquality flags on the latest row per filer:")
    print(f"  implausible RPO (cover > 40 quarters): {int(L.rpo_cover_q.gt(40).sum())}")
    print(f"  revenue does not reconcile to the annual: {int(P[P.cik.isin(L.cik)].groupby('cik').flag_revenue_mismatch.any().sum())}")
    print(f"  RPO step > 50% (disclosure event, not orders): {int(L.get('flag_rpo_step', pd.Series(dtype=bool)).sum())}")
    print("\nRPO cover distribution (latest quarter, all filers):")
    print(L.rpo_cover_q.describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_string())
