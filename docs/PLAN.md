# The plan: 50/50 QQQ/SMH with laggard rotation and a hedge

How the portfolio is run and what the daily alerts mean. The rules were chosen from the backtests in this
repository (`basket_backtest.py`, `blend_backtest.py`, `hedge_overlay.py`); none of this is investment advice.

## Rules

| | Rule |
|---|---|
| Core | Two sleeves of equal size: a QQQ sleeve parked in QQQ and an SMH sleeve parked in SMH. |
| Deposits | Each month, half into QQQ and half into SMH. |
| QQQ sleeve rotation | When a chip/tech stock worth at least $50B closes 30% or more below its 1-year high *relative to QQQ*, buy 2% of the QQQ sleeve of it, paid from QQQ. |
| SMH sleeve rotation | When one of the 25 largest chip stocks closes 30% or more below its 1-year high *relative to SMH*, buy 2% of the SMH sleeve of it, paid from SMH. |
| Limits | At most 10% of a sleeve in one stock and 40% of a sleeve in stocks. A stock re-alerts only after 63 trading days. When there is not room for every alert, the largest companies fill first; nothing is sold to make room. |
| Hold | Stocks are held; there is no sell signal. |
| Hedge | WU SP500 Hedging Signal [2.2] only. When it turns on, keep QQQ and SMH and, in the taxable account, buy PSQ on margin worth 50% of each sleeve (the loan is capped at 50% of the sleeve; plan leverage about 1.5x). When it turns off, sell the PSQ, repay the loan, and put anything left back into the ETFs. Borrowing instead of selling avoids realizing gains on every hedge; selling 25% of the QQQ sleeve and about 29% of the SMH sleeve into PSQ gives the same protection without margin. |
| January | Trim any stock above 10% of its sleeve to 10%; if a sleeve's stocks exceed 40% of it, scale them down to 40%; then move money between QQQ and SMH so the sleeves are equal. |

## The daily alert

Every weekday after the US close the "Plan alerts" workflow runs `plan_alerts.py`. Each report opens with a verdict:

- **Today: no action.** Nothing to trade; keep the monthly DCA going.
- **Today: N action(s).** A numbered list, then the details:
  - *Hedge ON / Hedge OFF* -- buy or sell PSQ as described above (amounts in dollars if HOLDINGS is set).
  - *QQQ / SMH sleeve: buy N stock(s)* -- the stocks, how far behind their benchmark they are, their size, and the amount.
  - *Monthly deposit* -- first trading day of the month.
  - *January: trim and rebalance* -- first run of the year.

E-mails go out when there is something to do and every Monday. The committed copy (`results/alerts/latest.md`) and
the run log are public and leave out the hedge and any dollar amounts; the e-mail has everything.

### Where the hedge signal comes from

Only the **WU SP500 Hedging Signal [2.2]** (TradingView) moves the hedge:

1. The `WU_HEDGE` repository variable: `on` / `off` overrides everything; with a date (`on 2026-10-14`) it only
   records a signal you received elsewhere (e.g. WealthUmbrella's text message), and a newer alert e-mail takes over.
2. Otherwise your TradingView alert e-mails: two alerts on the indicator (its exit and its re-entry), each with
   "Send email" ticked and a message containing `WU_HEDGE=on` or `WU_HEDGE=off`. The workflow reads the newest one
   from the Gmail account in `SMTP_USER` over IMAP with the same app password (`wu_mail.py`) and remembers it in the
   private state. A message such as `{"content": "WU_HEDGE=on"}` also works as a TradingView webhook to the
   Discord webhook URL, for an instant ping.
3. With neither, the hedge is left as it is.

The Nasdaq breadth signal computed from Yahoo new highs and lows (`breadth_live.py`) is shown for information only.
In the backtests, hedging on it cost more than it saved: buy and hold beat it after tax.

## Setup

1. Merge this branch into `main` (scheduled workflows run only from the default branch).
2. Repository secrets (Settings > Secrets and variables > Actions):
   - `SMTP_USER`, `SMTP_PASS` (a Gmail app password), `MAIL_TO` -- e-mail.
   - `BREADTH_PARAMS` -- calibration and levels for the breadth signal (kept out of the public code).
   - `HOLDINGS` (optional) -- `sleeve,ticker,shares` lines for everything you hold, PSQ included; update after trading.
   - `NTFY_TOPIC` (optional) -- a long random topic name; install the ntfy app and subscribe to it for phone pushes.
     Messages pass through ntfy.sh.
   - `DISCORD_WEBHOOK` (optional) -- a webhook URL for a channel in a private Discord server (Server settings >
     Integrations > Webhooks > New Webhook > Copy Webhook URL); action days post there.
3. Repository variable `WU_HEDGE` (optional) -- `on` / `off` (manual override) or `on 2026-10-14` (a dated signal
   that newer WU alert e-mails replace).
4. The stock universe refreshes itself quarterly (`universe.yml`); the breadth counts refresh on every alert run.
