"""ASML annual revenue breakdown (technology, end-use, new/used, geography) from every 20-F XBRL instance. Deterministic."""
import edgar, xbrl_segments as S, pandas as pd, tables as T
j, rows = edgar.submissions(937966)
f20 = sorted([r for r in rows if r["form"] in ("20-F", "20-F/A")], key=lambda r: r["filingDate"])
parts = []
for r in f20:
    p = S.parse(937966, r["accessionNumber"])
    if len(p): parts.append(p.assign(filed=pd.Timestamp(r["filingDate"]), form=r["form"]))
b = pd.concat(parts, ignore_index=True); b = b[(b.metric == "revenue") & (b.duration_months == 12)]
KIND = lambda a, m: ("geography" if a == "geography" else "end-use" if "Logic" in m or "Memory" in m else "new/used" if "Systems" in m else
                     "product vs service" if m in ("Product", "Service And Field Options") else "technology")
b["kind"] = [KIND(a, m) for a, m in zip(b["axis"], b.members)]; b["name"] = b.members.str.replace("+Product", "", regex=False).str.replace("Product+", "", regex=False)
b["name"] = b.name.str.replace("Logic+", "", regex=False).str.replace("Memory+", "", regex=False).where(~b.members.str.contains("Logic|Memory"), b.members.str.split("+").str[0])
M = __import__("json").load(open("config/ASML.json"))["breakdown_map"]; b["name"] = b.name.map(lambda x: M.get(x, x))
b.loc[b.name == "Service And Field Options", "kind"] = "product vs service"
b.loc[b.name.str.contains("Largest Customer"), "kind"] = "customer"
# one scheme per (kind, year): members only from the FIRST filing that reports that kind for that year (schemes change between 20-Fs)
b["year"] = b.period_end.dt.year
firstacc = b.sort_values("filed").groupby(["kind", "year"]).accn.first()
b_first = b[[firstacc.get((k, y)) == a for k, y, a in zip(b.kind, b.year, b.accn)]]
ann_first = b_first.drop_duplicates(["kind", "name", "year"]).rename(columns={"value": "first", "accn": "first_accn", "filed": "first_filed"})
lat = b.sort_values("filed").groupby(["kind", "year"]).accn.last()
b_lat = b[[lat.get((k, y)) == a for k, y, a in zip(b.kind, b.year, b.accn)]].drop_duplicates(["kind", "name", "year"])
ann = ann_first.merge(b_lat[["kind", "name", "year", "value", "accn", "filed"]].rename(columns={"value": "latest", "accn": "latest_accn", "filed": "latest_filed"}), on=["kind", "name", "year"], how="outer")
ann["period_end"] = pd.to_datetime(ann.year.astype(int).astype(str) + "-12-31"); ann.to_pickle("out/ASML_breakdown_annual.pkl")
print(len(f20), "20-Fs; with dimensional revenue:", len(parts), "| years:", ann.period_end.dt.year.min(), "-", ann.period_end.dt.year.max())
pv = ann.pivot_table(index=["kind", "name"], columns=ann.period_end.dt.year, values="first", aggfunc="first").round(0); print(pv.to_string())
# validation: each breakdown must sum to its total (geography & product/service -> total net sales; technology & end-use & new/used -> system sales)
# reference totals: the four quarterly results releases of that year (independent of the 20-F): total net sales and system sales
q = pd.read_pickle("out/ASML_q.pkl"); q["year"] = pd.to_datetime(q.period_end).dt.year
qs = q.groupby("year").agg(total=("revenue", "sum"), n=("revenue", "count"), system=("system_sales", "sum"), ns=("system_sales", "count"))
chk = []
for (kind, y), g in ann_first.groupby(["kind", "year"]):
    if kind == "customer": continue
    r = qs.loc[y] if y in qs.index else None
    ref = None if r is None else (r.total if r.n == 4 else None) if kind in ("geography", "product vs service") else (r.system if r.ns == 4 else None)
    sm = g["first"].sum(); tol = max(3, 0.003 * ref) if ref else 0
    chk.append(dict(kind=kind, year=y, sum=sm, ref=ref, status="ok" if ref and abs(sm - ref) <= tol else "no reference (release data incomplete)" if not ref else f"DIFF {sm - ref:+.0f}"))
c = pd.DataFrame(chk); c.to_pickle("out/ASML_breakdown_check.pkl"); print(c.groupby("kind").status.value_counts().to_string()); print(c[c.status.str.startswith("DIFF")].to_string())