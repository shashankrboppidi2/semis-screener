"""Customers stage 2: validated model answers (Haiku, Sonnet overrides) -> out/{T}_customers.pkl, first reported by filing date."""
import json, sys, pandas as pd, customers_assemble as CA, edgar
A = json.load(open("queue/s2/accepted.json")); S = {}
for l in open("queue/s2/sonnet.out.jsonl"): x = json.loads(l); S[x["id"]] = x
for t in sys.argv[1:]:
    cik = json.load(open(f"config/{t}.json"))["cik"]; j, rows = edgar.submissions(cik); filed = {r["accessionNumber"]: r["filingDate"] for r in rows}
    fin = pd.read_pickle(f"out/{t}_fin.pkl"); cal = sorted(set(pd.to_datetime(fin[fin.duration_months.isin([3, 12])].period_end)))
    res = {k.split("|")[1]: v for k, v in A.items() if k.startswith(f"customers_{t}|")}; res.update({i: v for i, v in S.items() if v["task"] == f"customers_{t}"})
    d = CA.assemble(f"queue/customers_{t}.jsonl", res, cal, 12, filed); nn = []
    for i, v in res.items():
        for p in v["output"].get("none_over_10pct_periods", []):
            k = CA.period_key(p, 12)
            if not k: continue
            approx = pd.Timestamp(year=k[0], month=12, day=28) - pd.DateOffset(months=3 * (4 - k[1])); pe = min(cal, key=lambda c: abs((c - approx).days))
            if abs((pe - approx).days) <= 45: nn.append(dict(accn=i, filed=filed[i], period_end=pe, duration=k[2], customer="none >= 10%", type="none", pct=0.0, is_floor=False, model=v["model"]))
    d = pd.concat([d, pd.DataFrame(nn)]) if nn else d
    d = d.sort_values("filed").drop_duplicates(["period_end", "duration", "customer"]).sort_values(["period_end", "duration", "customer"])
    d.to_pickle(f"out/{t}_customers.pkl")
    print(t, len(d), "rows,", d.period_end.nunique(), "periods | models:", d.model.value_counts().to_dict(), "| floor flags:", int(d.is_floor.sum()))
