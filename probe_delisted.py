"""Probe free sources for delisted-stock price history (1990s-2000s), to judge whether a survivorship-free 1990-2007
backtest is feasible. Prints coverage per ticker; writes results/history/probe_delisted.csv."""
import io, os, time
import pandas as pd, requests
NAMES = {"SUNW": "Sun Microsystems", "NT": "Nortel", "LU": "Lucent", "CPQ": "Compaq", "WCOM": "WorldCom", "COMS": "3Com",
         "PALM": "Palm", "AOL": "AOL", "YHOO": "Yahoo", "EMC": "EMC", "BRCM": "Broadcom (old)", "XLNX": "Xilinx", "ALTR": "Altera",
         "LLTC": "Linear Tech", "MXIM": "Maxim", "NSM": "National Semi", "NOVL": "Novell", "GTW": "Gateway", "DEC": "Digital Equipment",
         "CMGI": "CMGI", "JDSU": "JDS Uniphase", "QCOM": "Qualcomm (control: still listed)", "INTC": "Intel (control)"}
UA = {"User-Agent": "Mozilla/5.0"}
rows = []
for t, nm in NAMES.items():
    rec = dict(ticker=t, name=nm)
    for src, url in (("stooq", f"https://stooq.com/q/d/l/?s={t.lower()}.us&i=d"),):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            txt = r.text
            if r.status_code == 200 and txt.startswith("Date"):
                df = pd.read_csv(io.StringIO(txt))
                rec[f"{src}_first"], rec[f"{src}_last"], rec[f"{src}_rows"] = df.Date.iloc[0], df.Date.iloc[-1], len(df)
            else:
                rec[f"{src}_first"] = f"none ({r.status_code}: {txt[:40].strip()!r})"
        except Exception as e:
            rec[f"{src}_first"] = f"error {type(e).__name__}"
        time.sleep(1)
    try:
        import yfinance as yf
        d = yf.download(t, start="1990-01-01", end="2010-01-01", progress=False, auto_adjust=False)
        rec["yahoo_first"] = str(d.index[0].date()) if len(d) else "none"; rec["yahoo_rows"] = len(d)
    except Exception as e:
        rec["yahoo_first"] = f"error {type(e).__name__}"
    rows.append(rec); print(rec, flush=True)
os.makedirs("results/history", exist_ok=True)
pd.DataFrame(rows).to_csv("results/history/probe_delisted.csv", index=False)
