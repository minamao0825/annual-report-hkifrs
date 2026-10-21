"""Simple standalone HTML summary for reviewed data."""

from __future__ import annotations

from html import escape

import pandas as pd


def html_report(frame: pd.DataFrame, *, company: str, period_end: str) -> bytes:
    rows = frame[frame["Company"].eq(company)].sort_values(["Section", "Metric", "Period end"])
    if rows.empty:
        raise ValueError("No published values for this company.")
    cells = []
    for _, row in rows.iterrows():
        cells.append("<tr>" + "".join(
            f"<td>{escape(str(value))}</td>" for value in (
                row["Section"], row["Metric"], row["Period end"],
                f"{float(row['Value (millions)']):,.2f}", row["Currency"] + " millions",
                f"PDF p.{int(row['PDF page'])}", row["Audit status"],
            )
        ) + "</tr>")
    title = escape(company)
    output = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title} | HK IFRS 17</title>
<style>body{{font-family:Arial,sans-serif;color:#16243a;margin:0}}header{{background:#00338d;color:white;padding:48px 7%}}
main{{padding:32px 7%}}h1{{font-size:36px;margin:0 0 8px}}p{{line-height:1.5}}table{{border-collapse:collapse;width:100%;font-size:12px}}
th,td{{border-bottom:1px solid #dce4ef;padding:9px;text-align:left}}th{{background:#eaf2ff;color:#00338d}}
footer{{margin-top:28px;color:#65738a;font-size:12px}}@media print{{header{{padding:28px}}main{{padding:20px}}}}</style></head>
<body><header><h1>{title}</h1><p>HK IFRS 17 financial statements explorer · Reviewed data report</p></header>
<main><h2>Financial statement values</h2><p>Filing period: {escape(period_end)}. Values are shown in each filing's original currency, normalised to millions. This report contains verified published cells only.</p>
<table><thead><tr><th>Section</th><th>Metric</th><th>Period end</th><th>Amount</th><th>Unit</th><th>Source</th><th>Audit status</th></tr></thead>
<tbody>{''.join(cells)}</tbody></table><footer>Check the source PDF and review workbook for original values, units and notes.</footer></main></body></html>"""
    return output.encode("utf-8")
