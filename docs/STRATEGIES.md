# Strategies A, B and C

Three variants of the same plan were tested in this repository and in the session that built it. **A is live**
(see [PLAN.md](PLAN.md) for the exact operating rules); B and C are documented here so they can be picked up later.
Every number below is a backtest of a hypothetical account, $100,000 at the start plus $4,000 on the first trading
day of each month, 2007-01-03 to 2026-10-23 unless stated, with a 54% marginal tax rate (Ontario top bracket: capital
gains taxed at 27%, margin interest deducted at 54%), 0.1% trading cost, margin at T-bills + 1.6%, and everything
sold on the last day with tax paid on all open gains. Nothing here is investment advice.

## What the three have in common

| | Rule |
|---|---|
| Sleeves | Two equal sleeves: a QQQ sleeve and an SMH sleeve. Deposits split 50/50; the sleeves are rebalanced to 50/50 each January. |
| Laggard buys | QQQ sleeve: a chip/tech stock worth $50B+ closes 30% or more below its 252-day high *relative to QQQ*. SMH sleeve: one of the 25 largest chip stocks does the same *relative to SMH*. Buy 2% of the sleeve of it the next day. The same name can alert again only after 63 trading days. Caps: 10% of the sleeve per name, 40% of the sleeve in names; largest market caps fill first when room is short. |
| Paying for laggards | Cash first, the rest on margin (a short "bridge" loan). Nothing is sold on an alert day. At the next monthly deposit the deposit repays the loan (hedge loan first, then bridge); if the bridge is not cleared, that much ETF is sold. |
| Holding | Laggards are held. They are only cut back in January when over a cap. |
| Hedge | WU SP500 Hedging Signal. When it says out: keep everything and buy PSQ (-1x Nasdaq-100) on margin worth 50% of the QQQ sleeve and beta/2 (capped at 50%) of the SMH sleeve, total loan capped at 50% of long holdings. When it says in: sell PSQ, repay the loan, leftover into the core. Live, the hedge also covers the picks bucket (PLAN.md). |
| January | Tax settled; names trimmed to the caps (proceeds to the core); sleeves rebalanced 50/50 by selling core. |
| Order mechanics (B and C) | Deposits go to the most-underweight position of the sleeve, not split six ways; re-weights, trims and rebalances under $500 are skipped; the same ticker in both sleeves is one order; tax and rebalance sales come from the ETF first. These cut B's orders from about 172 to about 115 a year with no change in results. |

## Where they differ: the core of each sleeve

| | A | B | C |
|---|---|---|---|
| QQQ sleeve core | 100% QQQ | 50% QQQ + 50% top-5 Nasdaq-100 stocks | 100% top-5 Nasdaq-100 stocks |
| SMH sleeve core | 100% SMH | 50% SMH + 50% top-5 chip stocks | 100% top-5 chip stocks |
| Top-5 picks | none | best 63-day total return among the Nasdaq-100 members of the day (point-in-time) / the 25 largest chips; re-picked on the first trading day of each quarter; equal weight (10% of core each) | same, 20% of core each |
| Re-pick | - | names that dropped out are sold, new ones bought, ETF vs top-5 reset to 50/50 | names that dropped out are sold, new ones bought, five equal weights |
| Deposits | the ETF | half ETF, half the five picks (most-underweight first) | the five picks (most-underweight first) |

## Results, 2007-2026

| | A | B | C |
|---|---|---|---|
| After tax, everything sold | $20.4M | $23.0M | $26.4M |
| Annual return (time-weighted) | 22.9% | 24.1% | 25.3% |
| Sharpe (vs T-bills) | 0.96 | 0.95 | 0.91 |
| Worst drawdown (2008) | -33% | -35% | -40% |
| Tax paid along the way | $1.3M | $2.3M | $3.4M |
| Orders a year | 56 | 115 (172 before the order mechanics) | 170 |
| Annual turnover | 15% | 120% | 216% |
| Days a year with a sale | about 6 | about 9 | about 8 |
| ETFs as a share of holdings | 54-60% | 23-30% | 0% |
| 30 rolling 5-year windows vs A | - | beats A in 27/30, median +7%, worst -8% | beats A in 27/30, median +12%, worst -15% |

Benchmarks with the same deposits: 50/50 QQQ/SMH buy-and-hold with a January rebalance $12.1M (-57% drawdown,
Sharpe 0.73); QQQ alone $7.4M (-53%). A's core without laggards or hedge: $11.4M. With the hedge only: $15.9M. With
laggards only (no hedge): $13.6M. Roughly: half of A's result over buy-and-hold comes from the hedge, a quarter from
the laggards.

### How robust the differences are

- **Hedge timing.** The hedge dates before the signal's launch are the vendor's back-calculated history. A hedge
  that is 2 trading days late costs A about 8% of the end value; 5 days late about 25%. A breadth signal built in
  this repository from public data did not help at all (A with it: $12.9M vs $13.6M unhedged), so the result depends
  on the vendor's signal being as good live as its history.
- **Outliers.** When the eleven biggest single-stock winners (NVDA, MU, ARM, AMD, TSLA, STM, AMAT, LRCX, ASX, AVGO,
  DELL) are allowed only two-thirds of their outperformance over their ETF, with every buy and sell signal unchanged,
  B and C fall to A's level ($17.2M / $17.0M vs A $17.2M). At half, A is ahead of both. B and C still beat A in
  about 20 of 30 five-year windows in those tests, by 2-4%, with lower Sharpe and worse worst-cases. The top ten
  names make two-thirds or more of all stock-level profit in every strategy.
- **Earlier history, 1994-2007** (index stand-ins, reconstructed prices for delisted names, so indicative only):
  A $2.1-2.3M, B $2.2-3.9M, C $2.1-7.4M depending on the universe; with a realistic universe of $10B+ names C
  roughly matched A, because the 2000-2002 momentum crash hit the chip picks (-81% to -93%) harder than the index.
- **ETF-majority versions of C** (25-45% of the core in the top-5, laggards capped at 15-25% so ETFs stay above half
  of holdings): $19.0-20.3M, about A's result with three times the orders. C's edge comes from the top-5 slice, so
  a small slice earns a small edge.
- **Selling only once a year** (deposits fund laggards, no bridge; top-5 re-picked yearly): A $17.7M, B/C $16-19M.
  Momentum needs the quarterly swap; the yearly re-pick gives up $5-10M. Monthly settlement of the bridge loan is
  what made "no selling to buy" workable.

## Trading days and taxes, started 2025-01-02 (to 2026-10-23)

| | A | B (adjusted) | C |
|---|---|---|---|
| Orders (sleeves netted) | 117 | 257 | about 300 |
| Days with any order | about 40 | 48 (27 a year) | about 50 |
| Days with a sale | 9 | 13 | 17 |
| Stocks/ETFs sold per year | $31k | $235k | about $400k |
| Average holding period of what was sold | 105 days; laggards 349 | 98 days; top-5 101 | about 60-100 |
| Realized gains on stocks/ETFs | about $0 | $66k | $121k |

B's and C's gains come from selling the quarter's winners at each re-pick; A realizes almost nothing because it
holds. Whichever runs in a taxable account: keep a pooled adjusted-cost-base ledger per ticker (CRA method), watch
the 30-day superficial-loss rule (monthly deposits re-buying a name just sold at a loss deny the loss; 3 cases in A,
7 in B, 17 in C over this period), file T1135 once the cost of US holdings exceeds CAD 100k, and ask an accountant
about two things before running B or C in a taxable account: whether a quarterly buy-sell cycle of this size could be
treated as business income (100% taxable rather than 50%), and whether interest on the PSQ hedge loan is deductible
(the backtest assumes it is). The capital-gains election under s. 39(4) covers Canadian securities only, so it does
not help here.

## Why A is live

- A's stock side is buy-and-hold: 18 sales a year, laggards held about a year on average, nearly all gains
  unrealized. B's quarterly re-pick turns $211k a year of 3-month holdings with real profits each quarter, which
  touches three of CRA's trader factors at once (frequency, short ownership, margin).
- A's edge does not need NVDA-scale winners to show up; B's and C's 20-year lead disappears when the biggest
  winners are shrunk by a third.
- A has the best Sharpe and the shallowest drawdown of the three, a third of the orders, and the least tax drag.

The audit of the three (process over outcome) scored them similarly on policy, testing and measurement (4/5) and
poorly on diversification (1/5: QQQ and SMH move together, correlation 0.86 since 2007, 0.91 over the last year;
semiconductors are two-thirds of holdings; the only offset is a short of the same index). The single biggest gap is
that the hedge's edge rests on vendor-backfilled dates that cannot be audited from here.

## Switching to B later

B as adjusted is the candidate if the top-5 sleeve is wanted:

1. Decide where the top-5 sleeve lives. In a taxable account the quarterly turnover is taxed and raises the trader
   question; in a TFSA the tax goes away but CRA can tax a TFSA that is "carrying on a business", so the holding
   period matters there too.
2. If longer holds are needed, test a top-10 buffer (keep a pick while it stays in the top 10, replace it only when it
   drops out) or a semi-annual re-pick. Neither has been backtested yet; the buffer usually halves momentum turnover.
3. Add to the alerts: the quarterly ranking (Nasdaq-100 membership of the day for the QQQ sleeve, the 25 largest chips
   for the SMH sleeve), the re-pick order list, deposits to the most-underweight position, and the $500 minimum.

## Data and model caveats

Prices are dividend- and split-adjusted closes (trades at the close, fractional shares, no slippage beyond 0.1%);
the stock universe before 2010 is thinner and the 1990s tests use reconstructed price paths for delisted names;
market caps use SEC share counts; the whole account is treated as taxable; FX (USD/CAD), dividend withholding, US
estate tax and IBKR's margin requirement changes for concentrated names are not modeled. The simulation code with
the hedge dates is not in this repository (the repository is public and the signal is a paid product); the public
pieces are `basket_backtest.py`, `blend_backtest.py`, `hedge_overlay.py` and the data fetchers under `fetch_*.py`.
