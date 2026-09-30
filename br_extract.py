"""Extract forward guidance from each earnings release in the RPO universe.

Only guidance is read here. The ACTUAL revenue comes from the tier-1 XBRL panel, which is already
validated -- parsing headline figures out of press releases would add a second source of error for
a number we already hold.

Regex first (guidance_generic), which read ~79% of guides in the semis run. A release goes to the
model queue only when the deterministic guide_text_present() test says a revenue guide is in the
text and no pattern could read it -- so releases that genuinely guide nothing cost nothing.

Checkpointed per release; rerun to resume.
"""
import edgar, earnings_docs as E, guidance_generic as GG, pandas as pd, json, os, time, re

CKPT = "out/br_guide_ckpt.jsonl"
KEYS = ("revenue_low", "revenue_mid", "revenue_high", "revenue_pm_abs",
        "fy_revenue_low", "fy_revenue_mid", "fy_revenue_high", "fy_revenue_pm_abs")

def done_set():
    if not os.path.exists(CKPT): return set()
    s = set()
    for line in open(CKPT):
        try: s.add(json.loads(line)["accn"])
        except Exception: pass
    return s

def one(r):
    x = E.exhibits(int(r.cik), r.accn)
    txt = x.get("EX-99.1") or ("\n".join(x.values()) if x else "")
    if not txt and r.primary:
        try: txt = E.to_lines(edgar.get(edgar.doc_url(int(r.cik), r.accn, r.primary)))
        except Exception: txt = ""
    if not txt: return dict(status="no text")
    g, window, ok = GG.read(txt)
    rec = {k: g.get(k) for k in KEYS if g.get(k) is not None}
    present = GG.guide_text_present(txt)
    rec["status"] = "regex" if rec else ("needs model" if present else "no guidance in release")
    if rec["status"] == "needs model": rec["model_text"] = GG.model_text(txt, 1800)
    return rec

if __name__ == "__main__":
    R = pd.read_pickle("out/br_releases.pkl")
    D = done_set(); todo = R[~R.accn.isin(D)]
    print(f"releases {len(R):,} | done {len(D):,} | to do {len(todo):,}", flush=True)
    f = open(CKPT, "a"); t0 = time.time()
    for i, r in enumerate(todo.itertuples()):
        try: rec = one(r)
        except Exception as e: rec = dict(status=f"error: {type(e).__name__}")
        rec.update(cik=int(r.cik), accn=r.accn, filed=r.filed, form=r.form)
        f.write(json.dumps(rec) + "\n"); f.flush()
        if (i + 1) % 250 == 0:
            el = time.time() - t0
            print(f"  {i+1}/{len(todo)} | {el/(i+1):.2f}s each | eta {(len(todo)-i-1)*el/(i+1)/60:.0f} min", flush=True)
    f.close()
    rows = [json.loads(l) for l in open(CKPT)]
    G = pd.DataFrame(rows).drop_duplicates("accn")
    G.to_pickle("out/br_guidance.pkl")
    print("\nstatus:", G.status.value_counts().to_dict())
    print("releases with a readable revenue guide:", int(G.status.eq("regex").sum()))
