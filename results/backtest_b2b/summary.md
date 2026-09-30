# Book-to-bill backtest (as first reported)

Run 2026-09-30. 329 filer-quarters with prices, 17 companies, entries 2018-07 to 2026-05. Returns are excess over SPY from the first close after the 10-Q/10-K filing. Pre-registered: 4 tests at 63 days, Bonferroni alpha 0.0125 on the placebo p-value.

| test | horizon | cohorts | events | mean rank IC | IC t (NW) | share of cohorts IC>0 | top-minus-bottom quintile / gate minus rest | t (NW) | placebo p | passes |
|---|---|---|---|---|---|---|---|---|---|---|
| H4 backlog-building gate | 63d | 21 | 68 |  |  | 57% | +2.06% | 0.69 | 0.279 | no |
| H4 backlog-building gate | 126d | 20 | 64 |  |  | 60% | -3.22% | -0.59 | 0.617 | n/a (126d not a test) |

## Robustness of H1 (b2b level, 63 days)

| slice | cohorts | mean IC | IC t | top-minus-bottom quintile |
|---|---|---|---|---|

## How to read it

* **Rank IC**: correlation, within each quarterly cohort, between the signal's rank and the next-63-day excess return's rank. Around +0.02 to +0.05 is what usable single factors look like; 0 is no information.
* **Placebo p**: the signal is shuffled among the same cohort's names 2,000 times; p is how often chance did as well. This is the number the pass/fail uses.
* **Survivorship**: only companies with a current ticker are in the universe, so failed and acquired companies are missing.
* **Not tested**: transaction costs, and anything intraday. The 126-day rows overlap across cohorts; their t-stats use Newey-West errors.
