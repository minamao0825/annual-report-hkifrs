"""The chart-led HK extraction map must preserve source table and method scope."""

from __future__ import annotations

import json

import fitz
import pandas as pd

from hkifrs17.catalog import METRIC_BY_CODE, PILOT_FILINGS
from hkifrs17.charts import analytical_ratio_rows
from hkifrs17.data import normalize_records
from hkifrs17.demo import demo_records
from hkifrs17.extraction_plan import TABLE_FAMILIES, TABLE_METRICS
from hkifrs17.metric_blueprint import CHART_REQUIREMENTS, source_table_for
from hkifrs17.storage import pdf_path


def test_source_step7_inventory_has_an_explicit_hk_disposition_and_source_table():
    assert len(CHART_REQUIREMENTS) == 42
    ids = {item.source_id for item in CHART_REQUIREMENTS}
    assert {"summary_table", "csm_table", "discount_rate", "confidence_level", "nbv_table"} <= ids
    assert next(item for item in CHART_REQUIREMENTS if item.source_id == "csm_equity").decision == "Exclude"
    assert next(item for item in CHART_REQUIREMENTS if item.source_id == "exp_struct").decision == "Exclude"
    assert "solvency" in next(item for item in CHART_REQUIREMENTS if item.source_id == "six_dimensional_charts").note
    for item in CHART_REQUIREMENTS:
        assert item.decision in {"Reuse", "Adapt", "Conditional", "Exclude"}
        if item.decision == "Exclude":
            assert not item.metrics and item.note
        for code in item.metrics:
            assert code in METRIC_BY_CODE and source_table_for(code) in TABLE_METRICS
    assert set(TABLE_FAMILIES["Insurance contract movements"]).isdisjoint(
        TABLE_FAMILIES["Reinsurance contract movements"])


def test_fwd_note_13_page_leads_follow_actual_subtables_and_exclude_narrative_pages():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "FWD_2025")
    hints = dict(filing["note_page_hints"])
    assert hints[63] == "Insurance non-PAA remaining/incurred movement"
    assert hints[65] == "Insurance non-PAA measurement reconciliation"
    assert hints[67] == "Insurance PAA remaining/incurred movement"
    assert hints[69] == "Reinsurance non-PAA remaining/incurred movement"
    assert hints[71] == "Reinsurance non-PAA measurement reconciliation"
    assert hints[73] == "Reinsurance PAA remaining/incurred movement"
    assert hints[75] == "Initially recognised insurance contracts"
    assert (76, "Expected CSM recognition") in filing["note_page_hints"]
    assert hints[54] == "Expenses note"
    assert hints[81] == hints[82] == hints[84] == hints[85] == "Investment assets note"
    assert not any(page in (13, 64, 66, 68, 70, 72, 74, 77, 78, 83)
                   for page, _ in filing["note_page_hints"])
    with fitz.open(pdf_path(filing)) as document:
        assert "Insurance contract assets" in document[61].get_text()
        assert "not measured under the premium allocation approach" in document[62].get_text()
        assert "Analysis by measurement component" in document[64].get_text()
        assert "contracts measured under the premium allocation approach" in document[66].get_text()
        assert "Reinsurance contracts held not measured" in document[68].get_text()
        assert "Effect of contracts initially recognised" in document[74].get_text()
        assert "Within one year" in document[75].get_text()


def test_requested_table_types_are_available_for_each_filing_scope():
    requested = {
        "Financial position", "Profit or loss", "Cash flows", "Equity movement",
        "Insurance revenue note", "Insurance service expense analysis",
        "Other comprehensive income analysis", "Expenses note",
        "Insurance non-PAA remaining/incurred movement",
        "Insurance PAA remaining/incurred movement",
        "Insurance non-PAA measurement reconciliation",
        "Initially recognised insurance contracts", "Investment assets note",
        "Discount rates · HKD",
    }
    assert requested <= set(TABLE_METRICS)
    assert requested <= {table for family in TABLE_FAMILIES.values() for table in family}
    yf = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    sun = next(item for item in PILOT_FILINGS if item["document_id"] == "SUN_2025")
    assert yf["scope"] == "Consolidated" and yf["page_rotation_hints"][31] == 90
    assert (30, "Financial position") in yf["note_page_hints"]
    assert sun["scope"] == "Company"
    assert (16, "Financial position") in sun["note_page_hints"]
    assert (19, "Cash flows") in sun["note_page_hints"]


def test_fwd_profit_or_loss_result_is_not_the_note_total_including_oci():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "FWD_2025")
    assert "NET_INV_RESULT" in TABLE_METRICS["Profit or loss"]
    assert "NET_INV_RESULT_TOTAL" not in TABLE_METRICS["Profit or loss"]
    assert "NET_INV_RESULT_TOTAL" in TABLE_METRICS["Investment result analysis"]
    assert "NET_INV_RESULT" not in TABLE_METRICS["Investment result analysis"]
    with fitz.open(pdf_path(filing)) as document:
        statement = document[7].get_text()
        note = document[51].get_text()
    assert "Net investment result" in statement and "17,861" in statement
    assert "Amounts recognised in OCI" in note and "113,534" in note


def test_percentage_disclosures_do_not_get_monetary_conversion(monkeypatch):
    import hkifrs17.pdf as pdf

    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "FWD_2025")
    monkeypatch.setattr(pdf, "page_png", lambda *args, **kwargs: b"page")
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"records": [
                {"metric_code": "DISCOUNT_HKD_1Y_RF", "period_end": "2025-12-31",
                 "original_value": 2.63, "source_unit": "USD thousands",
                 "source_label": "HKD 1 year · Risk free"},
                {"metric_code": "DISCOUNT_HKD_1Y_RF", "period_end": "2024-12-31",
                 "original_value": 3.88, "source_unit": "percent",
                 "source_label": "HKD 1 year · Risk free comparative"},
            ]})}}]}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(pdf.requests, "post", fake_post)
    rows = pdf.extract_model_page(pdf_path(filing), filing, 79, list(PILOT_FILINGS),
                                  base_url="https://api.example.com/v1", model="vision", api_key="test-key",
                                  metric_codes={"DISCOUNT_HKD_1Y_RF"},
                                  table_names=["Discount rates · HKD"])
    assert rows.loc[0, "Source unit"] == "percent"
    assert rows.loc[0, "Currency"] == "%"
    assert rows.loc[0, "Value (millions)"] == 2.63
    assert len(rows) == 1
    assert "source_unit must be \"percent\"" in captured["json"]["messages"][1]["content"][0]["text"]
    assert "Extract ONLY the 2025 reporting year" in captured["json"]["messages"][1]["content"][0]["text"]


def test_analytical_ratios_leave_missing_inputs_visible():
    rows = demo_records("FWD_2025")
    ratios, gaps = analytical_ratio_rows(rows)
    assert "Insurance service margin" in set(ratios["Metric"])
    assert "New profitable contract CSM / PV inflows" in set(gaps["Ratio"])
    assert gaps["Status"].eq("Missing inputs").all()
