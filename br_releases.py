"""Find the recent earnings releases for every filer in the RPO universe.

A two-consecutive-quarter beat-and-raise flag needs only the last handful of releases per company,
not the full history: the guide given two quarters ago, the actual that followed it, the guide given
one quarter ago, and the actual that followed that. Six releases give headroom for a missed quarter.

Checkpointed per filer, so the run resumes rather than restarting.
"""
import edgar, pandas as pd, numpy as np, json, os, sys, time

OUT = "out/br_releases.pkl"
CKPT = "out/br_releases_ckpt.jsonl"
N_REL = 6

def universe():
    P = pd.read_pickle("out/tier1_panel.pkl")
    ciks = sorted(P[P.rpo.notna()].cik.unique())
    L = pd.read_pickle("out/tier1_latest.pkl")
    gated = set(L[L.gated].cik)            # run these first so a usable result exists early
    return sorted(ciks, key=lambda c: (c not in gated, c))

def done_set():
    if not os.path.exists(CKPT): return set()
    s = set()
    for line in open(CKPT):
        try: s.add(json.loads(line)["cik"])
        except Exception: pass
    return s

def releases_for(cik):
    j, rows = edgar.submissions(cik)
    forms = ("8-K", "6-K")
    r = [x for x in rows if x["form"] in forms and x["filingDate"] >= "2024-01-01"]
    r = sorted(r, key=lambda x: x["filingDate"], reverse=True)
    out = []
    for x in r:
        # item 2.02 is "Results of Operations and Financial Condition" -- the earnings 8-K
        items = (x.get("items") or "")
        if x["form"] == "8-K" and "2.02" not in items: continue
        out.append(dict(cik=cik, accn=x["accessionNumber"], filed=x["filingDate"], form=x["form"],
                        primary=x.get("primaryDocument"), items=items, report=x.get("reportDate")))
        if len(out) >= N_REL: break
    return out

if __name__ == "__main__":
    U = universe(); D = done_set()
    todo = [c for c in U if int(c) not in D]
    print(f"universe {len(U)} filers | already done {len(D)} | to do {len(todo)}", flush=True)
    t0 = time.time(); f = open(CKPT, "a")
    for i, cik in enumerate(todo):
        try:
            rel = releases_for(int(cik))
            f.write(json.dumps({"cik": int(cik), "releases": rel}) + "\n"); f.flush()
        except Exception as e:
            f.write(json.dumps({"cik": int(cik), "releases": [], "err": f"{type(e).__name__}: {str(e)[:80]}"}) + "\n"); f.flush()
        if (i + 1) % 100 == 0:
            el = time.time() - t0
            print(f"  {i+1}/{len(todo)} | {el/ (i+1):.2f}s each | eta {(len(todo)-i-1)*el/(i+1)/60:.0f} min", flush=True)
    f.close()
    rows = []
    for line in open(CKPT):
        o = json.loads(line); rows += o.get("releases", [])
    R = pd.DataFrame(rows).drop_duplicates(["cik", "accn"])
    R.to_pickle(OUT)
    print(f"\nreleases found: {len(R):,} across {R.cik.nunique():,} filers | median per filer {R.groupby('cik').size().median():.0f}")
    print(R.form.value_counts().to_dict())
