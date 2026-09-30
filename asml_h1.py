"""ASML H1 net-system-sales breakdown (technology / end-use / new-used / geography) from the Q2 statutory interim report exhibit.
Cut deterministically, read by Haiku, accepted only if every block's rows sum to its printed Total row (validate_h1)."""
import re, json, pandas as pd, earnings_docs as E, llm_fallback as LF
LF.SYSTEM["h1"] = """You read note tables from ASML's half-year statutory interim report. Return ONLY JSON:
{"units_scale":"thousands"|"millions","blocks":[{"kind":"technology"|"end-use"|"new/used"|"geography","period_end":"YYYY-MM-DD","measure":"net system sales"|"total net sales","rows":[{"name":"<as printed>","units":<number or null>,"value":<number as printed>}],"total_value":<the printed Total row value or null>,"total_units":<printed Total units or null>}]}
One block per table per period (current AND prior-year six-month periods). Copy values exactly as printed (do not convert thousands). Parentheses = negative. Skip non-current assets columns. Never compute totals."""
def cut(t):
    L = t.splitlines(); keep = []
    for i, l in enumerate(L):
        if re.search(r"per technology|per end-use|new and used|geographic(al)? (region|reporting)", l, re.I):
            j = i
            while j < len(L) and j < i + 40:
                keep.append(L[j]); j += 1
                if re.match(r"^Total\b", L[j - 1]) and not any(re.match(r"^For the six-month period ended [A-Z]", x) for x in L[j:j + 2]): break
    out = list(dict.fromkeys(keep))
    return "\n".join(out)[:7000]
def run():
    d = pd.read_pickle("out/ASML_q.pkl"); d = d[pd.to_datetime(d.period_end).dt.month == 6]; items = []
    for _, r in d.iterrows():
        x = E.exhibits(937966, r.accn)
        for n, t in x.items():
            if re.search(r"Net system sales per technology|geographic(al)? (region|reporting)", t) and re.search(r"six-month period", t):
                c = cut(t)
                if c: items.append(dict(id=r.accn, text=f"[ASML Q2 {pd.Timestamp(r.period_end).year} release, {n}]\n" + c)); break
    LF.enqueue("h1_ASML", items); print(len(items), "H1 notes queued, ~%d tokens" % sum(LF.approx_tokens(i["text"]) for i in items))
if __name__ == "__main__": run()
