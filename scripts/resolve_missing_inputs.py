"""Resolve the 31 previously open checks with source-page evidence.

Input is the immutable 2024–2025 source-checked workbook. A gross-balance
rollforward is not fabricated from a disclosed net cohort rollforward.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from hkifrs17.catalog import METRIC_BY_CODE, PILOT_FILINGS
from hkifrs17.checks import RULE_BY_ID, evaluate_checks, normalize_plan
from hkifrs17.data import COLUMNS, normalize_records
from scripts.build_two_year_dataset import PROFILES_2024


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs/HK_IFRS17_FWD_YF_SunLife_2024_2025_verified.xlsx"
OUT = ROOT / "scratch/resolved_export"
FILINGS = [*PILOT_FILINGS, *PROFILES_2024]

# The pages below are physical PDF pages. Amounts keep the report's signs and
# source units. A calculated subtotal is used only when its named component
# lines are independently reported on the cited page(s).
ADDITIONS = {
    "SUN_GROUP_2024": [
        ("CSM_NET_MOVEMENT", 6260, 103, "CSM: total changes in income/OCI 6,282 plus cash flows (22)", "Sum of two reported CSM movement subtotals on p.103."),
        ("INS_LIABS_NONPAA_CLOSE", 101409, 102, "Non-PAA insurance contracts: closing liabilities", "Reported gross liability, p.102."),
        ("INS_LIABS_PAA_CLOSE", 120, 108, "PAA insurance contracts: closing liabilities", "Reported gross liability, p.108."),
        ("INS_LIABS_NOTE_CLOSE", 101529, 102, "Non-PAA closing liabilities 101,409 plus PAA closing liabilities 120", "Sum of separately reported gross liabilities, pp.102 and 108."),
        ("REINS_ASSETS_NONPAA_CLOSE", -2372, 105, "Non-PAA reinsurance contracts: closing assets (2,372)", "Audited note presents reinsurance assets in parentheses, p.105."),
        ("REINS_ASSETS_PAA_CLOSE", -11, 109, "PAA reinsurance contracts: closing assets (11)", "Audited note presents reinsurance assets in parentheses, p.109."),
        ("REINS_ASSETS_NOTE_CLOSE", -2383, 105, "Non-PAA closing assets (2,372) plus PAA closing assets (11)", "Sum of separately reported signed assets, pp.105 and 109."),
    ],
    "SUN_2025": [
        ("INS_LIABS_NONPAA_CLOSE", 136935, 94, "Non-PAA insurance contracts: closing liabilities", "Reported gross liability, p.94."),
        ("INS_LIABS_PAA_CLOSE", 175, 98, "PAA insurance contracts: closing liabilities", "Reported gross liability, p.98."),
        ("INS_LIABS_NOTE_CLOSE", 137110, 94, "Non-PAA closing liabilities 136,935 plus PAA closing liabilities 175", "Sum of separately reported gross liabilities, pp.94 and 98."),
        ("REINS_ASSETS_NONPAA_CLOSE", -1802, 97, "Non-PAA reinsurance contracts: closing assets (1,802)", "Audited note presents reinsurance assets in parentheses, p.97."),
        ("REINS_ASSETS_PAA_CLOSE", -11, 99, "PAA reinsurance contracts: closing assets (11)", "Audited note presents reinsurance assets in parentheses, p.99."),
        ("REINS_ASSETS_NOTE_CLOSE", -1813, 97, "Non-PAA closing assets (1,802) plus PAA closing assets (11)", "Sum of separately reported signed assets, pp.97 and 99."),
    ],
    "YF_2024": [
        ("CSM_OPEN", 8099761183, 116, "Opening CSM: fair value transition 6,193,932,885 plus other 1,905,828,298", "Sum of two reported opening CSM columns, p.116."),
        ("CSM_NET_MOVEMENT", 1022736910, 116, "Total changes in P&L/OCI: CSM 781,513,515 plus 241,223,395", "Sum of two reported current-year CSM movement columns, p.116; no closing-minus-opening plug."),
        ("CSM_CLOSE", 9122498093, 116, "Closing CSM: fair value transition 6,975,446,400 plus other 2,147,051,693", "Sum of two reported closing CSM columns, p.116."),
        ("INS_NONPAA_CSM_CLOSE", 9122498093, 116, "Non-PAA insurance closing CSM: fair value transition plus other contracts", "Sum of two reported closing CSM columns, p.116."),
        ("REINS_NONPAA_PVFCF_CLOSE", 5686702425, 120, "Non-PAA reinsurance closing estimates of PV of future cash flows", "Reported closing component, p.120."),
        ("REINS_NONPAA_RA_CLOSE", 164980084, 120, "Non-PAA reinsurance closing risk adjustment", "Reported closing component, p.120."),
        ("REINS_NONPAA_CSM_CLOSE", 903708883, 120, "Non-PAA reinsurance closing CSM: 841,019,532 plus 62,689,351", "Sum of two reported closing CSM columns, p.120."),
        ("REINS_NONPAA_NET_CLOSE", 6755391392, 120, "Non-PAA reinsurance net closing balance", "Reported same-cohort closing total, p.120."),
    ],
    "YF_2025": [
        ("CSM_OPEN", 9122498093, 122, "Opening CSM: fair value transition 6,975,446,400 plus other 2,147,051,693", "Sum of two reported opening CSM columns, p.122."),
        ("CSM_NET_MOVEMENT", 1639266841, 122, "Total changes in P&L/OCI: CSM (431,099,765) plus 2,070,366,606", "Sum of two reported current-year CSM movement columns, p.122; no closing-minus-opening plug."),
        ("CSM_CLOSE", 10761764934, 122, "Closing CSM: fair value transition 6,544,346,635 plus other 4,217,418,299", "Sum of two reported closing CSM columns, p.122."),
        ("INS_NONPAA_CSM_CLOSE", 10761764934, 122, "Non-PAA insurance closing CSM: fair value transition plus other contracts", "Sum of two reported closing CSM columns, p.122."),
        ("REINS_NONPAA_PVFCF_CLOSE", 6271752643, 126, "Non-PAA reinsurance closing estimates of PV of future cash flows", "Reported closing component, p.126."),
        ("REINS_NONPAA_RA_CLOSE", 182131706, 126, "Non-PAA reinsurance closing risk adjustment", "Reported closing component, p.126."),
        ("REINS_NONPAA_CSM_CLOSE", 979566521, 126, "Non-PAA reinsurance closing CSM: 933,613,155 plus 45,953,366", "Sum of two reported closing CSM columns, p.126."),
        ("REINS_NONPAA_NET_CLOSE", 7433450870, 126, "Non-PAA reinsurance net closing balance", "Reported same-cohort closing total, p.126."),
    ],
}

REFERENCES = {
    "SUN_GROUP_2024": "Sun Life 2024 note 20, physical pp.102-109; audited consolidated 2024 cohort",
    "SUN_2025": "Sun Life 2025 note 20, physical pp.94-99; audited company 2025 cohort",
    "YF_2024": "YF Life 2024 note 21, physical pp.113-120; audited consolidated 2024 cohort",
    "YF_2025": "YF Life 2025 note 22, physical pp.119-126; audited consolidated 2025 cohort",
    "FWD_2024": "FWD 2024 note 13, physical pp.66-77; audited company 2024 cohort",
    "FWD_2025": "FWD 2025 note 13, physical pp.62-73; audited company 2025 cohort",
}


def _append_source_rows(base: pd.DataFrame) -> pd.DataFrame:
    rows = base.astype(object).where(pd.notna(base), None).to_dict("records")
    identities = {doc: base[base["Document ID"].eq(doc)].iloc[0].to_dict() for doc in ADDITIONS}
    for doc, additions in ADDITIONS.items():
        template = identities[doc]
        for code, value, page, label, evidence in additions:
            assert code in METRIC_BY_CODE and not (base["Document ID"].eq(doc) & base["Metric code"].eq(code)).any(), (doc, code)
            metric = METRIC_BY_CODE[code]
            item = dict(template)
            item.update({
                "Metric code": code, "Metric": metric.label, "Section": metric.section,
                "Original value": value, "Value (millions)": None,
                "Value status": "Reported", "PDF page": page, "Source label": label,
                "Audit status": "Sum of audited note lines" if evidence.startswith("Sum") else "Audited note",
                "Review status": "Verified", "Reviewer note": evidence,
            })
            rows.append(item)
    result = normalize_records(pd.DataFrame(rows)[COLUMNS], FILINGS)
    assert not result.duplicated(["Document ID", "Period end", "Metric code"]).any()
    return result.sort_values(["Company", "Period end", "Section", "Metric code"]).reset_index(drop=True)


def _review_plan(base: pd.DataFrame, records: pd.DataFrame) -> pd.DataFrame:
    plan = normalize_plan(base, FILINGS, set(records["Document ID"]))
    for index, row in plan.iterrows():
        doc, year, check = row["Document ID"], row["Period end"], row["Check ID"]
        if year not in {"2024-12-31", "2025-12-31"} or not records["Document ID"].eq(doc).any():
            continue
        if year != records.loc[records["Document ID"].eq(doc), "Period end"].iloc[0]:
            continue
        if check in {"LIABILITY_ROLL", "REINSURANCE_ROLL"}:
            plan.at[index, "Assessment"] = "Not applicable"
            plan.at[index, "Measurement method"] = "Mixed"
            plan.at[index, "Note scope"] = "Different or net scope"
            plan.at[index, "Note reference"] = REFERENCES[doc]
            plan.at[index, "Reason"] = (
                "This check requires an independent movement of the gross statement balance. "
                "The note reports movements for net contract cohorts, with opening and closing gross "
                "assets/liabilities only. The same-cohort INS_NET_ROLL or REINS_NET_ROLL is checked separately."
            )
        elif doc in {"YF_2024", "YF_2025"} and check in {"INS_LIABS_METHOD", "REINS_ASSETS_METHOD"}:
            plan.at[index, "Assessment"] = "Applicable"
            plan.at[index, "Measurement method"] = "Mixed"
            plan.at[index, "Note scope"] = "Different or net scope"
            plan.at[index, "Note reference"] = REFERENCES[doc]
            plan.at[index, "Reason"] = (
                "The audited note shows PAA incurred-claims columns but no separately reported "
                "whole-contract PAA closing subtotal. Insurance statement liabilities also deduct "
                "insurance acquisition cash-flow assets. Do not infer a PAA balance as a residual."
            )
        elif doc in ADDITIONS and check in {"CSM_ROLL", "LIABILITY_NOTE", "REINSURANCE_NOTE",
                                             "INS_LIABS_METHOD", "REINS_ASSETS_METHOD",
                                             "INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS"}:
            plan.at[index, "Assessment"] = "Applicable"
            plan.at[index, "Measurement method"] = "Mixed" if check != "CSM_ROLL" else "GMM"
            plan.at[index, "Note scope"] = "Same entity and balance basis"
            plan.at[index, "Note reference"] = REFERENCES[doc]
            if check == "REINSURANCE_NOTE" and doc.startswith("SUN"):
                plan.at[index, "Formula basis"] = "Reverse note sign for statement comparison"
    return normalize_plan(plan, FILINGS, set(records["Document ID"]))


def _export(name: str, frame: pd.DataFrame) -> None:
    values = frame.astype(object).where(pd.notna(frame), None).to_dict("records")
    (OUT / f"{name.replace(' ', '_')}.json").write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = pd.read_excel(BASE, sheet_name=None)
    records = _append_source_rows(previous["Records"])
    plan = _review_plan(previous["Check plan"], records)
    checks = evaluate_checks(records, FILINGS, plan, verified_only=True)
    checks = checks[checks["Period end"].isin(("2024-12-31", "2025-12-31"))].copy()
    assert len(checks) == 102 and not checks["Result"].eq("Difference").any()
    mandatory = checks[checks["Check ID"].isin(("PRIMARY", "SERVICE", "BALANCE"))]
    assert len(mandatory) == 18 and mandatory["Result"].eq("Pass").all()

    before = previous["Checks"]
    before = before[before["Result"].eq("Missing inputs")]
    assert len(before) == 31
    review = before[["Document ID", "Company", "Period end", "Check ID", "Check", "Missing inputs"]].copy()
    review = review.rename(columns={"Missing inputs": "Previously missing fields"})
    review = review.merge(checks[["Document ID", "Period end", "Check ID", "Result", "Missing inputs", "Note reference"]],
                          on=["Document ID", "Period end", "Check ID"], validate="one_to_one")
    notes = plan[["Document ID", "Period end", "Check ID", "Reason"]]
    review = review.merge(notes, on=["Document ID", "Period end", "Check ID"], validate="one_to_one")
    review["Resolution"] = review.apply(lambda item: (
        "Source fields extracted and reconciled" if item["Result"] == "Pass" else
        "Gross/net scope makes this check inapplicable; same-cohort net rollforward remains checked" if item["Result"] == "Not applicable" else
        "Full PAA method subtotal not separately disclosed; do not infer a residual"
    ), axis=1)
    review = review[["Document ID", "Company", "Period end", "Check ID", "Check",
                     "Previously missing fields", "Result", "Missing inputs", "Resolution", "Note reference", "Reason"]]

    coverage = previous["Coverage"].copy()
    for index, row in coverage.iterrows():
        doc = records.loc[records["Company"].eq(row["Insurer"]) & records["Period end"].eq(row["Period end"]), "Document ID"].iloc[0]
        source = checks[checks["Document ID"].eq(doc)]
        coverage.at[index, "Verified cells"] = int(records["Document ID"].eq(doc).sum())
        for status in ("Pass", "Difference", "Missing inputs", "Not applicable"):
            coverage.at[index, status] = int(source["Result"].eq(status).sum())
        coverage.at[index, "Coverage note"] = "See Missing review: no opening-minus-closing plug; source, method and scope checked."

    readme = pd.DataFrame({"Instruction": [
        "HK IFRS 17 | 2024–2025 audited insurer data with follow-up review of 31 previously missing checks.",
        "Records contains current-year 2024 and 2025 values only; PDF page is the one-based physical page.",
        "Missing review traces every one of the 31 former Missing inputs to a new check result and its source/scope rationale.",
        "A reported net-cohort movement is not substituted for an undisclosed gross asset or liability movement; such invalid gross-roll checks are documented Not applicable.",
        "Insurance/reinsurance PVFCF + RA + CSM checks now explicitly target the same non-PAA cohort rather than the all-method note total.",
        "YF's statement insurance liability deducts assets for insurance acquisition cash flows from the gross contract-balance note; no PAA method subtotal is inferred by subtraction.",
        "Sun Life 2024 is consolidated while Sun Life 2025 is company-only; they are separate display identities and not a like-for-like year-on-year pair.",
        "Source units and source signs are preserved, including Sun Life reinsurance assets shown in parentheses in its note.",
        "Only Pass or a documented Not applicable is resolved. Any remaining Missing inputs is unresolved, not a pass.",
        "Upload this workbook in Step 5 to share its verified Records with Steps 5 and 6.",
    ]})
    current_pairs = set(map(tuple, records[["Document ID", "Period end"]].itertuples(index=False, name=None)))
    plan = plan[plan[["Document ID", "Period end"]].apply(tuple, axis=1).isin(current_pairs)].copy()
    for name, frame in (("Coverage", coverage), ("Missing review", review), ("Records", records),
                        ("Checks", checks), ("Check plan", plan), ("Read me", readme)):
        _export(name, frame)
    print("Cells:", len(records), "checks:", checks["Result"].value_counts().to_dict())
    print("Previously missing:", review["Result"].value_counts().to_dict())
    print(review[review["Result"].eq("Missing inputs")][["Document ID", "Check ID", "Missing inputs"]].to_string(index=False))


if __name__ == "__main__":
    main()
