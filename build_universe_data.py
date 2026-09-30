"""Cross-ticker workbook: coverage and QA per ticker, revenue history side by side, segment inventory, guidance accuracy."""
import json, glob, os, sys, pandas as pd, numpy as np, tables as T
from openpyxl import Workbook
from build_workbooks import title, hdr, put, table, grid, ratio, growth, legend, F_B, F_BB, F_I, F_BL, qlabel
def have(t, k): return os.path.exists(f"out/{t}_{k}.pkl")
def tickers():
    return sorted({os.path.basename(p).split("_")[0] for p in glob.glob("out/*_fin.pkl")})
def qrev(t, cfg):
    if cfg.get("filer_type") == "FPI" and not os.path.exists(f"out/{t}_q.pkl"):
        return pd.Series(dtype=float)          # IFRS / unconfigured foreign filer: annual only, no quarterly series
    if cfg.get("filer_type") == "FPI":
        q = pd.read_pickle(f"out/{t}_q.pkl"); return pd.Series(q.revenue.values, index=pd.to_datetime(q.period_end)).sort_index()
    f = pd.read_pickle(f"out/{t}_fin.pkl"); f = f[(f.canonical == "revenue") & (f.duration_months == 3) & (f.basis == "as_first_reported")]
    return pd.Series(f.value.values, index=pd.to_datetime(f.period_end)).sort_index()
def rows_for(t):
    cfg = json.load(open(f"config/{t}.json")); r = dict(ticker=t, name=cfg.get("name", t), annual_form=cfg.get("annual_form"), fye_month=cfg.get("fye_month"),
                                                       currency=cfg.get("currency", "USD"), cik=cfg["cik"], cik_chain=len(cfg.get("cik_chain", [1])))
    f = pd.read_pickle(f"out/{t}_fin.pkl"); f["period_end"] = pd.to_datetime(f.period_end)
    q = f[(f.duration_months == 3) & (f.basis == "as_first_reported")]
    rv = qrev(t, cfg); ann = f[(f.canonical == "revenue") & (f.duration_months == 12)]
    r.update(fin_values=len(f), quarters=len(rv), first_quarter=rv.index.min() if len(rv) else None, last_quarter=rv.index.max() if len(rv) else None,
             annual_years=int(ann.period_end.dt.year.nunique()), annual_from=ann.period_end.min(), annual_to=ann.period_end.max(),
             frequency="quarterly + annual" if len(rv) else "annual only (20-F; quarterly needs the 6-K results tables)")
    if have(t, "seg"):
        s = pd.read_pickle(f"out/{t}_seg.pkl"); seg = s[(s["axis"] == "segment") & s.name.notna()]
        r.update(segment_names=", ".join(sorted(seg.name.unique())[:12]), n_segment_series=seg.name.nunique(),
                 segment_first=pd.to_datetime(seg.period_end).min() if len(seg) else None,
                 other_axes=", ".join(sorted(x for x in s["axis"].unique() if x != "segment")))
    if have(t, "addup"):
        a = pd.read_pickle(f"out/{t}_addup.pkl")
        if len(a):
            vc = a.issue.value_counts(); ok = int(vc.get("sum ok", 0)); bad = int(sum(v for k, v in vc.items() if k.startswith("sum ") and k != "sum ok"))
            r.update(segments_reconcile=f"{ok}/{ok + bad}", segment_rules=", ".join(f"{k.split('—')[0].strip()}: {v}" for k, v in vc.items() if not k.startswith("sum ")) or "none")
    if have(t, "guid_check"):
        g = pd.read_pickle(f"out/{t}_guid_check.pkl")
        if len(g):
            vc = g.status.value_counts(); r.update(guides_checked=len(g), guides_within_20pct=int(vc.get("ok", 0)), guides_flagged=int(vc.get("CHECK", 0)),
                                                   guide_median_err=float((g.ratio - 1).abs().median()) if g.ratio.notna().any() else None)
    for k, lab in (("earn", "releases_parsed"), ("customers", "customer_rows"), ("kpi_q", "kpi_rows")):
        if have(t, k):
            d = pd.read_pickle(f"out/{t}_{k}.pkl"); r[lab] = len(d["H"]) if isinstance(d, dict) else len(d)
    A = json.load(open("out/model_answers.json")) if os.path.exists("out/model_answers.json") else {}
    for nm in ("guidance", "customers"):
        used = [v for k, v in A.items() if k.startswith(f"{nm}_{t}|")]
        r[f"model_reads_{nm}"] = len(used); r[f"model_sonnet_{nm}"] = sum(1 for v in used if v.get("model") == "sonnet")
    if os.path.exists(f"out/{t}_guid_final.pkl"):
        G = pd.read_pickle(f"out/{t}_guid_final.pkl")
        m = G.method.str.split(":").str[0].str.split(" —").str[0].value_counts()
        r["guides_read_by"] = "; ".join(f"{k}: {v}" for k, v in m.items())
    return r
if __name__ == "__main__":
    TS = sys.argv[1:] or tickers(); rows = []
    for t in TS:
        try: rows.append(rows_for(t))
        except Exception as e: rows.append(dict(ticker=t, name=f"ERROR {type(e).__name__}: {e}"))
    d = pd.DataFrame(rows)
    U = pd.read_pickle("out/etf_universe_map.pkl")
    for e in ("SMH", "SOXX"):
        col = f"{e} wt %"; m = dict(zip(U.ticker, U.get(f"{e} wt % (24 Sep)", pd.Series(dtype=float))))
        d[col] = d.ticker.map(m)
    d = d.sort_values(["SMH wt %", "SOXX wt %"], ascending=False, na_position="last")
    wb = Workbook(); ws = wb.active; ws.title = "Coverage & QA"
    title(ws, f"Semis universe — what was extracted per ticker and how it checked out ({len(d)} tickers)",
          "One workbook per ticker holds the detail. Segments reconcile = quarters where the reported segments sum to that filing's own consolidated revenue. "
          "Guides within 20% = company revenue guides whose guided quarter came in within 20% of the implied midpoint.")
    cols = ["ticker", "name", "SMH wt %", "SOXX wt %", "currency", "annual_form", "fye_month", "cik", "cik_chain", "frequency", "quarters", "first_quarter", "last_quarter", "annual_years", "annual_from", "annual_to",
            "fin_values", "n_segment_series", "segment_first", "segments_reconcile", "segment_rules", "other_axes", "releases_parsed", "guides_checked",
            "guides_within_20pct", "guides_flagged", "guide_median_err", "guides_read_by", "customer_rows", "kpi_rows",
            "model_reads_guidance", "model_sonnet_guidance", "model_reads_customers", "model_sonnet_customers", "segment_names"]
    cols = [c for c in cols if c in d]
    table(ws, d[cols], 4, widths={"name": 30, "segment_names": 60, "segment_rules": 46, "other_axes": 26, "guides_read_by": 40, "frequency": 30}, nfs={"SMH wt %": "0.00", "SOXX wt %": "0.00", "guide_median_err": "0.0%", "cik": "0"})
    ws2 = wb.create_sheet("Revenue quarterly (all)")
    title(ws2, "Quarterly revenue as first reported, every ticker (reporting currency; ASML in EUR, TSM/ASX/UMC in TWD)", "Calendar quarter-ends; a 52/53-week filer's quarter is placed on the nearest quarter-end.")
    series = {}
    for t in d.ticker:
        try: series[t] = qrev(t, json.load(open(f"config/{t}.json")))
        except Exception: pass
    idx = sorted({pd.Timestamp(p).to_period("Q").end_time.normalize() for s in series.values() for p in s.index})
    rows2 = []
    for t, s in series.items():
        v = {pd.Timestamp(p).to_period("Q").end_time.normalize(): x for p, x in s.items()}
        rows2.append(dict(key=t, label=t, values=v, note=json.load(open(f"config/{t}.json")).get("currency", "USD") + " m"))
    grid(ws2, 4, idx, rows2, None, label_w=12)
    wb.save("out/semis_universe_data.xlsx"); print("saved; tickers:", len(d))
    pd.set_option("display.width", 250)
    print(d[[c for c in ["ticker", "quarters", "first_quarter", "segments_reconcile", "n_segment_series", "guides_checked", "guides_within_20pct", "model_queue_guidance", "model_queue_customers"] if c in d]].to_string(index=False))
