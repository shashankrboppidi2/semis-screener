"""Income statement + balance sheet from SEC companyfacts (XBRL). Deterministic, no model. Output: long table with first-reported and latest-filed values."""
import pandas as pd, numpy as np, edgar
CONCEPTS = {  # canonical -> us-gaap concepts in priority order
 "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet"],
 "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
 "gross_profit": ["GrossProfit"], "research_and_development": ["ResearchAndDevelopmentExpense"],
 "sga": ["SellingGeneralAndAdministrativeExpense"], "total_operating_expenses": ["OperatingExpenses"], "operating_income": ["OperatingIncomeLoss"],
 "income_before_tax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
 "income_tax": ["IncomeTaxExpenseBenefit"], "net_income": ["NetIncomeLoss"], "eps_basic": ["EarningsPerShareBasic"], "eps_diluted": ["EarningsPerShareDiluted"],
 "shares_basic": ["WeightedAverageNumberOfSharesOutstandingBasic"], "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
 "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"], "marketable_securities": ["MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "ShortTermInvestments"],
 "accounts_receivable": ["AccountsReceivableNetCurrent"], "inventories": ["InventoryNet"], "total_current_assets": ["AssetsCurrent"], "total_assets": ["Assets"],
 "accounts_payable": ["AccountsPayableCurrent"], "total_current_liabilities": ["LiabilitiesCurrent"], "total_liabilities": ["Liabilities"], "total_equity": ["StockholdersEquity"]}
IFRS = {  # canonical -> ifrs-full concepts (TSMC, UMC, ASE and other IFRS foreign private issuers; annual only in companyfacts)
 "revenue": ["Revenue", "RevenueFromSaleOfGoods", "RevenueFromContractsWithCustomers"], "cost_of_revenue": ["CostOfSales"], "gross_profit": ["GrossProfit"],
 "research_and_development": ["ResearchAndDevelopmentExpense"], "sga": ["SellingGeneralAndAdministrativeExpense"],
 "operating_income": ["ProfitLossFromOperatingActivities"], "income_before_tax": ["ProfitLossBeforeTax"], "income_tax": ["IncomeTaxExpenseContinuingOperations"],
 "net_income": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"], "eps_basic": ["BasicEarningsLossPerShare"], "eps_diluted": ["DilutedEarningsLossPerShare"],
 "cash_and_equivalents": ["CashAndCashEquivalents"], "accounts_receivable": ["TradeAndOtherCurrentReceivables"], "inventories": ["Inventories"],
 "total_current_assets": ["CurrentAssets"], "total_assets": ["Assets"], "accounts_payable": ["TradeAndOtherCurrentPayables"],
 "total_current_liabilities": ["CurrentLiabilities"], "total_liabilities": ["Liabilities"], "total_equity": ["EquityAttributableToOwnersOfParent", "Equity"]}
def load(cik):
    cf = edgar.getj(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{edgar.cik10(cik)}.json"); gaap = cf["facts"].get("us-gaap", {}); rows = []
    if not gaap and cf["facts"].get("ifrs-full"):          # IFRS filer: same extraction, ifrs-full concept names
        gaap = cf["facts"]["ifrs-full"]; CONCEPTS.clear(); CONCEPTS.update(IFRS)
    for can, cons in CONCEPTS.items():
        for pri, con in enumerate(cons):
            if con not in gaap: continue
            for unit, facts in gaap[con]["units"].items():
                scale = 1 if "/shares" in unit else 1e6   # USD and shares -> millions; EPS stays per share
                for f in facts:
                    if f.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "20-F/A", "6-K"): continue
                    s = pd.Timestamp(f["start"]) if "start" in f else None; e = pd.Timestamp(f["end"])
                    dur = 0 if s is None else int(round((e - s).days / 30.44))
                    rows.append(dict(canonical=can, concept=con, priority=pri, period_end=e, duration_months=dur, value=f["val"] / scale, unit=unit, accn=f["accn"], form=f["form"], filed=pd.Timestamp(f["filed"])))
    df = pd.DataFrame(rows); df = df[df.duration_months.isin([0, 3, 6, 9, 12])]
    # one unit per company: IFRS filers tag the same fact in the reporting currency and a USD convenience translation.
    # Keep the currency the filer uses for most facts (its reporting currency); per-share units are separate by construction.
    money = df[~df.unit.str.contains("/shares")]
    if len(money) and money.unit.nunique() > 1:
        keep = money.unit.value_counts().index[0]; df = df[df.unit.str.contains("/shares") | (df.unit == keep)]
    # unit sanity: filers sometimes tag share counts in thousands (NVIDIA 2009-2011). Fix values 1000x below the metric's median and flag them.
    sh = df.canonical.str.startswith("shares"); med = df[sh].groupby("canonical").value.transform("median")
    fix = sh & (df.value < med.reindex(df.index).fillna(0) / 100)
    df.loc[fix, "value"] = df.loc[fix, "value"] * 1000; df["unit_fix"] = fix
    # one concept per canonical+period: the highest-priority concept that has it
    df = df[df.priority == df.groupby(["canonical", "period_end", "duration_months"]).priority.transform("min")]
    df.to_pickle(f"{edgar.CACHE}/../all_facts_{cik}.pkl")   # every vintage, for validators
    first = df.sort_values(["filed", "accn"]).groupby(["canonical", "period_end", "duration_months"]).head(1).assign(basis="as_first_reported")
    last = df.sort_values(["filed", "accn"]).groupby(["canonical", "period_end", "duration_months"]).tail(1).assign(basis="latest_filed")
    out = pd.concat([first, last]).drop_duplicates(["canonical", "period_end", "duration_months", "basis"])
    # Q4 = FY - 9M YTD (flows only, both first reported)
    f = out[out.basis == "as_first_reported"]; a = f[f.duration_months == 12]; n = f[f.duration_months == 9]
    q4 = a.merge(n, on="canonical", suffixes=("", "_9"))
    q4 = q4[((q4.period_end - q4.period_end_9).dt.days.between(80, 100)) & ~q4.canonical.str.startswith(("eps", "shares"))]
    q4 = q4.assign(value=q4.value - q4.value_9, duration_months=3, basis="as_first_reported", concept=q4.concept + " (FY-9M)")[out.columns]
    have = set(zip(f[f.duration_months == 3].canonical, f[f.duration_months == 3].period_end))
    q4 = q4[[(c, p) not in have for c, p in zip(q4.canonical, q4.period_end)]]
    return pd.concat([out, q4], ignore_index=True), cf.get("entityName")
