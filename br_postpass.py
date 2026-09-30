"""Second-tier guidance read over the collected release text, plus percentage-to-dollar conversion.

The fetch stage stores the outlook text for every release its first-tier patterns could not read.
This pass applies the market-wide patterns to that stored text -- no refetching -- and converts
growth-rate guidance into dollars against the year-ago quarter, so a filer that guides "revenue
growth of 7% to 12%" is comparable with one that guides "$1.02 to $1.08 billion".

What neither tier can read is left for the model, and what the stricter has_guide() says contains
no forward revenue guide is recorded as guiding nothing rather than sent anywhere.
"""
import json, pandas as pd, numpy as np, os, br_patterns as BP

def load_ckpt():
    rows = [json.loads(l) for l in open("out/br_guide_ckpt.jsonl")]
    return pd.DataFrame(rows).drop_duplicates("accn", keep="last")

def run():
    G = load_ckpt()
    G["tier"] = np.where(G.status == "regex", "tier1 semis patterns",
                 np.where(G.status == "no guidance in release", "no guidance", "unread"))
    need = G.status.eq("needs model") & G.model_text.notna()
    recs = []
    for i, t in zip(G.index[need], G.model_text[need]):
        r = BP.read_with_period(t)
        recs.append((i, r, BP.has_guide(t)))
    for i, r, hg in recs:
        if r:
            G.loc[i, "tier"] = "tier2 market patterns"
            for k, v in r.items(): G.loc[i, k if k != "period" else "guide_period"] = v
        else:
            # The model pass was built, run and then REJECTED. Two Haiku agents on the same slice
            # returned 6% and 54% guidance rates; spot-checking the 54% showed EPS guidance
            # ("GAAP EPS guidance to $4.83 to $4.93"), EBITDA guidance and reported actuals all
            # captured as revenue guidance, while the 6% agent rejected textbook revenue guidance
            # quoted verbatim in its own prompt. Neither direction is usable for a flag meant to
            # drive decisions, so guidance here is deterministic-only and coverage is lower.
            G.loc[i, "tier"] = "unreadable (no deterministic pattern)"
    G.to_pickle("out/br_guidance_enriched.pkl")
    print("guidance read by tier:"); print(G.tier.value_counts().to_string())
    if "basis" in G: print("\nbasis:", G.basis.value_counts().to_dict())
    if "guide_period" in G: print("period:", G.guide_period.value_counts().to_dict())
    return G

if __name__ == "__main__":
    G = run()
    print(f"\nreleases with a usable revenue guide: {int(G.tier.isin(['tier1 semis patterns','tier2 market patterns']).sum()):,} of {len(G):,}")
    print(f"left for the model: {int(G.tier.eq('for model').sum()):,}")
