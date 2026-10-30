"""Filing-specific review plan and explicit four-state reconciliation results.

All movements are independently transcribed, signed amounts from the same
disclosed note. We never infer a missing movement from opening and closing.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd

from .data import UNIT_FACTORS, normalize_records


RESULTS = ("Pass", "Difference", "Missing inputs", "Not applicable", "Not evaluated")
ASSESSMENTS = ("To assess", "Applicable", "Not applicable")
METHODS = ("Not confirmed", "GMM", "VFA", "PAA", "Mixed", "Other disclosed basis")
NOTE_SCOPES = ("Not confirmed", "Same entity and balance basis", "Different or net scope")
FORMULA_BASES = ("Signed source amounts", "Subtract positive service expense",
                 "Subtract positive reinsurance expense", "Subtract both positive expenses",
                 "Reverse note sign for statement comparison")
CHECKS_WORKFLOW_VERSION = 2
PLAN_COLUMNS = ["Document ID", "Period end", "Check ID", "Assessment", "Measurement method",
                "Note scope", "Note reference", "Reason", "Formula basis"]


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    group: str
    total: str | None
    parts: tuple[str, ...]
    mandatory: bool = False
    same_scope: bool = False


RULES = (
    Rule("PRIMARY", "Primary statement inputs", "Coverage", None,
         ("INS_REVENUE", "INS_EXPENSE", "REINS_RESULT", "INS_SERVICE_RESULT",
          "TOTAL_ASSETS", "TOTAL_LIABS", "EQUITY", "OPERATING_CF"), True),
    Rule("SERVICE", "Insurance service result bridge", "Primary statements", "INS_SERVICE_RESULT",
         ("INS_REVENUE", "INS_EXPENSE", "REINS_RESULT"), True),
    Rule("BALANCE", "Assets = liabilities + equity", "Primary statements", "TOTAL_ASSETS",
         ("TOTAL_LIABS", "EQUITY"), True),
    Rule("REVENUE_NOTE", "Insurance revenue: statement vs note", "Cross-table", "INS_REVENUE",
         ("INS_REVENUE_NOTE_TOTAL",), same_scope=True),
    Rule("LIABILITY_NOTE", "Insurance liabilities: statement vs note", "Cross-table", "INS_LIABS",
         ("INS_LIABS_NOTE_CLOSE",), same_scope=True),
    Rule("REINSURANCE_NOTE", "Reinsurance assets: statement vs note", "Cross-table", "REINS_ASSETS",
         ("REINS_ASSETS_NOTE_CLOSE",), same_scope=True),
    Rule("CSM_ROLL", "CSM opening + signed movements = closing", "Rollforward", "CSM_CLOSE",
         ("CSM_OPEN", "CSM_NET_MOVEMENT")),
    Rule("LIABILITY_ROLL", "Insurance liabilities opening + signed movements = closing",
         "Rollforward", "INS_LIABS_NOTE_CLOSE",
         ("INS_LIABS_NOTE_OPEN", "INS_LIABS_NOTE_MOVEMENT")),
    Rule("REINSURANCE_ROLL", "Reinsurance assets opening + signed movements = closing",
         "Rollforward", "REINS_ASSETS_NOTE_CLOSE",
         ("REINS_ASSETS_NOTE_OPEN", "REINS_ASSETS_NOTE_MOVEMENT")),
    Rule("REV_NONPAA_COMP", "Non-PAA revenue: disclosed components = note subtotal",
         "Note composition", "REV_NONPAA_TOTAL",
         ("REV_CSM_SERVICE", "REV_RA_RELEASE", "REV_EXPECTED_CLAIMS", "REV_ACQ_RECOVERY")),
    Rule("REV_TOTAL_SPLIT", "Insurance revenue: non-PAA + PAA = note total",
         "Note composition", "INS_REVENUE_NOTE_TOTAL", ("REV_NONPAA_TOTAL", "REV_PAA_TOTAL")),
    Rule("INS_LIABS_METHOD", "Insurance liabilities: non-PAA + PAA = note closing total",
         "Note composition", "INS_LIABS_NOTE_CLOSE", ("INS_LIABS_NONPAA_CLOSE", "INS_LIABS_PAA_CLOSE")),
    Rule("REINS_ASSETS_METHOD", "Reinsurance assets: non-PAA + PAA = note closing total",
         "Note composition", "REINS_ASSETS_NOTE_CLOSE", ("REINS_ASSETS_NONPAA_CLOSE", "REINS_ASSETS_PAA_CLOSE")),
    Rule("INS_NET_ROLL", "Insurance note cohort: opening + P&L/OCI + cash = closing",
         "Rollforward", "INS_NOTE_NET_CLOSE", ("INS_NOTE_NET_OPEN", "INS_NOTE_PL_OCI", "INS_NOTE_CASHFLOWS")),
    Rule("REINS_NET_ROLL", "Reinsurance note cohort: opening + P&L/OCI + cash = closing",
         "Rollforward", "REINS_NOTE_NET_CLOSE", ("REINS_NOTE_NET_OPEN", "REINS_NOTE_PL_OCI", "REINS_NOTE_CASHFLOWS")),
    Rule("INS_MEAS_COMPONENTS", "Insurance same-cohort: PVFCF + RA + CSM = net closing",
         "Note composition", "INS_NOTE_NET_CLOSE",
         ("INS_NOTE_PVFCF_CLOSE", "INS_NOTE_RA_CLOSE", "INS_NOTE_CSM_CLOSE")),
    Rule("REINS_MEAS_COMPONENTS", "Reinsurance same-cohort: PVFCF + RA + CSM = net closing",
         "Note composition", "REINS_NOTE_NET_CLOSE",
         ("REINS_NOTE_PVFCF_CLOSE", "REINS_NOTE_RA_CLOSE", "REINS_NOTE_CSM_CLOSE")),
)
# This bridge is emitted only for filings with disclosed gross insurance balances.
# It is not a standing check-plan row, but Excel formulas need its rule definition.
CONDITIONAL_RULES = (
    Rule("INS_GROSS_NET_BRIDGE",
         "Insurance net closing = gross closing + signed acquisition asset",
         "Cross-table", "INS_LIABS_NOTE_CLOSE",
         ("INS_GROSS_CLOSE", "INS_ACQ_ASSET_CLOSE")),
)
RULE_BY_ID = {rule.id: rule for rule in (*RULES, *CONDITIONAL_RULES)}
CHECK_COLUMNS = ["Document ID", "Period end", "Check ID", "Group", "Check", "Result",
                 "Missing inputs", "Difference (millions)", "Tolerance (millions)", "Detail",
                 "Company", "Legal entity", "Scope", "Currency", "Assessment", "Reason", "Measurement method",
                 "Note scope", "Note reference", "Formula basis", "Required inputs"]


def default_plan(filings: list[dict], document_ids: set[str] | None = None) -> pd.DataFrame:
    rows = []
    for filing in filings:
        if document_ids is not None and filing["document_id"] not in document_ids:
            continue
        year = int(filing["period_end"][:4])
        for period in (filing["period_end"], f"{year - 1}{filing['period_end'][4:]}"):
            for rule in RULES:
                rows.append({"Document ID": filing["document_id"], "Period end": period,
                             "Check ID": rule.id, "Assessment": "Applicable" if rule.mandatory else "To assess",
                             "Measurement method": "Not confirmed", "Note scope": "Not confirmed",
                             "Note reference": "", "Reason": "", "Formula basis": "Signed source amounts"})
    return pd.DataFrame(rows, columns=PLAN_COLUMNS)


def normalize_plan(frame: pd.DataFrame, filings: list[dict], document_ids: set[str] | None = None) -> pd.DataFrame:
    expected = default_plan(filings, document_ids)
    if frame is None or frame.empty:
        return expected
    if not set(PLAN_COLUMNS).issubset(frame.columns):
        raise ValueError("The check plan is missing required columns.")
    actual = frame[PLAN_COLUMNS].fillna("").copy()
    keys = ["Document ID", "Period end", "Check ID"]
    if actual.duplicated(keys).any():
        raise ValueError("The check plan has duplicate filing, period and check rows.")
    valid = set(map(tuple, expected[keys].itertuples(index=False, name=None)))
    if any(key not in valid for key in actual[keys].itertuples(index=False, name=None)):
        raise ValueError("The check plan contains an unknown filing, period or check.")
    result = expected.set_index(keys)
    supplied = actual.set_index(keys)
    result.update(supplied)
    result = result.reset_index()[PLAN_COLUMNS]
    for index, row in result.iterrows():
        rule = RULE_BY_ID[row["Check ID"]]
        if row["Assessment"] not in ASSESSMENTS or row["Measurement method"] not in METHODS or row["Note scope"] not in NOTE_SCOPES:
            raise ValueError(f"Check plan row {index + 2} has an invalid selection.")
        if row["Formula basis"] not in FORMULA_BASES:
            raise ValueError(f"Check plan row {index + 2} has an invalid formula basis.")
        if row["Formula basis"] in FORMULA_BASES[1:4] and rule.id != "SERVICE":
            raise ValueError(f"{rule.name}: service expense sign options apply only to SERVICE.")
        if row["Formula basis"] == FORMULA_BASES[4] and not rule.same_scope:
            raise ValueError(f"{rule.name}: reverse note sign applies only to cross-table checks.")
        if rule.mandatory and row["Assessment"] != "Applicable":
            raise ValueError(f"{rule.name} is a required primary statement check.")
        if row["Assessment"] == "Not applicable" and not str(row["Reason"]).strip():
            raise ValueError(f"{rule.name}: explain why the check does not apply.")
    return result


def evaluate_checks(frame: pd.DataFrame, filings: list[dict], plan: pd.DataFrame | None = None,
                    *, verified_only: bool = False, automatic: bool = False) -> pd.DataFrame:
    rows = normalize_records(frame, filings)
    if rows.empty:
        return pd.DataFrame(columns=CHECK_COLUMNS)
    documents = {filing["document_id"]: filing for filing in filings}
    ids = set(rows["Document ID"])
    settings = normalize_plan(plan, filings, ids).set_index(["Document ID", "Period end", "Check ID"])
    output = []
    for (document_id, period), group in rows.groupby(["Document ID", "Period end"]):
        filing = documents[document_id]
        reported = group[group["Value status"].isin(("Reported", "Derived from disclosed items"))]
        if verified_only:
            reported = reported[reported["Review status"].eq("Verified")]
        values = dict(zip(reported["Metric code"], reported["Value (millions)"]))
        source_labels = dict(zip(reported["Metric code"], reported["Source label"].fillna("")))
        source_pages = dict(zip(reported["Metric code"], reported["PDF page"]))
        source_values = {
            str(row["Metric code"]): float(row["Original value"]) * UNIT_FACTORS[str(row["Source unit"])][1]
            for _, row in reported.iterrows()
        }
        source_steps = [UNIT_FACTORS[unit][1] for unit in reported["Source unit"]]
        tolerance = max(0.002, 2 * max(source_steps, default=0.001))
        for rule in RULES:
            setting = settings.loc[(document_id, period, rule.id)]
            # Some insurers disclose policyholder taxes as a distinct revenue
            # component. Include it only for the filing where it is reported.
            total_code = rule.total
            parts = rule.parts
            if rule.id == "CSM_ROLL" and any(code in values for code in
                    ("INS_CSM_FV_PL_OCI", "INS_CSM_OTHER_PL_OCI")):
                parts = ("CSM_OPEN", "INS_CSM_FV_PL_OCI", "INS_CSM_OTHER_PL_OCI")
            if rule.id == "LIABILITY_ROLL" and any(code in values for code in
                    ("INS_GROSS_OPEN", "INS_GROSS_PL_OCI", "INS_GROSS_CASH",
                     "INS_GROSS_CLOSE", "INS_ACQ_ASSET_CLOSE")):
                total_code = "INS_GROSS_CLOSE"
                parts = ("INS_GROSS_OPEN", "INS_GROSS_PL_OCI", "INS_GROSS_CASH")
            # Some filings' INS_NOTE_NET_CLOSE includes both PAA and non-PAA.
            # When the explicit non-PAA cohort is available, match its three
            # measurement components to that same cohort instead.
            if rule.id == "INS_MEAS_COMPONENTS" and "INS_NONPAA_NET_CLOSE" in values:
                total_code = "INS_NONPAA_NET_CLOSE"
                split = {"INS_CSM_FV_CLOSE", "INS_CSM_OTHER_CLOSE"} <= values.keys()
                subtotal_page = source_pages.get("INS_NONPAA_CSM_CLOSE")
                component_page = source_pages.get("INS_CSM_FV_CLOSE")
                use_split = split and ("INS_NONPAA_CSM_CLOSE" not in values
                                       or subtotal_page != component_page)
                parts = (("INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE",
                          "INS_CSM_FV_CLOSE", "INS_CSM_OTHER_CLOSE") if use_split else
                         ("INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE",
                          "INS_NONPAA_CSM_CLOSE"))
            elif rule.id == "REINS_MEAS_COMPONENTS" and "REINS_NONPAA_NET_CLOSE" in values:
                total_code = "REINS_NONPAA_NET_CLOSE"
                split = {"REINS_CSM_FV_CLOSE", "REINS_CSM_OTHER_CLOSE"} <= values.keys()
                subtotal_page = source_pages.get("REINS_NONPAA_CSM_CLOSE")
                component_page = source_pages.get("REINS_CSM_FV_CLOSE")
                use_split = split and ("REINS_NONPAA_CSM_CLOSE" not in values
                                       or subtotal_page != component_page)
                parts = (("REINS_NONPAA_PVFCF_CLOSE", "REINS_NONPAA_RA_CLOSE",
                          "REINS_CSM_FV_CLOSE", "REINS_CSM_OTHER_CLOSE") if use_split else
                         ("REINS_NONPAA_PVFCF_CLOSE", "REINS_NONPAA_RA_CLOSE",
                          "REINS_NONPAA_CSM_CLOSE"))
            if rule.id in {"INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS"}:
                # Prefer a visibly labelled non-PAA Total from the same table
                # as the components. A similarly named movement-table column
                # can represent only remaining coverage or include PAA.
                note_code = ("INS_NOTE_NET_CLOSE" if rule.id == "INS_MEAS_COMPONENTS"
                             else "REINS_NOTE_NET_CLOSE")
                note_label = str(source_labels.get(note_code, ""))
                component_pages = {source_pages.get(code) for code in parts if code in values}
                if (note_code in values and len(component_pages) == 1
                        and source_pages.get(note_code) in component_pages
                        and re.search(r"non.PAA|not (?:measured )?under (?:the )?PAA", note_label, re.I)
                        and re.search(r"(?:net )?closing balance|closing assets|closing liabilities", note_label, re.I)
                        and re.search(r"\bTotal\b", note_label, re.I)):
                    total_code = note_code
            parts = parts + (("REV_POLICYHOLDER_TAX",) if rule.id == "REV_NONPAA_COMP"
                                  and "REV_POLICYHOLDER_TAX" in values else ())
            required = ((total_code,) if total_code else ()) + parts
            missing = [code for code in required if code not in values]
            invalid_reason = ""
            if rule.id in {"REVENUE_NOTE", "LIABILITY_NOTE", "REINSURANCE_NOTE"}:
                audited_start = filing.get("page_profit")
                note_page = source_pages.get(parts[0])
                if (isinstance(audited_start, int) and note_page is not None
                        and pd.notna(note_page) and 0 < float(note_page) < audited_start):
                    invalid_reason = ("The mapped note cell precedes the audited financial statements; "
                                      "verify the original PDF and re-extract the audited note cell in Step 2.")
            if rule.id == "CSM_ROLL" and "CSM_NET_MOVEMENT" in required:
                if re.search(r"reinsurance", str(source_labels.get("CSM_NET_MOVEMENT", "")), re.I):
                    invalid_reason = "Insurance CSM movement was mapped from a reinsurance table; correct it in Step 2."
            elif rule.id == "LIABILITY_ROLL" and "INS_LIABS_NOTE_MOVEMENT" in required:
                if re.search(r"profit or loss and OCI", str(source_labels.get("INS_LIABS_NOTE_MOVEMENT", "")), re.I):
                    invalid_reason = ("The supplied movement contains profit or loss and OCI only; "
                                      "extract gross opening, profit or loss/OCI, cash flows and "
                                      "the signed acquisition asset separately.")
            elif rule.id in {"INS_LIABS_METHOD", "REINS_ASSETS_METHOD"}:
                nonpaa_code, paa_code = (("INS_LIABS_NONPAA_CLOSE", "INS_LIABS_PAA_CLOSE")
                                         if rule.id == "INS_LIABS_METHOD" else
                                         ("REINS_ASSETS_NONPAA_CLOSE", "REINS_ASSETS_PAA_CLOSE"))
                nonpaa_label = str(source_labels.get(nonpaa_code, ""))
                paa_label = str(source_labels.get(paa_code, ""))
                if (any(re.search(r"present value|excluding loss", label, re.I)
                        for label in (nonpaa_label, paa_label))
                        or re.search(r"not (?:measured )?under (?:the )?PAA|non.PAA", paa_label, re.I)):
                    invalid_reason = ("A method-level closing balance points to a component or the opposite "
                                      "method. Correct the cells in Step 2; if full method totals are absent, "
                                      "document the original note and mark this rule Not applicable.")
            elif rule.id in {"INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS"}:
                label = str(source_labels.get(total_code, ""))
                if re.search(r"excluding loss|loss.recovery component", label, re.I):
                    invalid_reason = "The mapped net closing balance is one component, not the same-cohort Total."
                elif total_code.endswith("NONPAA_NET_CLOSE") and not re.search(
                        r"non.PAA|not (?:measured )?under (?:the )?PAA", label, re.I):
                    invalid_reason = "The mapped Total does not identify the non-PAA measurement cohort."
                # A source table may continue on the next physical PDF page.
                # Page mismatch alone is not evidence of a different cohort.
            if rule.id == "INS_NET_ROLL" and not invalid_reason:
                if any(re.search(r"\b20\d{2}\b", str(source_labels.get(code, "")))
                       and period[:4] not in re.findall(r"\b20\d{2}\b", str(source_labels.get(code, "")))
                       for code in required if code in values and not code.endswith("_OPEN")):
                    invalid_reason = "A movement or closing source label names another table year; correct it in Step 2."
            if rule.id == "REINS_NET_ROLL" and not invalid_reason:
                close_label = str(source_labels.get("REINS_NOTE_NET_CLOSE", ""))
                other_labels = " ".join(str(source_labels.get(code, "")) for code in parts)
                if (re.search(r"non.PAA|not (?:measured )?under (?:the )?PAA", close_label, re.I)
                        and not re.search(r"non.PAA|not (?:measured )?under (?:the )?PAA", other_labels, re.I)):
                    invalid_reason = ("The closing cell is a non-PAA subtotal while opening, P&L/OCI "
                                      "and cash flows use the all-method Total; correct the source mapping in Step 2.")
            assessment = setting["Assessment"]
            detail = ""
            difference = None
            if assessment == "Not applicable":
                result = "Not applicable"
                detail = str(setting["Reason"])
                missing = []
            elif automatic and not rule.mandatory and not any(code in values for code in required):
                result = "Not evaluated"
                detail = "No verified source cells are mapped to this optional rule; no arithmetic was performed."
            elif not automatic and assessment == "To assess":
                result = "Missing inputs"
                detail = "Confirm whether this disclosure and check apply to this filing and period."
            elif not automatic and rule.group != "Primary statements" and not rule.mandatory and setting["Measurement method"] == "Not confirmed":
                result = "Missing inputs"
                detail = "Confirm the note's measurement method (GMM, VFA, PAA or mixed)."
            elif not automatic and rule.group != "Primary statements" and not rule.mandatory and not str(setting["Note reference"]).strip():
                result = "Missing inputs"
                detail = "Enter the source note and page reference."
            elif not automatic and rule.group in {"Rollforward", "Note composition"} and setting["Note scope"] == "Not confirmed":
                result = "Missing inputs"
                detail = "Confirm all components use one disclosed contract population and sign presentation."
            elif rule.id in {"CSM_ROLL", "INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS"} and setting["Measurement method"] == "PAA":
                result = "Missing inputs"
                detail = "A PAA-only cohort does not support this CSM composition check. Document Not applicable or identify the GMM/VFA cohort."
            elif rule.same_scope and (setting["Note scope"] == "Different or net scope"
                                      or (not automatic and setting["Note scope"] != "Same entity and balance basis")):
                result = "Missing inputs"
                detail = "Confirm matching company/group scope, gross or net basis, and sign presentation."
            elif invalid_reason:
                result = "Missing inputs"
                detail = invalid_reason
            elif missing:
                result = "Missing inputs"
                detail = "Extract and verify each missing source field."
            elif rule.total is None:
                result = "Pass"
                detail = "Required primary statement cells are present and verified." if verified_only else "Required primary statement cells are present."
            else:
                # Measurement note components must retain their signed source
                # basis. The CSM display balance may have been reoriented to
                # positive, while PVFCF, RA and the net balance have not.
                calculation_values = (source_values if rule.id in {
                    "INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS"
                } else values)
                contributions = {code: float(calculation_values[code]) for code in parts}
                if rule.id == "SERVICE":
                    basis = setting["Formula basis"]
                    if basis in ("Subtract positive service expense", "Subtract both positive expenses"):
                        contributions["INS_EXPENSE"] *= -1
                    if basis in ("Subtract positive reinsurance expense", "Subtract both positive expenses"):
                        contributions["REINS_RESULT"] *= -1
                if rule.same_scope and setting["Formula basis"] == "Reverse note sign for statement comparison":
                    contributions = {code: -amount for code, amount in contributions.items()}
                difference = float(calculation_values[total_code]) - sum(contributions.values())
                result = "Pass" if abs(difference) <= tolerance else "Difference"
                detail = "Within source-unit tolerance." if result == "Pass" else "Compare the source page, signs and disclosed scope."
            output.append({"Document ID": document_id, "Company": filing["company"],
                           "Legal entity": filing["legal_entity"], "Scope": filing["scope"],
                           "Currency": filing["currency"], "Period end": period,
                           "Check ID": rule.id, "Group": rule.group, "Check": rule.name,
                           "Assessment": assessment, "Reason": setting["Reason"],
                           "Measurement method": setting["Measurement method"],
                           "Note scope": setting["Note scope"], "Note reference": setting["Note reference"],
                           "Formula basis": setting["Formula basis"],
                           "Required inputs": ", ".join(required), "Missing inputs": ", ".join(missing),
                           "Difference (millions)": round(difference, 6) if difference is not None else None,
                           "Tolerance (millions)": tolerance, "Result": result, "Detail": detail})
            if rule.id == "LIABILITY_ROLL" and any(code in values for code in
                    ("INS_GROSS_OPEN", "INS_GROSS_PL_OCI", "INS_GROSS_CASH",
                     "INS_GROSS_CLOSE", "INS_ACQ_ASSET_CLOSE")):
                bridge_codes = ("INS_LIABS_NOTE_CLOSE", "INS_GROSS_CLOSE", "INS_ACQ_ASSET_CLOSE")
                bridge_missing = [code for code in bridge_codes if code not in values]
                bridge_difference = None
                if assessment == "Not applicable":
                    bridge_result, bridge_detail = "Not applicable", str(setting["Reason"])
                elif not automatic and (assessment == "To assess" or
                        setting["Measurement method"] == "Not confirmed" or
                        not str(setting["Note reference"]).strip() or
                        setting["Note scope"] != "Same entity and balance basis"):
                    bridge_result, bridge_detail = "Missing inputs", "Confirm the same note, entity and balance basis."
                elif bridge_missing:
                    bridge_result, bridge_detail = "Missing inputs", "Extract and verify each missing source field."
                else:
                    bridge_difference = float(values[bridge_codes[0]]) - sum(
                        float(values[code]) for code in bridge_codes[1:])
                    bridge_result = "Pass" if abs(bridge_difference) <= tolerance else "Difference"
                    bridge_detail = ("Within source-unit tolerance." if bridge_result == "Pass"
                                     else "Compare the gross closing amount and signed acquisition asset to the net note balance.")
                output.append({**output[-1], "Check ID": "INS_GROSS_NET_BRIDGE",
                               "Group": "Cross-table",
                               "Check": "Insurance net closing = gross closing + signed acquisition asset",
                               "Required inputs": ", ".join(bridge_codes),
                               "Missing inputs": ", ".join(bridge_missing),
                               "Difference (millions)": (round(bridge_difference, 6)
                                                         if bridge_difference is not None else None),
                               "Result": bridge_result, "Detail": bridge_detail})
    return pd.DataFrame(output, columns=CHECK_COLUMNS)


def automatic_arithmetic_checks(frame: pd.DataFrame, filings: list[dict],
                                plan: pd.DataFrame | None = None,
                                *, verified_only: bool = True) -> pd.DataFrame:
    """Screen every identity from verified cells, independent of manual applicability.

    The temporary plan only bypasses applicability and scope gates so arithmetic
    can run. A numerical match does not establish that note populations match.
    """
    rows = normalize_records(frame, filings)
    if rows.empty:
        return pd.DataFrame(columns=["Document ID", "Period end", "Check ID", "Check",
                                     "Arithmetic result", "Missing inputs", "Difference (millions)",
                                     "Tolerance (millions)", "Required inputs", "Detail"])
    screening_plan = normalize_plan(plan, filings, set(rows["Document ID"])).copy()
    screening_plan["Assessment"] = "Applicable"
    screening_plan["Measurement method"] = "Mixed"
    screening_plan["Note scope"] = "Same entity and balance basis"
    screening_plan["Note reference"] = "Automatic arithmetic screen only"
    screened = evaluate_checks(rows, filings, screening_plan, verified_only=verified_only)
    output = screened[["Document ID", "Period end", "Check ID", "Check", "Result",
                       "Missing inputs", "Difference (millions)", "Tolerance (millions)",
                       "Required inputs", "Detail"]].copy()
    output = output.rename(columns={"Result": "Arithmetic result"})
    output["Arithmetic result"] = output["Arithmetic result"].replace({
        "Pass": "Match", "Missing inputs": "Missing source cells",
    })
    return output


def require_resolved_checks(checks: pd.DataFrame, *, automatic: bool = False) -> None:
    note_reference = checks["Note reference"].fillna("").astype(str)
    has_pdf_page = note_reference.str.contains(
        r"\b(?:p\.?|pp\.?|page(?:s)?|PDF\s*p\.?|PDF\s*pp\.?)\s*\d+|第\s*\d+\s*页",
        case=False, regex=True)
    unsupported_method = checks[
        checks["Check ID"].isin(("INS_LIABS_METHOD", "REINS_ASSETS_METHOD"))
        & checks["Result"].eq("Not applicable")
        & (~has_pdf_page | checks["Reason"].fillna("").astype(str).str.strip().eq(""))
    ]
    if not unsupported_method.empty:
        raise ValueError("A method-split rule marked Not applicable needs both a reason "
                         "and the original note with its physical PDF page reference.")
    # A reviewer may document a genuinely undisclosed optional note component.
    # The rule still runs and the gap stays visible; mandatory and mismatched
    # identities always block approval.
    documented_gap = (
        checks["Result"].eq("Missing inputs")
        & ~checks["Check ID"].isin({rule.id for rule in RULES if rule.mandatory})
        & (checks["Assessment"].isin(("Applicable", "To assess")) if automatic else checks["Assessment"].eq("Applicable"))
        & checks["Reason"].fillna("").astype(str).str.strip().ne("")
        & checks["Note reference"].fillna("").astype(str).str.strip().ne("")
        & checks["Detail"].eq("Extract and verify each missing source field.")
    )
    allowed = ("Pass", "Not applicable", "Not evaluated") if automatic else ("Pass", "Not applicable")
    unresolved = checks[~checks["Result"].isin(allowed) & ~documented_gap]
    if not unresolved.empty:
        counts = unresolved["Result"].value_counts().to_dict()
        raise ValueError(f"Resolve all checks before approval or publication: {counts}.")
