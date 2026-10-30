"""Repeat extraction must stay idempotent and retain only source-backed cells."""

import json

import fitz
import pandas as pd

from hkifrs17.catalog import METRIC_BY_CODE, PILOT_FILINGS
from hkifrs17.data import COLUMNS
from hkifrs17.extraction_plan import TABLE_METRICS, merge_extracted
from hkifrs17.pdf import _row, extract_model_page, extraction_prompt
from hkifrs17.source_templates import VERIFIED_CONTRACT_SUBTABLES


YF = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")


class Response:
    def __init__(self, records):
        self.records = records

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": json.dumps({"records": self.records})}}]}


def _blank_pdf(tmp_path):
    path = tmp_path / "scanned.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    return path


def _record(code, amount, page, review="Pending"):
    row = _row(YF, code, "2025-12-31", amount, page, f"{code} | 2025", "HKD")
    row["Review status"] = review
    return row


def test_successful_retry_replaces_one_page_pending_set_only():
    current = pd.DataFrame([
        _record("PROFIT", 10, 27),
        _record("INS_REVENUE", 20, 27),
        _record("PBT", 30, 27, "Verified"),
        _record("TOTAL_ASSETS", 40, 29),
    ], columns=COLUMNS)
    incoming = pd.DataFrame([_record("PROFIT", 11, 27)], columns=COLUMNS)
    merged, counts = merge_extracted(current, incoming, source_task=(27, "Profit or loss"))
    assert set(merged["Metric code"]) == {"PROFIT", "PBT", "TOTAL_ASSETS"}
    assert merged.set_index("Metric code").at["PROFIT", "Original value"] == 11
    assert merged.set_index("Metric code").at["PBT", "Original value"] == 30
    assert counts == {"added": 0, "replaced_pending": 1,
                      "removed_pending": 1, "preserved": 0}
    repeated, repeat_counts = merge_extracted(merged, incoming, source_task=(27, "Profit or loss"))
    assert len(repeated) == len(merged)
    assert repeat_counts["added"] == repeat_counts["removed_pending"] == 0
    unchanged, _ = merge_extracted(merged, incoming.iloc[:0], source_task=(27, "Profit or loss"))
    pd.testing.assert_frame_equal(unchanged, merged)


def test_interest_eir_keeps_only_printed_total(monkeypatch, tmp_path):
    records = []
    for label, amount in [
        ("Financial assets measured at amortised cost", 1_807_281_529),
        ("Financial assets measured at fair value through other comprehensive income", 1_322_844_976),
        ("Total interest revenue calculated using effective interest method", 3_130_126_505),
    ]:
        records.append({"metric_code": "INV_INTEREST_EIR", "period_end": "2025-12-31",
                        "original_value": amount, "source_unit": "HKD",
                        "source_label": f"{label} | 2025 | Total",
                        "table_year": "2025", "column_heading": "2025 | Total",
                        "unit_evidence": "$"})
    monkeypatch.setattr("hkifrs17.pdf.requests.post", lambda *args, **kwargs: Response(records))
    result = extract_model_page(_blank_pdf(tmp_path), YF, 1, list(PILOT_FILINGS),
                                base_url="https://example.com/v1", model="vision", api_key="test",
                                metric_codes={"INV_INTEREST_EIR"},
                                table_names=["Investment result analysis"])
    assert len(result) == 1
    assert result.iloc[0]["Original value"] == 3_130_126_505
    assert "ONLY the row explicitly labelled Total interest revenue" in extraction_prompt(
        YF, [METRIC_BY_CODE["INV_INTEREST_EIR"]], ["Investment result analysis"])


def test_mixed_reinsurance_page_exposes_all_method_total_metrics(monkeypatch, tmp_path):
    from hkifrs17 import source_templates

    families = VERIFIED_CONTRACT_SUBTABLES["YF_2025"][124]
    assert "Reinsurance net movement" in families
    assert "Reinsurance contract balances" in families
    monkeypatch.setattr(source_templates, "verified_contract_subtables",
                        lambda path, filing, page: families)
    monkeypatch.setattr(source_templates, "verified_contract_years_map",
                        lambda path, filing: {1: ("2025",)})
    records = [
        {"metric_code": "REINS_NOTE_PL_OCI", "period_end": "2025-12-31",
         "original_value": 555_482_860, "source_unit": "HKD",
         "source_label": "Total changes in the statement of profit or loss and OCI | 2025 | Total",
         "table_year": "2025", "column_heading": "2025 | Total", "unit_evidence": "$"},
        {"metric_code": "REINS_ASSETS_NOTE_CLOSE", "period_end": "2025-12-31",
         "original_value": 7_482_492_186, "source_unit": "HKD",
         "source_label": "Closing assets | 2025 | Total | Reinsurance contracts",
         "table_year": "2025", "column_heading": "2025 | Total", "unit_evidence": "$"},
    ]
    monkeypatch.setattr("hkifrs17.pdf.requests.post", lambda *args, **kwargs: Response(records))
    result = extract_model_page(_blank_pdf(tmp_path), YF, 1, list(PILOT_FILINGS),
                                base_url="https://example.com/v1", model="vision", api_key="test",
                                metric_codes=set(TABLE_METRICS["Insurance and reinsurance contracts"]),
                                table_names=["Insurance and reinsurance contracts"])
    assert set(result["Metric code"]) == {"REINS_NOTE_PL_OCI", "REINS_ASSETS_NOTE_CLOSE"}
