"""Reporting tables per ticker (deterministic). Every value carries first-reported and latest printing plus its source rule.
Q4 rule (all dimensional series): Q4 = FY - 9M, first-reported from the first FY printing minus the first 9M printing,
latest from the latest FY minus the latest 9M. Applied per (dimension member, metric)."""
import pandas as pd, numpy as np, json, os

def fq(pe, fye_month=12):
    """fiscal (year, quarter) for a period end; 52/53-week ends a few days off month end snap to the nearest month end."""
    pe = pd.Timestamp(pe); a = pe + pd.offsets.MonthEnd(0); b = pe - pd.offsets.MonthEnd(1)
    me = a if abs((a - pe).days) <= abs((pe - b).days) else b
    m, y = me.month, me.year
    return (y if m <= fye_month else y + 1), ((m - fye_month - 1) % 12) // 3 + 1

def _vint(g):
    g = g.sort_values("filed")
    return pd.Series(dict(first=g.value.iloc[0], first_filed=g.filed.iloc[0], first_accn=g.accn.iloc[0],
                          latest=g.value.iloc[-1], latest_filed=g.filed.iloc[-1], latest_accn=g.accn.iloc[-1], printings=g.value.round(3).nunique()))

def dim_quarterly(df, key_cols, extra=None):
    """df: long facts with key_cols + metric, period_end, duration_months, value, filed, accn. Returns quarterly first/latest incl. derived Q4."""
    df = df.copy(); df["filed"] = pd.to_datetime(df.filed); df["period_end"] = pd.to_datetime(df.period_end)
    k = key_cols + ["metric"]; out = []
    q3 = df[df.duration_months == 3].groupby(k + ["period_end"]).apply(_vint, include_groups=False).reset_index(); q3["source"] = "reported 3M"
    out.append(q3)
    fy = df[df.duration_months == 12].groupby(k + ["period_end"]).apply(_vint, include_groups=False).reset_index()
    nm = df[df.duration_months == 9].groupby(k + ["period_end"]).apply(_vint, include_groups=False).reset_index()
    rows = []
    for _, r in fy.iterrows():
        m = nm
        for c in k: m = m[m[c] == r[c]]
        m = m[(r.period_end - m.period_end).dt.days.between(80, 100)]
        if not len(m): continue
        m = m.iloc[0]
        rows.append({**{c: r[c] for c in k}, "period_end": r.period_end, "first": r["first"] - m["first"], "first_filed": r.first_filed, "first_accn": r.first_accn,
                     "latest": r.latest - m.latest, "latest_filed": r.latest_filed, "latest_accn": r.latest_accn, "printings": max(r.printings, m.printings), "source": "derived Q4 = FY - 9M"})
    d = pd.DataFrame(rows)
    COLS = key_cols + ["metric", "period_end", "first", "first_filed", "first_accn", "latest", "latest_filed", "latest_accn", "printings", "source"]
    q3 = q3.reindex(columns=[c for c in COLS if c in q3.columns] + [c for c in COLS if c not in q3.columns])
    d = d.reindex(columns=q3.columns) if len(d) else pd.DataFrame(columns=q3.columns)
    allq = pd.concat([q3, d], ignore_index=True)
    # a reported 3M value beats a derived one for the same key (some filers tag Q4 directly)
    allq["pri"] = (allq.source != "reported 3M").astype(int)
    allq = allq.sort_values("pri").drop_duplicates(k + ["period_end"]).drop(columns="pri")
    return allq.sort_values(k + ["period_end"]).reset_index(drop=True)

def dim_annual(df, key_cols):
    df = df.copy(); df["filed"] = pd.to_datetime(df.filed); df["period_end"] = pd.to_datetime(df.period_end)
    return df[df.duration_months == 12].groupby(key_cols + ["metric", "period_end"]).apply(_vint, include_groups=False).reset_index()

def segments(t):
    """segment, sub-segment (product within segment) and geography series from the validated XBRL facts (+ model-read gaps)."""
    s = pd.read_pickle(f"out/{t}_seg.pkl"); s = s[s.value.notna()].copy()
    seg = s[(s["axis"] == "segment") & s.name.notna()].copy()
    A = json.load(open("queue/s2/accepted.json")) if os.path.exists("queue/s2/accepted.json") else {}   # model reads are not shipped
    add = []
    for k, v in A.items():                                   # validated model reads (AMD Q1 2022 Xilinx and comparatives)
        if k.startswith(f"segments_{t}|"):
            acc = k.split("|")[1]; filed = seg[seg.accn == acc].filed.min()
            for r in v["output"]["rows"]:
                for m in ("revenue", "operating_income"):
                    if r.get(m) is not None:
                        import run_xbrl_names as RN                       # match the printed row label to an existing series
                        nm = RN.match(r["segment"], seg)
                        add.append(dict(accn=acc, filed=filed, period_end=pd.Timestamp(r["period_end"]), duration_months=r["duration_months"], metric=m, name=nm, value=float(r[m]), model="haiku (validated)"))
    if add:
        a = pd.DataFrame(add)
        key = set(zip(seg.accn, seg.period_end, seg.duration_months, seg.metric, seg.name))
        a = a[[(x.accn, x.period_end, x.duration_months, x.metric, x.name) not in key for x in a.itertuples()]]
        seg = pd.concat([seg, a], ignore_index=True)
    agg = {c: "first" for c in seg.columns if c not in ("value",)}
    seg = seg.groupby(["accn", "period_end", "duration_months", "metric", "name"], as_index=False, dropna=False).agg({**agg, "value": "sum"})
    sub = s[s["axis"] == "product_or_service+segment"].copy()
    sub["name"] = sub.members.str.split("+").str[0]; sub["parent"] = sub.members.str.split("+").str[1]
    # the parent member can differ between 10-Q and 10-K for the same product (AMD FY2025 10-K: Gaming within 'Gaming', 10-Qs: within
    # 'Client And Gaming'), so series key on the product; parent = the one used most often
    sub["parent"] = sub.name.map(sub.groupby("name").parent.agg(lambda x: x.value_counts().index[0]))
    geo = s[s["axis"] == "geography"].copy(); geo["name"] = geo.members
    return seg, sub, geo
