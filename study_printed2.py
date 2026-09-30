"""Was the segment revenue actually printed in the earnings release?

Numeric, not textual: every number in the release is parsed to a float, and a segment figure
counts as printed if some number in the text matches it within a tolerance, at any of the
scalings a filer uses (millions, thousands, billions). Releases round -- '$2.56 billion' for
2,564 million -- so an exact string test produces false negatives; the tolerance is set to the
coarsest rounding a release plausibly uses (3 significant figures).
"""
import pandas as pd, numpy as np, re, os, json, earnings_docs as E
SQ = pd.read_pickle("out/study_segment_quarters.pkl")
EV = pd.read_pickle("out/study_events.pkl")
NUM = re.compile(r"\(?\d[\d,]*(?:\.\d+)?\)?")
def floats(txt):
    out = set()
    for m in NUM.finditer(txt):
        try: out.add(float(m.group(0).strip("()").replace(",", "")))
        except ValueError: pass
    return sorted(out)
def hit(x, arr):
    for s in (1.0, 1e-3, 1e3):            # millions as printed, billions, thousands
        y = x * s
        if y == 0: continue
        tol = max(abs(y) * 0.006, abs(y) * 5e-3, 0.011 if s == 1e-3 else 0.6)
        i = np.searchsorted(arr, y - tol)
        if i < len(arr) and arr[i] <= y + tol: return True
    return False
rows = []
for t, g in EV.groupby("ticker"):
    if not os.path.exists(f"out/{t}_earn.pkl"): continue
    cik = json.load(open(f"config/{t}.json"))["cik"]
    H = pd.read_pickle(f"out/{t}_earn.pkl")["H"].copy(); H["filed"] = pd.to_datetime(H.filed)
    acc = dict(zip(H.filed, H.accn))
    for _, r in g.iterrows():
        a = acc.get(r.release)
        if not a: rows.append(dict(ticker=t, period_end=r.period_end, printed=np.nan, note="no release exhibit")); continue
        try: arr = np.array(floats("\n".join(E.exhibits(cik, a).values())))
        except Exception as e: rows.append(dict(ticker=t, period_end=r.period_end, printed=np.nan, note=str(e)[:40])); continue
        v = SQ[(SQ.ticker == t) & (SQ.period_end == r.period_end)].rev.dropna().astype(float)
        if not len(v) or not len(arr): rows.append(dict(ticker=t, period_end=r.period_end, printed=np.nan, note="nothing to match")); continue
        n = sum(hit(x, arr) for x in v)
        rows.append(dict(ticker=t, period_end=r.period_end, printed=n / len(v), n_seg=len(v), note=f"{n}/{len(v)}"))
d = pd.DataFrame(rows); d.to_pickle("out/study_printed.pkl")
ok = d[d.printed.notna()]
print("quarters checked:", len(ok), "| mean share of segment figures found in the release: %.2f" % ok.printed.mean())
print("quarters with at least 80 pct printed: %.2f" % (ok.printed >= .8).mean(), "| with none printed: %.2f" % (ok.printed == 0).mean())
print(ok.groupby("ticker").printed.agg(["mean", "size"]).round(2).to_string())
print("unchecked:", d[d.printed.isna()].note.value_counts().to_dict())
