"""Show how primary statement totals compare with the corresponding note totals."""

from __future__ import annotations

import pandas as pd


PAIR_CODES = {
    "REVENUE_NOTE": ("INS_REVENUE", "INS_REVENUE_NOTE_TOTAL"),
    "LIABILITY_NOTE": ("INS_LIABS", "INS_LIABS_NOTE_CLOSE"),
    "REINSURANCE_NOTE": ("REINS_ASSETS", "REINS_ASSETS_NOTE_CLOSE"),
}


def statement_note_corroboration(rows: pd.DataFrame, arithmetic: pd.DataFrame,
                                 source_checks: pd.DataFrame) -> pd.DataFrame:
    """A numeric match supports common scope only after both source cells match the PDF."""
    columns = ["Period end", "Check", "Statement page", "Note page",
               "Statement value (millions)", "Note value (millions)",
               "Arithmetic result", "Difference (millions)",
               "Statement image", "Note image", "Note scope basis", "Conclusion"]
    if rows.empty or arithmetic.empty:
        return pd.DataFrame(columns=columns)
    records = {(str(row["Period end"]), str(row["Metric code"])): row
               for _, row in rows.iterrows()}
    images = {(str(row["Period end"]), str(row["Metric code"])): row
              for _, row in source_checks.iterrows()}
    output = []
    for _, check in arithmetic[arithmetic["Check ID"].isin(PAIR_CODES)].iterrows():
        period = str(check["Period end"])
        main_code, note_code = PAIR_CODES[str(check["Check ID"])]
        main, note = records.get((period, main_code)), records.get((period, note_code))
        main_image = images.get((period, main_code))
        note_image = images.get((period, note_code))
        main_status = "Not checked" if main_image is None else str(main_image["Source check"])
        note_status = "Not checked" if note_image is None else str(note_image["Source check"])
        result = str(check["Arithmetic result"])
        scope_basis = "" if note_image is None else str(note_image.get("Scope basis", ""))
        if result == "Match" and main_status == note_status == "Match" and scope_basis:
            conclusion = "Corroborated: amounts and both PDF cells agree; review scope basis"
        elif result == "Match":
            conclusion = "Amounts agree; PDF scope/source evidence still needs review"
        elif result == "Difference":
            conclusion = "Investigate year, unit, gross/net basis and source columns"
        else:
            conclusion = "Cannot compare until both disclosed source cells are available"
        output.append({
            "Period end": period, "Check": str(check["Check"]),
            "Statement page": None if main is None else int(main["PDF page"]),
            "Note page": None if note is None else int(note["PDF page"]),
            "Statement value (millions)": None if main is None else float(main["Value (millions)"]),
            "Note value (millions)": None if note is None else float(note["Value (millions)"]),
            "Arithmetic result": result,
            "Difference (millions)": check["Difference (millions)"],
            "Statement image": main_status, "Note image": note_status,
            "Note scope basis": scope_basis, "Conclusion": conclusion,
        })
    return pd.DataFrame(output, columns=columns)
