"""Daily alerts for the plan (strategy A): QQQ/SMH sleeves with laggard buys, a WU hedge on margin, 70/30 next to a
discretionary stock-pick bucket. Rules in docs/PLAN.md.

  Account      ETF_SHARE (70%) runs the plan in two equal sleeves; the rest (30%) is the PICKS bucket (your own stock
               picks, not traded by these alerts, but counted and hedged).
  QQQ sleeve   parked in QQQ; alert when a chip/tech name of $50bn+ closes >= 30% below its 252-day high relative to QQQ
  SMH sleeve   parked in SMH; alert when one of the 25 largest chip names closes >= 30% below its 252-day high vs SMH
  Each alert = buy STEP (2%) of that sleeve the same day: from cash first, the rest on margin (the "bridge" loan),
  repaid at the next monthly deposit. Nothing is sold on an alert day. Caps 10% of the sleeve per name, 40% in names;
  a name re-alerts only after 63 trading days; largest caps fill first when room is short. Orders under MIN_TRADE
  ($500) are skipped. Names are held.
  Monthly       first trading day: the deposit repays the margin loan first (hedge loan, then bridge), then the plan's
               share goes to the more underweight sleeve's ETF (one order) and the picks' share stays as cash. If the
               bridge is not cleared, sell that much ETF from the more overweight sleeve.
  Hedge        WU SP500 Hedging Signal only. On: keep everything and buy PSQ on margin worth 50% of each sleeve (SMH:
               beta/2, capped at 50%) and 50% of the picks; the total loan is capped at LOAN_CAP (50%) of the
               account's long holdings. Off: sell all PSQ, repay the loan, put anything left into the more underweight
               ETF. The WU state comes from
    WU_HEDGE        repository variable "on" / "off", set by hand (overrides everything when set); with a date
                    ("on 2026-10-14") it only seeds the state and a newer alert e-mail takes over
    WU e-mail       else the newest TradingView WU alert e-mail with WU_HEDGE=on / off, read over IMAP (wu_mail.py);
                    the last one seen is kept in the private state, so a quiet spell keeps the hedge as it is
  With no WU state the hedge is left as it is. The Nasdaq breadth signal (breadth_live.py, BREADTH_PARAMS) is shown
  for information only.
  January      trim names above 10% of the sleeve / 40% in names (slices under MIN_TRADE skipped), rebalance the
               sleeves to 50/50 and the account toward ETF_SHARE, selling ETF first; set the tax aside.
  Guardrails   every report with HOLDINGS: loan / long holdings (warn above LOAN_CAP), estimated excess liquidity at
               a 30% requirement (warn below 20% of holdings), any name above 10% of the whole account.
  Every report opens with a verdict: no action, or a numbered list of today's orders (same ticker netted across
  sleeves). Dollar amounts and the hedge are in the e-mail only; the committed copy and the run log are public.

Inputs (all optional except prices):
  results/universe/        tickers, SIC, share counts and splits (build_tech_universe.py, refreshed quarterly)
  HOLDINGS                 secret, CSV "sleeve,ticker,shares": sleeve QQQ or SMH (the ETF and that sleeve's names),
                           PICKS (your own picks), PSQ on any sleeve, and one row "CASH,USD,<dollars>" for the USD
                           cash balance (negative = margin loan). With it the report prints dollar amounts and share
                           counts; without it, percentages.
  ETF_SHARE                variable, the plan's share of the account (default 0.70); MONTHLY_DEPOSIT (default 4000)
  BREADTH_PARAMS           secret, breadth calibration and levels (see breadth_live.py)
  SMTP_HOST/PORT/USER/PASS, MAIL_TO   e-mail (sent when there is something to do, or on Mondays)
  NTFY_TOPIC               secret, optional phone push via ntfy.sh on action days (the topic name is the password)
  DISCORD_WEBHOOK          secret, optional push to a Discord channel webhook on action days
State: state/plan_alerts.json (last alert per sleeve and name, January done). Private state (workflow cache, never
committed): WU state, hedge on/off, the hedge loan and the bridge loan. Report: results/alerts/latest.md.

python plan_alerts.py            # live, Yahoo prices
python plan_alerts.py --offline  # from the price files already in results/ (for testing; FORCE_JANUARY / FORCE_MONTHLY)
"""
import io, json, os, re, sys, glob
import numpy as np
import pandas as pd
from tech_caps import daily_caps

STEP, CAP_NAME, CAP_TOT, FLOOR_B, TOP_N, DROP, SPACING = 0.02, 0.10, 0.40, 50.0, 25, 0.30, 63
MIN_TRADE, LOAN_CAP, MAINT, EXCESS_WARN, BOOK_CAP = 500.0, 0.50, 0.30, 0.20, 0.10
ETF_SHARE = float(os.getenv("ETF_SHARE", "0.70") or 0.70)
DEPOSIT = float(os.getenv("MONTHLY_DEPOSIT", "4000") or 4000)
IOF_HEDGE = float(os.getenv("IOFUND_HEDGE", "") or 0)   # I/O Fund's hedge as a share of its book in SMH terms (e.g. 0.75); 0 = off
UNI, STATE, OUT = "results/universe", "state/plan_alerts.json", "results/alerts"
PRIVATE = "state/private.json"        # hedge state and loans: kept in the workflow cache, never committed (public repo)
CHIP_SIC = {3674}
SLEEVES = ("QQQ", "SMH")

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
        px_t = close[t].dropna()
        if px_t.empty: continue                                       # a failed download (Yahoo hiccup): skip the name today
        c = daily_caps(px_t, s, g[["end", "shares"]], meta.adr_ratio.get(t, 1.0))
        if len(c): out[t] = c.iloc[-1]
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
    """HOLDINGS secret -> (frame of positions, cash). Cash row: sleeve CASH or ticker CASH/USD, shares = dollars."""
    raw = os.getenv("HOLDINGS", "").strip()
    if not raw: return None, 0.0
    h = pd.read_csv(io.StringIO(raw)); h.columns = [c.strip().lower() for c in h.columns]
    h["sleeve"] = h.sleeve.astype(str).str.upper().str.strip(); h["ticker"] = h.ticker.astype(str).str.upper().str.strip()
    is_cash = (h.sleeve == "CASH") | h.ticker.isin(["CASH", "USD"])
    cash = float(h[is_cash].shares.sum()); h = h[~is_cash].copy()
    live = [adj_close[t].dropna().iloc[-1] if t in adj_close else np.nan for t in h.ticker]
    h["price"] = h["price"].astype(float).where(h["price"].notna(), live) if "price" in h else live   # optional price column
    h["value"] = h.shares * h.price
    return h, cash

def iofund_picks():
    """IOFUND_PICKS secret: one "TICKER weight%" per line (commas, colons or spaces) -> {ticker: weight as a fraction}."""
    out = {}
    for t, w in re.findall(r"([A-Za-z][A-Za-z.\-]{0,9})\s*[,:;\s]\s*([\d.]+)\s*%?", os.getenv("IOFUND_PICKS", "")):
        if t.lower() in ("ticker", "weight"): continue
        out[t.upper()] = float(w) / 100.0
    return out

class Book:
    """Dollar view of the account from HOLDINGS: sleeves, picks, PSQ, cash, loan, targets and guardrails."""
    def __init__(s, H, cash):
        s.H, s.cash = H, cash
        s.sv = {k: H[(H.sleeve == k) & (H.ticker != "PSQ")].value.sum() for k in SLEEVES}
        s.picks = H[(H.sleeve == "PICKS") & (H.ticker != "PSQ")].value.sum()
        plan_psq = (H.ticker == "PSQ") & (H.sleeve != "IOHEDGE"); io_psq = (H.ticker == "PSQ") & (H.sleeve == "IOHEDGE")
        s.psq = H[plan_psq].value.sum(); s.psq_sh = H[plan_psq].shares.sum()        # the plan's WU hedge
        s.io_psq = H[io_psq].value.sum(); s.io_psq_sh = H[io_psq].shares.sum()      # I/O Fund hedge: yours, not traded here
        s.loan = max(0.0, -cash); s.free = max(0.0, cash)
        s.longs = s.sv["QQQ"] + s.sv["SMH"] + s.picks + s.psq + s.io_psq
        s.equity = s.longs + cash
        s.base = s.equity                                              # 70/30 targets on net liquidation: while hedged, the PSQ
                                                                       # bought with pick cash nets against the loan
        s.tgt = {k: ETF_SHARE / 2 * s.base for k in SLEEVES}; s.tgt_picks = (1 - ETF_SHARE) * s.base
    def names(s, k):                                                   # a sleeve's laggard names (not its ETF)
        return s.H[(s.H.sleeve == k) & ~s.H.ticker.isin([k, "PSQ"])].groupby("ticker").value.sum()
    def under(s):                                                      # the sleeve furthest below its target
        return min(SLEEVES, key=lambda k: s.sv[k] - s.tgt[k])
    def over(s):
        return max(SLEEVES, key=lambda k: s.sv[k] - s.tgt[k])
    def guard(s, loan=None, longs=None):
        loan = s.loan if loan is None else loan; longs = s.longs if longs is None else longs
        eq = longs - loan; exc = eq - MAINT * longs
        return dict(loan=loan, longs=longs, ratio=loan / longs if longs else 0.0, excess=exc, exc_ratio=exc / longs if longs else 1.0)

def guard_lines(g, when=""):
    out = [f"Margin{when}: loan ${g['loan']:,.0f} = {g['ratio']:.0%} of holdings (limit {LOAN_CAP:.0%}); "
           f"excess liquidity at a {MAINT:.0%} requirement about ${g['excess']:,.0f} ({g['exc_ratio']:.0%} of holdings)."]
    if g["ratio"] > LOAN_CAP: out.append(f"**Over the {LOAN_CAP:.0%} loan limit: reduce PSQ or add cash.**")
    elif g["exc_ratio"] < EXCESS_WARN: out.append(f"**Excess liquidity under {EXCESS_WARN:.0%} of holdings: reduce PSQ or add cash.**")
    return out

def main(offline=False):
    meta0 = pd.read_csv(f"{UNI}/tech_meta.csv")
    adj, close, new_splits = load_prices(offline, list(meta0.ticker))
    caps, meta = caps_now(close, new_splits)
    d, sig = signals(adj, caps, meta)
    td = adj.index
    state = json.load(open(STATE)) if os.path.exists(STATE) else {"QQQ": {}, "SMH": {}}
    if offline: state = {"QQQ": {}, "SMH": {}}                       # a test run never reads or writes the live state
    priv = json.load(open(PRIVATE)) if os.path.exists(PRIVATE) and not offline else {}
    # WU_HEDGE "on" / "off" overrides everything; "on 2026-10-14" (with a date) only seeds the state, and a newer
    # TradingView alert e-mail takes over from it
    m = re.fullmatch(r"(on|off)(?:[\s@]+(\d{4}-\d{2}-\d{2}))?", os.getenv("WU_HEDGE", "").strip().lower())
    wu = m.group(1) if m and not m.group(2) else None
    wu_src = "WU, WU_HEDGE variable" if wu else None
    if m and m.group(2) and m.group(2) > priv.get("wu_date", ""):
        priv["wu"], priv["wu_date"], priv["wu_from"] = m.group(1), m.group(2), "WU_HEDGE variable"
    if wu is None and not offline:                                   # else the newest TradingView WU alert e-mail
        try:
            import wu_mail
            got = wu_mail.latest()
            if got and f"{got[1]:%Y-%m-%d}" >= priv.get("wu_date", ""):
                priv["wu"], priv["wu_date"], priv["wu_from"] = got[0], f"{got[1]:%Y-%m-%d}", "TradingView alert e-mail"
            print("WU alert e-mails:", "read" if got else "none found")
        except Exception as e:
            print("WU alert e-mails unavailable:", type(e).__name__)
    if wu is None and priv.get("wu") in ("on", "off"):
        wu, wu_src = priv["wu"], f"WU, {priv.get('wu_from', 'TradingView alert e-mail')} of {priv.get('wu_date', '?')}"
    br = None
    try:
        import breadth_live
        if breadth_live.params() is not None:
            br = breadth_live.signal(None if offline else breadth_live.update_counts())
    except Exception as e:
        print("breadth signal unavailable:", str(e)[:200])
    r = np.log(adj[["QQQ", "SMH"]]).diff().iloc[-1260:]
    beta = r.SMH.cov(r.QQQ) / r.QQQ.var()
    frac = {"QQQ": 0.5, "SMH": min(0.5, beta / 2), "PICKS": 0.0 if IOF_HEDGE > 0 else 0.5}
    io_frac = IOF_HEDGE * beta                                       # I/O Fund's SMH hedge, in PSQ (QQQ) terms
    H, cash = holdings(close)
    B = Book(H, cash) if H is not None else None
    px = lambda t: close[t].dropna().iloc[-1]
    L = [f"# Plan alerts, {d:%A %Y-%m-%d}", ""]
    P = list(L)
    orders = {}                                                      # ticker -> signed dollars today (netted across sleeves)
    acts, pub_acts = [], []                                          # today's to-do list (private / public wording)
    todo = False
    hedge_loan, bridge = float(priv.get("hedge_loan", 0.0)), float(priv.get("bridge", 0.0))
    io_loan = 0.0
    if B is not None:                                                # the loans cannot exceed what IBKR shows
        if "hedge_loan" not in priv and B.psq_sh > 0: hedge_loan = min(B.loan, B.psq)   # no record yet: PSQ was bought on margin
        hedge_loan = min(hedge_loan, B.loan)
        io_loan = min(B.io_psq, max(0.0, B.loan - hedge_loan))         # margin behind the I/O Fund hedge: never "settled"
        bridge = min(bridge, max(0.0, B.loan - hedge_loan - io_loan))
    borrow_today = 0.0
    def order(t, x, why):
        orders[t] = orders.get(t, 0.0) + x
        return f"{'buy' if x > 0 else 'sell'} ${abs(x):,.0f} of {t} ({abs(x) / px(t):,.1f} sh at {px(t):,.2f}): {why}"
    month_start = (d.day <= 3 and len(td[(td.month == d.month) & (td.year == d.year)]) == 1) or bool(os.getenv("FORCE_MONTHLY"))
    january = (d.month == 1 and state.get("january_done") != d.year) or bool(os.getenv("FORCE_JANUARY"))

    # ---- allocation (e-mail only)
    if B is not None:
        L += ["## Account", ""]
        L.append(f"| | value | target | |\n|---|---|---|---|")
        for k in SLEEVES:
            nm = B.names(k).sum()
            L.append(f"| {k} sleeve | ${B.sv[k]:,.0f} | ${B.tgt[k]:,.0f} | ETF ${B.sv[k] - nm:,.0f}, names ${nm:,.0f} ({nm / B.sv[k] if B.sv[k] else 0:.0%} of the sleeve) |")
        L.append(f"| Picks | ${B.picks:,.0f} | ${B.tgt_picks:,.0f} | {(1 - ETF_SHARE):.0%} bucket; cash for picks counts here |")
        L.append(f"| PSQ hedge | ${B.psq:,.0f} | | {B.psq_sh:,.0f} sh (WU hedge) |")
        if B.io_psq_sh > 0 or IOF_HEDGE > 0:
            L.append(f"| PSQ, I/O Fund hedge | ${B.io_psq:,.0f} | " + (f"${io_frac * B.picks:,.0f}" if IOF_HEDGE > 0 else "") + f" | {B.io_psq_sh:,.0f} sh; covers the picks; sold with the WU hedge |")
        L.append(f"| Cash | ${cash:,.0f} | | {'margin loan' if cash < 0 else 'available'} |")
        L.append(f"| Equity | ${B.equity:,.0f} | | holdings ${B.longs:,.0f} |")
        L.append("")
        L += guard_lines(B.guard()); L.append("")
        allv = B.H[B.H.ticker != "PSQ"].groupby("ticker").value.sum()
        big = allv[(allv > BOOK_CAP * B.base) & ~allv.index.isin(SLEEVES)]
        for t, v in big.items():
            L.append(f"Note: {t} is {v / B.base:.0%} of the account across sleeves and picks (above {BOOK_CAP:.0%}); the caps are per sleeve, so this is for your judgement.")
        if len(big): L.append("")

    # ---- hedge: WU only. PSQ bought on margin: 50% of each sleeve (beta/2 for SMH) and 50% of the picks
    psq_held = B is not None and B.psq_sh > 0
    any_psq = B is not None and (B.psq_sh + B.io_psq_sh) > 0          # the I/O Fund hedge follows WU too: it exits with it
    want = (wu == "on") if wu else None
    prev = priv.get("hedge_on")
    P += ["## Hedge", "", "The hedge instructions are in the e-mail only (this file and the run log are public).", ""]
    L += ["## Hedge (PSQ)", ""]
    def psq_target(b):
        return frac["QQQ"] * b.sv["QQQ"] + frac["SMH"] * b.sv["SMH"] + frac["PICKS"] * b.picks
    def psq_buy(b, tgt):
        """PSQ to buy so the loan stays within LOAN_CAP of holdings: cash first, then margin."""
        if tgt <= b.free: return tgt, 0.0
        cap = max(b.free, b.longs - 2 * b.loan + 2 * b.free)         # L + (P - c) <= LOAN_CAP (longs + P), LOAN_CAP = 0.5
        p = min(tgt, cap); return p, max(0.0, p - b.free)
    if want is None:
        L.append("No WU signal yet (set up the TradingView alert e-mails, or the WU_HEDGE variable); no hedge change"
                 + (f" -- the hedge stays {'ON' if prev else 'OFF'}." if prev is not None else "."))
    else:
        need = None
        if B is not None: need = "on" if want and not psq_held else "off" if not want and any_psq else None
        elif prev is None or bool(prev) != bool(want): need = "on" if want else "off"
        if need == "on":
            todo = True
            txt = (f"Hedge ON ({wu_src}): keep everything; buy PSQ worth {frac['QQQ']:.0%} of the QQQ sleeve, {frac['SMH']:.0%} of the "
                   f"SMH sleeve (SMH beta {beta:.2f}) and " + (f"{io_frac:.0%} of the picks (I/O Fund's {IOF_HEDGE:.0%} SMH hedge)" if IOF_HEDGE > 0
                   else f"{frac['PICKS']:.0%} of the picks") + ", on margin.")
            L.append(f"**{txt}**")
            if B is not None:
                io_t = io_frac * B.picks if IOF_HEDGE > 0 else 0.0
                tgt = psq_target(B) + io_t; p, borrow = psq_buy(B, tgt)
                if io_t > 0: L.append(f"- of which ${io_t * p / tgt:,.0f} is the I/O Fund hedge: list those shares under IOHEDGE in HOLDINGS")
                L.append("- " + order("PSQ", p, f"{'the full hedge' if p >= tgt - 1 else f'cut from ${tgt:,.0f} by the {LOAN_CAP:.0%} loan limit'}; "
                                                f"${p - borrow:,.0f} from cash, ${borrow:,.0f} borrowed"))
                L += guard_lines(B.guard(B.loan + borrow, B.longs + p), " after")
                hedge_loan += borrow
            acts.append(f"Hedge ON: buy PSQ on margin")
        elif need == "off":
            todo = True
            txt = (f"Hedge OFF ({wu_src}): sell all PSQ" + (" (the WU hedge and the I/O Fund hedge)" if B is not None and B.io_psq_sh > 0 else "")
                   + ", repay the margin loan, put anything left toward the ETF target, the rest stays as pick cash.")
            L.append(f"**{txt}**")
            if B is not None:
                allp = B.psq + B.io_psq
                L.append("- " + order("PSQ", -allp, "the whole hedge" + (f" ({B.psq_sh:,.0f} WU + {B.io_psq_sh:,.0f} I/O Fund shares)" if B.io_psq_sh > 0 else "")))
                repay = min(allp, B.loan); left = allp - repay
                L.append(f"- repay ${repay:,.0f} of the loan (it happens by itself: the sale credits USD cash)")
                short = max(0.0, sum(B.tgt[k] - B.sv[k] for k in SLEEVES))   # the ETFs' gap to 70%; the rest is pick cash
                x = min(left, short)
                if x >= MIN_TRADE: L.append("- " + order(B.under(), x, "leftover PSQ proceeds into the more underweight sleeve, up to the ETF target"))
                else: x = 0.0
                if left - x >= 1: L.append(f"- ${left - x:,.0f} stays as cash for your picks (the ETFs are at target)")
                L += guard_lines(B.guard(B.loan - repay, B.longs - allp + x), " after")
            hedge_loan = 0.0
            acts.append("Hedge OFF: sell PSQ, repay the loan")
        else:
            L.append(f"Hedge stays {'ON' if want else 'OFF'} ({wu_src})" + ("; holdings match." if B is not None else "."))
            if want and B is not None:                               # top up for picks / names bought since it went on
                tgt = psq_target(B); short = tgt - B.psq
                if short > max(MIN_TRADE, 0.05 * tgt):
                    p, borrow = psq_buy(B, short); todo = True
                    L.append("- " + order("PSQ", p, f"top-up: the hedge target is ${tgt:,.0f} and you hold ${B.psq:,.0f}; ${p - borrow:,.0f} from cash, ${borrow:,.0f} borrowed"))
                    hedge_loan += borrow; acts.append("Hedge top-up: buy PSQ")
                elif short < -max(MIN_TRADE, 0.10 * tgt):
                    L.append(f"- PSQ is ${-short:,.0f} above the ${tgt:,.0f} target; no trade (the hedge is not trimmed while on).")
                if IOF_HEDGE > 0:                                    # the picks' hedge, sized like I/O Fund's
                    io_t = io_frac * B.picks; io_short = io_t - B.io_psq
                    if io_short > max(MIN_TRADE, 0.05 * io_t):
                        p, borrow = psq_buy(B, io_short); todo = True
                        L.append("- " + order("PSQ", p, f"I/O Fund hedge top-up: target ${io_t:,.0f} ({io_frac:.0%} of the picks), you hold ${B.io_psq:,.0f}; "
                                                        f"add the shares to the IOHEDGE row"))
                        acts.append("I/O Fund hedge top-up: buy PSQ")
                    elif io_short < -max(MIN_TRADE, 0.10 * io_t):
                        L.append(f"- I/O Fund hedge is ${-io_short:,.0f} above its ${io_t:,.0f} target; no trade.")
        if want != prev: priv["hedge_on"], priv["hedge_since"] = bool(want), str(d.date())
    if br:
        agree = "" if wu is None else ("; agrees with WU" if (wu == "on") == br["on"] else "; differs from WU")
        L.append(f"Breadth signal, for information (not traded): {'ON' if br['on'] else 'OFF'} since {br['since'].date() if br['since'] is not None else '-'} "
                 f"(lines {br['orange']:,.0f} / {br['blue']:,.0f} on {br['date'].date()}){agree}.")
    if wu: L.append(f"WU: {wu.upper()} ({wu_src}).")
    L.append("")

    # ---- I/O Fund picks vs what you hold (e-mail only: the list is a paid service's portfolio)
    io = iofund_picks()
    if io and B is not None:
        budget = (1 - ETF_SHARE) * B.equity
        held = B.H[(B.H.sleeve == "PICKS") & (B.H.ticker != "PSQ")].groupby("ticker").value.sum()
        rows = sorted(((t, w, w * budget, held.get(t, 0.0)) for t, w in io.items()), key=lambda r: -(r[2] - r[3]))
        missing = [r for r in rows if r[3] < 1 and r[2] >= MIN_TRADE]
        L += ["## I/O Fund picks", "", f"Picks budget ${budget:,.0f} ({1 - ETF_SHARE:.0%} of the account); invested ${held.sum():,.0f}.", ""]
        L += ["| ticker | I/O weight | target | you hold | to buy |", "|---|---|---|---|---|"]
        for t, w, tg, h in rows:
            L.append(f"| {t} | {w:.1%} | ${tg:,.0f} | ${h:,.0f} | " + (f"${tg - h:,.0f}" if tg - h >= 1 else "-") + " |")
        extra = [t for t in held.index if t not in io]
        L.append("")
        if extra: L.append(f"You hold picks that are not in I/O Fund's list: {', '.join(extra)} (sold or never in their portfolio; your call).")
        small = [r[0] for r in rows if r[3] < 1 and r[2] < MIN_TRADE]
        if small: L.append(f"Not held, but under ${MIN_TRADE:,.0f} at your size: {', '.join(small)}.")
        L.append("")
        if missing:
            todo = True; acts.append(f"I/O Fund picks you don't hold: {', '.join(f'{t} ${tg:,.0f}' for t, w, tg, h in missing)}")
            pub_acts.append("I/O Fund picks: see the e-mail")

    # ---- laggard alerts: buy today, cash first, the rest on margin
    buys_today = 0.0
    for s, bench in (("QQQ", "QQQ"), ("SMH", "SMH")):
        last = state.setdefault(s, {})
        fresh = []
        for t, v in sig[s].items():
            prev_d = last.get(t)
            gap = len(td[(td > pd.Timestamp(prev_d)) & (td <= d)]) if prev_d else None
            if prev_d is None or gap >= SPACING: fresh.append(t)
        fresh = sorted(fresh, key=lambda t: -caps.get(t, 0))
        hdr = [f"## {s} sleeve: {len(fresh)} new alert(s), {len(sig[s])} name(s) now >= {DROP:.0%} behind {bench}", ""]
        L += hdr; P += hdr
        if fresh:
            todo = True
            pub_acts.append(f"{s} sleeve: buy {len(fresh)} stock(s) ({', '.join(fresh)})")
            room = None
            if B is not None:
                V = B.sv[s]; nm = B.names(s); room = max(0.0, CAP_TOT * V - nm.sum())
                L.append(f"Sleeve ${V:,.0f}; in names ${nm.sum():,.0f}; room ${room:,.0f}; step ${STEP * V:,.0f}.")
                L.append("")
            th = [f"| buy | name | behind {bench} | market cap | amount | price |", "|---|---|---|---|---|---|"]
            L += th; P += th
            for t in fresh:
                if B is not None:
                    held = B.names(s).get(t, 0.0)
                    x = max(0.0, min(STEP * B.sv[s], CAP_NAME * B.sv[s] - held, room))
                    if x < 1: amt = "$0 (no room: skip)"; x = 0.0          # laggard buys are never skipped for size
                    else: amt = f"${x:,.0f}"; room -= x; buys_today += x; orders[t] = orders.get(t, 0.0) + x
                else:
                    amt = f"{STEP:.0%} of sleeve"
                row = f"| {t} | {meta.name.get(t, '')} | {sig[s][t]:+.0%} | ${caps.get(t, np.nan):,.0f}B | {{}} | {px(t):,.2f} |"
                L.append(row.format(amt)); P.append(row.format(f"{STEP:.0%} of sleeve"))
                last[t] = str(d.date())
            L.append(""); P.append("")
        others = [t for t in sig[s].index if t not in fresh]
        if others:
            ln = [f"Already alerted, still behind (no action): {', '.join(f'{t} {sig[s][t]:+.0%}' for t in others)}", ""]
            L += ln; P += ln
    if buys_today > 0 and B is not None:
        c = B.free; borrow = max(0.0, buys_today - c)
        L += ["## Paying for today's buys", "", f"Total ${buys_today:,.0f}: ${min(c, buys_today):,.0f} from cash, ${borrow:,.0f} on margin "
              f"(repaid at the next monthly deposit; nothing is sold today)."]
        L += guard_lines(B.guard(B.loan + borrow, B.longs + buys_today), " after"); L.append("")
        borrow_today = borrow
    lag_names = [t for t, x in orders.items() if x > 0 and t not in ("PSQ", "QQQ", "SMH")]
    if lag_names: acts.append(f"Laggards: buy {len(lag_names)} stock(s) ({', '.join(lag_names)}), cash first then margin")
    elif pub_acts and B is None: acts += [f"{a} -- {STEP:.0%} of the sleeve each" for a in pub_acts]
    elif pub_acts: acts.append("Laggard alerts with no room in the sleeve: nothing to buy")

    # ---- monthly deposit and settlement
    if month_start:
        todo = True
        L += ["## Monthly deposit and settlement", ""]; P += ["## Monthly deposit", "", f"Deposit: repay any margin loan first, then {ETF_SHARE:.0%} to the more "
                                                                        f"underweight sleeve's ETF and {1 - ETF_SHARE:.0%} to the picks' cash.", ""]
        if B is None:
            L.append(f"Deposit ${DEPOSIT:,.0f}: repay any margin loan first; then {ETF_SHARE:.0%} of what is left into the more underweight "
                     f"sleeve's ETF and {1 - ETF_SHARE:.0%} kept as cash for picks. If a laggard loan remains, sell that much ETF.")
        else:
            repay = min(DEPOSIT, B.loan); rest = DEPOSIT - repay; n = 1
            hl2 = max(0.0, hedge_loan - repay); br2 = max(0.0, B.loan - repay - hl2 - io_loan)
            L.append(f"{n}. Deposit ${DEPOSIT:,.0f}" + (f"; ${repay:,.0f} repays the loan (hedge loan left ${hl2:,.0f}, laggard loan left ${br2:,.0f})." if repay > 0 else ".")); n += 1
            etf_part, pick_part = ETF_SHARE * rest, (1 - ETF_SHARE) * rest
            if etf_part >= MIN_TRADE:
                u = B.under(); L.append(f"{n}. " + order(u, etf_part, f"the plan's {ETF_SHARE:.0%} of the deposit, into the more underweight sleeve")); n += 1
            elif rest > 0: L.append(f"{n}. ${etf_part:,.0f} for the ETFs is under ${MIN_TRADE:,.0f}: leave it as cash for next month."); n += 1
            if pick_part > 0: L.append(f"{n}. ${pick_part:,.0f} stays as cash for your picks."); n += 1
            if br2 >= MIN_TRADE:
                o = B.over(); L.append(f"{n}. " + order(o, -br2, "clear the laggard loan: sell ETF from the more overweight sleeve"))
                acts.append(f"Monthly settlement: sell ${br2:,.0f} of {o} to clear the laggard loan"); br2 = 0.0
            hedge_loan, bridge = hl2, br2 + borrow_today
        L.append("")
        acts.append(f"Monthly deposit ${DEPOSIT:,.0f}: repay the loan first, then {ETF_SHARE:.0%} to the underweight ETF, {1 - ETF_SHARE:.0%} to pick cash")
        pub_acts.append("Monthly deposit")

    # ---- January: tax, trims, rebalance
    if january:
        todo = True; state["january_done"] = d.year
        acts.append("January: set the tax aside, trim names to the caps, rebalance the sleeves 50/50"); pub_acts.append("January: trim and rebalance")
        L += ["## January: tax, trim and rebalance", ""]
        P += ["## January: trim and rebalance", "", f"Trim names to {CAP_NAME:.0%} of the sleeve and {CAP_TOT:.0%} in names; rebalance the sleeves to 50/50 and the "
              f"account toward {ETF_SHARE:.0%} / {1 - ETF_SHARE:.0%} (dollar amounts in the e-mail).", ""]
        L.append("1. Tax: add up last year's realized gains (PSQ sales, trims, rebalances) and margin interest; set 27% of the net gain aside.")
        if B is None:
            L.append(f"2. Trim any name above {CAP_NAME:.0%} of its sleeve to {CAP_NAME:.0%}; if a sleeve's names exceed {CAP_TOT:.0%}, scale them down. "
                     "3. Move money between QQQ and SMH so the sleeves are equal; use deposits first to bring the account back to "
                     f"{ETF_SHARE:.0%} / {1 - ETF_SHARE:.0%}.")
        else:
            n = 2
            for s in SLEEVES:
                V = B.sv[s]; g = B.names(s); freed = 0.0
                for t, v in g[g > CAP_NAME * V].items():
                    x = v - CAP_NAME * V
                    if x >= MIN_TRADE: L.append(f"{n}. " + order(t, -x, f"trim to {CAP_NAME:.0%} of the {s} sleeve")); freed += x; n += 1
                capped = g.clip(upper=CAP_NAME * V)
                if capped.sum() > CAP_TOT * V:
                    cut = capped.sum() - CAP_TOT * V; share = capped / capped.sum()
                    for t, w in share.items():
                        x = cut * w
                        if x >= MIN_TRADE: L.append(f"{n}. " + order(t, -x, f"names above {CAP_TOT:.0%} of the {s} sleeve")); freed += x; n += 1
                if freed >= MIN_TRADE: L.append(f"{n}. " + order(s, freed, "trim proceeds back into the sleeve's ETF")); n += 1
            gap = (B.sv["QQQ"] - B.sv["SMH"]) / 2
            if abs(gap) >= MIN_TRADE:
                frm, to = ("QQQ", "SMH") if gap > 0 else ("SMH", "QQQ")
                L.append(f"{n}. " + order(frm, -abs(gap), "rebalance the sleeves to 50/50 (sell the ETF, not the names)")); n += 1
                L.append(f"{n}. " + order(to, abs(gap), "rebalance the sleeves to 50/50")); n += 1
            drift = (B.sv["QQQ"] + B.sv["SMH"]) / B.base - ETF_SHARE if B.base else 0.0
            L.append(f"{n}. Plan vs picks: the plan is {ETF_SHARE + drift:.0%} of the account (target {ETF_SHARE:.0%}); "
                     + ("fine." if abs(drift) < 0.05 else "steer the next deposits to the side that is short rather than selling."))
        L.append("")

    # ---- verdict and footer
    def verdict(items, extra=""):
        if not items: return ["## Today: no action", "", "Nothing to trade." + extra, ""]
        return [f"## Today: {len(items)} action(s)", ""] + [f"{i}. {a}" for i, a in enumerate(items, 1)] + [""]
    net = {t: x for t, x in orders.items() if abs(x) >= 1}; sms_lines = []
    if net:
        L += ["## Orders (netted across sleeves, sells first)", ""]
        for t, x in sorted(net.items(), key=lambda z: z[1]):
            L.append(f"- {'SELL' if x < 0 else 'BUY'} {abs(x) / px(t):,.1f} {t} at about {px(t):,.2f} (${abs(x):,.0f})")
            sms_lines.append(f"{'SELL' if x < 0 else 'BUY'} {abs(x) / px(t):,.1f} {t} ~{px(t):,.2f}")
        L.append("")
    L[2:2] = verdict(acts)
    hedge_act = any(a.startswith("Hedge") for a in acts)
    P[2:2] = verdict(pub_acts + (["Hedge change: see the e-mail"] if hedge_act else []))
    foot = ["---", f"Rules: alerts are {STEP:.0%} of the sleeve, max {CAP_NAME:.0%} per name, {CAP_TOT:.0%} in names per sleeve; re-alert after "
            f"{SPACING} trading days; orders under ${MIN_TRADE:,.0f} skipped; laggards bought on margin and repaid monthly; loan limit "
            f"{LOAN_CAP:.0%} of holdings. Caps use SEC share counts refreshed quarterly. Not investment advice."]
    L += foot; P += foot
    if not month_start: bridge += borrow_today
    priv["hedge_loan"], priv["bridge"] = round(hedge_loan, 2), round(bridge, 2)

    os.makedirs(OUT, exist_ok=True); os.makedirs(os.path.dirname(STATE), exist_ok=True)
    md, pub = "\n".join(L) + "\n", "\n".join(P) + "\n"
    OUTP = (os.getenv("ALERTS_OUT") or "/tmp") if offline else OUT
    open(f"{OUTP}/latest.md", "w").write(md if offline else pub)        # committed copy: public data only
    if not offline:
        json.dump(state, open(STATE, "w"), indent=1, sort_keys=True)
        json.dump(priv, open(PRIVATE, "w"))
    html = md_to_html(md); open(f"{OUTP}/latest.html", "w").write(html if offline else md_to_html(pub))
    print(md if offline else pub)                                    # the run log of a public repository is public
    title = f"Plan {d:%Y-%m-%d}: " + (f"{len(acts)} action(s)" if acts else "no action")
    text = sms_text(title, acts, sms_lines)
    if os.getenv("ALERTS_DRY"): print("--- e-mail (dry run) ---"); print(md); print("--- text (dry run) ---"); print(text); return
    if offline: return
    # delivery: e-mail every weekday (MAIL_DAILY, default on) or on action days and Mondays; push and text likewise
    if todo or d.weekday() == 0 or flag("MAIL_DAILY", True):
        from email_report import send_mail
        send_mail(title, html)
    if acts or flag("PUSH_DAILY", True): push(title, acts or ["No action today."])
    if acts or flag("SMS_DAILY", False): send_text(title, text)

def flag(name, default):
    v = os.getenv(name, "").strip().lower()
    return default if v == "" else v in ("1", "true", "yes", "on")

def sms_text(title, acts, lines, limit=450):
    """Short plain text for an e-mail-to-SMS gateway: the verdict, the orders, 'details in e-mail'."""
    out = [title] + ([f"- {a}" for a in acts] if acts else ["No action today."]) + lines
    s = "\n".join(out)
    if len(s) > limit: s = s[:limit - 20].rsplit("\n", 1)[0] + "\n(more in e-mail)"
    return s

def send_text(subject, body):
    """Plain-text message to SMS_TO (e-mail-to-SMS gateway addresses, comma-separated) through the same Gmail SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    to = os.getenv("SMS_TO", "").strip(); host, user, pw = os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not to or not all([host, user, pw]): return
    m = MIMEText(body, "plain"); m["Subject"], m["From"], m["To"] = subject, user, to
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
            s.starttls(); s.login(user, pw); s.sendmail(user, [a.strip() for a in to.split(",")], m.as_string())
        print("text sent")
    except Exception as e:
        print("text failed:", type(e).__name__)                     # the error text could contain the address

def push(title, acts):
    import requests
    topic, hook = os.getenv("NTFY_TOPIC", "").strip(), os.getenv("DISCORD_WEBHOOK", "").strip()
    if topic:
        try:
            requests.post(f"https://ntfy.sh/{topic}", data="\n".join(acts).encode(), timeout=20,
                          headers={"Title": title, "Tags": "chart_with_upwards_trend"}).raise_for_status()
            print("push sent")
        except Exception as e:
            print("push failed:", type(e).__name__)                      # the error text would contain the topic
    if hook:
        msg = f"**{title}**\n" + "\n".join(f"- {a}" for a in acts)
        try:
            requests.post(hook, json={"content": msg[:1990]}, timeout=20).raise_for_status()   # Discord caps at 2000
            print("discord sent")
        except Exception as e:
            print("discord failed:", type(e).__name__)                   # the error text would contain the hook URL

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
        elif re.match(r"\d+\. ", line): out.append(f"<div>{line}</div>")
        elif line.strip() == "---": out.append("<hr>")
        elif line.strip(): out.append(f"<p>{line.replace('**', '')}</p>")
    if in_table: out.append("</table>")
    return "<html><body style='font-family:sans-serif'>" + "\n".join(out) + "</body></html>"

if __name__ == "__main__":
    main(offline="--offline" in sys.argv)
