"""Beat-and-raise flag: two consecutive quarters of beating the company's own prior guide while
raising the forward guide.

No connected source carries sell-side consensus or its revision history, so both legs are measured
against the company's OWN guidance. That is a different statement from beating the street -- in
some ways a stricter one, since management sets the bar it then clears.

  beat(Q)    actual revenue for Q, from the tier-1 XBRL panel, above the midpoint of the guide the
             company gave FOR Q in the release one quarter earlier. Growth-rate guides are turned
             into dollars against the year-ago quarter first.
  raise(R)   the full-year guide in release R above the full-year guide in the previous release,
             compared only when both fall in the same fiscal year -- across a year boundary the two
             guides describe different years. Where a filer gives no full-year guide, the fallback
             is that its next-quarter guide implies y/y growth above the y/y it just reported.
             raise_basis records which test ran, because they are not equally strong.

Releases are matched to the quarter they report by period end, never by counting releases, so a
missed or extra 8-K cannot shift the whole chain.
"""
import pandas as pd, numpy as np, os, json

def load():
    P = pd.read_pickle("out/tier1_panel.pkl")
    G = pd.read_pickle("out/br_guidance_enriched.pkl")
    R = pd.read_pickle("out/br_releases.pkl")
    G = G.merge(R[["accn", "primary"]], on="accn", how="left")
    G["filed"] = pd.to_datetime(G.filed)
    for c in ("revenue_low", "revenue_mid", "revenue_high", "fy_revenue_low", "fy_revenue_mid",
              "fy_revenue_high", "growth_low_pct", "growth_high_pct", "growth_mid_pct"):
        if c not in G: G[c] = np.nan
    if "guide_period" not in G: G["guide_period"] = None
    return P, G

def build():
    P, G = load()
    q = P.dropna(subset=["rev"])[["cik", "cqp", "rev", "rev_yoy"]].copy()
    q["qend"] = q.cqp.dt.end_time.dt.normalize()

    m = G.merge(q, on="cik", how="inner")
    m["lag"] = (m.filed - m.qend).dt.days
    m = m[m.lag.between(10, 100)].sort_values(["cik", "accn", "lag"]).drop_duplicates(["cik", "accn"])
    m = m.rename(columns={"cqp": "reported_q", "rev": "reported_rev", "rev_yoy": "reported_yoy"})
    m["guided_q"] = m.reported_q + 1
    m["fy"] = m.reported_q.dt.year
    m = m.sort_values(["cik", "reported_q"])

    # a guide tagged full_year is not a next-quarter guide; unknown is treated as quarterly only
    # when no full-year figure was found in the same release.
    is_q = (m.guide_period != "full_year")
    m["q_guide_mid"] = np.where(is_q, m.revenue_mid.fillna((m.revenue_low + m.revenue_high) / 2), np.nan)
    m["q_growth_mid"] = np.where(is_q, m.growth_mid_pct.fillna((m.growth_low_pct + m.growth_high_pct) / 2), np.nan)
    m["fy_guide_mid"] = m.fy_revenue_mid.fillna((m.fy_revenue_low + m.fy_revenue_high) / 2)
    m.loc[m.guide_period == "full_year", "fy_guide_mid"] = m.loc[m.guide_period == "full_year", "fy_guide_mid"].fillna(
        m.loc[m.guide_period == "full_year", "revenue_mid"].fillna(
            (m.loc[m.guide_period == "full_year", "revenue_low"] + m.loc[m.guide_period == "full_year", "revenue_high"]) / 2))

    # carry each release's forward guide onto the quarter it guides
    yago = P[["cik", "cqp", "rev"]].copy(); yago["cqp"] = yago.cqp + 4
    # one release per guided quarter: a filer can file several 8-Ks in a quarter, and without this
    # the same quarter is scored two or three times against different figures.
    gsrc = m.sort_values(["cik", "guided_q", "filed"]).drop_duplicates(["cik", "guided_q"], keep="last")
    gq = gsrc[["cik", "guided_q", "q_guide_mid", "q_growth_mid", "fy_guide_mid", "accn", "filed", "fy"]].rename(
        columns={"guided_q": "reported_q", "accn": "guide_accn", "filed": "guide_filed",
                 "fy_guide_mid": "prev_fy_guide", "fy": "prev_fy",
                 "q_guide_mid": "guide_for_this_q", "q_growth_mid": "growth_guide_for_this_q"})
    A = m.merge(gq, on=["cik", "reported_q"], how="left")
    A = A.merge(yago.rename(columns={"cqp": "reported_q", "rev": "reported_q_yago"}), on=["cik", "reported_q"], how="left")

    # growth-rate guides become dollars against the year-ago quarter so both kinds compare alike
    conv = A.reported_q_yago * (1 + A.growth_guide_for_this_q / 100)
    A["guide_mid"] = A.guide_for_this_q.fillna(conv)
    A["guide_kind"] = np.where(A.guide_for_this_q.notna(), "dollar guide",
                        np.where(conv.notna(), "growth guide converted to dollars", "none"))
    # PLAUSIBILITY GUARD. A next-quarter revenue guide sits close to the quarter actually reported:
    # measured on this data the actual/guide ratio is 1.007 at the 25th percentile and 1.049 at the
    # 75th, with 85% inside +/-15%. Values far outside that are misparsed figures, not guides --
    # a "beat" of +1,616% (IBM, read from "$1 billion of cost savings") is a parse error, and the
    # cluster at the old 0.4x floor was full-year guides being read as quarterly ones (LHX, MU).
    # The band is set from that observed distribution, not chosen a priori.
    ratio = A.guide_mid / A.reported_rev
    implausible = A.guide_mid.notna() & (~ratio.between(1 / 1.30, 1 / 0.80))
    A["guide_rejected"] = implausible
    A.loc[implausible, "guide_mid"] = np.nan
    A.loc[implausible, "guide_kind"] = "rejected: implausible vs reported revenue"
    A["beat"] = np.where(A.guide_mid.notna() & A.reported_rev.notna(), A.reported_rev > A.guide_mid, np.nan)
    A["beat_pct"] = A.reported_rev / A.guide_mid - 1

    same_fy = A.fy == A.prev_fy
    A["raise_fy"] = np.where(A.fy_guide_mid.notna() & A.prev_fy_guide.notna() & same_fy,
                             A.fy_guide_mid > A.prev_fy_guide, np.nan)
    A = A.merge(yago.rename(columns={"cqp": "guided_q", "rev": "guided_q_yago"}), on=["cik", "guided_q"], how="left")

    A["fwd_guide_mid"] = A.q_guide_mid
    A["guided_yoy"] = np.where(A.q_growth_mid.notna(), A.q_growth_mid / 100,
                               A.fwd_guide_mid / A.guided_q_yago - 1)
    # the same guard on the forward guide, using the quarter just reported as the yardstick
    fratio = A.fwd_guide_mid / A.reported_rev
    A.loc[A.fwd_guide_mid.notna() & (~fratio.between(0.6, 1.8)), ["fwd_guide_mid", "guided_yoy"]] = np.nan
    A.loc[A.guided_yoy.abs() > 2.0, "guided_yoy"] = np.nan          # a guide implying >200% y/y is a misread
    A["raise_accel"] = np.where(pd.notna(A.guided_yoy) & A.reported_yoy.notna(), A.guided_yoy > A.reported_yoy, np.nan)

    A["raise"] = np.where(A.raise_fy.notna(), A.raise_fy, A.raise_accel)
    A["raise_basis"] = np.where(A.raise_fy.notna(), "full-year guide raised vs prior full-year guide",
                         np.where(A.raise_accel.notna(), "next-quarter guide implies faster y/y than reported", "no raise test available"))
    A["beat_and_raise"] = np.where(A.beat.notna() & A["raise"].notna(), (A.beat == 1) & (A["raise"] == 1), np.nan)
    A = A.sort_values(["cik", "reported_q"])
    A.to_pickle("out/br_quarters.pkl")
    return A

def flag(A):
    rows = []
    for cik, g in A.dropna(subset=["beat_and_raise"]).groupby("cik"):
        g = g.sort_values("reported_q")
        last2 = g.tail(2)
        consec = len(last2) == 2 and (last2.reported_q.iloc[1] - last2.reported_q.iloc[0]).n == 1
        streak = 0
        for v in g.beat_and_raise.values[::-1]:
            if v == 1: streak += 1
            else: break
        rows.append(dict(cik=cik, latest_scored_q=g.reported_q.iloc[-1], scored_quarters=len(g), br_streak=streak,
                         two_consecutive=bool(consec and last2.beat_and_raise.sum() == 2),
                         last_beat=g.beat.iloc[-1], last_raise=g["raise"].iloc[-1],
                         last_beat_pct=g.beat_pct.iloc[-1], last_raise_basis=g.raise_basis.iloc[-1],
                         last_guide_kind=g.guide_kind.iloc[-1]))
    return pd.DataFrame(rows)

if __name__ == "__main__":
    A = build(); F = flag(A); F.to_pickle("out/br_flag.pkl")
    print(f"release-quarters scored: {len(A):,} | filers {A.cik.nunique():,}")
    print(f"  beat test available: {int(A.beat.notna().sum()):,} | raise test: {int(A['raise'].notna().sum()):,} | both: {int(A.beat_and_raise.notna().sum()):,}")
    print("  raise basis:", A.raise_basis.value_counts().to_dict())
    print("  guide kind:", A.guide_kind.value_counts().to_dict())
    print(f"  guides rejected as implausible vs reported revenue: {int(A.guide_rejected.sum()):,}")
    b = A.dropna(subset=["beat_pct"]).beat_pct
    print(f"  beat% distribution after the guard: p5 {b.quantile(.05):+.1%}, median {b.median():+.1%}, p95 {b.quantile(.95):+.1%}")
    print(f"\nfilers with at least one fully scored quarter: {len(F):,}")
    print(f"  TWO CONSECUTIVE beat-and-raise: {int(F.two_consecutive.sum()):,}")
    print("  streak:", F.br_streak.value_counts().sort_index().to_dict())
