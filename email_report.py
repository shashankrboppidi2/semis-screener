"""Weekly e-mail from the published results in results/ (run after run_screens.py).

    python email_report.py            # writes results/email.html, sends it if SMTP_* / MAIL_TO are set
    python email_report.py --no-send  # just write the file

Names not on the same list in the previous run (results/prev/, saved by run_screens.py before it overwrites
the CSVs) are marked NEW. What each list has behind it comes from the book-to-bill backtest
(results/backtest_b2b/summary.md), and says so in the e-mail, so nobody reads a research list as a buy list.
"""
import json, os, smtplib, sys, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT)
RES, PREV = "results", "results/prev"
REPO = "https://github.com/shashankrboppidi2/semis-screener"
TABLE = "<table border=1 cellpadding=4 style='border-collapse:collapse;font-size:13px'>"
TOP = 15

def load(name):
    p = f"{RES}/{name}.csv"
    return pd.read_csv(p) if os.path.exists(p) else pd.DataFrame()

def prev_keys(name, cols):
    p = f"{PREV}/{name}.csv"
    if not os.path.exists(p): return None                 # first run: nothing is "new"
    d = pd.read_csv(p)
    return set(map(tuple, d[cols].astype(str).values)) if all(c in d for c in cols) else set()

def pct(x): return "" if pd.isna(x) else f"{x:+.0%}"
def num(x, f="{:,.2f}"): return "" if pd.isna(x) else f.format(x)

def table(d, cols, heads, fmt, new=None):
    if not len(d): return "<p><i>none this week</i></p>"
    h = TABLE + "<tr>" + "".join(f"<th>{c}</th>" for c in heads) + "</tr>"
    for i, r in d.iterrows():
        cells = [fmt.get(c, str)(r[c]) if c in r else "" for c in cols]
        tag = " <b style='color:#b00'>NEW</b>" if new is not None and new.get(i) else ""
        h += "<tr>" + f"<td>{cells[0]}{tag}</td>" + "".join(f"<td>{c}</td>" for c in cells[1:]) + "</tr>"
    return h + "</table>"

def section(title, note, d, cols, heads, fmt, key_cols, name):
    pk = prev_keys(name, key_cols)
    new = None if pk is None else {i: tuple(map(str, r[key_cols])) not in pk for i, r in d.iterrows()}
    n_new = 0 if new is None else sum(new.values())
    return (f"<h3>{title} ({len(d)}{f', {n_new} new' if n_new else ''})</h3><p><i>{note}</i></p>"
            + table(d.head(TOP), cols, heads, fmt, new) + (f"<p><small>top {TOP} shown; the rest are in the workbook</small></p>" if len(d) > TOP else ""))

def build():
    st = json.load(open(f"{RES}/run_status.json")) if os.path.exists(f"{RES}/run_status.json") else {"steps": {}}
    failed = [k for k, v in st["steps"].items() if v.get("rc") != 0]
    t1c = ["ticker", "name", "industry", "cqp", "rev", "b2b", "b2b_trend", "rpo_yoy", "rev_yoy"]
    t1h = ["Ticker", "Company", "Industry", "Quarter", "Revenue $m", "Book-to-bill", "B2B vs prior 3q", "RPO y/y", "Revenue y/y"]
    t1f = {"rev": lambda x: num(x, "{:,.0f}"), "b2b": num, "b2b_trend": lambda x: num(x, "{:+.2f}"), "rpo_yoy": pct, "rev_yoy": pct,
           "ticker": lambda x: "—" if pd.isna(x) else x, "industry": lambda x: "" if pd.isna(x) else str(x)[:40], "name": lambda x: str(x)[:34]}
    key = ["name"]

    html = [f"<h2>Semis SEC screens — {time.strftime('%a %d %b %Y', time.gmtime())}</h2>",
            f"<p>Run finished {st.get('finished_utc', '?')} · {len(st['steps']) - len(failed)}/{len(st['steps'])} steps ok"
            + (f" · <b style='color:#b00'>failed: {', '.join(failed)}</b>" if failed else "") + "</p>",
            "<p><b>What to trust.</b> Book-to-bill <i>level</i> is the only list signal with backtest support "
            "(rank IC +0.05 over the next quarter vs SPY, top-minus-bottom fifth +2.8%; borderline once industry clustering is allowed for, "
            "and mostly in smaller companies). The 'backlog building ahead' gate and beat-and-raise showed <b>no edge</b>. "
            "Use these as a research queue and a tiebreaker for Cipher B signals, not as buy lists.</p>"]

    # semis cycle first: the one use the handoff's own study supports
    a = load("accel_ranked")
    if len(a):
        a = a[(a.short_history == False) & (a.streak >= 2) & (a.axis != "balance")]
        up = a[a.accel > 0].head(TOP)
        html.append(section("Semis: segments accelerating", "y/y growth rising for 2+ quarters running, 8+ quarters of history, "
                            "as first reported in 10-Q/10-K. Cycle-position read, not a stock signal.", up,
                            ["ticker", "axis", "series", "cq", "yoy", "accel", "streak", "share"],
                            ["Ticker", "Cut", "Series", "Quarter", "y/y", "Change in y/y", "Quarters accelerating", "Share of revenue"],
                            {"yoy": pct, "accel": lambda x: f"{x:+.0%}", "share": lambda x: num(x, "{:.0%}"), "series": lambda x: str(x)[:40]},
                            ["ticker", "series"], "accel_ranked"))

    b = load("tier1_backlog_ahead")
    html.append(section("Backlog building ahead", "book-to-bill > 1.05 and rising, revenue growth still under 15%. Backtest: no edge as a list — "
                        "read the b2b column instead.", b, t1c, t1h, t1f, key, "tier1_backlog_ahead"))
    c = load("tier1_accelerating")
    html.append(section("Backlog accelerating", "RPO growth accelerating with book-to-bill above 1.", c, t1c, t1h, t1f, key, "tier1_accelerating"))
    d = load("tier1_borrowing")
    if len(d): d = d[~d.industry.fillna("").str.contains("Real Estate")]      # b2b means little for land sales
    html.append(section("Borrowing from backlog (holdings check)", "revenue growing while book-to-bill < 0.95: shipping out of backlog "
                        "faster than orders arrive. Worth a look if you own one. Real estate excluded.", d, t1c, t1h, t1f, key, "tier1_borrowing"))
    s = load("tier1_rpo_step")
    html.append(section("RPO jumps (disclosure events)", "RPO up 1.5x+ in one quarter — usually a scope or disclosure change, not orders. News to read.",
                        s, t1c, t1h, t1f, key, "tier1_rpo_step"))
    f = load("beat_and_raise_flags")
    if len(f):
        f = f[f.two_consecutive == True]
        html.append(section("Beat and raise, two quarters running", "vs the company's own guidance. All clear on the weak leg "
                            "(next-quarter guide implies faster growth); backtest context: no edge shown for this flag.", f,
                            ["ticker", "latest_scored_q", "br_streak", "last_beat_pct", "last_raise_basis"],
                            ["Ticker", "Latest quarter", "Streak", "Last beat vs guide", "Raise basis"],
                            {"last_beat_pct": lambda x: f"{x:+.1%}", "ticker": lambda x: "—" if pd.isna(x) else x}, ["cik"], "beat_and_raise_flags"))

    html.append(f"<p>Workbooks: <a href='{REPO}/blob/main/results/market_bookings_screen.xlsx'>market bookings</a> · "
                f"<a href='{REPO}/blob/main/results/semis_acceleration_screen.xlsx'>semis acceleration</a> · "
                f"<a href='{REPO}/blob/main/results/beat_and_raise_screen.xlsx'>beat and raise</a> · "
                f"<a href='{REPO}/blob/main/results/backtest_b2b/summary.md'>backtest</a></p>")
    subject = f"Semis SEC screens {time.strftime('%Y-%m-%d', time.gmtime())}" + (" — STEPS FAILED" if failed else "")
    return subject, "\n".join(html)

def send_mail(subject, html):
    host, user, pw, to = os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"), os.getenv("MAIL_TO")
    if not all([host, user, pw, to]):
        print("mail not configured; skipping"); return
    m = MIMEMultipart("alternative"); m["Subject"], m["From"], m["To"] = subject, user, to
    m.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
            s.starttls(); s.login(user, pw); s.sendmail(user, to.split(","), m.as_string())
        print("mail sent to", to)
    except Exception as e:
        print("MAIL FAILED (results still saved):", str(e)[:200])

if __name__ == "__main__":
    subject, html = build()
    open(f"{RES}/email.html", "w").write(f"<!-- {subject} -->\n" + html)
    print(subject, "| wrote results/email.html")
    if "--no-send" not in sys.argv: send_mail(subject, html)
