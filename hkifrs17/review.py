"""Excel review round trip with source and check sheets."""

from __future__ import annotations

from io import BytesIO
import math

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .data import COLUMNS, LEGACY_COLUMNS, REVIEW_STATUSES, UNIT_FACTORS, normalize_records, reconciliation_checks
from .checks import ASSESSMENTS, FORMULA_BASES, METHODS, NOTE_SCOPES, PLAN_COLUMNS, RULES, RULE_BY_ID, default_plan, normalize_plan
from .review_flow import per_cell_checks
from .investigation import investigate_check_issues

REVIEW_WORKFLOW_VERSION = 11


AUDIT_STATUS_OPTIONS = (
    "Check source",
    "Audited statement",
    "Comparative in 2025 statement",
    "Unaudited comparative",
)


def _add_status_dropdown(sheet, column: str, options: tuple[str, ...], *, required: bool) -> None:
    letter = get_column_letter(COLUMNS.index(column) + 1)
    validation = DataValidation(
        type="list",
        formula1='"' + ",".join(options) + '"',
        allow_blank=not required,
    )
    validation.showDropDown = False
    validation.showErrorMessage = required
    validation.errorTitle = "Choose a valid status"
    validation.error = f"Select a status from the {column} dropdown."
    sheet.add_data_validation(validation)
    validation.add(f"{letter}2:{letter}1048576")


def _excel_arithmetic(rows: pd.DataFrame, checks: pd.DataFrame,
                      *, include_pending: bool = False) -> pd.DataFrame:
    """Independent Excel arithmetic for complete checks, linked to source cells."""
    indexed = {
        (row["Document ID"], row["Period end"], row["Metric code"]): (position + 2, row)
        for position, (_, row) in enumerate(rows.iterrows())
        if ((row["Review status"] == "Verified"
             or (include_pending and row["Review status"] == "Pending"))
                and row["Value status"] in {"Reported", "Derived from disclosed items"})
    }

    def amount(code: str, source: tuple[int, pd.Series], *, raw: bool) -> str:
        source_row, record = source
        factor = UNIT_FACTORS[str(record["Source unit"])][1]
        original = float(record["Original value"]) * factor
        displayed = float(record["Value (millions)"])
        orientation = -1 if not raw and original != 0 and abs(displayed + original) < 1e-8 else 1
        expression = (f"Records!$J${source_row}*VLOOKUP(Records!$K${source_row},"
                      "'Unit factors'!$A$2:$B$8,2,FALSE)")
        return f"({expression}*{orientation})" if orientation < 0 else f"({expression})"

    output = []
    for position, (_, check) in enumerate(checks.iterrows(), start=2):
        rule = RULE_BY_ID[check["Check ID"]]
        required = [code.strip() for code in str(check["Required inputs"]).split(",") if code.strip()]
        sources = [indexed.get((check["Document ID"], check["Period end"], code)) for code in required]
        record = {"Document ID": check["Document ID"], "Period end": check["Period end"],
                  "Check ID": rule.id, "Total (millions)": None,
                  "Components (millions)": None, "Difference (millions)": None,
                  "Tolerance (millions)": check["Tolerance (millions)"],
                  "Excel result": check["Result"], "Platform snapshot": check["Result"]}
        if check["Result"] in {"Pass", "Difference"} and all(source is not None for source in sources):
            status_test = lambda source_row: (
                f'OR(Records!$R${source_row}="Verified",Records!$R${source_row}="Pending")'
                if include_pending else f'Records!$R${source_row}="Verified"')
            gate = "AND(" + ",".join(
                f'{status_test(source[0])},'
                f'OR(Records!$N${source[0]}="Reported",Records!$N${source[0]}="Derived from disclosed items")'
                for source in sources
            ) + ")"
            if rule.total is None:
                record["Excel result"] = f'=IF({gate},"Pass","Missing inputs")'
            else:
                raw = rule.id in {"INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS"}
                record["Total (millions)"] = "=" + amount(required[0], sources[0], raw=raw)
                parts = []
                for code, source in zip(required[1:], sources[1:]):
                    sign = -1 if (
                        (rule.id == "SERVICE" and code == "INS_EXPENSE" and check["Formula basis"] in
                         {"Subtract positive service expense", "Subtract both positive expenses"})
                        or (rule.id == "SERVICE" and code == "REINS_RESULT" and check["Formula basis"] in
                            {"Subtract positive reinsurance expense", "Subtract both positive expenses"})
                        or (rule.same_scope and check["Formula basis"] == "Reverse note sign for statement comparison")
                    ) else 1
                    parts.append(("-" if sign < 0 else "+") + amount(code, source, raw=raw))
                record["Components (millions)"] = "=" + ("".join(parts).lstrip("+") or "0")
                record["Difference (millions)"] = f"=D{position}-E{position}"
                record["Excel result"] = (
                    f'=IF({gate},IF(ABS(F{position})<=G{position},"Pass","Difference"),"Missing inputs")'
                )
        output.append(record)
    return pd.DataFrame(output)


def review_workbook_bytes(frame: pd.DataFrame, filings: list[dict], plan: pd.DataFrame | None = None,
                          *, automatic: bool = False, include_pending: bool = False) -> bytes:
    rows = normalize_records(frame, filings)
    check_plan = normalize_plan(plan, filings, set(rows["Document ID"]))
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        rows.to_excel(writer, sheet_name="Records", index=False)
        checks = reconciliation_checks(rows, filings, check_plan,
                                       verified_only=not include_pending, automatic=automatic)
        checks.to_excel(writer, sheet_name="Checks", index=False)
        _excel_arithmetic(rows, checks, include_pending=include_pending).to_excel(
            writer, sheet_name="Excel arithmetic", index=False)
        pd.DataFrame([{"Source unit": unit, "Millions factor": factor}
                      for unit, (_, factor) in UNIT_FACTORS.items()]).to_excel(
                          writer, sheet_name="Unit factors", index=False)
        check_plan.to_excel(writer, sheet_name="Check plan", index=False)
        pd.DataFrame([
            {"Check ID": rule.id, "Check": rule.name, "Group": rule.group,
             "Required": rule.mandatory, "Total metric": rule.total or "Coverage only",
             "Component metrics": ", ".join(rule.parts),
             "Same-scope confirmation": rule.same_scope}
            for rule in RULES
        ]).to_excel(writer, sheet_name="Rule catalogue", index=False)
        pd.DataFrame([
            {"Instruction": "Check each original value, source unit, period and PDF page against the filing."},
            {"Instruction": "Pending cells enter Step 3 as candidates when sent directly from Step 2. Publishing promotes only cells that pass every platform check; Excluded rows never enter charts." if include_pending else "Set Review status to Verified only after source review. Excluded rows never enter charts."},
            {"Instruction": "Value (millions), Metric, Section and identity columns are recalculated on import. For percent source units, the numeric value is percentage points rather than millions."},
            {"Instruction": "A 2024 comparative does not automatically mean a separately audited 2024 filing."},
            {"Instruction": "Checks use Pending and Verified numeric candidates. Arithmetic matches do not prove the original year, column, unit or contract population; investigate flagged source cells before publication." if include_pending else "Checks use only Verified reported cells. Differences and partially missing rule inputs require review; optional rules with no mapped cells are shown as Not evaluated." if automatic else "Checks use only Verified reported cells. Differences and mandatory missing inputs block approval. An optional missing note cell requires a confirmed scope, note reference and written reason."},
            {"Instruction": "The Checks tab is a snapshot. Re-import the Step 3 workbook to recalculate automatic checks after editing exceptions." if automatic else "The Checks tab is a snapshot, not live Excel formulas. Re-import the edited workbook to recalculate every rule in Step 2."},
            {"Instruction": "Excel arithmetic recalculates complete checks from Records Original value and Source unit. Missing inputs and exception changes are independently reassessed by the platform on Step 3 upload." if automatic else "Excel arithmetic recalculates complete checks from Records Original value and Source unit; it is an independent arithmetic cross-check. Incomplete checks and changes to Check plan require Step 2 re-import."},
            {"Instruction": "Check plan is optional for exception notes or source sign choices. Not applicable needs a reason; method-split checks also need the original note and physical PDF page. A genuinely undisclosed optional cell needs a reason and note reference." if automatic else "Set each optional Check plan row to Applicable or Not applicable; the latter needs a reason."},
            {"Instruction": "Arithmetic matches must still be interpreted using the correct legal entity, contract population and accounting basis." if automatic else "For applicable note checks, confirm measurement method, note reference and matching scope where relevant."},
            {"Instruction": "For the SERVICE check only, set Formula basis if source expenses are shown as positive amounts."},
            {"Instruction": "A signed net movement must be independently disclosed in the same note and basis; never calculate it from opening and closing."},
        ]).to_excel(writer, sheet_name="Read me", index=False)
        for sheet in writer.book:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            sheet.column_dimensions["A"].width = 27
            sheet.column_dimensions["B"].width = 25
            if sheet.title == "Records":
                sheet.column_dimensions["P"].width = 46
                sheet.column_dimensions["S"].width = 62
                _add_status_dropdown(sheet, "Audit status", AUDIT_STATUS_OPTIONS, required=False)
                _add_status_dropdown(sheet, "Review status", REVIEW_STATUSES, required=True)
            elif sheet.title == "Check plan":
                for column, options in (("D", ASSESSMENTS), ("E", METHODS), ("F", NOTE_SCOPES), ("I", FORMULA_BASES)):
                    validation = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=False)
                    validation.showErrorMessage = True
                    sheet.add_data_validation(validation)
                    validation.add(f"{column}2:{column}1048576")
                sheet.column_dimensions["G"].width = 42
                sheet.column_dimensions["H"].width = 52
                sheet.column_dimensions["I"].width = 42
        writer.book.calculation.fullCalcOnLoad = True
    return output.getvalue()


def source_review_workbook_bytes(frame: pd.DataFrame, filings: list[dict],
                                 table_labels: list[str]) -> bytes:
    """Step 2 workbook: source cells grouped by the confirmed physical table."""
    rows = normalize_records(frame, filings)
    if len(rows) != len(table_labels):
        raise ValueError("Source table labels must match the source rows.")
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        rows.assign(**{"Source table": table_labels}).to_excel(writer, sheet_name="Records", index=False)
        pd.DataFrame([
            {"Instruction": "Review the original PDF page, year, scope, row, column, value, sign and source unit for each cell."},
            {"Instruction": "Edit incorrect values in Records. Leave Review status as Pending; uploading with the review confirmation verifies the included cells."},
            {"Instruction": "Set Review status to Excluded only for a cell that must not enter Step 3. Do not replace blanks or dashes with zero."},
            {"Instruction": "Source table is a review grouping label. The platform recalculates normalised values from Original value and Source unit."},
        ]).to_excel(writer, sheet_name="Read me", index=False)
        sheet = writer.book["Records"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        sheet.column_dimensions["P"].width = 48
        sheet.column_dimensions["S"].width = 56
        sheet.column_dimensions["T"].width = 46
        _add_status_dropdown(sheet, "Audit status", AUDIT_STATUS_OPTIONS, required=False)
        _add_status_dropdown(sheet, "Review status", REVIEW_STATUSES, required=True)
    return output.getvalue()


def step3_workbook_bytes(frame: pd.DataFrame, filings: list[dict],
                         plan: pd.DataFrame,
                         confirmed_pages: tuple[int, ...] = (),
                         source_audit: pd.DataFrame | None = None) -> bytes:
    """Full check workbook with a live formula for every reviewed source cell."""
    rows = normalize_records(frame, filings)
    include_pending = rows["Review status"].eq("Pending").any()
    workbook = load_workbook(BytesIO(review_workbook_bytes(
        rows, filings, plan, automatic=True, include_pending=include_pending)))
    checks = reconciliation_checks(rows, filings, plan,
                                   verified_only=not include_pending, automatic=True)
    cell_results = per_cell_checks(rows, checks, allow_pending=include_pending,
                                   confirmed_pages=set(confirmed_pages) if include_pending else None,
                                   source_audit=source_audit)
    if source_audit is not None:
        audit_rows = source_audit.set_index(["Document ID", "Period end", "Metric code"])
        audit_sheet = workbook.create_sheet("PDF source checks", 2)
        audit_sheet.append(["Document ID", "Period end", "Metric code", "Physical PDF page",
                            "Image result", "Observed value", "Observed unit", "Observed year",
                            "Observed row", "Observed column", "Observed scope", "Scope basis",
                            "Evidence box", "Reason"])
        for _, record in rows.iterrows():
            item = audit_rows.loc[(record["Document ID"], record["Period end"], record["Metric code"])]
            audit_sheet.append([item.get(column, "") for column in (
                "Document ID", "Period end", "Metric code", "PDF page", "Source check",
                "Observed value", "Observed unit", "Observed year", "Observed row",
                "Observed column", "Observed scope", "Scope basis", "Evidence box", "Reason")])
        audit_sheet.freeze_panes = "A2"
        audit_sheet.auto_filter.ref = audit_sheet.dimensions
        audit_sheet.column_dimensions["I"].width = 55
        audit_sheet.column_dimensions["J"].width = 55
        audit_sheet.column_dimensions["N"].width = 75
        manual_sheet = workbook.create_sheet("Manual source review", 3)
        manual_sheet.append(["Document ID", "Period end", "Metric code", "Physical PDF page",
                             "Source label", "Observed value", "Observed unit", "Observed year",
                             "Observed row", "Observed column", "Observed scope", "Reviewer note"])
        for _, record in rows.iterrows():
            manual_sheet.append([record["Document ID"], record["Period end"],
                                 record["Metric code"], int(record["PDF page"]),
                                 record["Source label"], None, None, None, None, None,
                                 None, None])
        manual_sheet.freeze_panes = "A2"
        manual_sheet.auto_filter.ref = manual_sheet.dimensions
        manual_sheet.column_dimensions["E"].width = 70
        manual_sheet.column_dimensions["I"].width = 55
        manual_sheet.column_dimensions["J"].width = 55
        manual_sheet.column_dimensions["L"].width = 60
    check_rows = {(item["Document ID"], item["Period end"], item["Check ID"]): position
                  for position, (_, item) in enumerate(checks.iterrows(), start=2)}
    sheet = workbook.create_sheet("Cell checks", 2)
    sheet.append(["Document ID", "Period end", "Metric code", "Physical PDF page",
                  "Source label", "Unit factor", "Recomputed value", "Stored value",
                  "Excel cell result", "Platform cell result", "Related rules", "Excel linked rules"])
    for position, (_, row) in enumerate(rows.iterrows(), start=2):
        source_value = float(row["Original value"]) * UNIT_FACTORS[str(row["Source unit"])][1]
        orientation = -1 if (source_value != 0 and math.isclose(
            source_value, -float(row["Value (millions)"]), abs_tol=1e-8)) else 1
        scope_gate = "TRUE"
        if row["Metric code"] == "INS_PAA_LIC_CLOSE":
            scope_gate = ("NOT(OR(" + ",".join(
                f'ISNUMBER(SEARCH("{phrase}",Records!P{position}))'
                for phrase in ("not under", "not measured under", "estimates of present value",
                               "estimate of present value", "present value of future cash flows",
                               "risk adjustment")
            ) + "))")
        elif row["Metric code"] == "INS_NONPAA_LIC_CLOSE":
            scope_gate = (f'NOT(AND(ISNUMBER(SEARCH("+",Records!P{position})),'
                          f'OR(ISNUMBER(SEARCH("present value of future cash flows",Records!P{position})),'
                          f'ISNUMBER(SEARCH("risk adjustment",Records!P{position})))))')
        page_gate = ("OR(" + ",".join(f"Records!O{position}={page}" for page in confirmed_pages) + ")"
                     if confirmed_pages else "FALSE")
        status_gate = (f'OR(Records!R{position}="Verified",'
                       f'AND(Records!R{position}="Pending",{page_gate}))'
                       if include_pending else f'Records!R{position}="Verified"')
        audit_gate = (f'OR(Records!R{position}="Pending",Records!Q{position}<>"Check source")'
                      if include_pending else f'Records!Q{position}<>"Check source"')
        image_gate = ("TRUE" if source_audit is None else
                      f'AND(\'PDF source checks\'!E{position}="Match",'
                      f'Records!J{position}=\'PDF source checks\'!F{position},'
                      f'Records!K{position}=\'PDF source checks\'!G{position},'
                      f'LEFT(Records!F{position},4)=\'PDF source checks\'!H{position})')
        related = checks[(checks["Document ID"] == row["Document ID"])
                         & (checks["Period end"] == row["Period end"])]
        related = related[related["Required inputs"].apply(
            lambda value: row["Metric code"] in {part.strip() for part in str(value).split(",")})]
        documented_gap = (related["Result"].eq("Missing inputs")
                          & related["Assessment"].isin(("Applicable", "To assess"))
                          & related["Reason"].fillna("").astype(str).str.strip().ne("")
                          & related["Note reference"].fillna("").astype(str).str.strip().ne("")
                          & related["Detail"].eq("Extract and verify each missing source field.")
                          & ~related["Check ID"].isin(("PRIMARY", "SERVICE", "BALANCE")))
        live_rules = related[~documented_gap]
        rule_terms = []
        for _, check in live_rules.iterrows():
            excel_row = check_rows[(check["Document ID"], check["Period end"], check["Check ID"])]
            result_cell = f"'Excel arithmetic'!H{excel_row}"
            rule_terms.append(f'OR({result_cell}="Pass",{result_cell}="Not applicable",'
                              f'{result_cell}="Not evaluated")')
        rule_formula = (f'=IF(AND({",".join(rule_terms)}),"Pass","Investigate")'
                        if rule_terms else '="Pass"')
        sheet.append([
            f"=Records!A{position}", f"=Records!F{position}", f"=Records!G{position}",
            f"=Records!O{position}", f"=Records!P{position}",
            f"=IFERROR(VLOOKUP(Records!K{position},'Unit factors'!$A$2:$B$8,2,FALSE),NA())",
            f"=Records!J{position}*F{position}*{orientation}",
            f"=Records!M{position}",
            f'=IFERROR(IF(AND({status_gate},Records!O{position}>0,{scope_gate},'
            f'LEN(TRIM(Records!P{position}))>0,LEN(TRIM(Records!Q{position}))>0,'
            f'{audit_gate},{image_gate},'
            f'ABS(G{position}-H{position})<=0.000001,L{position}="Pass"),'
            f'"Pass","Investigate"),"Investigate")',
            cell_results.iloc[position - 2]["Cell result"],
            ", ".join(related["Check ID"]),
            rule_formula,
        ])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.column_dimensions["E"].width = 60
    sheet.column_dimensions["K"].width = 42
    sheet.column_dimensions["L"].width = 24
    investigation = investigate_check_issues(rows, checks, set(confirmed_pages))
    leads_sheet = workbook.create_sheet("Investigation", 3)
    leads_sheet.append(list(investigation.columns))
    for values in investigation.itertuples(index=False, name=None):
        leads_sheet.append([None if pd.isna(value) else value for value in values])
    leads_sheet.freeze_panes = "A2"
    leads_sheet.auto_filter.ref = leads_sheet.dimensions
    leads_sheet.column_dimensions["G"].width = 70
    leads_sheet.column_dimensions["H"].width = 100
    leads_sheet.column_dimensions["I"].width = 80
    instructions = workbook["Read me"]
    instructions.append(["Step 3: Cell checks has live source, unit and linked-rule formulas for every source cell. Excel arithmetic has formulas for complete reconciliation rules. Investigation lists source-based leads only; verify them against the original PDF."])
    instructions.append(["Upload the checked workbook in Step 3. The platform recalculates all rules and source-cell checks from Records and Check plan; formula caches are never trusted."])
    if source_audit is not None:
        instructions.append(["Manual source review is parallel to the platform image check. For a cell you reviewed on its original physical PDF page, transcribe the observed value, unit, table year, row, numeric column and Company/Consolidated scope, then write a reviewer note. Leave other rows blank. The platform compares these entries to Records on upload; changing Records still requires Step 2."])
    workbook.calculation.fullCalcOnLoad = True
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def validate_step3_check_workbook(payload: bytes, expected_rows: int) -> None:
    """Reject a source-only workbook or deleted Excel check formulas."""
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=False)
    needed = {"Records", "Cell checks", "Excel arithmetic", "Check plan"}
    if not needed.issubset(workbook.sheetnames):
        raise ValueError("Upload the Step 3 check workbook with its Cell checks, Excel arithmetic and Check plan sheets.")
    sheet = workbook["Cell checks"]
    if sheet.max_row != expected_rows + 1 or sheet["I1"].value != "Excel cell result":
        raise ValueError("The Cell checks sheet does not match the approved source cells.")
    if sheet["L1"].value != "Excel linked rules" or any(
        row[0].data_type != "f" or row[3].data_type != "f"
        for row in sheet.iter_rows(min_row=2, max_row=expected_rows + 1,
                                   min_col=9, max_col=12)
    ):
        raise ValueError("A Cell checks Excel formula was removed. Download a fresh Step 3 workbook.")


def read_review_workbook(payload: bytes, filings: list[dict]) -> pd.DataFrame:
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=False)
    if "Records" not in workbook:
        raise ValueError("The Records sheet is missing.")
    sheet = workbook["Records"]
    records = list(sheet.values)
    if not records or (list(records[0])[:len(COLUMNS)] != COLUMNS
                       and list(records[0])[:len(LEGACY_COLUMNS)] != LEGACY_COLUMNS):
        raise ValueError("Records headers have changed.")
    if any(cell.data_type == "f" for row in sheet.iter_rows(min_row=2) for cell in row):
        raise ValueError("Replace formulas in Records with reviewed values before upload.")
    columns = (COLUMNS if list(records[0])[:len(COLUMNS)] == COLUMNS else LEGACY_COLUMNS)
    return normalize_records(pd.DataFrame([list(row)[:len(columns)] for row in records[1:]],
                                          columns=columns), filings)


def read_manual_source_reviews(payload: bytes, rows: pd.DataFrame, pdf_path) -> list[dict]:
    """Accept explicit, independently transcribed Excel source checks for unchanged cells."""
    from .source_audit import _check_observation, _fingerprint, pdf_stamp
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=False)
    if "Manual source review" not in workbook:
        return []
    source = workbook["Manual source review"]
    headers = [cell.value for cell in next(source.iter_rows(min_row=1, max_row=1))]
    expected = ["Document ID", "Period end", "Metric code", "Physical PDF page",
                "Source label", "Observed value", "Observed unit", "Observed year",
                "Observed row", "Observed column", "Observed scope", "Reviewer note"]
    if headers[:len(expected)] != expected:
        raise ValueError("Manual source review headers have changed.")
    indexed = {(item["Document ID"], item["Period end"], item["Metric code"]): item
               for _, item in rows.iterrows()}
    stamp = pdf_stamp(pdf_path)
    output = []
    seen = set()
    for excel_row in source.iter_rows(min_row=2):
        values = [cell.value for cell in excel_row[:len(expected)]]
        key = tuple(values[:3])
        if key in seen or key not in indexed:
            raise ValueError("Manual source review contains a duplicate or unknown source cell.")
        seen.add(key)
        if not any(value is not None and str(value).strip() for value in values[5:]):
            continue
        if any(cell.data_type == "f" for cell in excel_row[5:len(expected)]):
            raise ValueError("Manual source review needs typed source observations, not formulas.")
        if any(value is None or not str(value).strip() for value in values[5:len(expected)]):
            raise ValueError(f"Complete every observed field and reviewer note for {key[1]} {key[2]}.")
        row = indexed[key]
        if int(values[3]) != int(row["PDF page"]) or str(values[4]) != str(row["Source label"]):
            raise ValueError("Manual source review page or label differs from the approved source cell.")
        observed = {"observed_value": values[5], "observed_unit": values[6],
                    "observed_year": values[7], "observed_row": values[8],
                    "observed_column": values[9], "observed_scope": values[10],
                    "confidence": "High"}
        result = _check_observation(row, observed, require_evidence_box=False)
        if result["Source check"] != "Match":
            raise ValueError(f"Manual source review conflicts with {key[1]} {key[2]}: {result['Reason']}")
        result["Reason"] = "Manual Excel source review: " + str(values[11]).strip()
        result["Scope basis"] = "Manual review of original PDF"
        result["Fingerprint"] = _fingerprint(row, stamp)
        output.append(result)
    return output


def read_check_plan_workbook(payload: bytes, filings: list[dict], document_id: str) -> pd.DataFrame:
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=False)
    if "Check plan" not in workbook:
        return default_plan(filings, {document_id})
    sheet = workbook["Check plan"]
    records = list(sheet.values)
    if not records or list(records[0])[:len(PLAN_COLUMNS)] != PLAN_COLUMNS:
        raise ValueError("Check plan headers have changed.")
    if any(cell.data_type == "f" for row in sheet.iter_rows(min_row=2) for cell in row):
        raise ValueError("Replace formulas in Check plan with reviewed values before upload.")
    return normalize_plan(pd.DataFrame(records[1:], columns=PLAN_COLUMNS), filings, {document_id})
