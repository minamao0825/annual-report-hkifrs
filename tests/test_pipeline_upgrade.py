"""Source coverage and reviewed-snapshot handoff for the Step 1-6 path."""

from __future__ import annotations

import json
from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook

from hkifrs17 import external
from hkifrs17.checks import require_resolved_checks
from hkifrs17.extraction_plan import TABLE_METRICS, discovery_target_for
from hkifrs17.locator import discovery_prompt
from hkifrs17.pdf import extraction_prompt
from hkifrs17.source_templates import AUDITOR_TEMPLATES, table_examples, verified_table_options
from hkifrs17.catalog import PILOT_FILINGS
from hkifrs17.demo import demo_records
from hkifrs17.catalog import METRICS
from hkifrs17.review import review_workbook_bytes


def test_reviewed_source_codes_are_reachable_through_table_selection():
    # All 230 codes in the current audited Step 6 source store must remain
    # reachable after narrowing the discovery menu.
    source = external.load_external()
    assert not source.empty
    available = set().union(*(set(TABLE_METRICS[name]) for name in verified_table_options()))
    assert set(source["Metric code"]).issubset(available)
    for auditor in AUDITOR_TEMPLATES:
        assert {"Profit or loss", "Financial position", "Insurance and reinsurance contracts"}.issubset(
            verified_table_options(auditor)
        )
        assert not any(name in verified_table_options(auditor) for name in (
            "Insurance service expenses", "Insurance contract movement and measurement",
            "Reinsurance contract movement and measurement", "Initially recognised insurance contracts",
            "Initially recognised reinsurance contracts", "Expected CSM recognition",
            "Risk adjustment confidence level",
        ))
        assert "Discount rates and illiquidity premiums" in verified_table_options(auditor)
        assert not any(name.startswith("Discount rates ·") for name in verified_table_options(auditor))


def test_page_prompt_uses_selected_table_and_no_reference_page_number():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "FWD_2025")
    prompt = discovery_prompt(filing, [1, 2], ["Insurance and reinsurance contracts"], "EY")
    assert "Insurance and reinsurance contracts" in prompt
    assert "reference title" in prompt
    assert "PDF page 51" not in prompt
    assert "Insurance revenue analysis" in prompt
    assert "PAA" in prompt and "CSM" in prompt and "new business" in prompt
    assert "Profit or loss:" not in prompt


def test_single_target_prompt_keeps_shared_checks_without_unrelated_rules():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    investment = discovery_prompt(filing, [98, 99], ["Investment result analysis"], "KPMG")
    for required in ("audited financial-statement", "comparative year",
                     "reporting scope", "PHYSICAL PDF PAGE", "section_evidence",
                     "year_evidence", "scope_evidence", "visible_table_years"):
        assert required in investment
    assert "including component tables of interest" in investment
    assert "PAA, non-PAA" not in investment
    assert "not one candidate per currency" not in investment
    assert "capital-and-reserves" not in investment
    assert len(investment) < 4000
    assert "A title, contents entry, prose or keyword alone is insufficient" in investment
    assert "do not transcribe amounts" in investment.lower()
    assert "Group-only tables for a Company filing" in investment
    assert "Low only when table and year are visible" in investment

    discount = discovery_prompt(filing, [133], ["Discount rates and illiquidity premiums"], "KPMG")
    assert "not one candidate per currency" in discount
    assert "including component tables of interest" not in discount
    assert "capital-and-reserves" not in discount


def test_yf_combined_contract_and_discount_table_prompts():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    prompt = discovery_prompt(
        filing, [120, 133], ["Insurance and reinsurance contracts", "Discount rates and illiquidity premiums"],
        "KPMG",
    )
    assert "Insurance contracts, analysis by" in prompt
    assert "Reinsurance contracts held" in prompt
    assert "Note 22(a)(i)" not in prompt
    assert "analysis by measurement component" in prompt
    assert "row group" in prompt
    assert "Business Review" in prompt
    assert "source_section" in prompt
    assert "year_evidence" in prompt and "scope_evidence" in prompt
    assert "comparative year" in prompt
    assert "not one candidate per currency" in prompt
    assert "PDF page 120" not in prompt


def test_discovery_prompt_distinguishes_balance_from_credit_quality_and_company_notes():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    prompt = discovery_prompt(filing, [72, 113, 141], [
        "Financial investment classification", "Equity movement", "Investment result analysis",
    ], "KPMG")
    assert "credit-quality/rating/investment-grade" in prompt
    assert "capital-and-reserves" in prompt
    assert "Company-only table" in prompt
    assert "including component tables of interest" in prompt
    assert "reference title: Net financial result" in prompt
    assert "Note 6 Net financial result" not in prompt


def test_old_note_numbers_and_pages_are_absent_from_user_examples_and_prompts():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    tables = ["Investment result analysis", "Insurance and reinsurance contracts"]
    examples = table_examples("KPMG", tables)
    assert all("Reference PDF page(s)" not in item for item in examples)
    assert all("Note 6" not in str(item) and "Note 22" not in str(item)
               for item in examples)
    assert any("Net financial result" in item["Example note / table title"]
               for item in examples)
    prompt = discovery_prompt(filing, [120], tables, "KPMG")
    assert "Note 6" not in prompt and "Note 22" not in prompt
    assert "Investment result components" in prompt


def test_old_contract_table_hints_map_to_one_discovery_target():
    for old_name in (
        "Insurance service expenses", "Insurance revenue note",
        "Insurance contract movement and measurement",
        "Reinsurance contract movement and measurement",
        "Insurance non-PAA remaining/incurred movement",
        "Reinsurance PAA remaining/incurred movement",
        "Initially recognised insurance contracts",
        "Initially recognised reinsurance contracts", "Expected CSM recognition",
        "Risk adjustment confidence level",
    ):
        assert discovery_target_for(old_name) == "Insurance and reinsurance contracts"


def test_extraction_prompt_only_lists_selected_metric_codes():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "FWD_2025")
    metric = next(item for item in METRICS if item.code == "INS_REVENUE")
    prompt = extraction_prompt(filing, [metric], ["Insurance revenue note"])
    assert "INS_REVENUE:" in prompt
    assert "2025" in prompt
    assert "contract population" in prompt
    assert "REINS_RESULT:" not in prompt


def test_extraction_prompt_keeps_source_trace_and_two_years():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    metric = next(item for item in METRICS if item.code == "INS_NONPAA_NET_OPEN")
    prompt = extraction_prompt(filing, [metric],
                               ["Insurance non-PAA remaining/incurred movement"],
                               ("2025",), physical_page=120)
    for rule in ("PHYSICAL PDF PAGE 120", "2025-12-31", "2024-12-31",
                 "positive expense stays positive", "conflicting or uncertain unit",
                 "original row and column text", "Total versus CSM subtotal",
                 "do not derive", 'return {"records":[]}'):
        assert rule in prompt
    assert "Use the disclosed maturity buckets" not in prompt
    assert "For rates and confidence levels" not in prompt
    assert "Use the insurance revenue analysis" not in prompt


def test_combined_contract_extraction_keeps_detail_scopes_separate():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    selected = [metric for metric in METRICS if metric.code in {"CSM_NEW", "NB_INS_ONEROUS_LOSS"}]
    prompt = extraction_prompt(filing, selected, ["Insurance and reinsurance contracts"])
    assert "visible subtable first" in prompt
    assert "PAA and non-PAA" in prompt
    assert "initial contract balance is not automatically a loss component" in prompt


def test_documented_optional_missing_input_is_visible_but_not_a_gate_failure():
    row = {"Check ID": "INS_LIABS_METHOD", "Result": "Missing inputs",
           "Assessment": "Applicable", "Reason": "PAA subtotal is not separately disclosed.",
           "Note reference": "Note 20, p. 94", "Detail": "Extract and verify each missing source field."}
    require_resolved_checks(pd.DataFrame([row]))
    with pytest.raises(ValueError, match="Missing inputs"):
        require_resolved_checks(pd.DataFrame([{**row, "Reason": ""}]))
    with pytest.raises(ValueError, match="Difference"):
        require_resolved_checks(pd.DataFrame([{**row, "Result": "Difference"}]))


def test_latest_confirmed_snapshot_wins_per_filing(tmp_path, monkeypatch):
    base = demo_records("YF_2025")
    base.loc[base.index[0], "Source label"] = "integrated version"
    uploaded = base.copy()
    uploaded.loc[uploaded.index[0], "Source label"] = "external version"
    monkeypatch.setattr(external, "load_integrated", lambda: base)
    monkeypatch.setattr(external, "load_external", lambda: uploaded)
    monkeypatch.setattr(external, "integration_status", lambda: {"integrated_epoch": 100.0})
    monkeypatch.setattr(external, "EXTERNAL_IMPORTS_FILE", tmp_path / "external_imports.json")
    (tmp_path / "external_imports.json").write_text(json.dumps({"YF_2025": 50.0}), encoding="utf-8")
    result = external.load_analysis_records()
    assert "integrated version" in set(result["Source label"])
    assert "external version" not in set(result["Source label"])
    (tmp_path / "external_imports.json").write_text(json.dumps({"YF_2025": 150.0}), encoding="utf-8")
    result = external.load_analysis_records()
    assert "external version" in set(result["Source label"])
    assert "integrated version" not in set(result["Source label"])


def test_excel_arithmetic_references_original_source_cells_and_units():
    records = demo_records("YF_2025")
    records["Review status"] = "Verified"
    records["Audit status"] = "Audited statement"
    workbook = load_workbook(BytesIO(review_workbook_bytes(records, list(PILOT_FILINGS))))
    sheet = workbook["Excel arithmetic"]
    row = next(values for values in sheet.values if values[2] == "BALANCE")
    assert row[3].startswith("=(Records!$J$")
    assert "VLOOKUP" in row[4]
    assert row[5].startswith("=D")
    assert row[7].startswith("=IF(")
