# Book-to-bill backtest (as first reported)

Run 2026-09-30. 5,913 filer-quarters with prices, 389 companies, entries 2017-10 to 2026-06. Returns are excess over SPY from the first close after the 10-Q/10-K filing. Pre-registered: 4 tests at 63 days, Bonferroni alpha 0.0125 on the placebo p-value.

| test | horizon | cohorts | events | mean rank IC | IC t (NW) | share of cohorts IC>0 | top-minus-bottom quintile / gate minus rest | t (NW) | placebo p | passes |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 b2b level | 63d | 32 | 5,910 | +0.046 | 1.94 | 62% | +2.75% | 1.58 | 0.001 | **yes** |
| H1 b2b level | 126d | 31 | 5,664 | +0.059 | 1.88 | 65% | +5.76% | 1.67 | 0.000 | n/a (126d not a test) |
| H2 b2b trend | 63d | 29 | 4,980 | +0.007 | 0.52 | 52% | +0.89% | 0.84 | 0.314 | no |
| H2 b2b trend | 126d | 28 | 4,752 | +0.046 | 3.25 | 75% | +3.02% | 1.56 | 0.002 | n/a (126d not a test) |
| H3 RPO growth y/y | 63d | 29 | 5,127 | +0.039 | 1.15 | 62% | +3.08% | 1.40 | 0.006 | **yes** |
| H3 RPO growth y/y | 126d | 28 | 4,897 | +0.021 | 0.55 | 61% | +1.96% | 0.55 | 0.078 | n/a (126d not a test) |
| H4 backlog-building gate | 63d | 29 | 1,085 |  |  | 52% | +0.60% | 0.69 | 0.246 | no |
| H4 backlog-building gate | 126d | 28 | 1,045 |  |  | 64% | +0.84% | 0.60 | 0.288 | n/a (126d not a test) |

## Robustness of H1 (b2b level, 63 days)

| slice | cohorts | mean IC | IC t | top-minus-bottom quintile |
|---|---|---|---|---|
| first half | 19 | +0.035 | 0.96 | +3.01% |
| second half | 13 | +0.063 | 2.69 | +2.36% |
| revenue above median | 32 | +0.019 | 0.77 | +1.17% |
| revenue below median | 32 | +0.067 | 2.28 | +4.53% |

## How to read it

* **Rank IC**: correlation, within each quarterly cohort, between the signal's rank and the next-63-day excess return's rank. Around +0.02 to +0.05 is what usable single factors look like; 0 is no information.
* **Placebo p**: the signal is shuffled among the same cohort's names 2,000 times; p is how often chance did as well. This is the number the pass/fail uses.
* **Survivorship**: only companies with a current ticker are in the universe, so failed and acquired companies are missing.
* **Not tested**: transaction costs, and anything intraday. The 126-day rows overlap across cohorts; their t-stats use Newey-West errors.
