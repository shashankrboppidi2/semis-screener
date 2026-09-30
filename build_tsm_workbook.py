"""TSM_sec_history.xlsx — TSMC's quarterly history and KPIs, from its own 6-K filings.

TSMC files no 10-Qs and tags only annual figures in XBRL, so nothing here comes from the
quarterly XBRL that drives the other 33 workbooks. Each quarter is read from the earnings
release table, with the release's own YoY and QoQ percentages used as the check. Currency is
NT$ million throughout, as TSMC reports.
"""
import pandas as pd, numpy as np, os, json
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
B = Font(bold=True); HD = PatternFill("solid", fgColor="DDE6F0"); WRAP = Alignment(wrap_text=True, vertical="top")

def fq(pe):
    pe = pd.Timestamp(pe); return pe.year, (pe.month - 1) // 3 + 1

def put(ws, df, r0=1, note=None, pct=(), money=(), dec2=()):
    r = r0
    if note:
        c = ws.cell(r, 1, note); c.font = Font(italic=True); c.alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=max(6, len(df.columns)))
        ws.row_dimensions[r].height = 26; r += 3
    for j, col in enumerate(df.columns, 1):
        c = ws.cell(r, j, str(col)); c.font = B; c.fill = HD; c.alignment = WRAP
    for i, row in enumerate(df.itertuples(index=False), r + 1):
        for j, v in enumerate(row, 1):
            nm = str(df.columns[j - 1])
            if isinstance(v, pd.Timestamp): v = v.to_pydatetime()
            c = ws.cell(i, j, None if (isinstance(v, float) and pd.isna(v)) else v)
            if hasattr(v, "year") and not isinstance(v, (int, float)): c.number_format = "yyyy-mm-dd"
            elif isinstance(v, (int, float)):
                c.number_format = "0.0%" if nm in pct else ("#,##0" if nm in money else ("0.00" if nm in dec2 else "#,##0.0"))
    for j, col in enumerate(df.columns, 1):
        ws.column_dimensions[get_column_letter(j)].width = max(12, min(30, len(str(col)) + 3))
    ws.freeze_panes = ws.cell(r + 1, 1)
    return r + len(df)

def main():
    q = pd.read_pickle("out/TSM_q.pkl").sort_values("period_end")
    lat = pd.read_pickle("out/TSM_q_latest.pkl").sort_values("period_end")
    P = pd.read_pickle("out/TSM_q_printings.pkl")
    wb = Workbook(); wb.remove(wb.active)
    MET = [("revenue", "Net revenue"), ("gross_profit", "Gross profit"), ("operating_income", "Income from operations"),
           ("income_before_tax", "Income before tax"), ("net_income", "Net income")]

    # --- quarterly income statement, with margins and growth as live formulas
    ws = wb.create_sheet("Quarterly")
    d = q.copy(); d["fy"], d["fq"] = zip(*d.period_end.map(fq))
    cols = ["fy", "fq", "period_end", "filed"] + [m for m, _ in MET] + ["eps_diluted"]
    hdr = ["FY", "Q", "Quarter end", "Release date", "Net revenue", "Gross profit", "Income from operations",
           "Income before tax", "Net income", "EPS (NT$)", "Gross margin", "Operating margin", "Net margin",
           "Revenue y/y", "Revenue q/q", "Restated later?"]
    r0 = 4
    ws.cell(1, 1, "All figures NT$ million except EPS, as first reported in the quarter's own earnings release. "
                  "Margins and growth are formulas over the columns to their left; 'Restated later?' flags a quarter a later release printed differently.").font = Font(italic=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=16); ws.row_dimensions[1].height = 26
    for j, h in enumerate(hdr, 1):
        c = ws.cell(r0, j, h); c.font = B; c.fill = HD; c.alignment = WRAP
    rest = P.groupby("period_end").revenue.nunique()
    for i, row in enumerate(d.itertuples(index=False), r0 + 1):
        v = dict(zip(d.columns, row))
        ws.cell(i, 1, int(v["fy"])); ws.cell(i, 2, int(v["fq"]))
        ws.cell(i, 3, pd.Timestamp(v["period_end"]).to_pydatetime()).number_format = "yyyy-mm-dd"
        ws.cell(i, 4, pd.Timestamp(v["filed"]).to_pydatetime()).number_format = "yyyy-mm-dd"
        for k, (m, _) in enumerate(MET):
            c = ws.cell(i, 5 + k, None if pd.isna(v.get(m)) else float(v[m])); c.number_format = "#,##0"
        c = ws.cell(i, 10, None if pd.isna(v.get("eps_diluted")) else float(v["eps_diluted"])); c.number_format = "0.00"
        for k, num in enumerate(("F", "G", "I")):      # gross, operating, net margin
            c = ws.cell(i, 11 + k, f"=IF(E{i}=0,\"\",{num}{i}/E{i})"); c.number_format = "0.0%"
        prev4, prev1 = i - 4, i - 1
        ws.cell(i, 14, f"=IF({prev4}<{r0+1},\"\",IF(E{prev4}=0,\"\",E{i}/E{prev4}-1))" if prev4 >= r0 + 1 else "").number_format = "0.0%"
        ws.cell(i, 15, f"=IF(E{prev1}=0,\"\",E{i}/E{prev1}-1)" if prev1 >= r0 + 1 else "").number_format = "0.0%"
        ws.cell(i, 16, "yes" if rest.get(pd.Timestamp(v["period_end"]), 1) > 1 else "")
    for j in range(1, 17): ws.column_dimensions[get_column_letter(j)].width = 15
    ws.freeze_panes = ws.cell(r0 + 1, 1)

    # --- annual roll-up as formulas over the quarterly sheet
    wsa = wb.create_sheet("Annual from quarters")
    wsa.cell(1, 1, "Each year is the sum of its four quarters on the Quarterly tab, as formulas, so the tie to the 20-F can be checked in the sheet.").font = Font(italic=True)
    wsa.merge_cells(start_row=1, start_column=1, end_row=2, end_column=8)
    for j, h in enumerate(["FY", "Quarters", "Net revenue", "Gross profit", "Income from operations", "Income before tax", "Net income", "Gross margin"], 1):
        c = wsa.cell(4, j, h); c.font = B; c.fill = HD
    yrs = sorted(d.fy.unique()); rowmap = {}
    for i, row in enumerate(d.itertuples(index=False), r0 + 1): rowmap.setdefault(dict(zip(d.columns, row))["fy"], []).append(i)
    for k, y in enumerate(yrs):
        i = 5 + k; rs = rowmap[y]; rng = lambda L: ",".join(f"Quarterly!{L}{x}" for x in rs)
        wsa.cell(i, 1, int(y)); wsa.cell(i, 2, len(rs))
        for j, L in enumerate("EFGHI"):
            wsa.cell(i, 3 + j, f"=SUM({rng(L)})").number_format = "#,##0"
        wsa.cell(i, 8, f"=IF(C{i}=0,\"\",D{i}/C{i})").number_format = "0.0%"
    for j in range(1, 9): wsa.column_dimensions[get_column_letter(j)].width = 17

    # --- KPI tabs
    if os.path.exists("out/TSM_tech_mix.pkl"):
        tm = pd.read_pickle("out/TSM_tech_mix.pkl")
        nd = tm[tm.basis == "node"]
        w = nd.pivot_table(index="period_end", columns="node", values="pct_of_wafer_revenue").sort_index()
        def key(c):
            h = c.split("/")[0].rstrip("nmu")
            return (c.endswith("um"), -float(h))
        w = w[sorted(w.columns, key=key)].reset_index()
        w.insert(1, "sum of named nodes", w.drop(columns="period_end").sum(axis=1))
        cum = tm[tm.basis == "cumulative"].pivot_table(index="period_end", columns="node", values="pct_of_wafer_revenue")
        if len(cum): w = w.merge(cum.reset_index(), on="period_end", how="left")
        put(wb.create_sheet("Technology mix"), w,
            note="Share of wafer revenue by process node, as stated in each quarter's earnings release. TSMC names only its leading nodes, so the row is not "
                 "meant to reach 100% -- the named-node sum is shown so the gap is visible rather than implied. Where a release gave a cumulative bucket "
                 "instead (\'advanced technologies, defined as 28-nanometer and more advanced\'), it is held in its own column and never added to the node shares.")
    if os.path.exists("out/TSM_platform_mix.pkl"):
        pm = pd.read_pickle("out/TSM_platform_mix.pkl")
        w = pm.pivot_table(index="period_end", columns="platform", values="pct_of_revenue").sort_index().reset_index()
        w["total"] = w.drop(columns="period_end").sum(axis=1)
        put(wb.create_sheet("Platform mix"), w, note="Share of revenue by end platform (HPC, smartphone, IoT, automotive, DCE, other) from the quarterly earnings "
            "presentation. These are published as a pie chart, so they are readable only for the quarters where the chart labels survive as text; "
            "kept only where the shares found sum to 100% within rounding, and the total column shows that check.")
    if os.path.exists("out/TSM_monthly.pkl"):
        M = pd.read_pickle("out/TSM_monthly.pkl").sort_values("month_end")
        M = M[["month_end", "revenue_ntd_m"] + [c for c in ("ytd_ntd_m", "source", "filed") if c in M.columns]]
        wsm = wb.create_sheet("Monthly revenue")
        M2 = M.copy()
        put(wsm, M2, note="TSMC reports revenue monthly. NT$ million, from the release's own table; each row was accepted only when it reproduced the "
            "month-on-month and year-on-year percentages printed beside it. Three months should sum to the quarter on the Quarterly tab.", money=("revenue_ntd_m", "ytd_ntd_m"))
    if os.path.exists("out/TSM_guid.pkl"):
        G = pd.read_pickle("out/TSM_guid.pkl").sort_values("period_end")
        keep = [c for c in ("guided_at", "period_end", "filed", "rev_low", "rev_high", "rev_unit", "gm_low", "gm_high", "om_low", "om_high", "capex_low_usd_bn", "capex_high_usd_bn") if c in G.columns]
        put(wb.create_sheet("Guidance"), G[keep], note="Next-quarter guidance as given in each release. 'guided_at' is the quarter just reported, 'period_end' the quarter guided.", dec2=("rev_low", "rev_high"))
    put(wb.create_sheet("Printings"), P.sort_values(["period_end", "filed"]),
        note="Every printing of every quarter. Each release prints three quarters -- the current one, the year-ago quarter and the prior quarter -- so a "
             "figure that changed between releases is visible here.")
    put(wb.create_sheet("Latest printing"), lat, note="The most recent figure printed for each quarter, against the first-reported figures on the Quarterly tab.")
    src = pd.DataFrame([("SEC EDGAR 6-K", "earnings releases (EX-99.1) and the quarterly earnings presentation (EX-99.2); monthly revenue releases"),
                        ("Column alignment", "each row's numeric values read in order, the three quarter columns taken by position, then checked against the YoY and QoQ percentages the filer printed"),
                        ("Currency", "NT$ million as reported; TSMC also states a US$ revenue figure, not used here"),
                        ("Not from XBRL", "TSMC's XBRL carries annual figures only, so no quarterly figure here comes from it")],
                       columns=["source", "detail"])
    ws = wb.create_sheet("Method and sources"); put(ws, src)
    ws.column_dimensions["A"].width = 22; ws.column_dimensions["B"].width = 110
    for c in ws["B"]: c.alignment = WRAP
    wb.save("out/TSM_sec_history.xlsx")
    print("wrote out/TSM_sec_history.xlsx |", wb.sheetnames)
if __name__ == "__main__": main()
