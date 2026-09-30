"""Generic XBRL stage for one ticker: financials + segment facts + add-up validation. Prints the member list for config drafting."""
import re, edgar, xbrl_segments as S, xbrl_financials as XF, validators as V, pandas as pd, json, sys, os
t = sys.argv[1]; cfg = json.load(open(f"config/{t}.json")); cik = cfg["cik"]; start = cfg.get("start_period", "2010-04-01")
CHAIN = cfg.get("cik_chain", [cik])          # predecessor registrants: same business, new CIK after a redomicile
fil = []
for c_ in CHAIN:
    _j, _rows = edgar.submissions(c_)
    fil += [dict(x, cik=c_) for x in _rows if x["form"] in ("10-Q", "10-K", "20-F") and x["filingDate"] >= "2010-01-01"]
fil = sorted(fil, key=lambda r: r["filingDate"]); j, rows = edgar.submissions(cik)
if not fil:                                  # e.g. SKHY: registered, but no 10-Q/10-K/20-F filed yet; picked up once one is
    print(t, "no 10-Q/10-K/20-F filings yet - nothing to parse; existing out/ files left as they are"); sys.exit(0)
seg = pd.concat([S.parse(r["cik"], r["accessionNumber"]).assign(filed=pd.Timestamp(r["filingDate"]), form=r["form"], cik=r["cik"]) for r in fil], ignore_index=True)
if not len(seg) or "period_end" not in seg.columns:   # no dimensional facts at all: a single-segment filer, or an IFRS filer with no segment tags
    seg = pd.DataFrame(columns=["accn", "concept", "metric", "period_end", "duration_months", "axis", "members", "raw_members", "value", "ctx", "filed", "form", "cik"])
seg = seg[seg.period_end >= start] if len(seg) else seg
# names come from each filing's own label linkbase (xbrl_segments.all_member_labels); a config member_map is an override only.
# Series identity: members whose name matches after lowercasing and stripping non-alphanumerics are one series ('Datacenter' = 'Data Center'),
# displayed with the label from the most recent filing that used it.
# label normalisation (generic, not per-ticker): filers wrap segment names in boilerplate ('Reporting Segment Analog' = 'Analog')
# and use many names for the reconciling bucket. Normalising before keying keeps one continuous series per segment.
from run_xbrl_names import NORM, KEY
seg["ckey"] = seg.members.map(KEY)
# display name = the normalised label the filers used most often for that series (ties: the most recent)
_n = seg.assign(nm=seg.members.map(NORM)).sort_values("filed")
disp = _n.groupby("ckey").nm.agg(lambda s: s.value_counts().sort_values(ascending=False).index[0])
seg["name"] = seg.ckey.map(disp)
seg["name"] = [cfg.get("member_map", {}).get(m, cfg.get("member_map", {}).get(n, n)) for m, n in zip(seg.members, seg.name)]
seg.loc[seg.members.isin(cfg.get("_ignore_members", [])) | seg.name.map(lambda x: bool(S.SUBTOTAL.match(str(x)))), "name"] = None
# rule: a segment that appears only as product-by-segment pairs (Intel's Internet of Things Group in the FY2019 10-K) gets its
# segment-level figure from the sum of its own product lines — only when that filing has no segment-level fact for it, compared on
# the normalised series name so a different spelling cannot cause double counting.
if len(seg):
    comb = seg[seg["axis"] == "product_or_service+segment"].copy()
    if len(comb):
        comb["sname"] = [disp.get(KEY(x), NORM(x)) for x in comb.members.str.split("+").str[1]]
        bare = seg[seg["axis"] == "segment"]
        have = set(zip(bare.accn, bare.period_end, bare.duration_months, bare.metric, bare.name))
        g = comb.groupby(["accn", "period_end", "duration_months", "metric", "sname"], as_index=False).agg(
            value=("value", "sum"), filed=("filed", "first"), form=("form", "first"), cik=("cik", "first"), concept=("concept", "first"))
        keep = pd.Series([(a_, p_, d_, m_, n_) not in have for a_, p_, d_, m_, n_ in zip(g.accn, g.period_end, g.duration_months, g.metric, g.sname)], index=g.index)
        g = g[keep]
        if len(g):
            g = g.rename(columns={"sname": "name"}).assign(**{"axis": "segment", "members": g.sname, "raw_members": "(derived from product-by-segment rows)",
                                                              "ctx": None, "ckey": g.sname.map(KEY), "relabeled_from": None})
            seg = pd.concat([seg, g], ignore_index=True)
            print("derived", len(g), "segment-level values from product-by-segment rows")

# tag-swap guard (inline XBRL): the printed table row label overrules a conflicting member name (AMD 10-Qs 2022-24 rotate
# Data Center / Client / Gaming). Applied atomically per filing x period x duration x metric and only when the proposed names are a
# permutation of the existing ones (no duplicates), so a partial rotation can never collapse two segments into one.
MM = cfg.get("member_map", {}); BYKEY = dict(zip(disp.index, disp.values)); prim = {x["accessionNumber"]: x["primaryDocument"] for x in fil}; ciks = {x["accessionNumber"]: x["cik"] for x in fil}
seg["relabeled_from"] = None; nrel = set()
for acc in seg[seg["axis"] == "segment"].accn.unique():
    lab = S.ix_row_labels(ciks[acc], acc, prim[acc])
    if not lab: continue
    sub = seg[(seg.accn == acc) & (seg["axis"] == "segment")]
    for _, g in sub.groupby(["period_end", "duration_months", "metric"]):
        prop = {}
        for i in g.index:
            rl = lab.get((seg.at[i, "ctx"], round(seg.at[i, "value"], 3)))
            if not rl: continue
            rl = NORM(re.sub(r"\s*\(\d\)$", "", rl).strip()); rn = MM.get(rl) or BYKEY.get(KEY(rl))   # match on the normalised key, not the exact string
            if rn and seg.at[i, "name"] and rn != seg.at[i, "name"]: prop[i] = rn
        if not prop: continue
        after = [prop.get(i, seg.at[i, "name"]) for i in g.index]
        if len(set(after)) != len(after): continue        # not a bijection: leave the filing's own names alone
        for i, rn in prop.items(): seg.at[i, "relabeled_from"] = seg.at[i, "name"]; seg.at[i, "name"] = rn; nrel.add(acc)
print("tag-swap guard: relabeled", int(seg.relabeled_from.notna().sum()), "segment facts in", len(nrel), "filings")
fins = []
for c_ in CHAIN:
    f_, _ = XF.load(c_); fins.append(f_.assign(cik=c_))
fin = pd.concat(fins, ignore_index=True); fin = fin[fin.period_end >= start]
fin = fin.sort_values(["filed", "cik"]).drop_duplicates(["canonical", "period_end", "duration_months", "basis"])
allf = pd.concat([pd.read_pickle(f"{edgar.CACHE}/../all_facts_{c_}.pkl").assign(cik=c_) for c_ in CHAIN], ignore_index=True)
os.makedirs("out", exist_ok=True); fin.to_pickle(f"out/{t}_fin.pkl")
print(t, len(fil), "filings |", len(fin), "financial values |", len(seg), "dimensional facts |", edgar.STATS)
m = seg[seg["axis"].isin(["segment", "product_or_service"])]
print(m.groupby(["axis", "members"]).agg(first=("period_end", "min"), last=("period_end", "max"), n=("value", "size"), mapped=("name", lambda s: s.notna().all())).sort_values(["axis", "first"]).to_string())
if True:
    kept, rep = V.segment_addup(seg[seg.name.notna() | (seg["axis"] != "segment")], allf)
    print("add-up:", rep.issue.value_counts().to_dict() if len(rep) else {}); print(rep[rep.issue != "sum ok"].to_string() if len(rep) else "")
    kept.to_pickle(f"out/{t}_seg.pkl"); rep.to_pickle(f"out/{t}_addup.pkl")
