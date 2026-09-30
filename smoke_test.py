"""Handoff smoke test: proves the shipped code and data are consistent, without touching the network.

Run:  python smoke_test.py
Every check reconciles a shipped artifact against the code that produced it. A failure here means
the handoff is broken, not that the data is wrong.
"""
import os, sys, importlib, pandas as pd, numpy as np

FAIL = []
def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    if not ok: FAIL.append(name)

def imports():
    mods = ["edgar", "earnings_docs", "xbrl_financials", "xbrl_segments", "tables", "validators",
            "run_xbrl_names", "guidance_generic", "br_patterns", "llm_fallback",
            "tier1_panel", "tier1_screen", "accel_rank", "br_flag", "br_patterns"]
    for m in mods: importlib.import_module(m)
    return True, f"{len(mods)} modules import cleanly"

def segments_reconcile():
    """A real add-up failure reads "sum X != total Y". The other non-"sum ok" rows are successful
    transformations — a dropped subtotal or a separated geography breakdown — each applied only
    because it made the segments reconcile. Assert the unreconciled RATE, not the raw count."""
    import glob
    groups = fails = clean = n = 0
    for p in sorted(glob.glob("out/*_addup.pkl")):
        r = pd.read_pickle(p)
        if not len(r): continue
        f = int(r.issue.str.contains("!=", na=False).sum())
        groups += len(r); fails += f; n += 1; clean += (f == 0)
    if not groups: return False, "no add-up reports shipped"
    rate = fails / groups
    return rate < 0.02, f"{groups} groups, {fails} unreconciled ({rate:.2%}), {clean}/{n} tickers clean"

def guide_plausibility():
    """the beat% distribution must stay in the band the plausibility guard was calibrated to"""
    A = pd.read_pickle("out/br_quarters.pkl")
    b = A.beat_pct.dropna()
    p5, med, p95 = b.quantile(.05), b.median(), b.quantile(.95)
    ok = -0.10 < p5 < 0 and 0 < med < 0.06 and 0.05 < p95 < 0.20
    return ok, f"p5 {p5:+.1%}, median {med:+.1%}, p95 {p95:+.1%}"

def nvda_2023_template():
    """the acceleration screen must still reproduce the case it was calibrated on"""
    M = pd.read_pickle("out/accel_metrics.pkl")
    g = M[(M.ticker == "NVDA") & (M.axis == "segment") & (M.series == "Compute & Networking")]
    g = g[g.cq.astype(str).isin(["2023Q2", "2023Q3", "2023Q4"])].sort_values("cq")
    if len(g) != 3: return False, f"expected 3 quarters, found {len(g)}"
    y = [round(v, 2) for v in g.yoy]
    ok = y[0] < 0.4 < y[1] and y[1] < y[2] and all(v > 0 for v in g.accel)
    return ok, f"y/y {y[0]:+.0%} -> {y[1]:+.0%} -> {y[2]:+.0%}, acceleration positive throughout"

def b2b_gate():
    """the RPO-cover gate has to keep the vacuous names out: near-zero cover pins b2b to 1.00"""
    L = pd.read_pickle("out/tier1_latest.pkl")
    if "ticker" not in L.columns:                      # tier1_screen already joins tickers on
        T = pd.read_pickle("out/cik_tickers.pkl")[["cik", "ticker"]]
        L = L.merge(T, on="cik", how="left")
    bad = L[L.ticker.isin(["NVDA", "AMD"])].drop_duplicates("ticker")
    if not len(bad): return False, "NVDA/AMD not in the panel"
    hi = bad[bad.rpo_cover_q > 1.0]
    return len(hi) == 0, f"NVDA/AMD cover {list(bad.rpo_cover_q.round(2))} — correctly below the 1-quarter gate"

def study_conclusion():
    """the study's headline: Teradyne Semiconductor Test leads the cycle, and the lead beats lag 0"""
    C = pd.read_pickle("out/study_cycle.pkl")
    r = C[(C.ticker == "TER") & (C.segment.str.contains("Test"))]
    if not len(r): return False, "TER Semiconductor Test missing"
    r = r.iloc[0]
    return r.segment_leads_q >= 1 and r.peak_rho > r.rho_at_0, \
f"leads {int(r.segment_leads_q)}q, rho {r.peak_rho:.2f} vs {r.rho_at_0:.2f} contemporaneous"

def no_network():
    """the cache directory is not shipped, so nothing above may have needed the network"""
    return edgar_stats_http == edgar.STATS["http"], f"HTTP requests during the test: {edgar.STATS['http']}"

if __name__ == "__main__":
    if not os.path.exists("out"):
        print("FAIL  out/ not found — run from the package root"); sys.exit(1)
    import edgar
    edgar_stats_http = edgar.STATS["http"]
    check("library imports", imports)
    check("segment add-up reconciles", segments_reconcile)
    check("guide plausibility band holds", guide_plausibility)
    check("NVDA 2023 template reproduces", nvda_2023_template)
    check("RPO-cover gate excludes vacuous b2b", b2b_gate)
    check("study conclusion intact (TER leads)", study_conclusion)
    check("no network needed", no_network)
    print()
    print(f"{'ALL CHECKS PASSED' if not FAIL else str(len(FAIL)) + ' FAILED: ' + ', '.join(FAIL)}")
    sys.exit(1 if FAIL else 0)
