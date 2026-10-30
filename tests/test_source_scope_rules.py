"""Prevent the YF year, column, unit and population errors from recurring."""

from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook

from hkifrs17.catalog import PILOT_FILINGS
from hkifrs17.checks import CHECK_COLUMNS, require_resolved_checks
from hkifrs17.data import normalize_records, reconciliation_checks
from hkifrs17.pdf import _model_record_issue, _row
from hkifrs17.review import step3_workbook_bytes
from hkifrs17.review_flow import confirm_source_rows, per_cell_checks, source_scope_issue


FILING = next(f for f in PILOT_FILINGS if f["document_id"] == "YF_2025")
FILINGS = list(PILOT_FILINGS)


def _checked_rows(items):
    records = []
    for code, amount, page, label in items:
        row = _row(FILING, code, "2025-12-31", amount, page, label, "HKD")
        row["Review status"] = "Verified"
        row["Audit status"] = "Audited statement"
        records.append(row)
    return normalize_records(pd.DataFrame(records), FILINGS)


def test_scanned_contract_record_rejects_wrong_year_unit_and_component():
    item = {"metric_code": "INS_NONPAA_NET_CLOSE", "period_end": "2025-12-31",
            "source_unit": "HKD", "source_label": "2025 insurance non-PAA net closing balance",
            "table_year": "2024", "column_heading": "Total", "unit_evidence": "$"}
    assert "table year 2024" in _model_record_issue(item, FILING, strict_contract=True)
    item["table_year"] = "2025"
    item["unit_evidence"] = "HK$ million"
    assert "printed million unit" in _model_record_issue(item, FILING, strict_contract=True)
    item["source_unit"] = "HKD millions"
    item["unit_evidence"] = "HK$ million"
    item["column_heading"] = "Assets excluding loss-recovery component"
    assert "measurement component" in _model_record_issue(item, FILING, strict_contract=True)
    item["column_heading"] = "Total"
    assert _model_record_issue(item, FILING, strict_contract=True) == ""


def test_every_model_cell_requires_column_year_and_unit_provenance():
    item = {"metric_code": "PROFIT", "period_end": "2025-12-31",
            "source_unit": "HKD millions", "source_label": "Profit for the year | 2025",
            "table_year": "2025", "column_heading": "2025 | Total",
            "unit_evidence": "HK$ million"}
    assert _model_record_issue(item, FILING, strict_contract=False, strict_evidence=True) == ""
    item["column_heading"] = "2024 | Total"
    assert "different table year" in _model_record_issue(
        item, FILING, strict_contract=False, strict_evidence=True)
    item["column_heading"] = "2025 | Total"
    item["source_unit"] = "USD millions"
    assert "HKD currency" in _model_record_issue(
        item, FILING, strict_contract=False, strict_evidence=True)
    item["source_unit"] = "HKD millions"
    item["unit_evidence"] = "HK$"
    assert "no visible million evidence" in _model_record_issue(
        item, FILING, strict_contract=False, strict_evidence=True)
    item["unit_evidence"] = ""
    assert "unit_evidence are required" in _model_record_issue(
        item, FILING, strict_contract=False, strict_evidence=True)


def test_profit_or_loss_oci_and_cash_must_use_their_own_rows():
    item = {"metric_code": "INS_GROSS_PL_OCI", "period_end": "2025-12-31",
            "source_unit": "HKD", "source_label": "Total cash flows | 2025",
            "table_year": "2025", "column_heading": "2025 | Total", "unit_evidence": "HK$"}
    assert "cash-flow row" in _model_record_issue(
        item, FILING, strict_contract=True)
    item["metric_code"] = "INS_GROSS_CASH"
    item["source_label"] = "Total changes in profit or loss and OCI | 2025"
    assert "profit-or-loss/OCI row" in _model_record_issue(
        item, FILING, strict_contract=True)


def test_csm_uses_insurance_disclosed_movements_not_reinsurance_value():
    rows = _checked_rows([
        ("CSM_OPEN", 100, 122, "Insurance CSM opening | Total"),
        ("CSM_CLOSE", 130, 122, "Insurance CSM closing | Total"),
        ("CSM_NET_MOVEMENT", 999, 126, "Reinsurance CSM net movement"),
        ("INS_CSM_FV_OPEN", 40, 122, "Insurance fair value CSM opening"),
        ("INS_CSM_OTHER_OPEN", 60, 122, "Insurance other CSM opening"),
        ("INS_CSM_FV_CLOSE", 50, 122, "Insurance fair value CSM closing"),
        ("INS_CSM_OTHER_CLOSE", 80, 122, "Insurance other CSM closing"),
        ("INS_CSM_FV_PL_OCI", 10, 122, "Insurance fair value CSM total P&L and OCI changes"),
        ("INS_CSM_OTHER_PL_OCI", 20, 122, "Insurance other CSM total P&L and OCI changes"),
        ("INS_NONPAA_NET_CLOSE", 150, 122, "Insurance contracts not measured under PAA | Total"),
        ("INS_NONPAA_PVFCF_CLOSE", 20, 122, "Insurance non-PAA PVFCF closing"),
        ("INS_NONPAA_RA_CLOSE", 0, 122, "Insurance non-PAA RA closing"),
    ])
    checks = reconciliation_checks(rows, FILINGS, automatic=True).set_index("Check ID")
    assert checks.loc["CSM_ROLL", "Result"] == "Pass"
    assert checks.loc["INS_MEAS_COMPONENTS", "Result"] == "Pass"
    assert "CSM_NET_MOVEMENT" not in checks.loc["CSM_ROLL", "Required inputs"]
    assert "INS_CSM_FV_CLOSE" in checks.loc["INS_MEAS_COMPONENTS", "Required inputs"]


def test_gross_movement_and_signed_acquisition_asset_bridge_to_net():
    rows = _checked_rows([
        ("INS_GROSS_OPEN", 100, 120, "Insurance gross opening | Total"),
        ("INS_GROSS_PL_OCI", 20, 120, "Insurance total changes in profit or loss and OCI"),
        ("INS_GROSS_CASH", 30, 120, "Insurance total cash flows"),
        ("INS_GROSS_CLOSE", 150, 120, "Insurance gross closing | Total"),
        ("INS_ACQ_ASSET_CLOSE", -5, 119, "Insurance acquisition cash-flow asset | signed"),
        ("INS_LIABS_NOTE_CLOSE", 145, 119, "Insurance net liabilities | Total"),
    ])
    checks = reconciliation_checks(rows, FILINGS, automatic=True).set_index("Check ID")
    assert checks.loc["LIABILITY_ROLL", "Result"] == "Pass"
    assert checks.loc["LIABILITY_ROLL", "Required inputs"].endswith("INS_GROSS_CASH")
    assert checks.loc["INS_GROSS_NET_BRIDGE", "Result"] == "Pass"
    assert checks.loc["INS_GROSS_NET_BRIDGE", "Required inputs"].endswith("INS_ACQ_ASSET_CLOSE")
    changed = rows.copy()
    changed.loc[changed["Metric code"].eq("INS_GROSS_CLOSE"), "Original value"] = 10_150
    changed.loc[changed["Metric code"].eq("INS_GROSS_CLOSE"), "Value (millions)"] = 10_150 / 1_000_000
    broken = reconciliation_checks(changed, FILINGS, automatic=True).set_index("Check ID")
    assert broken.loc["LIABILITY_ROLL", "Result"] == "Difference"
    assert broken.loc["INS_GROSS_NET_BRIDGE", "Result"] == "Difference"


def test_conditional_gross_net_bridge_exports_live_excel_formula():
    rows = _checked_rows([
        ("INS_GROSS_OPEN", 100, 120, "Insurance gross opening | Total"),
        ("INS_GROSS_PL_OCI", 20, 120, "Insurance total changes in profit or loss and OCI"),
        ("INS_GROSS_CASH", 30, 120, "Insurance total cash flows"),
        ("INS_GROSS_CLOSE", 150, 120, "Insurance gross closing | Total"),
        ("INS_ACQ_ASSET_CLOSE", -5, 119, "Insurance acquisition cash-flow asset | signed"),
        ("INS_LIABS_NOTE_CLOSE", 145, 119, "Insurance net liabilities | Total"),
    ])
    workbook = load_workbook(BytesIO(step3_workbook_bytes(rows, FILINGS, None)))
    arithmetic = workbook["Excel arithmetic"]
    matches = [row for row in arithmetic.iter_rows(min_row=2)
               if row[2].value == "INS_GROSS_NET_BRIDGE"]
    assert len(matches) == 1
    assert matches[0][3].data_type == "f"
    assert matches[0][4].data_type == "f"
    assert matches[0][5].data_type == "f"
    assert matches[0][7].data_type == "f"


def test_paa_incurred_claims_component_cannot_become_a_verified_total():
    component = ("Net closing balance as at 31 December | Estimates of present value "
                 "of future cash flows | 2024 | Liabilities for incurred claims | Contracts under PAA")
    wrong_method = ("Contracts not under PAA | Net closing balance as at 31 December "
                    "| 2025 | Insurance contracts PAA")
    assert "measurement component" in source_scope_issue("INS_PAA_LIC_CLOSE", component)
    assert "non-PAA column" in source_scope_issue("INS_PAA_LIC_CLOSE", wrong_method)
    item = {"metric_code": "INS_PAA_LIC_CLOSE", "period_end": "2024-12-31",
            "source_unit": "HKD", "source_label": component,
            "table_year": "2024", "column_heading": "2024 | Contracts under PAA | Estimates of present value of future cash flows",
            "unit_evidence": "$"}
    assert "measurement component" in _model_record_issue(item, FILING, strict_contract=True)
    pending = pd.DataFrame([_row(FILING, "INS_PAA_LIC_CLOSE", "2025-12-31", 994_533_981,
                                 120, wrong_method, "HKD")])
    with pytest.raises(ValueError, match="non-PAA column"):
        confirm_source_rows(pending, [0], FILING, FILINGS)
    checked = _checked_rows([("INS_PAA_LIC_CLOSE", 994_533_981, 120, wrong_method)])
    checks = reconciliation_checks(checked, FILINGS, automatic=True)
    result = per_cell_checks(checked, checks)
    assert result.iloc[0]["Cell result"] == "Investigate"
    assert "non-PAA column" in result.iloc[0]["Source trace"]
    workbook = load_workbook(BytesIO(step3_workbook_bytes(checked, FILINGS, None)))
    assert "not under" in workbook["Cell checks"]["I2"].value


def test_nonpaa_incurred_claims_cannot_sum_paa_component_column():
    label = ("Closing liabilities | Contracts not under PAA + Estimates of present value "
             "of future cash flows + Risk adjustment for non-financial risk | 2024")
    assert "combines multiple printed columns" in source_scope_issue(
        "INS_NONPAA_LIC_CLOSE", label)
    item = {"metric_code": "INS_NONPAA_LIC_CLOSE", "period_end": "2024-12-31",
            "source_unit": "HKD", "source_label": label,
            "table_year": "2024", "column_heading": "2024 | Contracts not under PAA",
            "unit_evidence": "$"}
    assert "combines multiple printed columns" in _model_record_issue(
        item, FILING, strict_contract=True)
    row = _row(FILING, "INS_NONPAA_LIC_CLOSE", "2024-12-31", 676_637_101,
               121, label, "HKD")
    row["Review status"] = "Verified"
    row["Audit status"] = "Comparative in 2025 statement"
    checked = normalize_records(pd.DataFrame([row]), FILINGS)
    result = per_cell_checks(checked, reconciliation_checks(checked, FILINGS, automatic=True))
    assert result.iloc[0]["Cell result"] == "Investigate"
    assert "combines multiple printed columns" in result.iloc[0]["Source trace"]
    workbook = load_workbook(BytesIO(step3_workbook_bytes(checked, FILINGS, None)))
    assert "present value of future cash flows" in workbook["Cell checks"]["I2"].value


def test_measurement_rule_uses_total_from_component_table():
    rows = _checked_rows([
        ("REINS_NONPAA_NET_CLOSE", 55, 124,
         "Net closing balance | Assets for remaining coverage excluding loss-recovery component"),
        ("REINS_NOTE_NET_CLOSE", 100, 126,
         "Net closing balance | Total | Reinsurance non-PAA"),
        ("REINS_NONPAA_PVFCF_CLOSE", 60, 126,
         "Net closing balance | Present value | Reinsurance non-PAA"),
        ("REINS_NONPAA_RA_CLOSE", 10, 126,
         "Net closing balance | Risk adjustment | Reinsurance non-PAA"),
        ("REINS_CSM_FV_CLOSE", 20, 126,
         "Net closing balance | Fair value CSM | Reinsurance non-PAA"),
        ("REINS_CSM_OTHER_CLOSE", 10, 126,
         "Net closing balance | Other CSM | Reinsurance non-PAA"),
    ])
    result = reconciliation_checks(rows, FILINGS, automatic=True)
    check = result.set_index("Check ID").loc["REINS_MEAS_COMPONENTS"]
    assert check["Result"] == "Pass"
    assert check["Required inputs"].startswith("REINS_NOTE_NET_CLOSE")


def test_method_split_exception_requires_a_pdf_note_reference():
    check = pd.DataFrame([{**{column: "" for column in CHECK_COLUMNS},
                           "Check ID": "INS_LIABS_METHOD", "Result": "Not applicable",
                           "Reason": "The note splits incurred claims only.", "Note reference": ""}])
    with pytest.raises(ValueError, match="physical PDF page"):
        require_resolved_checks(check, automatic=True)
    check.at[0, "Note reference"] = "Note 22(a)"
    with pytest.raises(ValueError, match="physical PDF page"):
        require_resolved_checks(check, automatic=True)
    check.at[0, "Note reference"] = "Note 22(a), physical PDF pp.120-121"
    require_resolved_checks(check, automatic=True)


def test_front_matter_amount_cannot_be_used_as_audited_note_balance():
    rows = _checked_rows([
        ("INS_LIABS", 100_000_000, 29, "Insurance contract liabilities | 2025"),
        ("INS_LIABS_NOTE_CLOSE", 100, 14, "Insurance contract liabilities | 2025"),
    ])
    check = reconciliation_checks(rows, FILINGS, automatic=True).set_index("Check ID").loc["LIABILITY_NOTE"]
    assert check["Result"] == "Missing inputs"
    assert "precedes the audited financial statements" in check["Detail"]
