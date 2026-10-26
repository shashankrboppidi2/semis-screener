"""Tiingo coverage check for a survivorship-free 1990-2007 backtest. Uses the TIINGO_KEY secret (never printed).
1) Tiingo's public supported-tickers list: how many US stocks it carries that stopped trading before 2010.
2) Price history for well-known delisted tech names (and two live controls).
Writes results/history/probe_tiingo.csv and probe_tiingo_universe.txt."""
import io, os, time, zipfile
import pandas as pd, requests
KEY = os.environ.get("TIINGO_KEY", "").strip()
OUT = "results/history"; os.makedirs(OUT, exist_ok=True)
NAMES = {"SUNW": "Sun Microsystems", "NT": "Nortel", "LU": "Lucent", "CPQ": "Compaq", "WCOM": "WorldCom", "COMS": "3Com",
         "PALM": "Palm", "AOL": "AOL", "YHOO": "Yahoo", "EMC": "EMC", "BRCM": "Broadcom (old)", "XLNX": "Xilinx", "ALTR": "Altera",
         "LLTC": "Linear Tech", "MXIM": "Maxim", "NSM": "National Semi", "NOVL": "Novell", "GTW": "Gateway", "CMGI": "CMGI",
         "JDSU": "JDS Uniphase", "QCOM": "Qualcomm (control)", "INTC": "Intel (control)"}
lines = []
try:
    z = requests.get("https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip", timeout=60)
    t = pd.read_csv(zipfile.ZipFile(io.BytesIO(z.content)).open("supported_tickers.csv"))
    t["startDate"] = pd.to_datetime(t.startDate, errors="coerce"); t["endDate"] = pd.to_datetime(t.endDate, errors="coerce")
    us = t[t.exchange.isin(["NYSE", "NASDAQ", "AMEX", "NYSE MKT", "NYSE ARCA"]) & (t.assetType == "Stock")]
    dead = us[(us.endDate < "2010-01-01") & (us.startDate < "2007-01-01")]
    lines += [f"US stocks listed: {len(us)}", f"stopped trading before 2010 with history before 2007: {len(dead)}",
              f"... with history starting before 1995: {(dead.startDate < '1995-01-01').sum()}"]
    for k in NAMES: 
        r = us[us.ticker.str.upper() == k]
        lines.append(f"{k}: " + ("; ".join(f"{a.date() if pd.notna(a) else '?'} to {b.date() if pd.notna(b) else '?'} ({e})" for a, b, e in zip(r.startDate, r.endDate, r.exchange)) if len(r) else "not in list"))
    dead[["ticker", "exchange", "startDate", "endDate"]].to_csv(f"{OUT}/tiingo_delisted_pre2010.csv.gz", index=False)
except Exception as e:
    lines.append(f"supported_tickers download failed: {type(e).__name__}")
open(f"{OUT}/probe_tiingo_universe.txt", "w").write("\n".join(lines) + "\n"); print("\n".join(lines), flush=True)
rows = []
if not KEY: print("TIINGO_KEY not set", flush=True)
for tk, nm in NAMES.items():
    rec = dict(ticker=tk, name=nm)
    if KEY:
        try:
            r = requests.get(f"https://api.tiingo.com/tiingo/daily/{tk.lower()}/prices",
                             params=dict(startDate="1990-01-01", endDate="2012-12-31", token=KEY), timeout=60)
            if r.status_code == 200 and r.text.startswith("["):
                d = pd.DataFrame(r.json())
                if len(d): rec.update(first=d.date.iloc[0][:10], last=d.date.iloc[-1][:10], rows=len(d), adj_ok=bool("adjClose" in d))
                else: rec["first"] = "empty"
            else:
                rec["first"] = f"http {r.status_code}: {r.text[:60]!r}".replace(KEY, "***")
        except Exception as e:
            rec["first"] = f"error {type(e).__name__}"
        time.sleep(4)
    rows.append(rec); print(rec, flush=True)
pd.DataFrame(rows).to_csv(f"{OUT}/probe_tiingo.csv", index=False)
