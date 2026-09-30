"""Minimal cached EDGAR client. SEC fair-access: <=10 req/s and a descriptive User-Agent (set SEC_UA to your name + email)."""
import os, time, json, hashlib, urllib.request, gzip
_PLACEHOLDER = "SemisResearch research@example.org"
UA = os.environ.get("SEC_UA", _PLACEHOLDER)
if UA == _PLACEHOLDER:
    import sys, warnings
    warnings.warn(
        "SEC_UA is not set, so requests go out with a placeholder User-Agent. The SEC's fair-access "
        "policy requires a real name and email, and it rate-limits then blocks clients that omit one. "
        'Set SEC_UA="Your Name you@domain" before any run larger than a handful of requests.',
        RuntimeWarning, stacklevel=2)
    print("WARNING: SEC_UA not set — using a placeholder User-Agent. See README.", file=sys.stderr)
ROOT = os.path.dirname(os.path.abspath(__file__)); CACHE = f"{ROOT}/cache"; _last = [0.0]; STATS = {"http": 0, "cache": 0, "bytes": 0}
os.makedirs(CACHE, exist_ok=True)
# data.sec.gov answers (submissions, companyfacts, frames) change every time a filer files, so they expire;
# www.sec.gov/Archives documents never change and are cached for good. SEC_CACHE_TTL_HOURS=0 disables expiry.
TTL_H = float(os.environ.get("SEC_CACHE_TTL_HOURS", "20"))
def _fresh(url, p):
    return not (TTL_H > 0 and "://data.sec.gov/" in url and time.time() - os.path.getmtime(p) > TTL_H * 3600)
def get(url, binary=False):
    """Cache bodies gzipped (SEC text/XML compresses ~5x); legacy uncompressed entries are still read."""
    p = f"{CACHE}/{hashlib.sha1(url.encode()).hexdigest()}"
    if os.path.exists(p + ".gz") and _fresh(url, p + ".gz"):
        STATS["cache"] += 1; b = gzip.decompress(open(p + ".gz", "rb").read())
    elif os.path.exists(p) and _fresh(url, p):
        STATS["cache"] += 1; b = open(p, "rb").read()
    else:
        wait = 0.12 - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        for attempt in range(4):
            try:
                r = urllib.request.urlopen(req, timeout=60); b = r.read()
                if r.headers.get("Content-Encoding") == "gzip": b = gzip.decompress(b)
                break
            except Exception as e:
                if attempt == 3: raise
                time.sleep(2 ** attempt)
        _last[0] = time.time(); STATS["http"] += 1; STATS["bytes"] += len(b)
        open(p + ".gz", "wb").write(gzip.compress(b, 6))
    return b if binary else b.decode("utf-8", errors="ignore")
def getj(url): return json.loads(get(url))
def cik10(cik): return str(int(cik)).zfill(10)
def submissions(cik):
    j = getj(f"https://data.sec.gov/submissions/CIK{cik10(cik)}.json"); rows = []
    blocks = [j["filings"]["recent"]] + [getj(f"https://data.sec.gov/submissions/{f['name']}") for f in j["filings"].get("files", [])]
    for b in blocks:
        for i in range(len(b["accessionNumber"])):
            rows.append({k: b[k][i] for k in ["accessionNumber", "filingDate", "reportDate", "form", "primaryDocument", "items"] if k in b})
    return j, rows
def filing_index(cik, acc):
    return getj(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/index.json")
def doc_url(cik, acc, name): return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{name}"

def doc_types(cik, acc):
    """[(document type, filename)] from the small -index-headers.html (SGML header, HTML-escaped) - avoids downloading the
    whole submission .txt, which can be 100 MB when a filer attaches image-heavy slide decks."""
    import html as _h, re as _re
    u = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index-headers.html"
    t = _h.unescape(get(u))
    return [(m.group(1).strip(), m.group(2).strip()) for m in _re.finditer(r"<TYPE>([^<\n]+)[\s\S]{0,300}?<FILENAME>([^<\n]+)", t)]
