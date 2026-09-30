# Backlog

Ordered by expected value. Each task names the files it touches and how to tell it worked.

---

## Rejected approaches — do not rebuild these

**A Haiku pass to read guidance the regexes miss.** Built, run over 1,796 releases, and thrown
away. Two agents on the *same slice* with the *same prompt* returned 6% and 54% guidance rates.
Spot-checking the 54%: "GAAP EPS guidance to approximately $4.83 to $4.93" captured as revenue
guidance, Adjusted EBITDA guidance captured as revenue guidance, and reported actuals ("Record
Compression Infrastructure segment revenues of $315.1 million") captured as guidance. The 6% agent
rejected "The Company expects revenues for the fiscal third quarter ending June 30, 2024 to be in
the range of $19 million to $21 million" — quoted verbatim in its own prompt. Neither error
direction is acceptable in a flag meant to drive decisions. If you revisit this, it needs a
held-out labelled set and a measured precision/recall, not a better prompt.

**A 575-pair cross-company lead-lag scan.** Produced impressive-looking leads. A circular-shift
placebo (which destroys real timing while preserving each series' autocorrelation) threw up *more*
large lead gains than the real data: 27% of pseudo-pairs beat a 0.15 lead gain versus 19% of real
pairs. Pure multiple-testing artifact. `study_leadlag.py` keeps the placebo — the per-company and
per-segment tests in `study_cycle.py` are the defensible versions, one pre-specified test each.

**A roll-up-equals-sum-of-siblings rule in segment add-up.** Too aggressive; it silently dropped
real segments (NVDA 188→181, TXN 184→183). Reverted. `validators.py` now applies a transformation
only when it makes the segments reconcile.

---

## 1. Package it, without breaking it

Imports are flat and ~40 paths are relative to `out/` and `config/`. Move to `lib/` + `stages/` +
`semis/config/`, add `pyproject.toml`, make paths resolve from a package root rather than the CWD.

Done when: `pytest` green, and `tier1_frames.py → tier1_panel.py → tier1_screen.py` reproduces
`out/tier1_latest.pkl` row-for-row from any working directory.

Delete the superseded scripts listed at the end of README.md in the same pass.

## 2. Mine the 1,796 unreadable releases for deterministic patterns

**Highest-value data work.** Guidance coverage is 2,062 of 7,054 releases (29%), and that is the
binding constraint on the beat-and-raise flag — only 172 filers get a single scored quarter.

`out/br_guidance_enriched.pkl` has the stored outlook text for every unread release in
`model_text`. Cluster it by phrasing, find the recurring forms, add them to `br_patterns.py`.
Known gaps found by hand and already fixed give the flavour: the forward verb often comes *before*
the revenue noun with a long period clause between it and the figure ("expects revenues for the
fiscal third quarter (3Q24) ending June 30, 2024 to be in the range of $19 million to $21
million" — the gap limit was 60 chars, needed 130); and percentage guidance ("organic net sales
growth in the range of 8.3% to 9.3%") needs its own pattern plus conversion against the year-ago
base.

Done when: coverage above 50% of releases, `br_validate.py` still passes, and the `beat_pct`
distribution stays near p5 −3%, median +3%, p95 +11%. **A widening jump in that distribution means
new false positives, not new coverage.**

## 3. Make the raise leg mean what it says

Every flagged name currently clears on the weak leg. `br_flag.py` computes `raise_fy` (a genuine
raised full-year guide) but only 120 of 934 raise tests can use it, because it needs a readable
full-year guide in two consecutive releases *in the same fiscal year*.

Two fixes: fiscal year is currently approximated as `reported_q.dt.year`, which is wrong for
off-calendar filers — derive it from the filer's fiscal year end (available in `tier1_sic.pkl` as
`fy_end`). And task 2's coverage feeds this directly.

Done when a material share of flags carry `raise_strength == "strong"`.

## 4. Turn it into a monitor

Everything is a point-in-time snapshot today. Trigger on EDGAR arrival for the universe,
recompute, alert on threshold crossings. That is the difference between a leading indicator and a
historical table.

Add a `state/` table of last-seen accession per CIK; poll the submissions API; on a new 8-K with
item 2.02 or a new 10-Q, rerun only the affected filer. Note `tier1_frames.py` is whole-market per
call, so schedule it daily rather than per-filer.

## 5. Scale the acceleration score by each series' own volatility

`accel_rank.py` ranks raw acceleration, which structurally favours small lumpy segments — KLAC
Patterning swings ±30pp routinely, so its +61% quarter means far less than ADI's steady climb.
Score acceleration as a z-score against the series' own history, and promote `qoq_3q` from a
display column to a confirmation requirement.

Also split trough-exit from high-level acceleration: MCHP (−48% → +38%) and MRVL (+21% → +46%) are
different phenomena that one ranked list conflates.

## 6. Disclosure-change detector

The two largest signals in the data are both disclosure *events*, not values: AVGO's RPO stepping
$45bn → $164.6bn (plausibly a scope change as AI commitments became non-cancellable) and MU
re-disclosing RPO after a five-year gap. ASML discontinuing bookings is the same class pointing the
other way.

Cheap to build on the printings tables already kept (`out/*_q_printings.pkl`,
`out/ASML_kpi_printings.pkl`): flag when a filer starts, stops, redefines or restates a KPI. Also
promote the `short_history` warning in `accel_rank.py` to a hard gate requiring restated
comparatives — MU's CDBU currently tops the acceleration screen at +653% on 7 quarters of history.

## 7. Backtest book-to-bill properly

Never tested. It is the most likely place for real signal: forward-looking by construction, buried
in footnotes, and absent from the returns study entirely.

Must use pipeline 1's as-first-reported path, **not** tier-1 frames (restatement bias). The
machinery exists in `study_events.py` (earnings-release date matching) and `study_run2.py` (rank
IC, quintiles, subsamples, placebo). One specific hypothesis worth pre-registering: RPO is
disclosed in the 10-Q, not usually the press release, so for RPO the *filing* date is the
information date — the opposite of revenue, where the release date is. The release-to-filing gap
is a median 13 days.

## 8. Widen pipeline 1 beyond semis

The per-ticker config is identifiers only, so it generalizes. Run segment extraction over the
tier-2 shortlist (139 names in `market_bookings_screen.xlsx`) rather than the whole market: ~335
requests and ~47 MB per ticker means the shortlist is a few hours and ~7 GB, the full market is
days and 46 GB against a 26 GB disk allowance. Prune raw filings after parsing to keep disk
bounded, and checkpoint per ticker.

This is also what gives the returns study enough cross-section to detect a modest edge: 21 names
means quintiles of 2–4 stocks, which would miss one.
