"""Guidance patterns for a market-wide universe.

guidance_generic's patterns were tuned on semiconductor releases and read 79% of those guides; on
the whole market they read 16%, because the rest of the market phrases guidance differently and
often gives it as a GROWTH RATE rather than a dollar figure ("revenue growth of 7% to 12%").

This module adds, deliberately kept separate so the validated semis path is untouched:
  - more dollar phrasings ("estimated to be", "raising guidance to", "in the range of $X to $Y")
  - percentage guidance, converted to dollars against the year-ago base so it is comparable
  - a stricter test for whether a release contains a forward revenue guide at all, since the
    generic one fires on reported actuals ("Revenue of $158.3 million") and so would have sent
    thousands of releases to the model for nothing.
"""
import re

MULT = {"billion": 1000.0, "bn": 1000.0, "b": 1000.0, "million": 1.0, "mm": 1.0, "m": 1.0}
B = r"(billion|million|bn|mm?|b)\b"
FWD = r"(?:expects?|expected|estimates?|estimated|anticipates?|anticipated|projects?|projected|forecasts?|forecasted|guidance|outlook|sees|targets?|raising|raised|increasing|increased|reaffirm\w*|reiterat\w*)"
REV = r"(?:total |net |consolidated |organic |pro forma )?(?:revenues?|net sales|sales)"

def _m(v, u): return float(v.replace(",", "").replace("$", "").strip()) * MULT[u.lower().rstrip(".")]

DOLLAR = [
    # range: "revenue ... expected to be between $X and $Y million" / "$X to $Y billion" / "$X-$Y million"
    rf"{REV}[^.]{{0,90}}?{FWD}[^.]{{0,60}}?\$?\s?([\d,.]+)\s*(?:{B})?\s*(?:to|-|–|and|through)\s*\$?\s?([\d,.]+)\s*{B}",
    rf"{FWD}[^.]{{0,40}}?{REV}[^.]{{0,130}}?\$?\s?([\d,.]+)\s*(?:{B})?\s*(?:to|-|–|and|through)\s*\$?\s?([\d,.]+)\s*{B}",
]
POINT = [
    rf"{REV}[^.]{{0,90}}?{FWD}[^.]{{0,60}}?(?:approximately|about|around|~)?\s*\$\s?([\d,.]+)\s*{B}",
    rf"{FWD}[^.]{{0,40}}?{REV}[^.]{{0,130}}?(?:approximately|about|around|~)?\s*\$\s?([\d,.]+)\s*{B}",
]
# headline forms: "Guidance of $440-460 Million in Revenue", "Raises Full Year Revenue Guidance to $1.02 Billion"
HEADLINE = [
    rf"guidance of \$?\s?([\d,.]+)\s*(?:-|–|to)\s*\$?\s?([\d,.]+)\s*{B}\s*(?:in|of)?\s*{REV}",
    rf"{REV}\s*guidance\s*(?:range\s*)?(?:of|to)\s*\$?\s?([\d,.]+)\s*(?:-|–|to)\s*\$?\s?([\d,.]+)\s*{B}",
    rf"(?:raises?|raising|increases?|increasing|lifts?)[^.]{{0,40}}?{REV}[^.]{{0,30}}?guidance[^.]{{0,30}}?to\s*\$?\s?([\d,.]+)\s*{B}",
]
PCT_RANGE = [
    rf"{FWD}[^.]{{0,40}}?{REV}[^.]{{0,60}}?(?:growth|increase|grow|up)?[^.]{{0,40}}?(?:of|by|in the range of|between)\s*\(?(-?[\d.]+)\)?\s*%\s*(?:to|-|–|and)\s*\(?(-?[\d.]+)\)?\s*%",
    rf"{REV}[^.]{{0,90}}?{FWD}[^.]{{0,70}}?(?:growth |increase |up |grow )?(?:of |by |in the range of |between )?\(?(-?[\d.]+)\)?\s*%\s*(?:to|-|–|and)\s*\(?(-?[\d.]+)\)?\s*%",
    rf"{REV}\s*(?:growth)?[^.]{{0,40}}?(?:up|grow(?:th)? of)\s*(-?[\d.]+)\s*%\s*(?:to|-|–)\s*(-?[\d.]+)\s*%",
]
PCT_POINT = [rf"{REV}[^.]{{0,90}}?{FWD}[^.]{{0,70}}?(?:growth|increase|grow|up)\s*(?:of|by)?\s*(?:approximately|about|~)?\s*(-?[\d.]+)\s*%"]

# words that mean the number is a RESULT, not a guide
PAST = re.compile(r"\b(was|were|totaled|totalled|increased to|decreased to|grew to|of \$[\d,.]+ (?:million|billion) (?:compared|versus|vs)|reported|surpassed|achieved|delivered)\b", re.I)
# a dollar figure in the same clause as any of these is not a revenue guide: IBM's "$1 billion of
# cost savings" was being read as a revenue guide and scored as a 1,616% beat.
NOT_REV = re.compile(r"cost savings|synergies|debt|EBITDA|cash flow|capital expenditure|capex|buyback|repurchase|dividend|backlog|bookings|pipeline|"
                     r"acquisition|purchase price|impairment|charge|tax|interest expense|net income|earnings per share|\bEPS\b|margin|liquidity|"
                     r"share count|market (?:size|opportunity)|TAM|contract value|award", re.I)

def _clause(t, start):
    return re.split(r"[.;•]\s|---", t[:start])[-1][-200:]

def _rejected(t, start, end):
    """the clause around a candidate figure, tested for markers that make it not a revenue guide"""
    c = _clause(t, start) + t[start:end + 60]
    return bool(PAST.search(c) or NOT_REV.search(c))

def read_dollar(t):
    for rx in HEADLINE[:2]:
        for m in re.finditer(rx, t, re.I):
            if _rejected(t, m.start(), m.end()): continue
            try:
                u = m.group(m.lastindex); lo, hi = _m(m.group(1), u), _m(m.group(2), u)
            except Exception: continue
            if hi > lo > 0 and hi / lo < 5: return dict(revenue_low=lo, revenue_high=hi, revenue_mid=(lo + hi) / 2, basis="headline range")
    for rx in HEADLINE[2:]:
        for m in re.finditer(rx, t, re.I):
            if _rejected(t, m.start(), m.end()): continue
            try: v = _m(m.group(1), m.group(2))
            except Exception: continue
            if v > 0: return dict(revenue_mid=v, basis="headline raise")
    for rx in DOLLAR:
        for m in re.finditer(rx, t, re.I):
            if _rejected(t, m.start(), m.end()): continue
            try:
                u = m.group(m.lastindex)
                lo, hi = _m(m.group(1), u), _m(m.group(2), u)
            except Exception: continue
            if hi > lo > 0 and hi / lo < 5: return dict(revenue_low=lo, revenue_high=hi, revenue_mid=(lo + hi) / 2, basis="dollar range")
    for rx in POINT:
        for m in re.finditer(rx, t, re.I):
            if _rejected(t, m.start(), m.end()): continue
            try: v = _m(m.group(1), m.group(2))
            except Exception: continue
            if v > 0: return dict(revenue_mid=v, basis="dollar point")
    return {}

def read_pct(t):
    for rx in PCT_RANGE:
        for m in re.finditer(rx, t, re.I):
            if _rejected(t, m.start(), m.end()): continue
            lo, hi = float(m.group(1)), float(m.group(2))
            if -60 <= lo <= hi <= 200: return dict(growth_low_pct=lo, growth_high_pct=hi, growth_mid_pct=(lo + hi) / 2, basis="growth range")
    for rx in PCT_POINT:
        for m in re.finditer(rx, t, re.I):
            if _rejected(t, m.start(), m.end()): continue
            v = float(m.group(1))
            if -60 <= v <= 200: return dict(growth_mid_pct=v, basis="growth point")
    return {}

GUIDE_CUE = re.compile(rf"{FWD}", re.I)
def has_guide(text):
    """Stricter than guidance_generic's version: a forward-looking verb AND a revenue word AND a
    figure, all inside one clause, with no past-tense marker. The loose test fires on reported
    actuals, which is why 63% of a market-wide sample looked like it needed a model."""
    flat = re.sub(r"\s+", " ", text)
    for m in GUIDE_CUE.finditer(flat):
        w = flat[max(0, m.start() - 120):m.start() + 260]
        if not re.search(REV, w, re.I): continue
        if not re.search(r"[$€£]\s?[\d,.]+|\d+(\.\d+)?\s?%", w): continue
        if PAST.search(w[:160]): continue
        return True
    return False

def read(text):
    t = re.sub(r"\s+", " ", text)
    out = read_dollar(t) or read_pct(t)
    return out


ANNUAL = re.compile(r"full[- ]year|fiscal (?:year )?20\d\d|for 20\d\d|FY\s?20?\d\d|annual", re.I)
QTR = re.compile(r"\b(?:Q[1-4]|first|second|third|fourth)[- ]?quarter|next quarter|the quarter|current quarter", re.I)

def period_of(text, m_start):
    """Which period a guide refers to, read from its own clause: the cue NEAREST the number wins,
    so 'full-year revenue of $X' and 'fourth-quarter revenue of $X' in one release do not collide."""
    ctx = _clause(text, m_start) + text[m_start:m_start + 60]
    last = lambda rx: max([x.end() for x in rx.finditer(ctx)] or [-1])
    a, q = last(ANNUAL), last(QTR)
    if max(a, q) < 0: return "unknown"
    return "full_year" if a > q else "quarter"

def read_with_period(text):
    """Same as read(), but also reports which period the guide covers and where it was found."""
    t = re.sub(r"\s+", " ", text)
    for reader in (read_dollar, read_pct):
        # re-run the winning pattern to recover the match position for period classification
        out = reader(t)
        if not out: continue
        pats = (HEADLINE + DOLLAR + POINT) if reader is read_dollar else (PCT_RANGE + PCT_POINT)
        pos = None
        for rx in pats:
            for m in re.finditer(rx, t, re.I):
                if _rejected(t, m.start(), m.end()): continue
                pos = m.start(); break
            if pos is not None: break
        out["period"] = period_of(t, pos) if pos is not None else "unknown"
        return out
    return {}
