"""Company-agnostic guidance reader: find the outlook sentences anywhere in the release, apply a pattern library, report what it could not read."""
import re
from earnings_extract import normalise, money
from earnings_docs import nums
BOILER = re.compile(r"forward-looking statements|safe harbor|Private Securities Litigation|risks and uncertainties|actual results", re.I)
NUMW = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
def windows(text):
    """every outlook-like sentence + the next 5 (a CEO quote often comes before the Outlook section)"""
    t = re.sub(r"\s*(±|\+/-|\+/–|plus/minus)\s*", " plus or minus ", re.sub(r"\s+", " ", text))
    t = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s?%", lambda m: NUMW[m[1].lower()] + "%", t, flags=re.I)
    sents = [x for x in re.split(r"(?<=[.!?])\s+|\s[•Ÿ·]\s?\|?\s*", t) if x.strip()]; out = []
    for i, s in enumerate(sents):
        if BOILER.search(s) or len(s) > 600: continue
        h = s if re.search(r"\b(revenue|revenues|net sales|sales)\b", s, re.I) else " ".join(sents[i:i + 3])   # 'TI expects: • Revenue: $3.31 – 3.59 billion'
        if re.search(r"\b(expects?|expected to be|guidance|outlook|forecast(?:ing|s|ed)?|anticipat(?:e|es|ed|ing)|project(?:s|ed|ing)?|targeting)\b", s, re.I) and re.search(r"\b(revenue|revenues|net sales|sales)\b", h, re.I) and re.search(r"\d|flat", h) \
           and not re.search(r"previously (expected|guided)|was (above|below|within|in line)|came in", s, re.I):
            out.append(normalise(" ".join(x for x in sents[i:i + 6] if not BOILER.search(x))))
    return out
def outlook_text(text):
    w = windows(text); return w[0] if w else ""
B = r"(billion|million)"
CUR = r"(?:\$|€|EUR ?)"
PATTERNS = [
 ("sales_range_cur", rf"(?:total )?net sales (?:to be )?between {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}? and {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("sales_around_cur", rf"(?:total )?net sales (?:of|at|expected)?\s?(?:around|about|approximately) {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2])}),
 ("gm_range", r"gross margin (?:of |to be )?between (\d+(?:\.\d+)?)\s?% and (\d+(?:\.\d+)?)\s?%", lambda m: {"gm_low": float(m[1]), "gm_high": float(m[2])}),
 ("gm_about", r"gross margin (?:in Q\d \d{4} )?(?:of |at )?(?:about|around|approximately) (\d+(?:\.\d+)?)\s?%", lambda m: {"gm_mid": float(m[1])}),
 ("rev_mid_pm_pct", rf"revenue[^.]{{0,40}}?(?:is expected to be|to be) (?:approximately )?\$(\d[\d,]*(?:\.\d+)?)\s*{B},? plus or minus (\d+(?:\.\d+)?)%", lambda m: {"revenue_mid": money(m[1], m[2]), "revenue_pm_pct": float(m[3])}),
 ("rev_mid_pm_abs", rf"revenue[^.]{{0,40}}?(?:is expected to be|to be) (?:approximately )?\$(\d[\d,]*(?:\.\d+)?)\s*{B},? plus or minus \$(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2]), "revenue_pm_abs": money(m[3], m[4])}),
 ("rev_range", rf"revenue (?:is expected to be |to be )?(?:in the range of|between) \$(\d[\d,]*(?:\.\d+)?)\s*{B}? (?:to|and) \$(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("rev_range_a_pm", rf"revenue(?:s)?[^.]{{0,40}}?in a range of {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B} plus or minus {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2]), "revenue_pm_abs": money(m[3], m[4])}),
 ("rev_range_a_to", rf"revenue(?:s)?[^.]{{0,40}}?in a range of {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}? (?:to|and) {CUR}?\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("rev_of_x_to_y", rf"revenue(?:s)? of {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}? (?:to|and) {CUR}?\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("rev_forecast_pm_abs", rf"(?:forecast\w*|expect\w*|anticipat\w*|project\w*)[^.]{{0,45}}?revenue(?:s)? (?:of|to be|at) (?:approximately |about |around )?{CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B},? plus or minus {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2]), "revenue_pm_abs": money(m[3], m[4])}),
 ("rev_forecast_of", rf"(?:forecast\w*|expect\w*|anticipat\w*|project\w*)[^.]{{0,45}}?revenue(?:s)? (?:of|to be|at) (?:approximately |about |around )?{CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2])}),
 ("rev_in_range_of", rf"revenue(?:s)?[^.]{{0,30}}?(?:in|within) the range of {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}? (?:to|and) {CUR}?\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("rev_between_cur", rf"revenue(?:s)? (?:is |are )?(?:expected to be |forecast to be )?between {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}? and {CUR}?\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("rev_table_range", rf"(?:total |net )?revenue[^|\n]{{0,30}}?\|?\s*{CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*(?:-|to|–)\s*{CUR}?\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[3]), "revenue_high": money(m[2], m[3])}),
 ("rev_guid_approx", rf"revenue guidance of (?:approximately|about|around) {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2])}),
 ("rev_expected_pm_pct", rf"(?:net |total )?revenue (?:is |are )?expected to be (?:approximately )?{CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B},? plus or minus (\d+(?:\.\d+)?)\s?%", lambda m: {"revenue_mid": money(m[1], m[2]), "revenue_pm_pct": float(m[3])}),
 ("rev_pm_abs_table", rf"(?:total |net )?revenue[^|\n]{{0,30}}?\|?\s*{CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B} plus or minus {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2]), "revenue_pm_abs": money(m[3], m[4])}),
 ("rev_approx_only", rf"(?:total |net )?revenue (?:is |are )?expected to be (?:approximately|about|around) {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2])}),
 ("gm_table_pair", r"gross margin \|?\s*(\d+(?:\.\d+)?)\s?% \|?\s*(\d+(?:\.\d+)?)\s?%", lambda m: {"gm_gaap": float(m[1]), "gm_nongaap": float(m[2])}),
 ("gm_approx", r"gross margin[^.|\n]{0,30}?(?:of |to be )?(?:approximately|about|around) (\d+(?:\.\d+)?)\s?%", lambda m: {"gm_mid": float(m[1])}),
 ("gm_range_to", r"gross margin (?:is |are )?expected to be (\d+(?:\.\d+)?)\s?% to (\d+(?:\.\d+)?)\s?%", lambda m: {"gm_low": float(m[1]), "gm_high": float(m[2])}),
 ("rev_colon_range", rf"revenue:?\s*{CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}?\s*(?:[–—-]|to)\s*{CUR}?\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("eps_colon_range", r"earnings per share:?\s*\$(\d+(?:\.\d+)?)\s*(?:[–—-]|to)\s*\$?(\d+(?:\.\d+)?)", lambda m: {"eps_low": float(m[1]), "eps_high": float(m[2])}),
 ("rev_qoq_range", r"revenue to (increase|grow|decrease|decline|be down|be up) (?:approximately )?(\d+(?:\.\d+)?)\s?%?\s?(?:[–—-]|to)\s?(\d+(?:\.\d+)?)\s?% sequentially", lambda m: {"revenue_qoq_low_pct": (-1 if m[1].lower() in ("decrease", "decline", "be down") else 1) * float(m[2]), "revenue_qoq_high_pct": (-1 if m[1].lower() in ("decrease", "decline", "be down") else 1) * float(m[3])}),
 ("rev_direction", r"revenue to be (flat to (?:slightly )?(?:down|up)|(?:down|up|flat)(?: slightly)?) (?:seasonally|sequentially)", lambda m: {"revenue_direction": m[1].lower()}),
 ("rev_range_cur", rf"(?:revenue|net sales|sales) (?:of |to be )?between {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}? and {CUR}?\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("rev_qoq_pm2", r"revenue to (increase|grow|decrease|decline) (?:by )?(?:approximately )?(\d+(?:\.\d+)?)%,? plus or minus (\d+(?:\.\d+)?)%,? sequentially", lambda m: {"revenue_qoq_pct": (-1 if m[1].lower() in ("decrease", "decline") else 1) * float(m[2]), "revenue_qoq_pm_pct": float(m[3])}),
 ("sales_range_cur2", rf"(?:total )?(?:net )?sales (?:of |to be |at )?between {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}? and {CUR}?\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_low": money(m[1], m[2] or m[4]), "revenue_high": money(m[3], m[4])}),
 ("sales_around_cur2", rf"(?:Q[1-4]|(?:first|second|third|fourth)[- ]quarter)[^.]{{0,40}}?(?:total )?(?:net )?sales (?:of |at |to be )?(?:around|about|approximately) {CUR}\s?(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"revenue_mid": money(m[1], m[2])}),
 ("rev_qoq_pm", r"revenue to (increase|grow|decrease|decline|be down|be up) (?:by )?(?:approximately )?(\d+(?:\.\d+)?)% sequentially,? plus or minus (\d+(?:\.\d+)?)%", lambda m: {"revenue_qoq_pct": (-1 if m[1].lower() in ("decrease", "decline", "be down") else 1) * float(m[2]), "revenue_qoq_pm_pct": float(m[3])}),
 ("rev_flat", r"revenue to be (?:approximately )?flat sequentially", lambda m: {"revenue_qoq_pct": 0.0}),
 ("eps_range", r"earnings per share (?:between|in the range of) \$(\d+(?:\.\d+)?) (?:and|to) \$(\d+(?:\.\d+)?)", lambda m: {"eps_low": float(m[1]), "eps_high": float(m[2])}),
 ("gm_nongaap", r"non-GAAP gross margin (?:is expected to be|to be|of) (?:approximately )?(\d+(?:\.\d+)?)%", lambda m: {"gm_nongaap": float(m[1])}),
 ("gm_both", r"GAAP and non-GAAP gross margins are expected to be (\d+(?:\.\d+)?)% and (\d+(?:\.\d+)?)%", lambda m: {"gm_gaap": float(m[1]), "gm_nongaap": float(m[2])}),
 ("gm_same", r"GAAP and non-GAAP gross margins are expected to be (\d+(?:\.\d+)?)%", lambda m: {"gm_gaap": float(m[1]), "gm_nongaap": float(m[1])}),
 ("opex_nongaap", rf"non-GAAP operating expenses (?:are expected to be|to be|of) (?:approximately )?\$(\d[\d,]*(?:\.\d+)?)\s*{B}", lambda m: {"opex_nongaap": money(m[1], m[2])}),
]
ANNUAL = re.compile(r"full[- ]year|for (the year )?20\d\d\b(?! (first|second|third|fourth)[- ]quarter)|20\d\d (total )?(net )?sales|annual|for 20\d\d,|in 20\d\d|20\d\d revenue", re.I)
HALF = re.compile(r"\bhalf\b|\bH[12]\b", re.I)
QTR = re.compile(r"\bQ[1-4]\b|(first|second|third|fourth)[- ]quarter|next quarter|the quarter", re.I)
def period_of(t, m):
    """rule: a guide's period is read from its own clause (text since the previous sentence break, up to the number)."""
    ctx = re.split(r"[.;•]\s|---", t[:m.start()])[-1][-160:] + t[m.start():m.start() + 40]
    last = lambda rx: max([x.end() for x in rx.finditer(ctx)] or [-1])      # the cue nearest the number decides
    q, h, a = last(QTR), last(HALF), last(ANNUAL)
    if max(q, h, a) < 0 or q > max(h, a): return ""
    return "h_" if h > a else "fy_"
def _apply(t):
    out = {}
    for name, rx, fn in PATTERNS:
        for m in re.finditer(rx, t, re.I):
            pre = period_of(t, m) if name.startswith(("sales", "rev")) else ""
            for k, v in fn(m).items(): out.setdefault(pre + k, v)
            if not pre: break          # first quarterly match wins; annual/half matches are kept under fy_/h_ and search continues
    return out
ROW = re.compile(r"^\s*(?:total |net |u\.s\. gaap )?revenue(?:s)?\b", re.I)
CUE = re.compile(r"outlook|guidance|expects?|business outlook|financial outlook", re.I)
UNIT = re.compile(r"\b(billion|million|bn|mm?)\b", re.I)
def table_guide(text):
    """Deterministic reader for the guidance TABLE most filers print ('Outlook ... Revenue | $8.10 Billion | +/- | $400 Million').
    A revenue row counts only when an outlook/guidance cue appears in the 12 lines above it, and the row is not a results row
    (results rows carry a prior-year comparison column, i.e. 3+ money cells with no +/- and no single unit word)."""
    L = [l for l in text.splitlines() if l.strip()]; out = {}
    for i, l in enumerate(L):
        if not ROW.match(l) or "|" not in l: continue
        ctx = " ".join(L[max(0, i - 12):i])
        # the ROW must look like a guide, not a results line: a currency symbol plus either a +/- marker or an inline unit word.
        # Results rows are bare comparative numbers ('Revenue | 6,722,238 | 5,841,488 | +15.1%') and are rejected by this test.
        pmrow = bool(re.search(r"(\+/-|±|plus or minus)", l))
        # a guide row carries a currency symbol, or a +/- marker with the unit in a '(in millions)' header above (Applied Materials)
        if not CUE.search(ctx): continue
        if not re.search(r"[$€£]", l) and not (pmrow and re.search(r"\(in (millions|billions|thousands)", ctx, re.I)): continue
        if re.search(r"[$€£]", l) and not (pmrow or UNIT.search(l)): continue
        if re.search(r"%", l) and not re.search(r"(\+/-|±|plus or minus)", l): continue
        cells = [c.strip() for c in l.split("|")][1:]
        pm = any(re.fullmatch(r"(plus or minus|\+/-|±)", c, re.I) for c in cells)
        mon = [(c, nums(c)[0]) for c in cells if nums(c) and re.search(r"[\d]", c)]
        if not mon: continue
        gu = UNIT.search(l) or re.search(r"\(in (millions|billions|thousands)", ctx, re.I) or UNIT.search(ctx[-300:])
        gunit = (gu.group(1).lower().rstrip("s") if gu else None)
        def scale(cell, v):
            u = UNIT.search(cell); u = u.group(1).lower() if u else gunit
            u = (u or "").rstrip("s")
            return v * (1000 if u in ("billion", "bn") else 0.001 if u == "thousand" else 1 if u in ("million", "mm", "m") else (1 if abs(v) > 100 else 1000))
        vals = [scale(c, v) for c, v in mon]
        uniq = []
        for v in vals:
            if not any(abs(v - u) < 1e-9 for u in uniq): uniq.append(v)
        if pm and len(uniq) >= 2: out.update(revenue_mid=uniq[0], revenue_pm_abs=uniq[1]); break
        if len(uniq) == 2 and uniq[1] > uniq[0]: out.update(revenue_low=uniq[0], revenue_high=uniq[1]); break
        if len(uniq) == 1: out.update(revenue_mid=uniq[0]); break
    return out
def read(text):
    """first window whose text yields a revenue guide wins; else the first window goes to the model queue"""
    W = windows(text)
    for t in W:
        out = _apply(t)
        if any(k.startswith("revenue") for k in out): return out, t, True
    t = W[0] if W else ""; out = _apply(t)
    if not any(k.startswith("revenue") for k in out):
        tg = table_guide(text)
        if tg: out.update(tg); return out, (t or "(guidance table)"), True
    return out, t, any(k.startswith("revenue") for k in out)

def model_text(text, limit=2500):
    """what the model sees when no pattern reads the guide: all outlook windows (deduped), else the release opening"""
    W = list(dict.fromkeys(windows(text)))
    return ("\n---\n".join(W))[:limit] if W else "(no outlook sentence found)\n" + re.sub(r"\s+", " ", text)[:1500]

def guide_text_present(text):
    """Deterministic 'is there a revenue guide in this release at all' test: an outlook/guidance/forecast cue within 400 characters of a
    currency figure. Releases that fail it are recorded as giving no guidance (many filers guide only on the call) and are not queued."""
    flat = re.sub(r"\s+", " ", text)
    for m in CUE.finditer(flat):
        w = flat[max(0, m.start() - 200):m.start() + 400]
        if re.search(r"[$€£]\s?\d", w) and re.search(r"revenue|sales", w, re.I): return True
    return False
