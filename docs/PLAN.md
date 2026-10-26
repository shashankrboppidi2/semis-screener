# The plan (strategy A): QQQ/SMH sleeves with laggard buys, a WU hedge on margin, 70/30 with a picks bucket

How the taxable account is run and what the daily alerts mean. The rules were chosen from the backtests in this
repository (`basket_backtest.py`, `blend_backtest.py`, `hedge_overlay.py`) and the 2007-2026 / 1990s tests of the
funding and hedge variants; none of this is investment advice.

## Rules

| | Rule |
|---|---|
| Account | 70% runs the plan in two equal sleeves (`ETF_SHARE`); 30% is the **picks** bucket: your own stock picks, not traded by the alerts but counted in the targets and covered by the hedge. |
| Core | A QQQ sleeve parked in QQQ and an SMH sleeve parked in SMH, equal in size. |
| QQQ sleeve laggards | When a chip/tech stock worth at least $50B closes 30% or more below its 1-year high *relative to QQQ*, buy 2% of the QQQ sleeve of it that day. |
| SMH sleeve laggards | When one of the 25 largest chip stocks closes 30% or more below its 1-year high *relative to SMH*, buy 2% of the SMH sleeve of it that day. |
| Paying for laggards | Cash in the account first, the rest on margin (the "laggard loan"). Nothing is sold on an alert day. |
| Limits | At most 10% of a sleeve in one stock and 40% of a sleeve in stocks. A stock re-alerts only after 63 trading days. When there is not room for every alert, the largest companies fill first; nothing is sold to make room. The e-mail flags any stock above 10% of the whole account (a stock can qualify in both sleeves and in the picks). |
| Hold | Stocks are held; there is no sell signal. |
| Monthly | First trading day: the deposit (`MONTHLY_DEPOSIT`) repays the margin loan first (hedge loan, then laggard loan). Of what is left, 70% buys the ETF of the sleeve furthest below its target (one order) and 30% stays as cash for picks. If the laggard loan is not cleared, sell that much ETF from the sleeve furthest above target. |
| Hedge | WU SP500 Hedging Signal only. When it turns on: keep everything and buy PSQ on margin worth 50% of the QQQ sleeve, 50% of the SMH sleeve (beta/2, capped at 50%) and 50% of the picks; the total loan is capped at 50% of the account's long holdings. While on, PSQ is topped up when new picks or laggards leave it more than 5% short, never trimmed. When it turns off: sell all PSQ, repay the loan, put anything left into the ETF of the sleeve furthest below target. |
| January | Set aside 27% of last year's net realized gain (PSQ sales, trims, rebalances, less margin interest). Trim any stock above 10% of its sleeve to 10%; if a sleeve's stocks exceed 40%, scale them down (slices under $500 skipped); proceeds go to the sleeve's ETF. Rebalance the sleeves to 50/50 by selling ETF, not stocks. Bring the account back toward 70/30 with the next deposits rather than sales. |
| Small orders | Re-weights, trims, rebalances and deposit buys under $500 are skipped and left for the next month. Laggard buys are never skipped for size. Orders in the same ticker from both sleeves are netted into one. |
| Guardrails | Every e-mail shows the loan as a share of long holdings (limit 50%) and the estimated excess liquidity at IBKR's 30% requirement (warning below 20% of holdings). These are the account's own numbers: a TFSA cannot be collateral and is not part of this plan. |

Backtest, 2007-2026, $100k + $4k/month, 54% marginal tax, everything sold at the end: $20.4M after tax, Sharpe 0.96,
worst drawdown -33%, about 56 orders a year, sales on about 6 days a year. Half of the result came from the WU hedge
(whose pre-launch dates are back-calculated), a quarter from the laggard buys. The 50/50 QQQ/SMH buy-and-hold with the
same deposits made $12.1M with a -57% drawdown.

## The daily alert

Every weekday after the US close the "Plan alerts" workflow runs `plan_alerts.py`. Each report opens with a verdict:

- **Today: no action.** Nothing to trade.
- **Today: N action(s).** A numbered list, then the details and, in the e-mail, an *Orders* list netted across sleeves
  with share counts at the close:
  - *Hedge ON / OFF / top-up* -- PSQ as described above, with the cash/margin split and the margin figures after.
  - *Laggards: buy N stock(s)* -- the stocks, how far behind their benchmark they are, their size, the amount, and how
    today's buys are paid for.
  - *Monthly deposit and settlement* -- first trading day of the month.
  - *January* -- tax, trims, rebalance.

E-mails go out when there is something to do and every Monday. The committed copy (`results/alerts/latest.md`) and
the run log are public and leave out the hedge, the account and any dollar amounts; the e-mail has everything.

### Where the hedge signal comes from

Only the **WU SP500 Hedging Signal** (TradingView) moves the hedge:

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
   - `HOLDINGS` -- `sleeve,ticker,shares` lines for everything in the account; update after trading. Sleeves `QQQ`
     and `SMH` hold the ETF and that sleeve's laggards, `PICKS` holds your own picks, PSQ can sit on any sleeve, and
     one line `CASH,USD,<dollars>` gives the USD cash balance (negative while on margin). An optional fourth column
     `price` sets a price for a ticker the universe does not cover. Without the secret the report sizes in percent.
   - `NTFY_TOPIC` (optional) -- a long random topic name; install the ntfy app and subscribe to it for phone pushes.
   - `DISCORD_WEBHOOK` (optional) -- a webhook URL for a channel in a private Discord server; action days post there.
3. Repository variables: `WU_HEDGE` (optional, see above); `ETF_SHARE` (default 0.70); `MONTHLY_DEPOSIT` (default 4000).
4. The stock universe refreshes itself quarterly (`universe.yml`); the breadth counts refresh on every alert run.
