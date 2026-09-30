"""Re-extract TSMC's technology-node mix and platform mix over the quarterly releases already identified.

Two corrections over the first pass:
  1. TSMC's node sentence mixes single nodes ('3-nanometer accounted for 15%') with a cumulative
     bucket ('advanced technologies, defined as 28-nanometer and more advanced, accounted for 63%').
     Treating the second as the 28nm node made shares sum above 100%. Each figure is now labelled
     with its basis, so a cumulative bucket is never added to the node shares.
  2. The platform slide's labels can appear before or after the slide title in the extracted text,
     so both sides are searched, bounded by the neighbouring slide titles, and a quarter is kept
     only when four or more platforms are found and they sum to 100% within rounding.
"""
import pandas as pd, re, earnings_docs as E, edgar
from tsmc2 import text   # older releases carry the text in the 6-K body itself, with no EX-99 exhibit
CIK = 1046179
NODE = re.compile(r"(\d+(?:/\d+)?(?:\.\d+)?)[\s-]?(nanometer|nm|micron|micrometer)\b", re.I)
PCT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:percent|%)")
CUM = re.compile(r"advanced technolog|defined as|and more advanced|and below", re.I)
PLAT = ("Smartphone", "HPC", "IoT", "Automotive", "DCE", "Others")

def tech_mix(t, pe):
    flat = re.sub(r"\s+", " ", t)
    sent = next((s for s in re.split(r"(?<=[.])\s", flat[:8000]) if re.search(r"of total wafer revenue", s, re.I)), None)
    if not sent: return pd.DataFrame()
    out = []
    for cl in re.split(r";|(?<=revenue),?\s+and\s+", sent):
        n = NODE.search(cl); p = PCT.search(cl)
        if not (n and p): continue
        v = float(p.group(1))
        if not 0 < v <= 100: continue
        unit = "nm" if n.group(2).lower().startswith("n") else "um"
        cum = bool(CUM.search(cl))
        out.append(dict(period_end=pe, node=f"{n.group(1)}{unit}" + (" and below" if cum else ""),
                        basis="cumulative" if cum else "node", pct_of_wafer_revenue=v))
    d = pd.DataFrame(out)
    return d.drop_duplicates(["period_end", "node"]) if len(d) else d

def platform_mix(t, pe):
    flat = re.sub(r"\s+", " ", t)
    titles = [(m.start(), m.end(), m.group(1)) for m in re.finditer(r"([1-4]Q\d\d|\b20\d\d\b) Revenue by Platform", flat)]
    q = f"{(pe.month - 1) // 3 + 1}Q{pe.strftime('%y')}"
    for k, (s0, e0, lab) in enumerate(titles):
        if lab != q: continue
        lo = titles[k - 1][1] if k else max(0, s0 - 400)
        hi = titles[k + 1][0] if k + 1 < len(titles) else min(len(flat), e0 + 400)
        for seg in (flat[e0:hi], flat[lo:s0]):                 # labels can sit on either side of the title
            got = {}
            for p in PLAT:
                m = re.search(rf"{p}\s*(\d+(?:\.\d+)?)\s?%", seg)
                if m: got[p] = float(m.group(1))
            if len(got) >= 4 and 97 <= sum(got.values()) <= 103:
                return pd.DataFrame([dict(period_end=pe, platform=x, pct_of_revenue=v) for x, v in got.items()])
    return pd.DataFrame()

if __name__ == "__main__":
    P = pd.read_pickle("out/TSM_q_printings.pkl"); P["filed"] = pd.to_datetime(P.filed); P["period_end"] = pd.to_datetime(P.period_end)
    rel = P.sort_values("period_end").groupby("accn").agg(filed=("filed", "first"), cur=("period_end", "max")).reset_index()
    _j, _rows = edgar.submissions(CIK); prim = {x["accessionNumber"]: x["primaryDocument"] for x in _rows}
    TK, PL = [], []
    for r in rel.itertuples():
        try: t = text(r.accn, prim.get(r.accn, ""))
        except Exception: continue
        a = tech_mix(t, r.cur)
        if len(a): TK.append(a.assign(filed=r.filed, accn=r.accn))
        b = platform_mix(t, r.cur)
        if len(b): PL.append(b.assign(filed=r.filed, accn=r.accn))
    tk = pd.concat(TK, ignore_index=True).sort_values("filed").drop_duplicates(["period_end", "node"])
    tk.to_pickle("out/TSM_tech_mix.pkl")
    s = tk[tk.basis == "node"].groupby("period_end").pct_of_wafer_revenue.sum()
    print(f"technology mix: {len(tk)} rows over {tk.period_end.nunique()} quarters | named-node shares sum to a median {s.median():.0f}%, max {s.max():.0f}%")
    print("quarters where named nodes sum above 100%:", int((s > 100.5).sum()))
    print("cumulative buckets held separately:", int((tk.basis == "cumulative").sum()))
    if PL:
        pl = pd.concat(PL, ignore_index=True).sort_values("filed").drop_duplicates(["period_end", "platform"])
        pl.to_pickle("out/TSM_platform_mix.pkl")
        print(f"platform mix: {pl.period_end.nunique()} quarters ({pl.period_end.min().date()} -> {pl.period_end.max().date()})")
    else:
        import os
        if os.path.exists("out/TSM_platform_mix.pkl"): os.remove("out/TSM_platform_mix.pkl")
        print("platform mix: none readable")
