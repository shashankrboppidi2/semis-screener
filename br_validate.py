"""Validate model-read guidance the same way the rest of this pipeline validates model output:
every number must actually be printed in the text it was read from. A figure the model produced
that does not appear in the source is dropped, not trusted."""
import json, re, sys, os, pandas as pd, numpy as np

def printed_numbers(t):
    out = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", t):
        try: out.add(float(m.group(0).replace(",", "")))
        except ValueError: pass
    return sorted(out)

def is_printed(v, arr, scales=(1.0, 1e-3, 1e3)):
    if v is None or (isinstance(v, float) and np.isnan(v)): return True      # nothing to check
    for s in scales:
        x = v * s
        tol = max(abs(x) * 0.002, 0.01)
        i = np.searchsorted(arr, x - tol)
        if i < len(arr) and arr[i] <= x + tol: return True
    return False

def validate(out_files, in_files):
    IN = {}
    for f in in_files:
        for l in open(f):
            d = json.loads(l); IN[d["id"]] = d["text"]
    rows = []
    for f in out_files:
        if not os.path.exists(f): continue
        for l in open(f):
            l = l.strip()
            if not l: continue
            try: d = json.loads(l)
            except Exception: continue
            t = IN.get(d.get("id"), "")
            arr = np.array(printed_numbers(t))
            ok = {}
            for k in ("revenue_low", "revenue_high", "revenue_mid", "growth_low_pct", "growth_high_pct"):
                v = d.get(k)
                ok[k] = is_printed(v, arr) if v is not None else True
            d["all_printed"] = all(ok.values())
            d["dropped"] = [k for k, v in ok.items() if not v]
            rows.append(d)
    return pd.DataFrame(rows)

if __name__ == "__main__":
    outs = sys.argv[1].split(","); ins = sys.argv[2].split(",")
    V = validate(outs, ins)
    pos = V[~V.no_guidance.astype(bool)]
    print(f"rows {len(V)} | with guidance {len(pos)} | of those, every number printed in the source: {int(pos.all_printed.sum())} ({pos.all_printed.mean():.0%})")
    bad = pos[~pos.all_printed]
    if len(bad):
        print("\nfields not found in the source (these get dropped):")
        from collections import Counter
        print(Counter([k for r in bad.dropped for k in r]))
        print(bad.head(5)[["id", "revenue_low", "revenue_high", "revenue_mid", "dropped"]].to_string(index=False))
    V.to_pickle("out/br_model_validated.pkl")
