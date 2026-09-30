"""Run the screens end to end and publish the results to results/.

    python run_screens.py                    # every stage: tier1 br accel workbooks
    python run_screens.py tier1 accel        # just these
    python run_screens.py accel --no-fetch   # rebuild from the pickles already in out/, no SEC requests

Stages (each step runs in its own process; a failed step is logged and the rest carry on):
  tier1      market-wide RPO / book-to-bill panel from the XBRL frames API (~310 requests)
             -> out/market_bookings_screen.xlsx
  br         beat-and-raise vs each company's own guidance, over the tier-1 universe. Needs tier1's
             panel. Refetches the latest releases per filer; only releases not read before are opened.
             -> out/beat_and_raise_screen.xlsx
  accel      segment / product / geography acceleration over the semis tickers in out/all_tickers.txt.
             Refreshes each ticker's XBRL first (~335 requests per ticker cold, a handful warm).
             -> out/semis_acceleration_screen.xlsx
  workbooks  per-ticker SEC history workbooks (deterministic parts only: the model-read customer and
             guidance gaps are not shipped, so those tabs are skipped or thinner).
             -> out/{TICKER}_sec_history.xlsx

SEC_UA must be set to a real "Name email" contact string; the SEC blocks anonymous clients.
"""
import json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)                                          # every script reads and writes out/ and config/ relative to here
PUB = os.path.join(ROOT, "results")
LOGS = "out/logs"
STAGES = ["tier1", "br", "accel", "workbooks"]
TICKERS = open("out/all_tickers.txt").read().split()
status = {}

def step(name, cmd, timeout=3 * 3600):
    os.makedirs(LOGS, exist_ok=True)
    log = f"{LOGS}/{name}.txt"; t0 = time.time()
    print(f"-> {name}: {' '.join(cmd)}", flush=True)
    try:
        with open(log, "w") as f:
            rc = subprocess.run([sys.executable] + cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    status[name] = dict(rc=rc, secs=round(time.time() - t0))
    tail = open(log).read()[-1500:]
    if rc != 0:
        status[name]["tail"] = tail[-600:]
        print(f"   FAILED ({rc}) after {status[name]['secs']}s\n" + tail, flush=True)
    else:
        print(f"   ok, {status[name]['secs']}s | " + " / ".join(tail.strip().splitlines()[-2:])[:300], flush=True)
    return rc == 0

def seed_guide_ckpt():
    """br_extract checkpoints each release it has read in out/br_guide_ckpt.jsonl, which is not shipped. Rebuild it
    from the shipped br_guidance_enriched.pkl (same fields plus what br_postpass adds) so only NEW releases are
    fetched. Values filled by br_postpass's second-tier read are cleared; br_postpass recomputes them."""
    import pandas as pd
    if os.path.exists("out/br_guide_ckpt.jsonl") or not os.path.exists("out/br_guidance_enriched.pkl"): return
    G = pd.read_pickle("out/br_guidance_enriched.pkl")
    keys = ["revenue_low", "revenue_mid", "revenue_high", "revenue_pm_abs", "fy_revenue_low", "fy_revenue_mid", "fy_revenue_high", "fy_revenue_pm_abs"]
    with open("out/br_guide_ckpt.jsonl", "w") as f:
        for r in G.to_dict("records"):
            rec = {k: r.get(k) for k in ["status", "model_text", "cik", "accn", "filed", "form"] + keys}
            if rec["status"] != "regex":
                for k in keys: rec[k] = None
            rec = {k: v for k, v in rec.items() if v is not None and v == v}
            rec["cik"] = int(rec["cik"]); rec["filed"] = str(rec["filed"])[:10]
            f.write(json.dumps(rec) + "\n")
    print(f"   seeded out/br_guide_ckpt.jsonl with {len(G):,} releases already read", flush=True)

def tier1(fetch):
    if fetch:
        ok = step("tier1_frames", ["tier1_frames.py"]) and step("tier1_panel", ["tier1_panel.py"])
        if not ok: return
        step("tier1_sic", ["tier1_sic.py"])
        step("rpo_pull", ["rpo_pull.py"])
    if not os.path.exists("out/tier1_panel.pkl"):
        print("   tier1: out/tier1_panel.pkl is missing; it is not shipped, so run tier1 once with fetching on"); return
    step("tier1_screen", ["tier1_screen.py"]) and step("build_tier1_workbook", ["build_tier1_workbook.py"])

def br(fetch):
    if not os.path.exists("out/tier1_panel.pkl"):
        print("   br: needs out/tier1_panel.pkl from the tier1 stage"); return
    if fetch:
        seed_guide_ckpt()
        if os.path.exists("out/br_releases_ckpt.jsonl"): os.remove("out/br_releases_ckpt.jsonl")   # latest releases per filer, every run
        if not (step("br_releases", ["br_releases.py"]) and step("br_extract", ["br_extract.py"])): return
        step("br_postpass", ["br_postpass.py"])
    step("br_flag", ["br_flag.py"]) and step("br_build", ["br_build.py"])

def accel(fetch):
    if fetch:
        for t in TICKERS: step(f"xbrl_{t}", ["run_xbrl.py", t], timeout=3600)
    step("accel_series", ["accel_series.py"]) and step("accel_rank", ["accel_rank.py"]) and step("build_accel_workbook", ["build_accel_workbook.py"])

def workbooks(fetch):
    os.makedirs("queue", exist_ok=True)                 # the model-queue writer expects it; nothing reads the queue here
    if fetch:
        for t in TICKERS:
            fpi = json.load(open(f"config/{t}.json")).get("filer_type") == "FPI"
            step(f"{'fpi' if fpi else 'earnings'}_{t}", ["run_fpi.py" if fpi else "run_earnings2.py", t], timeout=3600)
    step("build_workbooks", ["build_workbooks.py"] + TICKERS, timeout=3 * 3600)

def publish():
    import pandas as pd
    os.makedirs(PUB, exist_ok=True)
    for f in ["market_bookings_screen", "beat_and_raise_screen", "semis_acceleration_screen"]:
        if os.path.exists(f"out/{f}.xlsx"): shutil.copy(f"out/{f}.xlsx", PUB)
    wb = [f"out/{t}_sec_history.xlsx" for t in TICKERS if os.path.exists(f"out/{t}_sec_history.xlsx")]
    if wb:
        os.makedirs(f"{PUB}/tickers", exist_ok=True)
        for p in wb: shutil.copy(p, f"{PUB}/tickers")
    # plain-text copies of the headline lists, so a run's changes show up in a git diff
    if os.path.exists("out/tier1_latest.pkl"):
        import tier1_screen as TS
        for k, d in TS.screens(pd.read_pickle("out/tier1_latest.pkl")).items():
            d[TS.COLS].to_csv(f"{PUB}/tier1_{k}.csv", index=False, float_format="%.4g")
    if os.path.exists("out/accel_ranked.pkl"):
        cols = ["ticker", "axis", "series", "cq", "value", "yoy", "accel", "streak", "cum_accel", "qoq_3q", "share", "score", "short_history"]
        pd.read_pickle("out/accel_ranked.pkl")[cols].to_csv(f"{PUB}/accel_ranked.csv", index=False, float_format="%.4g")
    if os.path.exists("out/br_flag.pkl"):
        F = pd.read_pickle("out/br_flag.pkl")
        T = pd.read_pickle("out/cik_tickers.pkl")[["cik", "ticker"]].drop_duplicates("cik") if os.path.exists("out/cik_tickers.pkl") else None
        if T is not None: F = F.merge(T, on="cik", how="left")
        F.sort_values(["two_consecutive", "br_streak", "last_beat_pct"], ascending=False).to_csv(f"{PUB}/beat_and_raise_flags.csv", index=False, float_format="%.4g")
    json.dump(dict(finished_utc=time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), steps=status), open(f"{PUB}/run_status.json", "w"), indent=1, default=str)

if __name__ == "__main__":
    args = sys.argv[1:]; fetch = "--no-fetch" not in args
    todo = [a for a in args if not a.startswith("--")] or STAGES
    bad = [a for a in todo if a not in STAGES]
    if bad: sys.exit(f"unknown stage(s) {bad}; choose from {STAGES}")
    if fetch and not os.environ.get("SEC_UA"): sys.exit('set SEC_UA="Your Name you@domain" first (or pass --no-fetch)')
    for s in STAGES:
        if s in todo: print(f"\n=== {s} ===", flush=True); globals()[s](fetch)
    publish()
    failed = [k for k, v in status.items() if v["rc"] != 0]
    print(f"\n{len(status) - len(failed)}/{len(status)} steps ok" + (f" | failed: {failed}" if failed else ""))
    # a stage-level failure (not one ticker out of 35) fails the run, so a broken pipeline shows red in Actions
    core = [k for k in failed if not k.startswith(("xbrl_", "earnings_", "fpi_"))]
    sys.exit(1 if core else 0)
