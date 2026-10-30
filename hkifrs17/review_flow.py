"""Step 2 source review and Step 3 cell-level validation helpers."""

from __future__ import annotations

import math
import re

import pandas as pd

from .data import NUMERIC_VALUE_STATUSES, UNIT_FACTORS, normalize_records
from .extraction_plan import TABLE_METRICS

SOURCE_REVIEW_VERSION = 4


def source_scope_issue(metric_code: str, source_label: str,
                       column_heading: str = "") -> str:
    """Flag disclosed component or method contradictions that arithmetic cannot catch."""
    evidence = " ".join((source_label, column_heading))
    if metric_code == "REINS_NOTE_NET_CLOSE" and re.search(
            r"non.PAA|not (?:measured )?under (?:the )?PAA", evidence, re.I):
        return "all-method reinsurance closing metric points to a non-PAA subtotal"
    if metric_code == "INS_NONPAA_LIC_CLOSE" and "+" in source_label and re.search(
            r"present value of future cash flows|risk adjustment", source_label, re.I):
        return "non-PAA incurred-claims metric combines multiple printed columns"
    if metric_code != "INS_PAA_LIC_CLOSE":
        return ""
    if re.search(r"\bnot\s+(?:measured\s+)?under\s+(?:the\s+)?PAA\b", evidence, re.I):
        return "PAA incurred-claims metric points to a non-PAA column"
    if re.search(r"estimates? of present value|present value of future cash flows|risk adjustment", evidence, re.I):
        return "PAA incurred-claims metric points to a measurement component, not its total"
    return ""


def source_table_labels(rows: pd.DataFrame, tasks: list[tuple[int, str]]) -> list[str]:
    """Use confirmed physical pages, never guessed note headings, to group cells."""
    labels = []
    for _, row in rows.iterrows():
        physical_page = int(row["PDF page"]) if pd.notna(row["PDF page"]) else 0
        matching = [table for page, table in tasks
                    if physical_page == page and row["Metric code"] in TABLE_METRICS[table]]
        labels.append(matching[0] if matching else "Other / manually entered")
    return labels


def confirm_source_rows(rows: pd.DataFrame, positions: list[int], filing: dict,
                        filings: list[dict]) -> pd.DataFrame:
    """One explicit review action verifies a table without status-cell editing."""
    result = rows.copy().reset_index(drop=True)
    current_year = str(filing["period_end"])[:4]
    for position in positions:
        row = result.loc[position]
        if row["Review status"] == "Excluded":
            continue
        if row["Value status"] not in NUMERIC_VALUE_STATUSES:
            result.at[position, "Review status"] = "Excluded"
            continue
        if not str(row["Source label"]).strip() or pd.isna(row["PDF page"]):
            raise ValueError(f"Row {position + 2}: check the source label and physical PDF page first.")
        scope_issue = source_scope_issue(str(row["Metric code"]), str(row["Source label"]))
        if scope_issue:
            raise ValueError(f"Row {position + 2}: {scope_issue}; correct or exclude this cell.")
        if str(row["Audit status"]).strip() in {"", "Check source", "nan"}:
            result.at[position, "Audit status"] = (
                "Audited statement" if str(row["Period end"])[:4] == current_year
                else f"Comparative in {current_year} statement"
            )
        result.at[position, "Review status"] = "Verified"
    return normalize_records(result, filings)


def per_cell_checks(rows: pd.DataFrame, checks: pd.DataFrame,
                    arithmetic: pd.DataFrame | None = None, *,
                    allow_pending: bool = False,
                    confirmed_pages: set[int] | None = None,
                    source_audit: pd.DataFrame | None = None) -> pd.DataFrame:
    """Trace every source cell and show both arithmetic and review-plan results."""
    output = []
    audit_index = ({} if source_audit is None else
                   {(item["Document ID"], item["Period end"], item["Metric code"]): item
                    for _, item in source_audit.iterrows()})
    for _, row in rows.iterrows():
        original = float(row["Original value"])
        calculated = original * UNIT_FACTORS[str(row["Source unit"])][1]
        stored = float(row["Value (millions)"])
        # CSM display orientation is explicitly handled by normalize_records.
        value_ok = math.isclose(abs(calculated), abs(stored), abs_tol=1e-6)
        linked = checks[(checks["Document ID"] == row["Document ID"])
                        & (checks["Period end"] == row["Period end"])]
        linked = linked[linked["Required inputs"].apply(
            lambda value: row["Metric code"] in {part.strip() for part in str(value).split(",")})]
        documented_gap = (linked["Result"].eq("Missing inputs")
                          & linked["Assessment"].isin(("Applicable", "To assess"))
                          & linked["Reason"].fillna("").astype(str).str.strip().ne("")
                          & linked["Note reference"].fillna("").astype(str).str.strip().ne("")
                          & linked["Detail"].eq("Extract and verify each missing source field.")
                          & ~linked["Check ID"].isin(("PRIMARY", "SERVICE", "BALANCE")))
        problems = linked[linked["Result"].isin(("Difference", "Missing inputs")) & ~documented_gap]
        arithmetic_linked = arithmetic
        if arithmetic_linked is not None:
            arithmetic_linked = arithmetic_linked[
                (arithmetic_linked["Document ID"] == row["Document ID"])
                & (arithmetic_linked["Period end"] == row["Period end"])
            ]
            arithmetic_linked = arithmetic_linked[arithmetic_linked["Required inputs"].apply(
                lambda value: row["Metric code"] in {part.strip() for part in str(value).split(",")})]
        arithmetic_result = (
            "Not screened" if arithmetic_linked is None else
            "No linked rule" if arithmetic_linked.empty else
            "Investigate" if arithmetic_linked["Arithmetic result"].isin(
                ("Difference", "Missing source cells")).any() else "Match"
        )
        candidate = allow_pending and row["Review status"] == "Pending"
        page_ok = (pd.notna(row["PDF page"])
                   and (not candidate or confirmed_pages is None
                        or int(row["PDF page"]) in confirmed_pages))
        audit_ok = candidate or str(row["Audit status"]).strip() not in {"", "Check source"}
        source_ok = (row["Review status"] == "Verified" or candidate) and bool(
            str(row["Source label"]).strip()) and page_ok and audit_ok
        scope_issue = source_scope_issue(str(row["Metric code"]), str(row["Source label"]))
        source_ok = source_ok and not scope_issue
        audit = audit_index.get((row["Document ID"], row["Period end"], row["Metric code"]))
        image_result = "Not required" if source_audit is None else (
            str(audit["Source check"]) if audit is not None else "Not checked")
        image_ok = source_audit is None or image_result == "Match"
        output.append({
            "Document ID": row["Document ID"], "Period end": row["Period end"],
            "Metric code": row["Metric code"], "Metric": row["Metric"],
            "Physical PDF page": row["PDF page"], "Original value": original,
            "Source unit": row["Source unit"], "Value (millions)": stored,
            "Source trace": ("Candidate: check PDF source" if source_ok and candidate else
                             "Pass" if source_ok else
                             f"Investigate: {scope_issue}" if scope_issue else "Investigate"),
            "PDF image check": image_result,
            "PDF image finding": "" if audit is None else str(audit["Reason"]),
            "Unit and value": "Pass" if value_ok else "Investigate",
            "Related rules": ", ".join(linked["Check ID"]),
            "Automatic arithmetic": arithmetic_result,
            "Automatic rule results": "" if arithmetic_linked is None else ", ".join(
                f"{r['Check ID']}: {r['Arithmetic result']}" for _, r in arithmetic_linked.iterrows()),
            "Rule results": ", ".join(f"{r['Check ID']}: {r['Result']}" for _, r in linked.iterrows()),
            "Cell result": "Pass" if source_ok and image_ok and value_ok and problems.empty else "Investigate",
        })
    return pd.DataFrame(output)
