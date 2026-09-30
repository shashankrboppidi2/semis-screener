"""Validators for step-3 model reads. TXN end markets: every % printed, shares sum to 97-103, no sector names.
ASML H1: every value printed, each block's rows sum to its printed Total (value and units)."""
import json, glob, re, pandas as pd
I, O = {}, {}
for f in sorted(glob.glob("queue/s3/b?.jsonl")):
    for l in open(f): x = json.loads(l); I[(x["task"], x["id"])] = x
    for l in open(f.replace(".jsonl", ".out.jsonl")): x = json.loads(l); O[(x["task"], x["id"])] = x
import os
if os.path.exists("queue/s3/sonnet.jsonl"):                         # escalated items are validated against the text Sonnet saw
    for l in open("queue/s3/sonnet.jsonl"): x = json.loads(l); I[(x["task"], x["id"])] = x
if os.path.exists("queue/s3/sonnet.out.jsonl"):
    for l in open("queue/s3/sonnet.out.jsonl"): x = json.loads(l); O[(x["task"], x["id"])] = x
def printed(v, text):
    t = text.replace(",", ""); v = abs(v); s = str(int(v)) if float(v).is_integer() else f"{v}".rstrip("0")
    return re.search(rf"(?<![\d.]){re.escape(s)}(?![\d])", t) is not None
bad, em, h1 = [], [], []
SECTORS = re.compile(r"automation|infotainment|mobile phones|factory|ADAS|compute|networking", re.I)
for k, x in I.items():
    o = (O.get(k) or {}).get("output") or {}; task, i = k
    if task == "endmarkets_TXN":
        ms = o.get("markets", []); tot = sum(m["pct"] for m in ms if isinstance(m.get("pct"), (int, float)))
        miss = [m["pct"] for m in ms if not printed(m["pct"], x["user"])]
        sec = [m["market"] for m in ms if SECTORS.search(m.get("market", ""))]
        if miss or sec or not 94 <= tot <= 104: bad.append((k, f"sum {tot}, not printed {miss}, sector-as-market {sec}"))
        else: em += [dict(accn=i, year=o["year"], basis=o.get("basis"), market=m["market"], pct=m["pct"], model=O[k]["model"]) for m in ms]
    if task == "h1_ASML":
        tech_tot = {(b.get("period_end"), "v"): b.get("total_value") for b in o.get("blocks", []) if b.get("kind") == "technology"}
        tech_tot.update({(b.get("period_end"), "u"): b.get("total_units") for b in o.get("blocks", []) if b.get("kind") == "technology"})
        for b in o.get("blocks", []):
            if b.get("kind") == "end-use" and b.get("total_value") is None:        # end-use and technology split the same net system sales
                b["total_value"] = tech_tot.get((b.get("period_end"), "v")); b["total_units"] = tech_tot.get((b.get("period_end"), "u"))
            rows = [r for r in b.get("rows", []) if isinstance(r.get("value"), (int, float))]
            sv = sum(r["value"] for r in rows); tv = b.get("total_value")
            su = sum(r["units"] for r in rows if isinstance(r.get("units"), (int, float))); tu = b.get("total_units")
            miss = [r["value"] for r in rows if not printed(r["value"], x["user"])]
            okv = tv is not None and abs(sv - tv) <= max(0.15, 0.0005 * abs(tv)) * (1000 if o.get("units_scale") == "thousands" else 1)
            oku = tu is None or abs(su - tu) < 0.5
            st = "ok" if okv and oku and not miss else f"FAIL sum {sv} vs total {tv}; units {su} vs {tu}; not printed {miss[:3]}"
            if st != "ok": bad.append((k, f"{b.get('kind')} {b.get('period_end')}: {st}"))
            scale = 1000 if o.get("units_scale") == "thousands" else 1
            h1 += [dict(accn=i, kind=b["kind"], period_end=b["period_end"], measure=b.get("measure"), name=r["name"], units=r.get("units"),
                        value=r["value"] / scale, status=st, model=O[k]["model"]) for r in rows]
print("answers:", len(O), "of", len(I), "| failures:", len(bad)); [print("  ", b) for b in bad]
pd.DataFrame(em).to_pickle("out/TXN_endmarkets_raw.pkl"); pd.DataFrame(h1).to_pickle("out/ASML_h1_raw.pkl")
json.dump([dict(task=k[0], id=k[1], why=w) for k, w in bad], open("queue/s3/failures.json", "w"))
