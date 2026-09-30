"""Merge the beat-and-raise flag into the market bookings screen and write the workbook."""
import pandas as pd, numpy as np, os
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule
import tier1_screen as TS

B = Font(bold=True); HD = PatternFill("solid", fgColor="DDE6F0"); WRAP = Alignment(wrap_text=True, vertical="top")
PCTC = {"rpo_yoy", "rpo_yoy_accel", "rev_yoy", "last_beat_pct", "beat_pct", "guided_yoy", "reported_yoy"}
MONEY = {"rev", "rpo", "d_rpo", "reported_rev", "guide_mid"}

def sheet(wb, name, df, note=None, widths=None, heat=None, freeze=3):
    ws = wb.create_sheet(name[:31]); r = 1
    if note:
        c = ws.cell(1, 1, note); c.font = Font(italic=True); c.alignment = WRAP
        ws.merge_cells(start_row=1, start_column=1, end_row=3, end_column=max(8, len(df.columns))); r = 5
    for j, col in enumerate(df.columns, 1):
        c = ws.cell(r, j, str(col)); c.font = B; c.fill = HD; c.alignment = WRAP
    for i, row in enumerate(df.itertuples(index=False), r + 1):
        for j, v in enumerate(row, 1):
            nm = str(df.columns[j - 1])
            if isinstance(v, pd.Period): v = str(v)
            if isinstance(v, (np.bool_, bool)): v = bool(v)
            c = ws.cell(i, j, None if (isinstance(v, float) and pd.isna(v)) else v)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and not pd.isna(v):
                c.number_format = "0.0%" if nm in PCTC else ("#,##0" if nm in MONEY else "0.00")
    for j, col in enumerate(df.columns, 1):
        ws.column_dimensions[get_column_letter(j)].width = (widths or {}).get(str(col), max(10, min(42, len(str(col)) + 3)))
    for col in (heat or []):
        if col not in df.columns or not len(df): continue
        L = get_column_letter(list(df.columns).index(col) + 1)
        ws.conditional_formatting.add(f"{L}{r+1}:{L}{r+len(df)}", ColorScaleRule(
            start_type="percentile", start_value=5, start_color="F8B3AE", mid_type="num", mid_value=0,
            mid_color="FFFFFF", end_type="percentile", end_value=95, end_color="A8D5A2"))
    ws.freeze_panes = ws.cell(r + 1, freeze)
    return ws

def main():
    F = pd.read_pickle("out/br_flag.pkl"); A = pd.read_pickle("out/br_quarters.pkl")
    T = pd.read_pickle("out/cik_tickers.pkl")[["cik", "ticker"]]
    P, L = TS.latest()
    A = A.merge(T, on="cik", how="left")
    F = F.merge(T, on="cik", how="left").merge(
        L[["cik", "name", "industry", "b2b", "b2b_trend", "rpo_yoy", "rev_yoy", "rpo_cover_q", "gated"]], on="cik", how="left")

    # strength of the flag: a raised full-year guide is a genuine raise; the fallback is only
    # "guiding to acceleration", which a shrinking company can satisfy while still shrinking.
    F["raise_strength"] = np.where(F.last_raise_basis.str.startswith("full-year"), "strong (full-year guide raised)",
                                   "weak (guides acceleration, not a raised guide)")
    F["growing"] = F.rev_yoy > 0
    F["flag"] = F.two_consecutive | (F.br_streak >= 2)
    hits = F[F.flag].sort_values(["br_streak", "last_beat_pct"], ascending=False)

    wb = Workbook(); wb.remove(wb.active)
    rows = [("What the flag means", "Two consecutive quarters in which the company beat its OWN prior revenue guidance and raised the forward guide. No connected source carries sell-side consensus or its revision history, so both legs are measured against management's own guidance rather than the street."),
            ("beat(Q)", "actual revenue for Q, from the tier-1 XBRL panel, above the midpoint of the guide given FOR Q in the release one quarter earlier. Growth-rate guides are converted to dollars against the year-ago quarter first."),
            ("raise(R)", "full-year guide above the previous release's full-year guide, compared only within the same fiscal year. Where a filer gives no full-year guide, the fallback is that the next-quarter guide implies y/y growth above the y/y just reported."),
            ("READ THIS BEFORE USING IT", "Every name that currently clears the flag does so on the WEAK fallback basis - none had two comparable full-year guides. The fallback says 'guiding to acceleration', not 'raised the guide', and a shrinking company can satisfy it while still shrinking: TREX is flagged with revenue down 44% y/y, UPLD with revenue down 8%. Use the raise_strength and growing columns; do not read the flag alone as 'improving fundamentals'."),
            ("", ""),
            ("Coverage, and why it is what it is", "7,054 earnings releases were fetched for the 1,696 RPO filers. Deterministic patterns read a revenue guide in 2,062 of them (29%). 3,205 releases contain no forward revenue guidance at all - many companies guide only on the call. A further 454 filers of the 1,696 file no earnings 8-K with item 2.02, so there is nothing to read."),
            ("The model pass was built and rejected", "A Haiku pass over the 1,796 unreadable releases was built, run, and thrown away. Two agents on the SAME slice with the same prompt returned 6% and 54% guidance rates. Spot-checking the 54% showed EPS guidance ('GAAP EPS guidance to $4.83 to $4.93'), EBITDA guidance and reported actuals all captured as revenue guidance; the 6% agent rejected textbook revenue guidance quoted verbatim in its own prompt. Neither error direction is acceptable in a flag meant to drive decisions, so guidance here is deterministic-only and coverage is lower as a result."),
            ("Plausibility guard", "A next-quarter revenue guide sits close to the quarter reported: measured here the actual/guide ratio is 1.007 at the 25th percentile and 1.049 at the 75th, 85% inside +/-15%. Guides outside 0.77x-1.25x are misparses and are dropped - 492 of them, including full-year guides misread as quarterly (LHX, MU) and IBM's '$1 billion of cost savings' read as a revenue guide, which had scored as a 1,616% beat."),
            ("Result after the guard", "beat% across all scored quarters: 5th percentile -3.3%, median +2.5%, 95th +11.4% - the shape you expect when companies set and then clear their own bar."),
            ("Scored", "5,786 release-quarters across 1,092 filers. 488 quarters have both a beat and a raise test; 172 filers have at least one fully scored quarter; 8 clear the two-consecutive flag.")]
    sheet(wb, "How to read this", pd.DataFrame(rows, columns=["", " "]), widths={"": 30, " ": 132}, freeze=1)

    COLS = ["ticker", "name", "industry", "latest_scored_q", "br_streak", "two_consecutive", "raise_strength",
            "growing", "last_beat_pct", "last_raise_basis", "last_guide_kind", "scored_quarters",
            "b2b", "b2b_trend", "rpo_yoy", "rev_yoy", "rpo_cover_q", "gated"]
    sheet(wb, "FLAGGED", hits[COLS], heat=["last_beat_pct", "rev_yoy", "b2b"], widths={"name": 32, "industry": 34, "last_raise_basis": 46},
          note="Filers with two or more consecutive beat-and-raise quarters. Sort by raise_strength and growing before acting: the flag alone does not mean improving fundamentals.")
    sheet(wb, "All scored filers", F.sort_values(["br_streak", "last_beat_pct"], ascending=False)[COLS],
          heat=["last_beat_pct", "rev_yoy"], widths={"name": 32, "industry": 34, "last_raise_basis": 46},
          note="Every filer with at least one fully scored quarter, flagged or not - so a name's absence from the flag list is visible as 'tested and failed' rather than 'not tested'.")
    QC = ["ticker", "reported_q", "reported_rev", "guide_mid", "guide_kind", "beat_pct", "beat",
          "reported_yoy", "guided_yoy", "raise", "beat_and_raise", "raise_basis", "guide_accn"]
    sheet(wb, "Quarter detail", A.dropna(subset=["beat_and_raise"]).sort_values(["ticker", "reported_q"])[QC],
          widths={"raise_basis": 46, "guide_accn": 22}, heat=["beat_pct"],
          note="Every scored quarter, with the guide it was scored against and the accession that guide came from, so any row can be traced back to a filing.")

    M = L.merge(F[["cik", "br_streak", "two_consecutive", "raise_strength", "growing", "last_beat_pct"]], on="cik", how="left")
    M["br_streak"] = M.br_streak.fillna(0)
    sheet(wb, "Bookings screen + flag", M[M.gated][TS.COLS + ["br_streak", "two_consecutive", "raise_strength", "last_beat_pct"]].sort_values(
              ["two_consecutive", "b2b"], ascending=False), heat=["b2b", "rpo_yoy", "last_beat_pct"],
          widths={"name": 32, "industry": 34}, note="The gated bookings universe with the beat-and-raise flag joined on. Blank streak means the filer could not be scored, not that it failed.")

    cov = pd.DataFrame([("RPO filers in the universe", 1696), ("of which file an earnings 8-K/6-K", 1242),
                        ("earnings releases fetched", 7054), ("releases with a guide read deterministically", 2062),
                        ("releases stating no forward revenue guidance", 3205),
                        ("releases with guidance no pattern could read", 1796),
                        ("release-quarters scored", 5786), ("quarters with both a beat and a raise test", 488),
                        ("filers with at least one fully scored quarter", 172),
                        ("filers clearing the two-consecutive flag", int(F.flag.sum()))],
                      columns=["stage", "count"])
    sheet(wb, "Coverage", cov, widths={"stage": 52}, freeze=1,
          note="Where the 1,696 filers go. The drop from 7,054 releases to 2,062 readable guides is the binding constraint on this flag.")
    wb.save("out/beat_and_raise_screen.xlsx")
    print("wrote out/beat_and_raise_screen.xlsx |", wb.sheetnames)
    print("flagged:", int(F.flag.sum()), "| strong basis:", int((hits.raise_strength.str.startswith("strong")).sum()), "| growing:", int(hits.growing.fillna(False).sum()))
if __name__ == "__main__": main()
