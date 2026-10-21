"""Confirm every FWD reported figure occurs on its cited physical PDF page."""

from pathlib import Path

import fitz
import pandas as pd


root = Path(__file__).resolve().parents[1]
records = pd.read_excel(root / "outputs" / "HK_IFRS17_FWD_YF_SunLife_2025_verified.xlsx", sheet_name="Records")
records = records[records["Document ID"].eq("FWD_2025")]
document = fitz.open(root / "disclosures" / "pilot" / "FWD_Bermuda_Audited_Financial_Statement_2025.pdf")
missing = []
for _, row in records.iterrows():
    value = float(row["Original value"])
    token = f"{abs(value):,.0f}" if row["Source unit"] != "percent" else f"{value:.2f}"
    page_text = document[int(row["PDF page"]) - 1].get_text()
    if token not in page_text and not (row["Metric code"] == "RA_CONFIDENCE_PCT" and "75th percentile" in page_text):
        missing.append((row["Metric code"], row["PDF page"], token))
print(f"FWD source-page numeric matches: {len(records) - len(missing)}/{len(records)}")
print("Missing tokens:", missing)
