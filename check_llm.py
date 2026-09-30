import json, re, pandas as pd, duckdb, llm_fallback as LF, sys
tag = sys.argv[1] if len(sys.argv) > 1 else ""
req = {json.loads(l)["id"]: json.loads(l) for l in open("queue/customers.jsonl")}
res = LF.results("customers")
if tag:  # merge escalated answers
    for k, v in LF.results("customers_sonnet").items(): res[k] = v
g = duckdb.connect("../nvda/db/nvda.duckdb", read_only=True).execute("select filing_id as accn, value from int.filing_fact_dated where section='customer_concentration'").df()
gold = g.groupby("accn").value.apply(lambda v: sorted({float(x) for x in v if x >= 10})).to_dict()
rows = []
for i, r in req.items():
    o = res.get(i, {}).get("output") or {}; text = r["user"]
    vals = [float(x["pct"]) for x in o.get("rows", []) if isinstance(x.get("pct"), (int, float))]
    in_text = all(re.search(r"(?<![\d.])" + re.escape(("%g" % v)) + r"\s?%", text) for v in vals)
    sane = all(10 <= v <= 100 for v in vals) and all(x.get("type") in ("direct", "indirect", "combined") for x in o.get("rows", []))
    expects = bool(re.search(r"\d{1,2}(?:\.\d)?\s?% of (our )?total revenue", text)) and not re.search(r"more than 10% of total revenue", text)
    nonempty = bool(vals) or bool(o.get("none_over_10pct_periods"))
    rows.append(dict(id=i, model=res.get(i, {}).get("model"), vals=sorted(set(vals)), valid=bool(o) and in_text and sane and (nonempty or not expects), gold=gold.get(i)))
d = pd.DataFrame(rows); d["has_gold"] = d.gold.notna()
d["exact"] = [set(a) == set(b) if isinstance(b, list) else None for a, b in zip(d.vals, d.gold)]
print("responses", len(res), "| valid", d.valid.mean().round(3), "| by model", d.model.value_counts().to_dict())
s = d[d.has_gold]; print(f"vs gold ({len(s)} filings with gold): exact set match {s.exact.mean():.3f}")
print(s[~s.exact.astype(bool)][["id", "model", "vals", "gold", "valid"]].to_string())
print("invalid (-> escalate):", d[~d.valid].id.tolist())
d.to_pickle("llm_customers_check.pkl")
