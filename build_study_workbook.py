"""One workbook for the leading-indicator study: sample, cycle position, return tests, robustness."""
import pandas as pd, numpy as np, os
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
import study_run2 as R

B = Font(bold=True); HD = PatternFill("solid", fgColor="DDE6F0"); WRAP = Alignment(wrap_text=True, vertical="top")

def sheet(wb, name, df, note=None, widths=None, pct=(), num3=()):
    ws = wb.create_sheet(name[:31]); r = 1
    if note:
        ws.cell(1, 1, note).font = Font(italic=True); ws.cell(1, 1).alignment = WRAP
        ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=max(6, len(df.columns)))
        ws.row_dimensions[1].height = 28; r = 4
    for j, c in enumerate(df.columns, 1):
        cl = ws.cell(r, j, str(c)); cl.font = B; cl.fill = HD; cl.alignment = WRAP
    for i, row in enumerate(df.itertuples(index=False), r + 1):
        for j, v in enumerate(row, 1):
            if isinstance(v, (pd.Period,)): v = str(v)
            if isinstance(v, pd.Timestamp): v = v.to_pydatetime()
            c = ws.cell(i, j, None if (isinstance(v, float) and pd.isna(v)) else v)
            nm = str(df.columns[j - 1])
            if isinstance(v, (int, float)) and not pd.isna(v):
                c.number_format = "0.0%" if nm in pct else ("0.000" if nm in num3 else "0.00")
            if isinstance(v, pd.Timestamp) or hasattr(v, "year") and not isinstance(v, (int, float)): c.number_format = "yyyy-mm-dd"
    for j, c in enumerate(df.columns, 1):
        w = max(11, min(34, len(str(c)) + 3))
        ws.column_dimensions[get_column_letter(j)].width = (widths or {}).get(str(c), w)
    ws.freeze_panes = ws.cell(r + 1, 1)
    return ws

def main():
    F = R.panel(); F = F[F.usable].copy()
    wb = Workbook(); wb.remove(wb.active)

    # 1 summary
    cyc = pd.read_pickle("out/study_cycle.pkl")
    lead = cyc[(cyc.segment_leads_q >= 1) & (cyc.peak_rho > 0.45)]
    ic60 = pd.DataFrame([r for s in R.SIG + R.BASE if (r := R.quarterly_ic(F, s, "b60"))])
    best = ic60.reindex(ic60.mean_ic.abs().sort_values(ascending=False).index).iloc[0] if len(ic60) else None
    ic = pd.DataFrame([r for sg in R.SIG + R.BASE for h in ("b60", "b120") if (r := R.quarterly_ic(F, sg, h))])
    sub = pd.read_pickle("out/study_subsample.pkl") if os.path.exists("out/study_subsample.pkl") else pd.DataFrame()
    rows = [("What was tested", "Whether quarterly segment revenue growth, as first reported, leads (a) the semiconductor cycle, (b) the company's own next-quarter revenue, and (c) its stock."),
            ("Universe", f"{F.ticker.nunique()} US semiconductor filers with segment detail in XBRL, {F.release.min().date()} to {F.release.max().date()}"),
            ("Events", f"{len(F)} earnings releases, each one verified to have printed the segment figures it is scored on, so no figure is used before it was public"),
            ("Signal timing", "as first reported; forward returns start at the close one trading day after the release, so the announcement move is excluded from them"),
            ("Benchmark", "equal-weight index of the same names, so the sector's own cycle cannot pass for stock selection"),
            ("Multiple testing", f"55 return tests were run. A 5% threshold after Bonferroni needs |t| > 3.5, which nothing here reaches; the weight below rests on consistency across horizons and halves, not on any single t."),
            ("", ""),
            ("Finding 1", f"Segment growth does carry a real lead over the industry cycle, and the ordering is economically coherent: {len(lead)} segments turn at least a quarter early, led by "
                          f"{lead.iloc[0].ticker} {lead.iloc[0].segment} at {int(lead.iloc[0].segment_leads_q)} quarters (rho {lead.iloc[0].peak_rho:.2f} at that lead vs {lead.iloc[0].rho_at_0:.2f} contemporaneous). Memory and compute turn first; analog, industrial and materials follow by one to two quarters." if len(lead) else ""),
            ("Finding 2", "That lead is about the industry, not about the filer's own next quarter. Segment growth predicts a company's next-quarter revenue strongly, but consolidated growth plus acceleration already capture nearly all of it - adding any segment signal lifts R-squared by at most 0.01."),
            ("Finding 3", "For returns, the segment detail is mostly priced on the print: growth signals correlate with the announcement-day move (t around 2 to 3.5), which is where the information goes."),
            ("Finding 4", "One signal survives past the print: the growth rate of the LARGEST segment. IC 0.13 at 60 days (t 2.9) and 0.13 at 120 days (t 2.6), the same sign in both halves of the sample, and it holds up net of consolidated revenue growth (t 2.0 at 60 days). No other segment signal does."),
            ("Finding 5", "It is fragile. The effect is present when the event is the earnings release and absent when the event is the 10-Q filing 13 days later, so it lives in the first weeks after the print. A quintile book holds 2 to 4 stocks a side and drew down 27% to 34% along the way."),
            ("Honest read", "Segment KPI growth is a good cycle indicator and a poor stock signal. Use it to place a company in the cycle and to read through to its customers and suppliers, not to pick stocks off the print."),
            ("Caveat", "21 names is a small cross-section; quintiles hold 2 to 4 stocks, so these tests would miss a small but real edge. Absence of evidence here is not evidence of absence.")]
    sheet(wb, "Summary", pd.DataFrame(rows, columns=["", "                                                                                          "]),
          widths={"": 26, "                                                                                          ": 120})

    sheet(wb, "Cycle position", cyc, widths={"segment": 34},
          note="One test per segment: its y/y growth against the median y/y of every company in the universe except its own parent, at leads of up to 3 quarters. "
               "segment_leads_q > 0 means the segment turns first. peak_rho is the correlation at that lead; rho_at_0 the contemporaneous one - a real lead beats it.")
    sheet(wb, "Cycle position by company", pd.read_pickle("out/study_leadlag_composite.pkl"),
          note="Same test at company level: peer-group growth vs each company. A positive number at +1/+2 means the peers moved first, so the company is late-cycle.")

    if os.path.exists("out/study_tsmc_lead.pkl"):
        sheet(wb, "TSMC monthly as indicator", pd.read_pickle("out/study_tsmc_lead.pkl"),
              note="TSMC publishes revenue every month, within ten days of month end - the earliest hard number in the chain. Its y/y growth, aggregated to a "
                   "calendar quarter, against each company's own y/y revenue growth. tsmc_leads_q > 0 means TSMC turned first. It is largely coincident with "
                   "its customers rather than ahead of them, and the correlations are modest.")
    fu = pd.read_pickle("out/study_fundamental.pkl")
    sheet(wb, "Predicting own revenue", fu, num3=("rho_next_yoy", "rho_next_accel", "rho_partial"),
          note="Spearman correlation of each signal with the company's NEXT quarter y/y revenue growth. rho_partial strips out this quarter's consolidated "
               "growth from both sides: what is left is what the segment detail adds.")

    for nm, f, note in (("Rank IC - returns", "out/study_ic_rel.pkl",
                         "Mean of the quarterly cross-sectional rank ICs. 'reaction' spans the release day and is the market's own response, not a tradable signal; "
                         "b5 to b120 are benchmark-relative returns measured from one trading day after the release."),
                        ("Quintile spreads", "out/study_spread_rel.pkl",
                         "Top minus bottom quintile, bucketed within each calendar quarter, benchmark-relative, equal weight."),
                        ("IC beyond total growth", "out/study_incremental_rel.pkl",
                         "Each segment signal rank-residualised on the company's consolidated revenue growth within the quarter, then re-tested.")):
        if os.path.exists(f): sheet(wb, nm, pd.read_pickle(f), num3=("mean_ic", "spread"), note=note)

    if os.path.exists("out/study_subsample.pkl"):
        sheet(wb, "Subsample stability", pd.read_pickle("out/study_subsample.pkl"), num3=("ic_2011_2018", "ic_2019_2026"),
              note="The same IC in each half of the sample. A signal that changes sign between halves is a fitted one.")
    if os.path.exists("out/study_samples.pkl"):
        sheet(wb, "Event-date sensitivity", pd.read_pickle("out/study_samples.pkl"), num3=("mean_ic",),
              note="The same ICs on three event dates: the verified release (no look-ahead possible, the primary sample), every release, and the 10-Q "
                   "filing date (conservative but a median 13 days late). The drift shows up on the release date and is gone by the filing date, which "
                   "places it in the first weeks after the print - and marks it as fragile.")
    if os.path.exists("out/study_backtest.pkl"):
        sheet(wb, "Backtest", pd.read_pickle("out/study_backtest.pkl"),
              note="Quarterly rebalanced long top quintile / short bottom quintile, held to the horizon, benchmark-relative. Before costs.")

    keep = ["ticker", "period_end", "release", "entry_date", "n_segments", "total_rev", "largest_seg", "largest_share", "printed",
            "best_seg_yoy", "worst_seg_yoy", "largest_seg_yoy", "wavg_seg_yoy", "seg_yoy_disp", "wavg_seg_accel", "share_segs_accelerating",
            "co_yoy", "co_accel", "reaction", "b5", "b20", "b60", "b120"]
    sheet(wb, "Event panel", F[[c for c in keep if c in F.columns]].sort_values(["ticker", "period_end"]),
          note="Every event in the study: the signals as first reported, and the forward returns they are scored against.")

    src = pd.DataFrame([("SEC EDGAR", "segment and consolidated revenue, as first reported, from 10-Q/10-K XBRL and the 8-K earnings releases"),
                        ("Fiscal.ai", "split-adjusted daily closes for the 22 names; the benchmark is built from these, equal weight"),
                        ("study_signals.py", "signal construction, 2% materiality floor on the year-ago segment base, winsorised at the 1st/99th percentile"),
                        ("study_events.py", "earnings release date per quarter, matched to the quarter by the revenue figure printed in the release"),
                        ("study_printed.py", "check that the release itself printed the segment figures, so nothing is scored before it was public"),
                        ("study_cycle.py / study_leadlag.py", "cycle position, with a circular-shift placebo to size what chance produces"),
                        ("study_run2.py", "rank IC, quintile spreads, incremental tests, subsamples, backtest")],
                       columns=["source", "what it provides"])
    sheet(wb, "Method and sources", src, widths={"source": 30, "what it provides": 100})
    wb.save("out/semis_leading_indicator_study.xlsx")
    print("wrote out/semis_leading_indicator_study.xlsx |", len(wb.sheetnames), "sheets:", wb.sheetnames)
if __name__ == "__main__": main()
