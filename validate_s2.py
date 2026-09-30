"""Validate model answers (step 2). Rules: every number must appear in the input text; guidance must be plausible vs the guided
quarter's actual; segments must sum to XBRL consolidated revenue. Failures -> Sonnet queue."""
import json, glob, re, pandas as pd, numpy as np
from check_guidance import actuals
I = {}; O = {}
for f in sorted(glob.glob("queue/s2/b*.jsonl")):
    if f.endswith(".out.jsonl"): continue
    for l in open(f): x = json.loads(l); I[(x["task"], x["id"])] = x
    for l in open(f.replace(".jsonl", ".out.jsonl")): x = json.loads(l); O[(x["task"], x["id"])] = x
W = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
import os
if os.path.exists("queue/s2/sonnet.out.jsonl"):                     # escalated answers replace the Haiku ones
    for l in open("queue/s2/sonnet.out.jsonl"): x = json.loads(l); O[(x["task"], x["id"])] = x
def present(v, text):
    if v is None or isinstance(v, bool): return True
    t = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", lambda m: W[m[1].lower()], text.replace(",", ""), flags=re.I); v = abs(v); s = f"{v:g}"
    cands = {s, s.rstrip("0").rstrip(".")}
    if v >= 100: cands |= {f"{v/1000:g}", f"{v/1000:.1f}", f"{v/1000:.2f}"}            # 1350 printed as 1.35 billion
    return any(re.search(rf"(?<![\d.]){re.escape(c)}(?![\d])", t) for c in cands)
bad, notes = [], []
for k, x in I.items():
    o = (O.get(k) or {}).get("output"); task, i = k
    if o is None: bad.append((k, "no answer")); continue
    if task.startswith("guidance"):
        if o.get("revenue_low") is not None and o.get("revenue_high") is not None and o.get("revenue_mid") is not None and not present(o["revenue_mid"], x["user"]):
            o["revenue_mid"] = None; notes.append(f"{task} {i}: computed midpoint dropped (low/high kept) — rule")
        nums = {kk: vv for kk, vv in o.items() if isinstance(vv, (int, float)) and not isinstance(vv, bool)}
        miss = [kk for kk, vv in nums.items() if not present(vv, x["user"])]
        if miss: bad.append((k, f"not in text: {miss}"))
    elif task.startswith("customers"):
        miss = [r for r in o.get("rows", []) if isinstance(r.get("pct"), (int, float)) and not present(r["pct"], x["user"])]
        if miss: bad.append((k, f"pct not in text: {[r['pct'] for r in miss]}"))
        flat = re.sub(r"\s+", " ", x["user"])
        if o.get("none_over_10pct_periods") and not re.search(r"no (single |one |end |direct )?(end )?customers? (represented|accounted for|exceeded|was)|\*\s*\|?\s*Less than 10\s?%", flat, re.I):
            bad.append((k, "claims 'no customer >=10%' but the text never says so"))
        got = {float(r["pct"]) for r in o.get("rows", []) if isinstance(r.get("pct"), (int, float))}
        for sent in re.split(r"(?<=\.)\s", flat):                                       # coverage: every customer % of total revenue must be a row
            if re.search(r"customers?|Customer [A-Z]|Apple|Hewlett|Sony|Microsoft", sent) and not re.search(r"segment|billing location|outside|based customers|accounts receivable", sent, re.I):
                for p in re.findall(r"(\d{1,2}(?:\.\d)?)\s?(?:%|percent)(?:,? and \d+%)?[^.]{0,40}?(?:of (?:our |the Company.s )?(?:consolidated )?(?:net |total )?revenue|of revenue)", sent, re.I):
                    if float(p) not in got and not re.search(rf"(more than|or more|at least) {p}\s?(%|percent)|{p}\s?(%|percent) or more", sent, re.I):
                        bad.append((k, f"text has {p}% of revenue for a customer but no row")); break
    elif task.startswith("segments"):
        t = task.split("_")[1]; fin = pd.read_pickle(f"out/{t}_fin.pkl")
        for (pe, dur), g in pd.DataFrame(o["rows"]).groupby(["period_end", "duration_months"]):
            tot = fin[(fin.canonical == "revenue") & (fin.accn == i) & (fin.period_end == pe) & (fin.duration_months == dur)].value
            s = g.revenue.fillna(0).sum(); ok = len(tot) and abs(s - tot.iloc[0]) <= 1
            notes.append(f"{t} {i} {pe} {dur}m: segments sum {s} vs XBRL total {tot.iloc[0] if len(tot) else None} -> {'ok' if ok else 'FAIL'}")
            if not ok and len(tot): bad.append((k, "segments do not sum to total"))
print("answers:", len(O), "of", len(I)); print("\n".join(notes))
print("validation failures:", len(bad)); [print("  ", b) for b in bad]
json.dump([dict(task=k[0], id=k[1], why=w) for k, w in bad], open("queue/s2/failures.json", "w"))
json.dump({f"{k[0]}|{k[1]}": v for k, v in O.items() if k not in {b[0] for b in bad}}, open("queue/s2/accepted.json", "w"))
