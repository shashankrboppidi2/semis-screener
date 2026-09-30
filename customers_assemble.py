"""Turn model answers into core rows: (period_end, duration, customer, type, pct), first reported. Period text -> fiscal period end via the XBRL calendar."""
import re, json, pandas as pd, llm_fallback as LF
ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
MON = "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
def date_period(txt, dur):
    """'three months ended July 26, 2015' / 'May 1, 2016' -> (Timestamp, duration)"""
    t = (txt or "").lower(); m = re.search(rf"({MON})\.? (\d{{1,2}}),? (\d{{4}})", t)
    if not m: return None
    d = {"three": 3, "six": 6, "nine": 9, "twelve": 12}; w = re.search(r"(three|six|nine|twelve) months", t)
    return pd.Timestamp(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}"), (d[w.group(1)] if w else (dur or 3))
def period_key(txt, dur):
    t = (txt or "").lower(); fy = re.search(r"(?:fiscal(?: year)?|fy)\s*'?(\d{4}|\d{2})\b", t) or re.search(r"\b(20\d\d)\b", t)   # calendar filers: '2012', 'first quarter of 2011'
    if not fy: return None
    if re.fullmatch(r"\s*(year )?(ended )?20\d\d\s*", t): return (int(fy.group(1)), 4, 12)
    y = int(fy.group(1)); y = y + 2000 if y < 100 else y
    m = re.search(r"(first|second|third|fourth) quarter", t)
    if m: return (y, ORD[m.group(1)], 3)
    if "first half" in t or "six months" in t: return (y, 2, 6)
    if "nine months" in t or "first three quarters" in t: return (y, 3, 9)
    if re.search(r"fiscal (year )?\d", t) or "full year" in t or "year" in t or dur == 12: return (y, 4, 12)
    return None
def assemble(req_file, res, calendar, fye_month, filed=None):
    req = {json.loads(l)["id"]: json.loads(l) for l in open(req_file)}; rows = []
    for i, r in req.items():
        o = (res.get(i) or {}).get("output") or {}; filed_order = i
        for x in o.get("rows", []):
            if not isinstance(x.get("pct"), (int, float)): continue
            vague = re.search(r"estimated to represent 10% or more|individually representing 10% or more", r["user"], re.I)
            floor = float(x["pct"]) == 10 and (x.get("exact") is False or bool(vague)) and bool(re.search(r"more than 10\s?%|10\s?% or more|at least 10\s?%", r["user"], re.I))
            # 'more than 10%' / '10% or more' is a floor flag, not a measured share: kept, marked is_floor (was dropped before);
            # 'approximately 22%' is a measured share even when the model marks it exact=false
            k = period_key(x.get("period"), x.get("duration_months")); dp = None if k else date_period(x.get("period"), x.get("duration_months"))
            if k:
                y, q, dur = k; approx = pd.Timestamp(year=y, month=fye_month, day=28) - pd.DateOffset(months=3 * (4 - q))
            elif dp: approx, dur = dp
            else: continue
            pe = min(calendar, key=lambda d: abs((d - approx).days))
            if abs((pe - approx).days) > 45: continue          # period outside the calendar (e.g. a 2009 comparative) is not snapped to a wrong date
            rows.append(dict(accn=i, period_end=pe, duration=dur, customer=x.get("customer"), type=x.get("type"), pct=float(x["pct"]), is_floor=bool(floor), model=(res.get(i) or {}).get("model")))
    d = pd.DataFrame(rows, columns=["accn", "period_end", "duration", "customer", "type", "pct", "is_floor", "model"])
    if not len(d): return d.assign(filed=pd.Series(dtype="datetime64[ns]"))
    # first reported = earliest FILING DATE (accession prefixes differ by filing agent, so accession order is not filing order)
    d["filed"] = d.accn.map(filed) if filed else d.accn
    first = d.groupby(["period_end", "duration"]).filed.transform("min")
    return d[d.filed == first]
