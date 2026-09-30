"""semis_acceleration_screen.xlsx — which disclosed KPI series are inflecting right now."""
import pandas as pd, numpy as np, os
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule

B = Font(bold=True); HD = PatternFill("solid", fgColor="DDE6F0"); WRAP = Alignment(wrap_text=True, vertical="top")
PCT = {"yoy", "accel", "cum_accel", "share", "qoq", "qoq_3q"}

def sheet(wb, name, df, note=None, widths=None, money=("value",), heat=None):
    ws = wb.create_sheet(name[:31]); r = 1
    if note:
        c = ws.cell(1, 1, note); c.font = Font(italic=True); c.alignment = WRAP
        ws.merge_cells(start_row=1, start_column=1, end_row=3, end_column=max(8, len(df.columns)))
        ws.row_dimensions[1].height = 15; r = 5
    for j, col in enumerate(df.columns, 1):
        c = ws.cell(r, j, str(col)); c.font = B; c.fill = HD; c.alignment = WRAP
    for i, row in enumerate(df.itertuples(index=False), r + 1):
        for j, v in enumerate(row, 1):
            nm = str(df.columns[j - 1])
            if isinstance(v, pd.Period): v = str(v)
            if isinstance(v, pd.Timestamp): v = v.to_pydatetime()
            c = ws.cell(i, j, None if (isinstance(v, float) and pd.isna(v)) else v)
            if isinstance(v, (int, float)) and not pd.isna(v):
                c.number_format = "0.0%" if (nm in PCT or nm.startswith("y/y ")) else ("#,##0" if nm in money else "0.00")
    n = len(df)
    for j, col in enumerate(df.columns, 1):
        ws.column_dimensions[get_column_letter(j)].width = (widths or {}).get(str(col), max(11, min(34, len(str(col)) + 3)))
    if heat and n:
        for col in heat:
            if col not in df.columns: continue
            L = get_column_letter(list(df.columns).index(col) + 1)
            ws.conditional_formatting.add(f"{L}{r+1}:{L}{r+n}",
                ColorScaleRule(start_type="percentile", start_value=5, start_color="F8B3AE",
                               mid_type="num", mid_value=0, mid_color="FFFFFF",
                               end_type="percentile", end_value=95, end_color="A8D5A2"))
    ws.freeze_panes = ws.cell(r + 1, 3)
    return ws

def traj(M, keys, nq=8, col="yoy"):
    """last nq quarters of y/y for the chosen series, one row each."""
    rows = []
    for t, ax, s in keys:
        g = M[(M.ticker == t) & (M.axis == ax) & (M.series == s)].dropna(subset=["value"]).sort_values("cq").tail(nq)
        if len(g) < 3: continue
        d = {"ticker": t, "axis": ax, "series": s}
        for _, x in g.iterrows(): d[f"y/y {x.cq}"] = x.yoy
        d["latest value"] = g.value.iloc[-1]; d["share of revenue"] = g.share.iloc[-1]
        rows.append(d)
    D = pd.DataFrame(rows)
    qcols = sorted([c for c in D.columns if c.startswith("y/y ")], key=lambda c: c[4:])
    return D[["ticker", "axis", "series", "latest value", "share of revenue"] + qcols]

def main():
    M = pd.read_pickle("out/accel_metrics.pkl"); ok = pd.read_pickle("out/accel_ranked.pkl"); L = pd.read_pickle("out/accel_latest.pkl")
    L["short_history"] = L.quarters_history < 8
    COLS = ["ticker", "axis", "series", "cq", "value", "yoy", "accel", "streak", "cum_accel", "qoq_3q", "share", "quarters_history", "short_history"]
    wb = Workbook(); wb.remove(wb.active)

    rows = [("What this screens for", "Not growth, but a change in the rate of growth, sustained. The template is NVIDIA in 2023: Compute & Networking went +21% y/y (Apr-23) to +166% (Jul-23) to +284% (Oct-23) - a jump in the level of y/y growth and a positive second difference, quarter after quarter."),
            ("accel", "y/y growth this quarter minus y/y growth last quarter. This is the signal; y/y alone is the level."),
            ("streak", "consecutive quarters of positive acceleration ending in the latest reported quarter."),
            ("cum_accel", "how far y/y has travelled over that streak, in growth-rate points."),
            ("qoq_3q", "three-quarter compound q/q growth. It turns before y/y does, because it does not wait for the year-ago base to roll off."),
            ("share", "the series as a share of company revenue, or for a balance series, of trailing revenue."),
            ("What is in the universe", "every quarterly revenue series these filers disclose - reportable segments, product lines, product-within-segment, geography - plus RPO and contract liabilities from XBRL and ASML's reported bookings."),
            ("Important", "the axes are alternative cuts of the same revenue, not additive. NVIDIA tags Data Center and also Compute, Networking, Hyperscale and Edge Computing, which re-slice it. Each series is scored on its own; nothing is summed across axes."),
            ("Guards", "a revenue series must be at least 5% of company revenue with a year-ago base over $20m; a balance series at least 3% of trailing revenue; series not reported in the latest quarter are excluded. short_history flags a segment with under 8 quarters, where a redefinition can distort the year-ago base."),
            ("All figures", "as first reported, from SEC XBRL. Currency is the filer's own reporting currency, in millions.")]
    sheet(wb, "How to read this", pd.DataFrame(rows, columns=["", " "]), widths={"": 24, " ": 125})

    core = ok[(ok.axis != "geography")].copy()
    sheet(wb, "Accelerating now", core[core.accel > 0][COLS], heat=["accel", "yoy", "cum_accel"],
          widths={"series": 38}, note="Every non-geography series whose growth rate rose in the latest reported quarter, ranked by acceleration weighted by the length of the run. "
          "Read accel with streak: one big quarter can be a base effect, three in a row is a trend.")
    sheet(wb, "Decelerating now", core[core.accel <= 0].sort_values("accel")[COLS], heat=["accel", "yoy"], widths={"series": 38},
          note="The same screen inverted - where the growth rate fell. Worth reading alongside the accelerating list, since the pair shows where the cycle is rotating.")

    top = [(r.ticker, r.axis, r.series) for r in core[core.accel > 0].head(22).itertuples()]
    sheet(wb, "Trajectory - accelerating", traj(M, top), widths={"series": 34}, heat=[f"y/y {q}" for q in []],
          note="The quarterly path of y/y growth for the series at the top of the screen. This is the view that shows whether a turn is building or is a single quarter.")

    bk = ok[ok.kind == "bookings / backlog"]
    sheet(wb, "Bookings and RPO", bk.sort_values("accel", ascending=False)[COLS], heat=["accel", "yoy"], widths={"series": 38},
          note="RPO (remaining performance obligation) is the closest thing to a bookings disclosure that US filers tag consistently; contract liabilities are the "
               "cash-collected slice of it. Note AVGO: acceleration is negative only because the step up happened a quarter earlier - read the level and the trajectory tab.")
    allb = L[L.kind == "bookings / backlog"].copy()
    sheet(wb, "Bookings and RPO - trajectory", traj(M, [(r.ticker, r.axis, r.series) for r in allb.itertuples()], nq=9),
          widths={"series": 38}, note="Every RPO and contract-liability series in the universe, materiality filter removed, so a small but fast-moving balance is visible too.")

    # early-stage turns: the cut that matters most, since the loud ones are already in the price
    early = core[(core.accel > 0) & (core.streak >= 2) & (core.yoy < 0.60) & (core.share >= 0.08)].sort_values(["streak", "accel"], ascending=False)
    sheet(wb, "Early-stage turns", early[COLS], heat=["accel", "yoy", "cum_accel"], widths={"series": 38},
          note="Series accelerating for two quarters or more while y/y growth is still under 60% - a turn that has not yet shown up as a headline number. "
               "Read the streak column first: a nine-quarter run climbing out of a deep trough (ADI, MCHP) is a different animal from a two-quarter "
               "reacceleration at a high level (MRVL), and the y/y column tells you which you are looking at.")
    sheet(wb, "Trajectory - early turns", traj(M, [(r.ticker, r.axis, r.series) for r in early.head(25).itertuples()]),
          widths={"series": 34}, note="Quarterly y/y path for the early-stage list. Several of these are climbing out of negative territory, where acceleration is partly an easy year-ago base - the path shows which.")

    hf = []
    if os.path.exists("out/TSM_monthly.pkl"):
        Mo = pd.read_pickle("out/TSM_monthly.pkl").sort_values("month_end")
        Mo["yoy"] = Mo.revenue_ntd_m / Mo.revenue_ntd_m.shift(12) - 1
        hf.append(Mo.tail(18)[["month_end", "revenue_ntd_m", "yoy"]].assign(source="TSMC monthly revenue (NT$ m)").rename(columns={"month_end": "period", "revenue_ntd_m": "value"}))
    if os.path.exists("out/ASML_kpi_q.pkl"):
        A = pd.read_pickle("out/ASML_kpi_q.pkl"); A = A[A.metric == "bookings_value"].sort_values("period_end")
        A["yoy"] = A.value_first / A.value_first.shift(4) - 1
        hf.append(A.tail(12)[["period_end", "value_first", "yoy"]].assign(source="ASML quarterly bookings (EUR m)").rename(columns={"period_end": "period", "value_first": "value"}))
    if hf:
        sheet(wb, "High-frequency indicators", pd.concat(hf, ignore_index=True)[["source", "period", "value", "yoy"]],
              widths={"source": 34}, note="Two disclosures that sit outside the XBRL screen. TSMC publishes revenue every month, within ten days of month end - the earliest "
              "hard number in the chain. ASML's bookings were the industry's only true quarterly bookings disclosure; the series ENDS at Q4 2025 because ASML stopped "
              "publishing the figure - its 2026 releases contain no bookings line at all. That is a disclosure change, not missing data.")

    sheet(wb, "Geography", ok[ok.axis == "geography"][COLS], heat=["accel", "yoy"], widths={"series": 30},
          note="Ship-to geography, kept separate because it is the noisiest cut: it moves with where a distributor takes delivery as much as with end demand.")
    sheet(wb, "All series - latest", L.sort_values(["ticker", "axis", "series"])[COLS + ["stale_q", "material"]], widths={"series": 38},
          note="Every series in the universe at its latest reported quarter, including those the guards excluded, with the reason visible in stale_q and material.")

    src = pd.DataFrame([("SEC XBRL (10-Q / 10-K)", "segment, product and geography revenue as first reported; Q4 derived as FY less 9M where a filer tags no separate Q4"),
                        ("SEC companyfacts", "RevenueRemainingPerformanceObligation and contract liabilities; companyfacts carries only undimensioned facts, so a filer that tags RPO solely under the expected-timing axis shows nothing here - a coverage gap, not a zero"),
                        ("ASML 6-K", "reported bookings and backlog, which ASML discloses directly and most US filers do not"),
                        ("Quarter mapping", "period ends snap to the nearest month end before the calendar quarter is taken, so a 52/53-week filer's quarters do not collide"),
                        ("Known gaps", "QCOM stopped tagging RPO after 2022; INTC's RPO is sparse; MU re-disclosed RPO in 2026 after a five-year gap, so it has no year-ago base; MU, ENTG and CBRS redefined segments recently - flagged as short_history"),
                        ("ASML bookings", "discontinued: the Q1 and Q2 2026 releases contain no bookings line, so the series ends at Q4 2025 (EUR 13.2bn, +86% y/y)"),
                        ("Verified", "Micron's $41.5bn quarter and Broadcom's RPO step from $45.0bn to $164.6bn were both checked against the source filings and, for Micron, against an independent data vendor")],
                       columns=["source", "detail"])
    ws = sheet(wb, "Method and sources", src, widths={"source": 26, "detail": 118})
    for c in ws["B"]: c.alignment = WRAP
    wb.save("out/semis_acceleration_screen.xlsx")
    print("wrote out/semis_acceleration_screen.xlsx |", wb.sheetnames)
if __name__ == "__main__": main()
