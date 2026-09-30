"""Earnings-day exhibits (8-K item 2.02: EX-99.1 press release, EX-99.2 CFO commentary) -> text with table rows kept on one line. Deterministic."""
import re, html as H, edgar
from lxml import html as LH
def exhibits(cik, acc):
    """EX-99* exhibit text. Preferred path: read the document list from the filing header and fetch only those exhibit files.
    Falls back to the full submission .txt (older filings where the header lists no filenames)."""
    out = {}
    try:
        names = [(t, f) for t, f in edgar.doc_types(cik, acc) if t.startswith("EX-99") and re.search(r"\.(htm|html|txt)$", f, re.I)]
    except Exception:
        names = []
    if names:
        for typ, fn in names:
            try: out.setdefault(typ.split()[0], []).append(to_lines(edgar.get(edgar.doc_url(cik, acc, fn))))
            except Exception: names = []; out = {}; break
    if not out:
        raw = edgar.get(edgar.doc_url(cik, acc, acc + ".txt"))
        for d in re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", raw, re.S):
            t = re.search(r"<TYPE>([^\n<]+)", d); typ = t.group(1).strip() if t else ""
            if not typ.startswith("EX-99"): continue
            body = re.search(r"<TEXT>(.*)</TEXT>", d, re.S); body = body.group(1) if body else d
            out.setdefault(typ.split()[0], []).append(to_lines(body))
    return {k: "\n".join(v) for k, v in out.items()}
def to_lines(body):
    if not re.search(r"<(html|table|p|div)", body, re.I): return body
    body = re.sub(r"^\s*<\?xml[^>]*>", "", body); doc = LH.fromstring(body.encode("utf-8", "ignore")); lines = []
    for el in doc.iter():
        if el.tag == "tr":
            cells = [re.sub(r"\s+", " ", c.text_content()).strip() for c in el.findall(".//td") + el.findall(".//th")]
            cells = [c for c in cells if c and c not in ("$", "%", ")")]
            if cells: lines.append(" | ".join(cells))
        elif el.tag in ("p", "div", "li") and el.find(".//table") is None and el.getparent() is not None and el.getparent().tag not in ("td", "th", "li"):
            t = re.sub(r"\s+", " ", el.text_content()).strip()
            if t: lines.append(t)
    return "\n".join(lines)
NUM = r"\(?-?\$?\s?[\d,]+(?:\.\d+)?\)?"
def nums(line):
    out = []
    for m in re.finditer(NUM, line):
        s = m.group(0); neg = s.startswith("(") and s.endswith(")"); v = re.sub(r"[^\d.\-]", "", s)
        if v in ("", ".", "-"): continue
        out.append(-float(v) if neg else float(v))
    return out
