"""Customer concentration for every ticker from the validated model answers -> out/{T}_customers.pkl (first reported by filing date)."""
import json, sys, os, pandas as pd, customers_assemble as CA, edgar
A = json.load(open("out/model_answers.json"))
for t in sys.argv[1:]:
    cfg = json.load(open(f"config/{t}.json")); cik = cfg["cik"]; fye = cfg.get("fye_month", 12)
    res = {k.split("|")[1]: v for k, v in A.items() if k.startswith(f"customers_{t}|")}
    if not res: print(t, "no customer answers"); continue
    filed = {}
    for c_ in cfg.get("cik_chain", [cik]):
        filed.update({r["accessionNumber"]: r["filingDate"] for r in edgar.submissions(c_)[1]})
    f = pd.read_pickle(f"out/{t}_fin.pkl"); cal = sorted(set(pd.to_datetime(f[f.duration_months.isin([3, 12])].period_end)))
    if not cal: print(t, "no calendar"); continue
    d = CA.assemble(f"queue/customers_{t}.jsonl", res, cal, fye, filed); nn = []
    for i, v in res.items():
        for p in v["output"].get("none_over_10pct_periods", []):
            k = CA.period_key(p, 12)
            if not k or i not in filed: continue
            approx = pd.Timestamp(year=k[0], month=fye, day=28) - pd.DateOffset(months=3 * (4 - k[1])); pe = min(cal, key=lambda c: abs((c - approx).days))
            if abs((pe - approx).days) <= 45: nn.append(dict(accn=i, filed=filed[i], period_end=pe, duration=k[2], customer="none >= 10%", type="none", pct=0.0, is_floor=False, model=v["model"]))
    d = pd.concat([d, pd.DataFrame(nn)]) if nn else d
    if not len(d): print(t, "no rows"); continue
    d = d.sort_values("filed").drop_duplicates(["period_end", "duration", "customer"]).sort_values(["period_end", "duration", "customer"])
    d.to_pickle(f"out/{t}_customers.pkl")
    print(t, len(d), "rows,", d.period_end.nunique(), "periods |", d.customer.nunique(), "distinct labels | floors:", int(d.is_floor.sum()))
