"""Read-only leads for investigating Step 3 reconciliation exceptions."""

from __future__ import annotations

import re
from collections import Counter

import pandas as pd


INVESTIGATION_COLUMNS = [
    "Period end", "Check ID", "Check", "Result", "Difference (millions)",
    "Missing metric codes", "Source cells and physical pages", "Automatic leads",
    "Review action",
]


def investigate_check_issues(rows: pd.DataFrame, checks: pd.DataFrame,
                             confirmed_pages: set[int] | None = None) -> pd.DataFrame:
    """Identify source, year, population and unit clues without changing cells.

    A lead is an instruction to inspect the original page, never permission to
    replace a reported value or to infer an undisclosed movement.
    """
    output = []
    page_year_evidence: dict[int, Counter[str]] = {}
    for _, source in rows.iterrows():
        if pd.isna(source["PDF page"]):
            continue
        page_year_evidence.setdefault(int(source["PDF page"]), Counter()).update(
            re.findall(r"(?<!\d)20\d{2}(?!\d)", str(source["Source label"]))
        )
    candidates = checks[checks["Result"].isin(("Difference", "Missing inputs"))]
    for _, check in candidates.iterrows():
        period = str(check["Period end"])
        year = period[:4]
        codes = [code.strip() for code in str(check["Required inputs"]).split(",") if code.strip()]
        present = rows[(rows["Document ID"] == check["Document ID"])
                       & (rows["Period end"] == check["Period end"])
                       & rows["Metric code"].isin(codes)]
        missing = [code.strip() for code in str(check["Missing inputs"]).split(",") if code.strip()]
        leads = []
        source_cells = []
        for _, row in present.iterrows():
            code = str(row["Metric code"])
            label = str(row["Source label"])
            lower = label.lower()
            page = int(row["PDF page"])
            source_cells.append(f"{code}: {float(row['Value (millions)']):,.6f}m (PDF p.{page})")
            label_years = set(re.findall(r"(?<!\d)20\d{2}(?!\d)", label))
            if label_years and year not in label_years and not code.endswith("_OPEN"):
                leads.append(f"{code} p.{page}: source label says {', '.join(sorted(label_years))}, record is {year}")
            page_years = page_year_evidence.get(page, Counter())
            if (sum(page_years.values()) >= 2 and len(page_years) == 1
                    and year not in page_years and not code.endswith("_OPEN")):
                leads.append(f"{code} p.{page}: other source labels on this page indicate {next(iter(page_years))}; verify the table-column year")
            if (code.startswith("INS_") or code.startswith("CSM_")) and re.search(r"\breinsurance\b", lower):
                leads.append(f"{code} p.{page}: insurance metric points to a reinsurance source")
            if code.startswith("REINS_") and re.search(r"\binsurance contracts\b", lower) and not re.search(r"\breinsurance\b", lower):
                leads.append(f"{code} p.{page}: reinsurance metric points to an insurance source")
            if confirmed_pages and page not in confirmed_pages:
                leads.append(f"{code} p.{page}: source page is outside the confirmed table pages")
            if (code.endswith("_NET_CLOSE") or code.endswith("_PAA_CLOSE")
                    or code.endswith("_NONPAA_CLOSE")) and re.search(
                        r"present value|risk adjustment|excluding loss|loss.recovery component", lower
                    ) and not re.search(r"\btotal\b|\bsum\b|\+", lower):
                leads.append(f"{code} p.{page}: source label names a component; verify the required total and cohort")
            if code.endswith("_MOVEMENT") and "profit or loss" in lower and "cash" not in lower:
                leads.append(f"{code} p.{page}: source label covers profit or loss/OCI only; check whether the rule also requires cash movements")
            if ("NONPAA" in code and re.search(r"\bunder (the )?paa\b", lower)
                    and not re.search(r"\bnot (measured )?under (the )?paa\b", lower)):
                leads.append(f"{code} p.{page}: non-PAA metric points to a PAA column")
        if len(present) == 2:
            values = [abs(float(value)) for value in present["Value (millions)"] if float(value) != 0]
            if len(values) == 2 and max(values) / min(values) >= 1000:
                leads.append("Amounts differ by at least 1,000 times; verify printed unit and stored source unit")
        for code in missing:
            other_year = rows[(rows["Document ID"] == check["Document ID"])
                              & (rows["Metric code"] == code)
                              & (rows["Period end"] != check["Period end"])]
            if not other_year.empty:
                references = ", ".join(
                    f"{item['Period end']} PDF p.{int(item['PDF page'])}"
                    for _, item in other_year.iterrows()
                )
                leads.append(f"{code}: mapped in another year ({references}); inspect the target-year continuation page")
            else:
                leads.append(f"{code}: no verified cell for {year}; inspect the original note before declaring a gap")
        if check["Result"] == "Difference":
            action = ("Inspect the listed original PDF cells, year, scope, total/subtotal, sign and unit. "
                      "Correct confirmed transcription or mapping in Step 2, then rerun Step 3.")
        elif not missing:
            action = ("Verify the flagged source page against the audited PDF table. "
                      "Correct or exclude the mapped cell in Step 2, then rerun Step 3.")
        else:
            action = ("Search the confirmed note pages for each missing code and extract it through Step 2 if disclosed. "
                      "If genuinely absent, document the note and reason; do not back-calculate it.")
        output.append({
            "Period end": period, "Check ID": check["Check ID"], "Check": check["Check"],
            "Result": check["Result"], "Difference (millions)": check["Difference (millions)"],
            "Missing metric codes": ", ".join(missing),
            "Source cells and physical pages": "; ".join(source_cells),
            "Automatic leads": "; ".join(dict.fromkeys(leads)) or
            "No metadata conflict found; inspect row, column and contract population in the original PDF",
            "Review action": action,
        })
    return pd.DataFrame(output, columns=INVESTIGATION_COLUMNS)
