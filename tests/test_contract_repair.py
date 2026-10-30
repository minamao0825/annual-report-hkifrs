"""YF 2025 scanned-note discovery and extraction regressions."""

import json
import re

import fitz
import pytest

from hkifrs17.catalog import PILOT_FILINGS
from hkifrs17.extraction_plan import TABLE_METRICS
from hkifrs17.locator import _parse_candidates, locate_model_pages
from hkifrs17.ocr_index import OCRIndex
from hkifrs17.page_radar import Experience, Lead, Navigation
from hkifrs17.pdf import _contract_page_families, extract_model_page
from hkifrs17.source_templates import verified_comparative_only_pages, verified_contract_subtables
from hkifrs17.storage import pdf_path


YF = next(filing for filing in PILOT_FILINGS if filing["document_id"] == "YF_2025")
CONTRACT = "Insurance and reinsurance contracts"


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}


def test_exact_yf_keeps_both_years_and_checks_contract_pages_singly(monkeypatch):
    leads = tuple(Lead(n, CONTRACT, "OCR note clue", "Contract movement", "Consolidated")
                  for n in (119, 120, 121, 122, 123))
    plan = Navigation("YF current-file titles", leads, (), 147, (), "Consolidated",
                      "Audited main statement", Experience(), ocr_pages=147)
    monkeypatch.setattr("hkifrs17.discovery_runtime.build_navigation", lambda *a, **kw: plan)
    monkeypatch.setattr("hkifrs17.locator.contact_sheet_png", lambda *a, **kw: b"page image")
    sent_pages = []

    def post(_url, **kwargs):
        content = kwargs["json"]["messages"][1]["content"]
        if isinstance(content, str):
            return Response({"navigation": [
                {"physical_page": 121, "table": CONTRACT},
                {"physical_page": 123, "table": CONTRACT},
            ]})
        prompt = content[0]["text"]
        pages = json.loads(re.search(r"physical PDF pages (\[[^]]+\])", prompt)[1])
        sent_pages.extend(pages)
        assert len(pages) == 1
        return Response({"candidates": [{
            "physical_page": page, "table": CONTRACT,
            "source_section": "notes_to_financial_statements",
            "section_evidence": "22 Insurance and reinsurance contracts",
            "year_evidence": f"{2024 if page in {121, 123, 125, 127} else 2025} table heading",
            "scope_evidence": "Consolidated",
            "evidence": "Insurance contract net closing balance and CSM",
        } for page in pages]})

    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    found, failures = locate_model_pages(
        pdf_path(YF), YF, first=27, last=147, tables=[CONTRACT],
        base_url="https://example.com/v1", model="test", api_key="test",
        pages_per_image=2, verify_pages=True,
    )
    assert failures == []
    assert {row["Physical PDF page"] for row in found} == {
        97, 119, 120, 121, 122, 123, 124, 125, 126, 127, 129, 130, 133,
    }
    assert {121, 123, 125, 127} <= set(sent_pages)
    assert {row["Physical PDF page"] for row in found if row["Table years"] == "2024"} >= {121, 123, 125, 127}


def test_exact_yf_comparative_contract_page_can_be_extracted(monkeypatch):
    assert verified_comparative_only_pages(pdf_path(YF), YF) == {121, 123, 125, 127}
    sent = []
    def post(_url, **kwargs):
        sent.append(kwargs["json"])
        return Response({"records": [{
            "metric_code": "INS_GROSS_OPEN", "period_end": "2024-12-31",
            "original_value": 321, "source_unit": "HKD",
            "source_label": "Insurance contracts | 2024 | opening Total",
            "table_year": "2024", "column_heading": "Total", "unit_evidence": "$",
        }, {
            "metric_code": "INS_GROSS_OPEN", "period_end": "2025-12-31",
            "original_value": 999, "source_unit": "HKD",
            "source_label": "Wrongly assigned year | 2025 | Total",
            "table_year": "2025", "column_heading": "Total", "unit_evidence": "$",
        }]})
    monkeypatch.setattr("hkifrs17.pdf.requests.post", post)
    frame = extract_model_page(pdf_path(YF), YF, 121, PILOT_FILINGS,
                               base_url="https://example.com/v1", model="test", api_key="test",
                               metric_codes=set(TABLE_METRICS[CONTRACT]), table_names=[CONTRACT])
    assert len(sent) == 1
    assert list(frame["Period end"]) == ["2024-12-31"]
    assert list(frame["PDF page"]) == [121]


def test_reviewed_yf_contract_page_uses_checked_subtables_in_one_request(monkeypatch):
    assert "Insurance non-PAA remaining/incurred movement" in verified_contract_subtables(pdf_path(YF), YF, 120)
    sent = []

    def post(_url, **kwargs):
        sent.append(kwargs["json"])
        prompt = kwargs["json"]["messages"][1]["content"][0]["text"]
        assert "INS_GROSS_OPEN" in prompt
        assert "REINS_NONPAA_NET_OPEN" not in prompt
        assert "only year(s) 2025" in prompt
        return Response({"records": [{
            "metric_code": "INS_GROSS_OPEN", "period_end": "2025-12-31",
            "original_value": 123, "source_unit": "HKD",
            "source_label": "Insurance contracts | 2025 | opening Total",
            "table_year": "2025", "column_heading": "Total", "unit_evidence": "$",
        }]})

    monkeypatch.setattr("hkifrs17.pdf.requests.post", post)
    frame = extract_model_page(pdf_path(YF), YF, 120, PILOT_FILINGS,
                               base_url="https://example.com/v1", model="test", api_key="test",
                               metric_codes=set(TABLE_METRICS[CONTRACT]), table_names=[CONTRACT])
    assert len(sent) == 1
    assert list(frame["Metric code"]) == ["INS_GROSS_OPEN"]


@pytest.mark.parametrize("page,code,amount", [
    (122, "INS_CSM_FV_OPEN", 6975446400),
    (126, "REINS_CSM_FV_OPEN", 841019532),
])
def test_split_csm_opening_columns_are_mapped_without_generic_total(monkeypatch, page, code, amount):
    sent = []

    def post(_url, **kwargs):
        sent.append(kwargs["json"])
        prompt = kwargs["json"]["messages"][1]["content"][0]["text"]
        assert code in prompt
        assert "omit CSM_OPEN, CSM_CLOSE" in prompt
        assert "A Total column for all measurement components is not a CSM subtotal" in prompt
        return Response({"records": [{
            "metric_code": code, "period_end": "2025-12-31",
            "original_value": amount, "source_unit": "HKD",
            "source_label": "Net opening balance | CSM fair value transition | 2025 | "
                            + ("Reinsurance" if code.startswith("REINS") else "Insurance"),
            "table_year": "2025", "column_heading": "CSM | fair value transition",
            "unit_evidence": "$",
        }]})

    monkeypatch.setattr("hkifrs17.pdf.requests.post", post)
    frame = extract_model_page(pdf_path(YF), YF, page, PILOT_FILINGS,
                               base_url="https://example.com/v1", model="test", api_key="test",
                               metric_codes=set(TABLE_METRICS[CONTRACT]), table_names=[CONTRACT])
    assert len(sent) == 1
    assert list(frame["Metric code"]) == [code]
    assert frame.iloc[0]["Original value"] == amount


def test_contract_header_crop_and_local_table_year_rescue(monkeypatch, tmp_path):
    path = tmp_path / "blank.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    seen = []
    def post(_url, **kwargs):
        seen.append(kwargs["json"]["messages"][1]["content"])
        return Response({"visible_tables": ["Insurance non-PAA remaining/incurred movement"],
                         "year_evidence": "Financial statements for the year ended 2025",
                         "scope_evidence": "Consolidated"})
    monkeypatch.setattr("hkifrs17.pdf.requests.post", post)
    monkeypatch.setattr("hkifrs17.ocr_index.scanned_text_index", lambda *a, **kw:
                        OCRIndex(((1, "Financial statements for 2025\n" + "heading\n" * 5 + "2025"),)))
    selected = _contract_page_families("full", YF, header_image="zoom", page_path=path,
                                       page_number=1, base_url="https://example.com/v1",
                                       model="test", api_key="test", fast_kimi=False,
                                       read_timeout=120)
    assert selected == ["Insurance non-PAA remaining/incurred movement"]
    assert len(seen[0]) == 3  # Prompt, full original page, magnified table header.
    monkeypatch.setattr("hkifrs17.ocr_index.scanned_text_index", lambda *a, **kw:
                        OCRIndex(((1, "Financial statements for 2025\n" + "heading\n" * 5 + "2024"),)))
    assert _contract_page_families("full", YF, header_image="zoom", page_path=path,
                                   page_number=1, base_url="https://example.com/v1",
                                   model="test", api_key="test", fast_kimi=False,
                                   read_timeout=120) == ["Insurance non-PAA remaining/incurred movement"]
    monkeypatch.setattr("hkifrs17.ocr_index.scanned_text_index", lambda *a, **kw:
                        OCRIndex(((1, "Financial statements for 2025\n" + "heading\n" * 5 + "2023"),)))
    with pytest.raises(ValueError, match="no reporting/comparative-year table heading"):
        _contract_page_families("full", YF, header_image="zoom", page_path=path,
                                page_number=1, base_url="https://example.com/v1",
                                model="test", api_key="test", fast_kimi=False,
                                read_timeout=120)


def test_duplicate_metric_drops_only_ambiguous_code(monkeypatch, tmp_path):
    path = tmp_path / "blank.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    def record(code, amount, label):
        return {"metric_code": code, "period_end": "2025-12-31",
                "original_value": amount, "source_unit": "HKD",
                "source_label": label, "table_year": "2025",
                "column_heading": "2025 | Total", "unit_evidence": "$"}
    payload = {"records": [record("OTHER_REVENUE", 20489282, "Investment management services | 2025"),
                           record("OTHER_REVENUE", 46138565, "Other income | 2025"),
                           record("PROFIT", 5000000, "Profit for the year | 2025")]}
    monkeypatch.setattr("hkifrs17.pdf.requests.post", lambda *a, **kw: Response(payload))
    frame = extract_model_page(path, YF, 1, PILOT_FILINGS,
                               base_url="https://example.com/v1", model="test", api_key="test",
                               metric_codes={"OTHER_REVENUE", "PROFIT"}, table_names=["Profit or loss"])
    assert list(frame["Metric code"]) == ["PROFIT"]
    assert "OTHER_REVENUE" in frame.iloc[0]["Reviewer note"]


def test_same_sun_2025_company_filing_yields_two_comparable_periods(monkeypatch, tmp_path):
    sun = next(filing for filing in PILOT_FILINGS if filing["document_id"] == "SUN_2025")
    path = tmp_path / "two_years.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(path)
    lead = {"physical_page": 1, "table": "Profit or loss",
            "source_section": "financial_statements",
            "section_evidence": "Statement of profit or loss",
            "year_evidence": "2024 comparative column", "scope_evidence": "Company column",
            "evidence": "Profit for the year"}
    found = _parse_candidates(json.dumps({"candidates": [lead]}), [1], ["Profit or loss"], sun)
    assert found[0]["Table years"] == "2024"
    assert _parse_candidates(json.dumps({"candidates": [
        {**lead, "scope_evidence": "Consolidated Group column"}]}), [1], ["Profit or loss"], sun) == []

    def post(_url, **kwargs):
        prompt = kwargs["json"]["messages"][1]["content"][0]["text"]
        assert "2025-12-31" in prompt and "2024-12-31" in prompt
        return Response({"records": [
            {"metric_code": "PROFIT", "period_end": "2025-12-31", "original_value": 100,
             "source_unit": "HKD millions", "source_label": "Profit for the year | 2025 Company",
             "table_year": "2025", "column_heading": "2025 | Company", "unit_evidence": "HK$ million"},
            {"metric_code": "PROFIT", "period_end": "2024-12-31", "original_value": 80,
             "source_unit": "HKD millions", "source_label": "Profit for the year | 2024 Company",
             "table_year": "2024", "column_heading": "2024 | Company", "unit_evidence": "HK$ million"},
        ]})

    monkeypatch.setattr("hkifrs17.pdf.requests.post", post)
    frame = extract_model_page(path, sun, 1, PILOT_FILINGS,
                               base_url="https://example.com/v1", model="test", api_key="test",
                               metric_codes={"PROFIT"}, table_names=["Profit or loss"])
    assert list(frame["Period end"]) == ["2025-12-31", "2024-12-31"]
    assert set(frame["Document ID"]) == {"SUN_2025"}
    assert set(frame["Scope"]) == {"Company"}


@pytest.mark.parametrize("page,code,amount", [
    (100, "INV_OTHER_REV_UNDERLYING_DESIGNATED", 56080988),
    (101, "INV_OTHER_REV_TOTAL", 3112110845),
    (102, "INV_IMPAIRMENT_TOTAL", -119359240),
])
def test_yf_investment_continuations_have_mapped_source_cells(monkeypatch, page, code, amount):
    assert code in TABLE_METRICS["Investment result analysis"]
    def post(_url, **kwargs):
        prompt = kwargs["json"]["messages"][1]["content"][0]["text"]
        assert code in prompt
        return Response({"records": [{"metric_code": code, "period_end": "2025-12-31",
                                      "original_value": amount, "source_unit": "HKD",
                                      "source_label": f"Note 6 printed row | 2025 | page {page}",
                                      "table_year": "2025", "column_heading": "2025 | Total",
                                      "unit_evidence": "$"}]})
    monkeypatch.setattr("hkifrs17.pdf.requests.post", post)
    frame = extract_model_page(pdf_path(YF), YF, page, PILOT_FILINGS,
                               base_url="https://example.com/v1", model="test", api_key="test",
                               metric_codes=set(TABLE_METRICS["Investment result analysis"]),
                               table_names=["Investment result analysis"])
    assert len(frame) == 1
    assert frame.iloc[0]["Metric code"] == code
    assert frame.iloc[0]["Original value"] == amount
