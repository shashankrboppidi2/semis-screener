"""Deterministic checks. Anything that fails is dropped or routed to the model queue — never silently kept."""
import pandas as pd, numpy as np, re
GEO = re.compile(r"^(country:|srt:.*Geograph)|^(europe|emea|americas?|asia|asia pacific|other asia pacific|other americas|rest of world|rest of asia|"
                 r"rest of europe.*|north america|latin america|united states|u\.s\.|usa|china|taiwan|japan|korea|south korea|singapore|india|germany|"
                 r"netherlands|israel|other countries|all other countries|domestic|international|foreign)$", re.I)
def _geo(name, raw): return bool(GEO.match(str(raw))) or bool(GEO.match(str(name).strip()))
def segment_addup(seg, fin, tol=1.0):
    """Per filing x period x duration x metric, in this order:
       1. drop a member whose value equals the consolidated total (a subtotal mis-tagged as a segment);
       2. if the rest still do not sum to the total, try removing geography-looking members - kept only if that makes it sum,
          so a real segment can never be silently dropped (NVIDIA FY2014-16 10-Ks hang revenue-by-country on the segment axis);
       3. record whether revenue segments sum to the filing's own consolidated revenue.
    Returns (kept, report)."""
    TOT = {m: fin[fin.canonical == m].drop_duplicates(["accn", "period_end", "duration_months"]).set_index(["accn", "period_end", "duration_months"]).value for m in ("revenue", "operating_income")}
    keep, rep, geo = [], [], []
    for (acc, pe, dur, met), g in seg[seg["axis"] == "segment"].groupby(["accn", "period_end", "duration_months", "metric"]):
        # dedupe on the XBRL member, not the display name: two different members can carry the same name (NVIDIA FY2014 10-K tags both
        # an 'All Other' segment and a corporate line that equals the consolidated total), and name-deduping would drop the real one.
        g = g.drop_duplicates("raw_members"); total = TOT[met].get((acc, pe, dur)); fits = lambda x: abs(x - total) <= max(tol, 0.001 * abs(total))
        if total is not None and len(g) > 1:
            bad = g[(g.value - total).abs() <= tol]
            if len(bad) and not fits(g.value.sum()):
                g = g.drop(bad.index)
                rep.append(dict(accn=acc, period_end=pe, duration=dur, metric=met, issue="member equals consolidated total — dropped", members=",".join(bad.name.astype(str))))
        # rule: some filers tag a group subtotal as if it were a segment (Intel's 'Total Intel Products' alongside CCPG / DCAI).
        # Drop the one member whose removal makes the rest sum to the consolidated total; ties prefer a name starting with 'Total'.
        if total is not None and len(g) > 2 and not fits(g.value.sum()):
            singles = [i for i in g.index if fits(g.value.sum() - g.at[i, "value"])]
            cand = []
            if singles:       # several members may each reconcile on their own: drop exactly one, preferring a 'Total ...' label
                cand = [sorted(singles, key=lambda i: (not str(g.at[i, "name"]).lower().startswith("total"), -abs(g.at[i, "value"])))[0]]
            elif len(g) >= 4:  # otherwise a roll-up and a corporate line may both need dropping; never leave fewer than two segments
                import itertools
                for i, j in itertools.combinations(list(g.index), 2):
                    if fits(g.value.sum() - g.at[i, "value"] - g.at[j, "value"]): cand = [i, j]; break
            if cand:
                pick = cand
                rep.append(dict(accn=acc, period_end=pe, duration=dur, metric=met, issue="subtotal member dropped (its removal reconciles the segments)", members=",".join(str(g.at[i, "name"]) for i in pick)))
                g = g.drop(index=pick)
        if total is not None and len(g) > 1 and not fits(g.value.sum()):
            ng = g[[not _geo(n, r) for n, r in zip(g.name, g.raw_members)]]
            if len(ng) and len(ng) < len(g) and fits(ng.value.sum()):
                moved = g.drop(ng.index).copy(); moved["axis"] = "geography (tagged on segment axis)"; geo.append(moved)
                rep.append(dict(accn=acc, period_end=pe, duration=dur, metric=met, issue="geography breakdown tagged on the segment axis — separated", members=",".join(moved.name.astype(str))))
                g = ng
        if met == "revenue" and total is not None and len(g) > 1:
            g = g.groupby("name", as_index=False, dropna=False).agg({**{c: "first" for c in g.columns if c != "value"}, "value": "sum"})   # members sharing a name are one line
            rep.append(dict(accn=acc, period_end=pe, duration=dur, metric=met, issue="sum ok" if fits(g.value.sum()) else f"sum {g.value.sum():.1f} != total {total:.1f}", members=",".join(g.name.astype(str))))
        keep.append(g)
    kept = pd.concat(keep + geo + [seg[seg["axis"] != "segment"]]) if keep else seg
    return kept, pd.DataFrame(rep)
