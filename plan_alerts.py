"""Daily alerts for the 50/50 QQQ/SMH rotation plan (blend_backtest rules).

  QQQ sleeve  park in QQQ; alert when a chip/tech name of $50bn+ closes >= 30% below its 252-day high relative to QQQ
  SMH sleeve  park in SMH; alert when one of the 25 largest chip names closes >= 30% below its 252-day high vs SMH
  Each alert = buy STEP (2%) of that sleeve from the sleeve's ETF; at most 10% of the sleeve per name and 40% in names;
  a name re-alerts only after 63 trading days. When a sleeve has too little room, the largest caps fill first; no
  displacement. January: trim names to 10% / 40% and rebalance the sleeves to 50/50.
  Hedge: the WU SP500 Hedging Signal is closed-source TradingView data, so it is not computed here. Set its state in
  the repository variable WU_HEDGE ("on" / "off") when the TradingView alert fires; the report then sizes PSQ
  (25% of the QQQ sleeve, beta-scaled for the SMH sleeve) or tells you to unwind it.

Inputs (all optional except prices):
  results/universe/        tickers, SIC, share counts and splits (build_tech_universe.py, refreshed quarterly)
  HOLDINGS                 secret, CSV "sleeve,ticker,shares" (sleeve QQQ or SMH; the ETFs and PSQ included) -> the
                           report prints dollar amounts, room left, trims and the rebalance; without it, percentages
  SMTP_HOST/PORT/USER/PASS, MAIL_TO   e-mail (sent when there is something to do, or on Mondays)
State: state/plan_alerts.json (last alert date per sleeve and name). Report: results/alerts/latest.md and .html.

python plan_alerts.py            # live, Yahoo prices
python plan_alerts.py --offline  # from the price files already in results/ (for testing)
"""
import io, json, os, sys, glob
import numpy as np
import pandas as pd
from tech_caps import daily_caps

STEP, CAP_NAME, CAP_TOT, FLOOR_B, TOP_N, DROP, SPACING = 0.02, 0.10, 0.40, 50.0, 25, 0.30, 63
UNI, STATE, OUT = "results/universe", "state/plan_alerts.json", "results/alerts"
CHIP_SIC = {3674}

def load_prices(offline, tickers):
    if offline:
        adj = pd.read_csv(f"{UNI}/tech_adj.csv.gz", index_col=0, parse_dates=True)
        close = pd.read_csv(f"{UNI}/tech_close.csv.gz", index_col=0, parse_dates=True)
        etf = pd.read_csv("results/prices/closes.csv", index_col=0, parse_dates=True)
        adj = adj.join(etf[["QQQ", "SMH", "PSQ"]], how="left"); close = close.join(etf[["QQQ", "SMH", "PSQ"]], how="left")
        adj = adj.loc[:adj.drop(columns=["QQQ", "SMH", "PSQ"]).dropna(how="all").index.max()]
        return adj.iloc[-1600:], close.reindex(adj.index).iloc[-1600:], pd.DataFrame(columns=["date", "ticker", "ratio"])
    import yfinance as yf
    d = yf.download(sorted(set(tickers) | {"QQQ", "SMH", "PSQ"}), period="7y", auto_adjust=False, actions=True,
                    progress=False, threads=True, group_by="column")
    spl = d["Stock Splits"].stack()
    spl = spl[spl > 0].rename("ratio").rename_axis(["date", "ticker"]).reset_index()
    return d["Adj Close"], d["Close"], spl

def caps_now(close, new_splits):
    meta = pd.read_csv(f"{UNI}/tech_meta.csv").set_index("ticker")
    sh = pd.read_csv(f"{UNI}/tech_shares.csv.gz", parse_dates=["end"])
    sp = pd.concat([pd.read_csv(f"{UNI}/tech_splits.csv", parse_dates=["date"]), new_splits]).drop_duplicates(["date", "ticker"])
    out = {}
    for t, g in sh.groupby("ticker"):
        if t not in close.columns: continue
        s = sp[sp.ticker == t].set_index("date").ratio
        out[t] = daily_caps(close[t].dropna(), s, g[["end", "shares"]], meta.adr_ratio.get(t, 1.0)).iloc[-1]
    return pd.Series(out), meta

def signals(adj, caps, meta):
    d = adj.index[-1]
    def behind(names, bench):
        x = adj[names].div(adj[bench], axis=0)
        hi = x.rolling(252, min_periods=252).max()
        return (x / hi - 1).loc[d]
    config = {os.path.basename(p)[:-5] for p in glob.glob("config/*.json")}
    names = [t for t in caps.index if t in adj.columns]
    chips = [t for t in names if t in config or meta.sic.get(t) in CHIP_SIC]
    bq = behind(names, "QQQ"); bs = behind(chips, "SMH")
    top = caps[chips].sort_values(ascending=False).head(TOP_N).index
    q = bq[(caps[names] >= FLOOR_B) & (bq <= -DROP)].sort_values()
    s = bs[bs.index.isin(top) & (bs <= -DROP)].sort_values()
    return d, {"QQQ": q, "SMH": s}

def holdings(adj_close):
    raw = os.getenv("HOLDINGS", "").strip()
    if not raw: return None
    h = pd.read_csv(io.StringIO(raw)); h.columns = [c.strip().lower() for c in h.columns]
    h["sleeve"] = h.sleeve.str.upper().str.strip(); h["ticker"] = h.ticker.str.upper().str.strip()
    h["price"] = [adj_close[t].dropna().iloc[-1] if t in adj_close else np.nan for t in h.ticker]
    h["value"] = h.shares * h.price
    return h

def main(offline=False):
    meta0 = pd.read_csv(f"{UNI}/tech_meta.csv")
    adj, close, new_splits = load_prices(offline, list(meta0.ticker))
    caps, meta = caps_now(close, new_splits)
    d, sig = signals(adj, caps, meta)
    td = adj.index
    state = json.load(open(STATE)) if os.path.exists(STATE) else {"QQQ": {}, "SMH": {}}
    if offline: state = {"QQQ": {}, "SMH": {}}                       # a test run never reads or writes the live state
    hedge = os.getenv("WU_HEDGE", "").strip().lower()
    r = np.log(adj[["QQQ", "SMH"]]).diff().iloc[-1260:]
    beta = r.SMH.cov(r.QQQ) / r.QQQ.var(); h_smh = 0.5 * beta / (1 + beta)
    H = holdings(close)
    L = [f"# Plan alerts, {d:%A %Y-%m-%d}", ""]
    todo = False

    # hedge
    frac = {"QQQ": 0.25, "SMH": h_smh}
    sv = {}
    if H is not None:
        for s in ("QQQ", "SMH"): sv[s] = H[H.sleeve == s].value.sum()
    psq_held = H is not None and (H.ticker == "PSQ").any() and H[H.ticker == "PSQ"].shares.sum() > 0
    P = list(L) + ["## Hedge", "", "The hedge instructions are in the e-mail only (this file and the run log are public).", ""]
    L += ["## Hedge (WU SP500 Hedging Signal, PSQ)", ""]
    if hedge not in ("on", "off"):
        L.append("WU_HEDGE is not set. Set the repository variable to `on` or `off` when the TradingView alert fires.")
    elif hedge == "on" and not psq_held:
        todo = True
        L.append(f"**Hedge ON.** Sell {frac['QQQ']:.0%} of the QQQ sleeve from QQQ and {frac['SMH']:.1%} of the SMH sleeve "
                 f"from SMH (SMH beta {beta:.2f}); buy PSQ with the proceeds.")
        if sv: L.append(f"That is ${frac['QQQ'] * sv['QQQ']:,.0f} of QQQ and ${frac['SMH'] * sv['SMH']:,.0f} of SMH into PSQ.")
    elif hedge == "off" and psq_held:
        todo = True
        L.append("**Hedge OFF.** Sell all PSQ; put each sleeve's PSQ back into that sleeve's ETF.")
    else:
        L.append(f"Hedge is {hedge}; holdings already match." if H is not None else f"Hedge is {hedge}.")
    L.append("")

    # rotation alerts
    for s, bench in (("QQQ", "QQQ"), ("SMH", "SMH")):
        last = state.setdefault(s, {})
        fresh = []
        for t, v in sig[s].items():
            prev = last.get(t)
            gap = len(td[(td > pd.Timestamp(prev)) & (td <= d)]) if prev else None
            if prev is None or gap >= SPACING: fresh.append(t)
        fresh = sorted(fresh, key=lambda t: -caps.get(t, 0))
        hdr = [f"## {s} sleeve: {len(fresh)} new alert(s), {len(sig[s])} name(s) now >= {DROP:.0%} behind {bench}", ""]
        L += hdr; P += hdr
        if fresh:
            todo = True
            room = None
            if H is not None:
                V = sv[s]; names_val = H[(H.sleeve == s) & ~H.ticker.isin([s, "PSQ"])].groupby("ticker").value.sum()
                room = max(0.0, CAP_TOT * V - names_val.sum())
                L.append(f"Sleeve ${V:,.0f}; in names ${names_val.sum():,.0f}; room ${room:,.0f}; step ${STEP * V:,.0f}.")
                L.append("")
            th = [f"| buy | name | behind {bench} | market cap | amount | price |", "|---|---|---|---|---|---|"]
            L += th; P += th
            for t in fresh:
                if H is not None:
                    held = H[(H.sleeve == s) & (H.ticker == t)].value.sum()
                    x = max(0.0, min(STEP * sv[s], CAP_NAME * sv[s] - held, room)); room -= x
                    amt = f"${x:,.0f}" + ("" if x > 0 else " (no room: skip)")
                else:
                    amt = f"{STEP:.0%} of sleeve"
                row = f"| {t} | {meta.name.get(t, '')} | {sig[s][t]:+.0%} | ${caps.get(t, np.nan):,.0f}B | {{}} | {close[t].dropna().iloc[-1]:,.2f} |"
                L.append(row.format(amt)); P.append(row.format(f"{STEP:.0%} of sleeve"))
                last[t] = str(d.date())
            L.append(""); P.append("")
        others = [t for t in sig[s].index if t not in fresh]
        if others:
            ln = [f"Already alerted, still behind (no action): {', '.join(f'{t} {sig[s][t]:+.0%}' for t in others)}", ""]
            L += ln; P += ln

    # January: trim and rebalance
    if (d.month == 1 and state.get("january_done") != d.year) or os.getenv("FORCE_JANUARY"):
        todo = True; state["january_done"] = d.year
        L += ["## January: trim and rebalance", ""]
        P += ["## January: trim and rebalance", "", "Trim names to 10% of the sleeve and 40% in names; rebalance the sleeves to 50/50 "
              "(dollar amounts in the e-mail).", ""]
        if H is None:
            L.append("Trim any name above 10% of its sleeve to 10%; if a sleeve's names exceed 40% of it, scale them down to 40%. "
                     "Then move money between QQQ and SMH so the two sleeves are equal.")
        else:
            for s in ("QQQ", "SMH"):
                V = sv[s]; g = H[(H.sleeve == s) & ~H.ticker.isin([s, "PSQ"])].groupby("ticker").value.sum()
                for t, v in g[g > CAP_NAME * V].items():
                    L.append(f"- {s} sleeve: sell ${v - CAP_NAME * V:,.0f} of {t} into {s}")
                if g.clip(upper=CAP_NAME * V).sum() > CAP_TOT * V:
                    L.append(f"- {s} sleeve: names exceed 40%; sell {1 - CAP_TOT * V / g.clip(upper=CAP_NAME * V).sum():.0%} of each into {s}")
            gap = (sv["QQQ"] - sv["SMH"]) / 2
            L.append(f"- Rebalance: move ${abs(gap):,.0f} from {'QQQ to SMH' if gap > 0 else 'SMH to QQQ'}.")
        L.append("")
    if d.day <= 3 and len(td[(td.month == d.month) & (td.year == d.year)]) == 1:
        L += ["## Monthly deposit", "", "Put half of this month's deposit into QQQ and half into SMH.", ""]
        P += ["## Monthly deposit", "", "Put half of this month's deposit into QQQ and half into SMH.", ""]
        todo = True
    foot = ["---", f"Rules: alerts are {STEP:.0%} of the sleeve, max {CAP_NAME:.0%} per name, {CAP_TOT:.0%} in names per sleeve; "
            f"re-alert after {SPACING} trading days. Caps use SEC share counts refreshed quarterly. Not investment advice."]
    L += foot; P += foot

    os.makedirs(OUT, exist_ok=True); os.makedirs(os.path.dirname(STATE), exist_ok=True)
    md, pub = "\n".join(L) + "\n", "\n".join(P) + "\n"
    if offline: OUTP = "/tmp" if not os.getenv("ALERTS_OUT") else os.getenv("ALERTS_OUT")
    else: OUTP = OUT
    open(f"{OUTP}/latest.md", "w").write(md if offline else pub)        # committed copy: public data only
    if not offline: json.dump(state, open(STATE, "w"), indent=1, sort_keys=True)
    html = md_to_html(md); open(f"{OUTP}/latest.html", "w").write(html if offline else md_to_html(pub))
    print(md if offline else pub)                                    # the run log of a public repository is public
    if os.getenv("ALERTS_DRY"): print("--- e-mail (dry run) ---"); print(md); return
    if (todo or d.weekday() == 0) and not offline:
        from email_report import send_mail
        send_mail(f"Plan alerts {d:%Y-%m-%d}" + (" - action needed" if todo else ""), html)

def md_to_html(md):
    out, in_table = [], False
    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "): continue
            if not in_table: out.append('<table border="1" cellpadding="4" style="border-collapse:collapse">'); in_table = True
            out.append("<tr>" + "".join(f"<td>{c.replace('**', '')}</td>" for c in cells) + "</tr>"); continue
        if in_table: out.append("</table>"); in_table = False
        if line.startswith("## "): out.append(f"<h3>{line[3:]}</h3>")
        elif line.startswith("# "): out.append(f"<h2>{line[2:]}</h2>")
        elif line.startswith("- "): out.append(f"<div>&bull; {line[2:]}</div>")
        elif line.strip() == "---": out.append("<hr>")
        elif line.strip(): out.append(f"<p>{line.replace('**', '')}</p>")
    if in_table: out.append("</table>")
    return "<html><body style='font-family:sans-serif'>" + "\n".join(out) + "</body></html>"

if __name__ == "__main__":
    main(offline="--offline" in sys.argv)
