"""Index stand-ins for the 1990-2007 core + hedge test: Nasdaq-100 (^NDX), PHLX Semiconductor (^SOX), S&P 500 (^GSPC)
and the 13-week T-bill yield (^IRX), daily from 1985, from Yahoo. Writes results/history/indexes.csv.gz."""
import os
import pandas as pd, yfinance as yf
d = yf.download(["^NDX", "^SOX", "^GSPC", "^IRX"], start="1985-01-01", auto_adjust=False, progress=False, group_by="column")["Close"]
os.makedirs("results/history", exist_ok=True)
d.to_csv("results/history/indexes.csv.gz", float_format="%.6g", index_label="date")
print({c: str(d[c].first_valid_index().date()) for c in d.columns}, flush=True)
