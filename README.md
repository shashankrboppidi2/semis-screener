# semis-screener

A fundamental screener built on SEC filings. Five pipelines, all deterministic except where
explicitly noted, all validated by reconciliation rather than by inspection.

What it currently produces:

| Output | What it is |
|---|---|
| `out/{TICKER}_sec_history.xlsx` | 34 per-ticker workbooks: quarterly income statement, segments, geography, guidance, customer concentration, all as-first-reported |
| `out/market_bookings_screen.xlsx` | Implied bookings and book-to-bill for every US filer disclosing RPO (1,696 filers) |
| `out/semis_acceleration_screen.xlsx` | Segment/product KPI acceleration across 28 semis filers, 549 series |
| `out/semis_leading_indicator_study.xlsx` | Whether segment growth leads the cycle, own fundamentals, or the stock |
| `out/beat_and_raise_screen.xlsx` | Two-consecutive-quarter beat-and-raise flag vs the company's own guidance |

**Read `BACKLOG.md` before writing code.** It has the prioritized work, and it records three
approaches that were built, measured and rejected — don't spend time rediscovering them.

---

## Quickstart

```bash
pip install -r requirements.txt
export SEC_UA="YourName your@email.com"     # REQUIRED. SEC blocks requests without a real UA.
python run_screens.py                        # tier1 -> br -> accel -> workbooks, results in results/
python run_screens.py tier1 br accel         # the weekly GitHub Actions set
python run_screens.py accel --no-fetch       # rebuild from the shipped pickles, no SEC requests
```

`run_screens.py` runs each step in its own process from this directory (so it works from any CWD),
logs to `out/logs/`, keeps going past a failed step, and copies the screen workbooks plus CSV
copies of the headline lists to `results/` with a `run_status.json`. It also seeds
`out/br_guide_ckpt.jsonl` from the shipped `br_guidance_enriched.pkl`, so the beat-and-raise
refresh only opens releases it has not read before.

On GitHub, `.github/workflows/screens.yml` runs `tier1 br accel` every Saturday (or by hand,
with a stage list) and commits `results/`. Add the repository secret `SEC_UA`. The SEC HTTP
cache is kept between runs with `actions/cache`; `data.sec.gov` answers (submissions,
companyfacts, frames) expire after `SEC_CACHE_TTL_HOURS` (default 20) so new filings are seen,
while archive documents are cached for good. The tier-1 date window and the `CURRENT` recency
gate roll forward with the calendar (`SEMIS_CURRENT_Q=2026Q1` pins the gate).

**Book-to-bill backtest** (`backtest_b2b.py`, BACKLOG task 7): as-first-reported RPO and revenue from companyfacts for
every RPO filer, dated to the 10-Q/10-K filing, returns in excess of SPY from the next close. Four hypotheses fixed
in the docstring before any result was seen; pass/fail on a within-cohort shuffle placebo with Bonferroni.
Run it from Actions ("Book-to-bill backtest"); results land in `results/backtest_b2b/summary.md`.

The original single-stage path still works:
`python tier1_frames.py && python tier1_panel.py && python tier1_screen.py`.

That path is the cheapest end-to-end proof the handoff works: ~309 SEC requests, ~10 minutes,
rebuilds the market-wide RPO panel from scratch.

`SEC_UA` currently falls back to a placeholder in `edgar.py`. **Set it to a real contact string
before any large run** — the SEC rate-limits and then blocks anonymous clients.

## Layout

Imports are flat (`import edgar`, `import tables`) and every script reads and writes `out/`.
Nothing is packaged. Restructuring into `lib/` + `stages/` is task 1 in the backlog; if you do it,
fix the ~40 relative reads to `out/` and `config/` at the same time or nothing will run.

```
*.py          84 scripts, flat. Inventory below.
config/*.json 36 per-ticker configs. Identifiers only for most tickers; NVDA/INTC/AMD carry
              earnings-release table hints. `member_map` is vestigial — segment naming is now
              derived from each filing's own label linkbase.
out/          pickles the stages read and write. Shipped partially — see "What is shipped".
```

## The five pipelines

```
                    SEC EDGAR (data.sec.gov + www.sec.gov/Archives)
                                     │
   ┌────────────────┬────────────────┼──────────────────┬────────────────────┐
   │                │                │                  │                    │
(1) per-ticker   (2) tier-1       (3) acceleration  (4) beat-and-raise   (5) study
    XBRL            frames            screen            flag                 (returns)
   run_xbrl.py    tier1_frames.py   accel_series.py   br_releases.py      study_signals.py
   run_earnings2  tier1_panel.py    accel_rank.py     br_extract.py       study_events.py
   run_fpi.py     tier1_screen.py   build_accel_      br_postpass.py      study_run2.py
   run_customers  tier1_sic.py        workbook.py     br_flag.py          study_cycle.py
   build_         build_tier1_                        br_build.py         build_study_
     workbooks.py   workbook.py                                             workbook.py
```

### 1. Per-ticker XBRL — `run_xbrl.py TICKER`
Segment, product and geography revenue plus the income statement, **as first reported**. The hard
parts, all solved and worth not breaking:
- Segment names come from each filing's own label linkbase (`xbrl_segments.all_member_labels`), not
  from config. Series identity is normalized in `run_xbrl_names.py` so "Datacenter" and "Data
  Center" are one series.
- Q4 is derived as FY − 9M where a filer tags no separate Q4 (`tables.dim_quarterly`).
- **Tag-swap guard**: AMD's 2022–24 10-Qs rotate Data Center / Client / Gaming member names against
  the printed table. The printed row label wins, applied atomically per filing×period×metric and
  only when the proposed names form a permutation. 138 facts relabeled across 9 filings.
- `cik_chain` in config walks predecessor registrants (AVGO: 1730168 ← 1649338 ← 1441634).
- Cost: ~335 SEC requests and ~47 MB of cache **per ticker**.

### 2. Tier-1 market-wide RPO — `tier1_frames.py` → `tier1_panel.py` → `tier1_screen.py`
The XBRL **frames** API returns every filer reporting a concept for a calendar period in ONE
request. The whole US market costs **309 requests and 51 MB**, versus ~354,000 requests and 46 GB
for the per-filer path. If you extend coverage, extend it here, not in pipeline 1.

Core identity: `implied bookings = revenue + Δ RPO`, `book-to-bill = bookings / revenue`.

### 3. Acceleration screen — `accel_series.py` → `accel_rank.py`
Scores every disclosed revenue series on the second difference of y/y growth, not the level. The
template is NVIDIA 2023: Compute & Networking went +21% → +166% → +284% y/y. Reportable segments
are often too coarse (NVDA's "Data Center" is a *product* disclosure), so segment, product,
product-within-segment and geography axes are all scored. **They are alternative cuts of the same
revenue and are never summed.**

### 4. Beat-and-raise — `br_releases.py` → `br_extract.py` → `br_postpass.py` → `br_flag.py`
Beat and raise measured against the company's **own guidance**; no connected source carries
sell-side consensus or its revision history. Coverage-starved: 2,062 readable guides from 7,054
releases. See BACKLOG task 2.

### 5. Leading-indicator study — `study_*.py`
The honest result: segment growth is a good **cycle-position** indicator and a poor **stock**
signal. Teradyne's Semiconductor Test turns 3 quarters before the industry (ρ 0.63 at that lead vs
0.37 contemporaneous). For returns, the signal is priced on the print; only largest-segment growth
net of consolidated growth survived, and it did not clear a multiple-testing bar.

## Validation contracts

These are the load-bearing checks. **If you change an extraction path, these must still pass.**

| Check | Where | Asserts |
|---|---|---|
| Segment add-up | `validators.segment_addup` | Segments sum to the consolidated total. Only reconciliation-validated transformations are applied — a subtotal is dropped, or a geography breakdown separated, **only if** that makes the segments reconcile. Across 18 tickers: 2,959 groups, **27 unreconciled (0.91%)**, 12 tickers fully clean. The non-"sum ok" rows in `out/*_addup.pkl` are mostly *successful* transformations, not failures — a real failure reads `sum X != total Y`. |
| Quarters → annual | `check_fpi.py TICKER` | Four quarters sum to the 20-F/10-K annual. TSMC: revenue, gross profit, operating income and pre-tax all tie exactly across 10 years. |
| Months → quarter | `check_tsm.py` | TSMC's three monthly releases sum to the quarter: 63/63 quarters, max error 0.007%. |
| Model output | `validate_s2.py`, `br_validate.py` | Every number a model produced must appear in the source text, at some scale. Unprinted fields are dropped. |
| Guide plausibility | `br_flag.py` | A next-quarter revenue guide must be 0.77–1.25× the quarter reported. Calibrated from the observed distribution (actual/guide is 1.007 at p25, 1.049 at p75). Rejects 492 misparses. |
| Workbook read-back | `verify_all.py` | Reopens every recalculated workbook and reconciles cells against the source pickles. 30/30 checks, 0 error cells, 42,809 formulas. |

Recalculation uses LibreOffice via the xlsx skill's `recalc.py`; `verify_all.py` runs after it.

## Known gaps — real, documented, not hidden

**Data**
- Segment add-up leaves 27 unreconciled groups of 2,959 (0.91%): QCOM 13, ENTG 9, INTC 2 (2024
  foundry eliminations), and one each for AMD (Q1 2022 Xilinx), ON and STM. Everything else ties.
- NXPI quarterly only from 2018 (20-F → 10-K switch). SKHY has no SEC financial history.
- 7 IFRS/FPI tickers are annual-only: ARM, ASX, NVMI, STM, TSEM, TSM, UMC. TSMC is handled
  separately (`tsmc2.py`, `tsm_kpis.py`) from its 6-K releases.
- TSMC net income diverges 0.5–3.3% from the 20-F every year while revenue, gross profit,
  operating income and pre-tax tie exactly. The break is entirely below the tax line — a basis
  difference, not an extraction error. Do not "fix" it.
- ASML discontinued its bookings disclosure after Q4 2025. The series ending there is correct.

**Method**
- Tier-1 frames return the **most recently filed** value per filer-period, so the panel is
  latest-reported, not as-first-reported. Fine for a current screen; **these signals cannot be
  backtested on it** without restatement bias. Pipeline 1 records filing dates and is the path for
  any backtest.
- Frames occasionally skip a filer-quarter (median coverage 100%, p25 85%). A gap breaks the
  consecutive-quarter chain, so Δ RPO is left blank rather than computed across it.
- Every name currently clearing the beat-and-raise flag does so on the **weak** raise leg
  ("guides acceleration"), not a raised full-year guide. TREX is flagged with revenue −44% y/y.
  Use the `raise_strength` and `growing` columns.
- 454 of the 1,696 RPO filers file no earnings 8-K with item 2.02 — nothing to read.

## What is shipped in `out/`

Included: `{TICKER}_seg.pkl` and `_fin.pkl` (the expensive pipeline-1 output, hours of fetching),
`tier1_latest.pkl`, `tier1_sic.pkl`, `cik_tickers.pkl`, `rpo_facts.pkl`, `accel_*.pkl`, `br_*.pkl`,
`study_*.pkl`, `TSM_*.pkl`, `ASML_kpi*.pkl`.

Excluded because they regenerate cheaply: `tier1_raw.pkl` (63 MB) and `tier1_panel.pkl` (41 MB) —
`python tier1_frames.py && python tier1_panel.py` rebuilds both in ~10 minutes. The 1.6 GB HTTP
cache is also excluded; it refills on demand.

## File inventory

**Library (import-only, no side effects)**
`edgar.py` SEC client: gzipped SHA1 disk cache, 0.12 s spacing, `doc_types()` reads the small
index-headers file so only EX-99 exhibits are fetched instead of a 100 MB submission ·
`earnings_docs.py` exhibit → text · `xbrl_financials.py` companyfacts → income statement/balance
sheet · `xbrl_segments.py` dimensional facts + label linkbase + `ix_row_labels` ·
`tables.py` quarterly/annual vintage tables, Q4 derivation · `validators.py` segment add-up ·
`run_xbrl_names.py` `NORM`/`KEY`/`match` name normalization · `guidance_generic.py` semis-tuned
guidance patterns · `br_patterns.py` market-wide guidance patterns + growth-rate handling ·
`llm_fallback.py` model queue and system prompts

**Stage runners** `run_xbrl.py` `run_earnings2.py` `run_fpi.py` `run_customers.py`
`run_customers_all.py` `run_all.py` · `tier1_frames.py` `tier1_panel.py` `tier1_screen.py`
`tier1_sic.py` `rpo_pull.py` · `accel_series.py` `accel_rank.py` `accel_screen.py` ·
`br_releases.py` `br_extract.py` `br_postpass.py` `br_flag.py` `br_validate.py` ·
`study_signals.py` `study_events.py` `study_printed2.py` `study_run2.py` `study_robust.py`
`study_cycle.py` `study_leadlag.py` `study_fundamental.py` `study_samples.py` `study_tsmc_lead.py`

**Builders** `build_workbooks.py` `build_tier1_workbook.py` `build_accel_workbook.py`
`build_study_workbook.py` `build_tsm_workbook.py` `build_universe.py` `build_universe_data.py`
`br_build.py`

**Validators** `validators.py` `check_fpi.py` `check_tsm.py` `check_guidance.py` `validate_s2.py`
`validate_s3.py` `validate_s4.py` `verify_all.py` `verify_workbooks.py` `br_validate.py`

**Ticker-specific** `tsmc2.py` `tsm_kpis.py` `tsm_monthly_early.py` `asml_kpis.py`
`asml_breakdown.py` `asml_h1.py` `txn_markets.py` `fpi_quarterly.py`

**Superseded — delete after reading** `tsmc.py` (→ `tsmc2.py`), `study_run.py` (→ `study_run2.py`),
`run_earnings.py` (→ `run_earnings2.py`), `study_printed.py` (→ `study_printed2.py`),
`accel_screen.py` (folded into `accel_series.py`), `earnings_extract.py`, `customers*.py`,
`score_*.py`, `seg_gap.py`, `merge_guidance.py`, `requeue_flagged.py`, `xcheck_*.py`,
`etf_holdings.py`, `make_configs.py`, `check_llm.py`
