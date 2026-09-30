"""Sequential batch runner (one process, so SEC fair-access stays under 10 req/s). Per ticker: XBRL -> earnings/FPI -> headline check
-> customer paragraphs -> guidance plausibility. Every step's outcome is logged; a failure never stops the batch."""
import json, os, glob, subprocess, sys, time, shutil
ORDER = ["INTC", "MU", "AVGO", "MRVL", "QCOM", "KLAC", "ADI", "AMAT", "LRCX", "MPWR", "TER", "TSM", "NXPI", "ALAB", "MCHP", "CRDO",
         "ON", "TSEM", "ENTG", "MTSI", "ASX", "UMC", "ARM", "STM", "CDNS", "SNPS", "NVMI", "SWKS", "CBRS", "SKHY"]
def sh(cmd, log, timeout=3600):
    t0 = time.time()
    with open(log, "w") as f:
        p = subprocess.run(["python3"] + cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode, round(time.time() - t0)
def prune(min_free_gb=8, keep=400):
    free = shutil.disk_usage("/tmp").free / 1e9
    if free >= min_free_gb: return 0
    files = sorted(glob.glob("cache/*"), key=os.path.getsize, reverse=True)[:keep]
    for p in files: os.remove(p)
    return len(files)
TAG = os.environ.get("RUN_TAG", "")                      # lets parallel workers keep separate status files
SF = f"out/run_all_status{TAG}.json"
status = json.load(open(SF)) if os.path.exists(SF) else {}
for t in [x for x in (sys.argv[1:] or ORDER)]:
    cfg = json.load(open(f"config/{t}.json")); fpi = cfg.get("filer_type") == "FPI"; st = status.setdefault(t, {})
    n = prune()
    if n: st["pruned_cache_files"] = n
    for name, cmd in ([("xbrl", ["run_xbrl.py", t])]
                      + ([("fpi", ["run_fpi.py", t])] if fpi else [("earnings", ["run_earnings2.py", t]), ("headline", ["xcheck_headline.py", t])])
                      + [("customers", ["run_customers.py", t]), ("guidance_check", ["check_guidance.py", t])]):
        if st.get(name, {}).get("rc") == 0: continue
        try: rc, secs = sh(cmd, f"out/{t}_{name}_log.txt")
        except subprocess.TimeoutExpired: rc, secs = "timeout", 3600
        st[name] = dict(rc=rc, secs=secs)
        if rc != 0: st[name]["tail"] = open(f"out/{t}_{name}_log.txt").read()[-400:]
    json.dump(status, open(SF, "w"), indent=1)
    print(t, {k: v.get("rc") for k, v in st.items() if isinstance(v, dict)}, flush=True)
