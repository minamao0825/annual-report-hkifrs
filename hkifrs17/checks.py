"""Filing-specific review plan and explicit four-state reconciliation results.

All movements are independently transcribed, signed amounts from the same
disclosed note. We never infer a missing movement from opening and closing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .data import UNIT_FACTORS, normalize_records


RESULTS = ("Pass", "Difference", "Missing inputs", "Not applicable")
ASSESSMENTS = ("To assess", "Applicable", "Not applicable")
METHODS = ("Not confirmed", "GMM", "VFA", "PAA", "Mixed", "Other disclosed basis")
NOTE_SCOPES = ("Not confirmed", "Same entity and balance basis", "Different or net scope")
FORMULA_BASES = ("Signed source amounts", "Subtract positive service expense",
                 "Subtract positive reinsurance expense", "Subtract both positive expenses",
                 "Reverse note sign for statement comparison")
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
RULE_BY_ID = {rule.id: rule for rule in RULES}
CHECK_COLUMNS = ["Document ID", "Period end", "Check ID", "Group", "Check", "Result",
                 "Missing inputs", "Difference (millions)", "Tolerance (millions)", "Detail",
                 "Company", "Legal entity", "Scope", "Currency", "Assessment", "Measurement method",
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
                    *, verified_only: bool = False) -> pd.DataFrame:
    rows = normalize_records(frame, filings)
    if rows.empty:
        return pd.DataFrame(columns=CHECK_COLUMNS)
    documents = {filing["document_id"]: filing for filing in filings}
    ids = set(rows["Document ID"])
    settings = normalize_plan(plan, filings, ids).set_index(["Document ID", "Period end", "Check ID"])
    output = []
    for (document_id, period), group in rows.groupby(["Document ID", "Period end"]):
        filing = documents[document_id]
        reported = group[group["Value status"].eq("Reported")]
        if verified_only:
            reported = reported[reported["Review status"].eq("Verified")]
        values = dict(zip(reported["Metric code"], reported["Value (millions)"]))
        source_steps = [UNIT_FACTORS[unit][1] for unit in reported["Source unit"]]
        tolerance = max(0.002, 2 * max(source_steps, default=0.001))
        for rule in RULES:
            setting = settings.loc[(document_id, period, rule.id)]
            # Some insurers disclose policyholder taxes as a distinct revenue
            # component. Include it only for the filing where it is reported.
            total_code = rule.total
            parts = rule.parts
            # Some filings' INS_NOTE_NET_CLOSE includes both PAA and non-PAA.
            # When the explicit non-PAA cohort is available, match its three
            # measurement components to that same cohort instead.
            if rule.id == "INS_MEAS_COMPONENTS" and "INS_NONPAA_NET_CLOSE" in values:
                total_code = "INS_NONPAA_NET_CLOSE"
                parts = ("INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE", "INS_NONPAA_CSM_CLOSE")
            elif rule.id == "REINS_MEAS_COMPONENTS" and "REINS_NONPAA_NET_CLOSE" in values:
                total_code = "REINS_NONPAA_NET_CLOSE"
                parts = ("REINS_NONPAA_PVFCF_CLOSE", "REINS_NONPAA_RA_CLOSE", "REINS_NONPAA_CSM_CLOSE")
            parts = parts + (("REV_POLICYHOLDER_TAX",) if rule.id == "REV_NONPAA_COMP"
                                  and "REV_POLICYHOLDER_TAX" in values else ())
            required = ((total_code,) if total_code else ()) + parts
            missing = [code for code in required if code not in values]
            assessment = setting["Assessment"]
            detail = ""
            difference = None
            if assessment == "Not applicable":
                result = "Not applicable"
                detail = str(setting["Reason"])
                missing = []
            elif assessment == "To assess":
                result = "Missing inputs"
                detail = "Confirm whether this disclosure and check apply to this filing and period."
            elif rule.group != "Primary statements" and not rule.mandatory and setting["Measurement method"] == "Not confirmed":
                result = "Missing inputs"
                detail = "Confirm the note's measurement method (GMM, VFA, PAA or mixed)."
            elif rule.group != "Primary statements" and not rule.mandatory and not str(setting["Note reference"]).strip():
                result = "Missing inputs"
                detail = "Enter the source note and page reference."
            elif rule.group in {"Rollforward", "Note composition"} and setting["Note scope"] == "Not confirmed":
                result = "Missing inputs"
                detail = "Confirm all components use one disclosed contract population and sign presentation."
            elif rule.id in {"CSM_ROLL", "INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS"} and setting["Measurement method"] == "PAA":
                result = "Missing inputs"
                detail = "A PAA-only cohort does not support this CSM composition check. Document Not applicable or identify the GMM/VFA cohort."
            elif rule.same_scope and setting["Note scope"] != "Same entity and balance basis":
                result = "Missing inputs"
                detail = "Confirm matching company/group scope, gross or net basis, and sign presentation."
            elif missing:
                result = "Missing inputs"
                detail = "Extract and verify each missing source field."
            elif rule.total is None:
                result = "Pass"
                detail = "Required primary statement cells are present and verified." if verified_only else "Required primary statement cells are present."
            else:
                contributions = {code: float(values[code]) for code in parts}
                if rule.id == "SERVICE":
                    basis = setting["Formula basis"]
                    if basis in ("Subtract positive service expense", "Subtract both positive expenses"):
                        contributions["INS_EXPENSE"] *= -1
                    if basis in ("Subtract positive reinsurance expense", "Subtract both positive expenses"):
                        contributions["REINS_RESULT"] *= -1
                if rule.same_scope and setting["Formula basis"] == "Reverse note sign for statement comparison":
                    contributions = {code: -amount for code, amount in contributions.items()}
                difference = float(values[total_code]) - sum(contributions.values())
                result = "Pass" if abs(difference) <= tolerance else "Difference"
                detail = "Within source-unit tolerance." if result == "Pass" else "Compare the source page, signs and disclosed scope."
            output.append({"Document ID": document_id, "Company": filing["company"],
                           "Legal entity": filing["legal_entity"], "Scope": filing["scope"],
                           "Currency": filing["currency"], "Period end": period,
                           "Check ID": rule.id, "Group": rule.group, "Check": rule.name,
                           "Assessment": assessment, "Measurement method": setting["Measurement method"],
                           "Note scope": setting["Note scope"], "Note reference": setting["Note reference"],
                           "Formula basis": setting["Formula basis"],
                           "Required inputs": ", ".join(required), "Missing inputs": ", ".join(missing),
                           "Difference (millions)": round(difference, 6) if difference is not None else None,
                           "Tolerance (millions)": tolerance, "Result": result, "Detail": detail})
    return pd.DataFrame(output, columns=CHECK_COLUMNS)


def require_resolved_checks(checks: pd.DataFrame) -> None:
    unresolved = checks[~checks["Result"].isin(("Pass", "Not applicable"))]
    if not unresolved.empty:
        counts = unresolved["Result"].value_counts().to_dict()
        raise ValueError(f"Resolve all checks before approval or publication: {counts}.")
