"""Correct one YF 2024 OCI source cell in saved Step 5/6 workbooks.

Physical page 25 of disclosures/uploads/YF Life_FS_2024.pdf prints
HKD 180,381,305 for the 2024 consolidated reinsurance finance OCI row.
"""

from __future__ import annotations

from pathlib import Path
import os
import tempfile

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = 180_381_305
MILLIONS = 180.381305
OLD_ORIGINAL = 60_381_305


def repair(path: Path) -> bool:
    workbook = load_workbook(path)
    if "Records" not in workbook:
        return False
    sheet = workbook["Records"]
    columns = {str(cell.value): cell.column for cell in sheet[1] if cell.value}
    required = {"Document ID", "Metric code", "Original value", "Value (millions)"}
    if not required.issubset(columns):
        return False
    changed = False
    for row in range(2, sheet.max_row + 1):
        if (sheet.cell(row, columns["Document ID"]).value != "YF_2024"
                or sheet.cell(row, columns["Metric code"]).value != "OCI_REINS_FINANCE"):
            continue
        stored = sheet.cell(row, columns["Original value"])
        if stored.value == ORIGINAL:
            continue
        if stored.value != OLD_ORIGINAL:
            raise ValueError(f"Unexpected YF 2024 OCI value in {path}: {stored.value!r}")
        stored.value = ORIGINAL
        sheet.cell(row, columns["Value (millions)"]).value = MILLIONS
        if "HKD value (millions)" in columns:
            sheet.cell(row, columns["HKD value (millions)"]).value = MILLIONS
        if "Source label" in columns:
            sheet.cell(row, columns["Source label"]).value = (
                "Net finance income from reinsurance contracts; 2024 column")
        if "Reviewer note" in columns:
            sheet.cell(row, columns["Reviewer note"]).value = (
                "Corrected against physical PDF page 25, consolidated statement of profit or loss "
                "and other comprehensive income, 2024 column: HKD 180,381,305.")
        changed = True
    if changed:
        handle, temporary = tempfile.mkstemp(prefix=".yf_oci_", suffix=".xlsx", dir=path.parent)
        os.close(handle)
        try:
            workbook.save(temporary)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return changed


if __name__ == "__main__":
    repaired = [path.name for path in sorted((ROOT / "outputs").glob("*.xlsx")) if repair(path)]
    fixture = ROOT / "tests" / "fixtures" / "chart_reference_2024_2025.xlsx"
    if repair(fixture):
        repaired.append(str(fixture.relative_to(ROOT)))
    print("Corrected:", ", ".join(repaired) if repaired else "already current")
