"""Combine regex-read guidance with the validated model answers into out/{T}_guid_final.pkl (one row per release, with how it was read)."""
import json, os, sys, pandas as pd, numpy as np
A = json.load(open("out/model_answers.json"))
for t in sys.argv[1:]:
    cfg = json.load(open(f"config/{t}.json"))
    p = f"out/{t}_guid.pkl" if cfg.get("filer_type") == "FPI" else f"out/{t}_earn.pkl"
    if not os.path.exists(p): print(t, "no releases parsed"); continue
    G = pd.read_pickle(p); G = (G if isinstance(G, pd.DataFrame) else G["G"]).copy(); G["filed"] = pd.to_datetime(G.filed)
    G["method"] = np.where(G.filter(regex="^revenue_").notna().any(axis=1), "regex", "not read")
    for key, v in A.items():
        task, acc = key.split("|")
        if task != f"guidance_{t}": continue
        o = v["output"]; i = G.index[G.accn == acc]
        if not len(i): continue
        i = i[0]
        if o.get("no_guidance"):
            G.loc[i, "method"] = f"model ({v['model']}): release gives no revenue guide"; continue
        per = str(o.get("guide_period") or "")
        pre = "fy_" if per == "full year" else "h_" if per == "half year" else ""
        for c in ("revenue_mid", "revenue_low", "revenue_high", "revenue_pm_pct", "revenue_pm_abs", "revenue_qoq_pct", "revenue_direction", "gm_gaap_pct", "gm_nongaap_pct", "eps_low", "eps_high"):
            if o.get(c) is None: continue
            col = pre + c
            if col not in G.columns: G[col] = pd.Series([None] * len(G), dtype=object)
            if col == "revenue_direction" or isinstance(o[c], str): G[col] = G[col].astype(object)
            if pd.isna(G.loc[i, col]) or G.loc[i, "method"] == "not read": G.loc[i, col] = o[c]
        G.loc[i, "method"] = f"model ({v['model']})" + (f" — {per}" if per and pre else "") + (" — update of current-quarter guide" if "update" in per else "")
    G.to_pickle(f"out/{t}_guid_final.pkl")
    print(t, len(G), "releases |", G.method.str.split(":").str[0].str.split(" —").str[0].value_counts().to_dict())
