"""Validate the step-4 model answers and merge every accepted answer (s2, s3, s4) into out/model_answers.json.
Rules: exactly one answer per queued item; every number must appear in the text the model was given; a midpoint that is not
printed is dropped (low/high kept); customer answers must not invent a 'no customer >= 10%' claim."""
import json, glob, os, re, sys
W = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
def printed(v, text):
    if v is None or isinstance(v, bool): return True
    t = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", lambda m: W[m[1].lower()], text.replace(",", ""), flags=re.I)
    v = abs(v); s = str(int(v)) if float(v).is_integer() else f"{v}".rstrip("0")
    cands = {s}
    if v >= 100: cands |= {f"{v/1000:g}", f"{v/1000:.1f}", f"{v/1000:.2f}"}
    if v < 10: cands |= {f"{v*1000:g}"}
    return any(re.search(rf"(?<![\d.]){re.escape(c)}(?![\d])", t) for c in cands)
def run(kind):
    I, O, bad, acc = {}, {}, [], {}
    for p in sorted(glob.glob(f"queue/s4_{kind}/b*.jsonl")):
        if ".out." in p: continue
        for l in open(p):
            x = json.loads(l); I[(x["task"], x["id"])] = x
        op = p.replace(".jsonl", ".out.jsonl")
        if not os.path.exists(op): bad.append((os.path.basename(p), "no output file")); continue
        for l in open(op):
            if l.strip():
                x = json.loads(l); O[(x["task"], x["id"])] = x
    for k, x in I.items():
        o = (O.get(k) or {}).get("output")
        if o is None: bad.append((k, "no answer")); continue
        txt = x["user"]
        if kind == "guidance":
            # a number the release does not print is dropped (the model derived it, e.g. +/-1.5% from a range); the printed fields stay.
            miss = [kk for kk, vv in o.items() if isinstance(vv, (int, float)) and not isinstance(vv, bool) and not printed(vv, txt)]
            for kk in miss: o[kk] = None
            o["dropped_unprinted"] = miss
            if not any(str(kk).startswith("revenue") and vv not in (None, [], False) for kk, vv in o.items()) and not o.get("no_guidance"):
                bad.append((k, f"no printed revenue figure survived (dropped {miss})")); continue
        else:
            miss = [r["pct"] for r in o.get("rows", []) if isinstance(r.get("pct"), (int, float)) and not printed(r["pct"], txt)]
            flat = re.sub(r"\s+", " ", txt)
            if miss: bad.append((k, f"pct not in text: {miss[:3]}")); continue
            if o.get("none_over_10pct_periods") and not re.search(r"no (single |one |end |direct )?(end )?customers? (represented|accounted for|exceeded|was)|\*\s*\|?\s*Less than 10\s?%", flat, re.I):
                o["none_over_10pct_periods"] = []
        acc[f"{k[0]}|{k[1]}"] = dict(O[k], output=o)
    return I, O, acc, bad
if __name__ == "__main__":
    merged = {}
    for f in ("queue/s2/accepted.json",):
        if os.path.exists(f): merged.update(json.load(open(f)))
    for f in ("queue/s2/sonnet.out.jsonl", "queue/s3/sonnet.out.jsonl"):
        if os.path.exists(f):
            for l in open(f):
                x = json.loads(l); merged[f"{x['task']}|{x['id']}"] = x
    for l in (open("queue/s3/b0.out.jsonl") if os.path.exists("queue/s3/b0.out.jsonl") else []): pass
    for kind in sys.argv[1:] or ["guidance", "customers"]:
        I, O, acc, bad = run(kind)
        merged.update(acc)
        print(f"{kind}: {len(I)} queued, {len(O)} answered, {len(acc)} accepted, {len(bad)} rejected")
        for b in bad[:12]: print("   ", b)
        json.dump([dict(task=k[0] if isinstance(k, tuple) else k, id=k[1] if isinstance(k, tuple) else "", why=w) for k, w in bad], open(f"queue/s4_{kind}/failures.json", "w"))
    json.dump(merged, open("out/model_answers.json", "w"))
    print("merged model answers:", len(merged))
