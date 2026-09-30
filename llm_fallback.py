"""Model fallback queue. Scripts enqueue small, self-contained requests; a runner answers them.
Production runner: Anthropic Messages/Batch API (Haiku first, Sonnet on validation failure), system prompt cached.
Test runner (this session, no API key): a Haiku subagent reads queue/<task>.jsonl and writes queue/<task>.out.jsonl."""
import json, os, re
ROOT = os.path.dirname(os.path.abspath(__file__))
SYSTEM = {
"customers": """You read one paragraph from a company's 10-Q/10-K about customer concentration. Return ONLY JSON:
{"rows":[{"period":"<period the % refers to, as written, e.g. 'first quarter of fiscal year 2027' or 'fiscal year 2026'>","duration_months":3|6|9|12,"customer":"<label as written or 'customer 1','customer 2' in order>","type":"direct"|"indirect"|"combined","pct":<number>,"exact":true|false}],"none_over_10pct_periods":["<periods where the text says no customer reached 10%>"]}
Rules: include EVERY period and EVERY percentage mentioned, including prior-year comparison periods and figures in tables (one row per customer per period).
Only % of TOTAL REVENUE (skip accounts receivable, geography, segments). 'aggregated approximately 20% ... from two customers' = one row type 'combined' pct 20.
'10% of our total revenue from one customer' is a real row (pct 10, exact true). 'estimated to represent 10% or more' = pct 10, exact false. Copy numbers exactly; never compute.""",
"guidance": """You read a company's 'Outlook' paragraph from an earnings release. Return ONLY JSON:
{"guide_period":"next quarter"|"current quarter (update)"|"half year"|"full year"|null,"no_guidance":true|false,"revenue_mid":<USD millions or null>,"revenue_low":null,"revenue_high":null,"revenue_pm_pct":<number or null>,"revenue_qoq_pct":null,"revenue_qoq_pm_pct":null,"revenue_yoy_pct":null,"revenue_direction":"up"|"down"|"flat"|"flat to down"|"flat to up"|null,"gm_gaap_pct":null,"gm_nongaap_pct":null,"gm_pm_bps":null,"opex_gaap":null,"opex_nongaap":null,"eps_low":null,"eps_high":null,"notes":"<exclusions, short>"}
USD millions ($1.35 billion = 1350). Use a range's low/high when a range is given instead of a midpoint. Copy numbers exactly; never compute a midpoint unless printed. Text may hold several '---' separated excerpts: use the company's forward guide (Outlook section), not a quote about past results or a previously issued guide. If no forward revenue guide is given, no_guidance=true."""}
SYSTEM["customers_sonnet"] = SYSTEM["customers"]
SYSTEM["guidance_eur"] = SYSTEM["guidance"].replace("<USD millions or null>", "<EUR millions or null>").replace("USD millions ($1.35 billion = 1350)", "EUR millions (EUR 1.35 billion = 1350). Also give \"rd\" and \"sga\" (EUR millions) if guided").replace('"eps_high":null,', '"eps_high":null,"rd":null,"sga":null,')
def enqueue(task, items, model="haiku", system=None):
    p = f"{ROOT}/queue/{task}.jsonl"
    with open(p, "w") as f:
        for it in items: f.write(json.dumps({"id": it["id"], "model": model, "system": system or (SYSTEM[task] if task in SYSTEM else SYSTEM[task.split("_")[0]]), "user": it["text"]}) + "\n")
    return p
def results(task):
    p = f"{ROOT}/queue/{task}.out.jsonl"; out = {}
    if os.path.exists(p):
        for l in open(p):
            if l.strip():
                r = json.loads(l); out[r["id"]] = r
    return out
def approx_tokens(s): return int(len(s) / 3.8)
