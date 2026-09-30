"""Guides read by regex but implausible (guided-quarter actual outside +/-20% of the implied midpoint) are re-read by the model.
Also queues releases where no pattern matched but the release does contain a guidance cue."""
import json, sys, pandas as pd, os, edgar, earnings_docs as E, guidance_generic as GG, llm_fallback as LF
for t in sys.argv[1:]:
    cfg = json.load(open(f"config/{t}.json")); cik = cfg["cik"]; items, seen = [], set()
    flagged = set()
    if os.path.exists(f"out/{t}_guid_check.pkl"):
        c = pd.read_pickle(f"out/{t}_guid_check.pkl"); flagged = set(c[c.status == "CHECK"].accn)
    G = pd.read_pickle(f"out/{t}_guid.pkl") if cfg.get("filer_type") == "FPI" else pd.read_pickle(f"out/{t}_earn.pkl")["G"]
    CH = {a: c_ for c_ in cfg.get("cik_chain", [cik]) for a in [x["accessionNumber"] for x in edgar.submissions(c_)[1]]} if len(cfg.get("cik_chain", [cik])) > 1 else {}
    for _, r in G.iterrows():
        unread = not any(str(k).startswith("revenue") and pd.notna(v) for k, v in r.items())
        if not (unread or r.accn in flagged) or r.accn in seen: continue
        x = E.exhibits(CH.get(r.accn, cik), r.accn); full = "\n".join(x.get(k, "") for k in sorted(x))
        if unread and not GG.guide_text_present(full):
            continue                                  # no guidance cue anywhere in the release: recorded as 'no guide given'
        items.append(dict(id=r.accn, text=GG.model_text(full))); seen.add(r.accn)
    LF.enqueue(f"guidance_{t}", items, system=LF.SYSTEM["guidance_eur"] if cfg.get("currency") == "EUR" else None)
    print(t, len(items), "releases queued for the model (%d flagged as implausible, %d unread) ~%d tokens" % (len(flagged & seen), len(seen) - len(flagged & seen), sum(LF.approx_tokens(i["text"]) for i in items)))
