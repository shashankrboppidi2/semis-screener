"""WU hedge state from TradingView alert e-mails, for plan_alerts.py.

Set two TradingView alerts on the WU indicator (exit and re-entry) with "Send email" on and a message containing
WU_HEDGE=on or WU_HEDGE=off. This reads the Gmail account in SMTP_USER over IMAP with the same app password (SMTP_PASS)
and returns the newest such alert as ("on" | "off", date), or None. Nothing about the result is printed: the run log of
this public repository is public.
"""
import email, imaplib, os, re
from email.utils import parsedate_to_datetime

PAT = re.compile(r"WU_HEDGE\s*=\s*(on|off)\b", re.I)
QUERY = '"from:tradingview.com WU_HEDGE newer_than:1500d"'

def _text(msg):
    parts = msg.walk() if msg.is_multipart() else [msg]
    out = [str(msg.get("Subject", ""))]
    for p in parts:
        if p.get_content_maintype() == "text":
            raw = p.get_payload(decode=True) or b""
            out.append(raw.decode(p.get_content_charset() or "utf-8", "replace"))
    return "\n".join(out)

def latest(user=None, pw=None, host="imap.gmail.com", limit=25):
    user, pw = user or os.getenv("SMTP_USER", ""), pw or os.getenv("SMTP_PASS", "")
    if not (user and pw): return None
    M = imaplib.IMAP4_SSL(host)
    try:
        M.login(user, pw.replace(" ", ""))
        if M.select('"[Gmail]/All Mail"', readonly=True)[0] != "OK": M.select("INBOX", readonly=True)
        typ, data = M.search(None, "X-GM-RAW", QUERY)
        ids = data[0].split()[-limit:] if typ == "OK" and data and data[0] else []
        best = None
        for i in ids:
            typ, got = M.fetch(i, "(BODY.PEEK[])")
            if typ != "OK" or not got or not isinstance(got[0], tuple): continue
            msg = email.message_from_bytes(got[0][1]); m = PAT.findall(_text(msg))
            if not m: continue
            when = parsedate_to_datetime(msg["Date"])
            if best is None or when > best[1]: best = (m[-1].lower(), when)
        return best
    finally:
        try: M.logout()
        except Exception: pass
