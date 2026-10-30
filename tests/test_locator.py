"""Page discovery must produce reviewable leads, never trusted page mappings."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
import requests
from streamlit.testing.v1 import AppTest

from hkifrs17.catalog import PILOT_FILINGS
from hkifrs17.locator import (
    _page_headings, _parse_candidates, contact_sheet_png, discovery_prompt,
    locate_model_pages, page_groups, parse_physical_pages,
)
from hkifrs17.source_templates import verified_pdf_page_leads
from hkifrs17.pdf import extract_model_page
from hkifrs17.extraction_plan import TABLE_METRICS
from hkifrs17.storage import ROOT
from hkifrs17 import storage


def _discovery_consent(app):
    return next(item for item in app.checkbox if item.label.startswith(
        ("Send first-60-page navigation summaries", "Send physical PDF pages")))


def _pdf(tmp_path: Path, count: int = 9) -> Path:
    path = tmp_path / "scanned.pdf"
    with fitz.open() as document:
        for number in range(1, count + 1):
            page = document.new_page()
            page.insert_text((60, 80), f"Note {number}: Insurance contract balances")
        document.save(path)
    return path


def test_contact_sheet_labels_physical_pages_and_range_validation(tmp_path):
    path = _pdf(tmp_path, 4)
    image = contact_sheet_png(path, [1, 3, 4])
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert page_groups(2, 9, 4) == [[2, 3, 4, 5], [6, 7, 8, 9]]
    assert page_groups(2, 4, 1) == [[2], [3], [4]]
    assert page_groups(2, 5, 2) == [[2, 3], [4, 5]]
    with pytest.raises(ValueError, match="outside the PDF"):
        contact_sheet_png(path, [5])


def test_exact_yf_pdf_still_requires_model_credentials():
    path = ROOT / "disclosures" / "pilot" / "YF_Life_FS_2025.pdf"
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    tables = ["Profit or loss", "Comprehensive income", "Investment result analysis",
              "Insurance and reinsurance contracts"]
    leads, covered = verified_pdf_page_leads(path, filing, 27, 133, tables)
    assert covered == set(tables)
    assert {(row["Physical PDF page"], row["Table"]) for row in leads} == {
        (27, "Profit or loss"), (28, "Comprehensive income"),
        *((page, "Investment result analysis") for page in (98, 99, 100, 101, 102)),
        *((page, "Insurance and reinsurance contracts")
          for page in (97, 119, 120, 121, 122, 123, 124, 125, 126, 127, 129, 130, 133)),
    }
    with pytest.raises(ValueError, match="model service URL"):
        locate_model_pages(path, filing, first=27, last=133, tables=tables,
                           base_url="", model="", api_key="")


def test_changed_pdf_never_inherits_checked_page_leads(tmp_path):
    path = _pdf(tmp_path, 9)
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    assert verified_pdf_page_leads(path, filing, 1, 9, ["Profit or loss"]) == ([], set())


def test_checked_source_pages_cover_all_step6_note_cells_in_three_pdfs():
    from hkifrs17.extraction_plan import TABLE_METRICS
    records = json.loads((ROOT / "data" /
                          "external_records.json").read_text(encoding="utf-8"))
    targets = ["Insurance and reinsurance contracts",
               "Financial investment classification",
               "Discount rates and illiquidity premiums"]
    for document_id, filename in (
        ("FWD_2025", "FWD_Bermuda_Audited_Financial_Statement_2025.pdf"),
        ("SUN_2025", "slhk-fs-2025.pdf"),
        ("YF_2025", "YF_Life_FS_2025.pdf"),
    ):
        filing = next(item for item in PILOT_FILINGS if item["document_id"] == document_id)
        path = ROOT / "disclosures" / "pilot" / filename
        leads, covered = verified_pdf_page_leads(path, filing, 1, 200, targets)
        assert covered == set(targets)
        for target in targets:
            reviewed_pages = {
                int(row["PDF page"]) for row in records
                if row["Document ID"] == document_id and row.get("PDF page")
                and row["Metric code"] in TABLE_METRICS[target]
            }
            lead_pages = {row["Physical PDF page"] for row in leads
                          if row["Table"] == target}
            assert reviewed_pages <= lead_pages, (document_id, target,
                                                   reviewed_pages - lead_pages)


def test_manual_page_review_accepts_multiple_pages_and_reports_invalid_entries():
    assert parse_physical_pages("26, 27, 26，28", 100) == ([26, 27, 28], [])
    assert parse_physical_pages("0, 101, p.5, 3", 100) == ([3], ["0", "101", "p.5"])


def test_step1_starts_with_model_location_without_duplicate_page_browsers():
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app_pages" / "01_extract.py"),
                            default_timeout=30).run()
    assert not app.exception
    assert not any(item.label == "Chart-driven indicator and source-table map"
                   for item in app.expander)
    assert not any("Select report-level tables. Insurance/reinsurance" in item.value
                   for item in app.caption)
    assert not app.toggle
    assert not any(item.type == "image" for item in app._tree)
    assert next(item for item in app.button if item.label == "Locate candidate pages")
    assert not any(item.label == "Extract all confirmed tables" for item in app.button)
    assert next(item for item in app.number_input if item.label == "First physical PDF page to scan").value == 27
    targets = next(item for item in app.multiselect if item.label == "Source tables to locate").options
    assert "Insurance and reinsurance contracts" in targets
    assert "Insurance service expenses" not in targets
    assert "Initially recognised insurance contracts" not in targets
    assert "Discount rates and illiquidity premiums" in targets
    assert "Discount rates · HKD" not in targets


def test_step1_exact_yf_pdf_requires_model_page_send_confirmation():
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app_pages" / "01_extract.py"),
                            default_timeout=30).run()
    selector = next(item for item in app.multiselect if item.label == "Source tables to locate")
    selector.set_value(list(selector.options)).run()
    assert not app.exception
    assert next(item for item in app.button
                if item.label == "Locate candidate pages").disabled
    assert _discovery_consent(app)


def test_unreviewed_pdf_still_requires_model_page_send_confirmation():
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app_pages" / "01_extract.py"),
                            default_timeout=30).run()
    next(item for item in app.selectbox if item.label == "Filing").set_value("CTF_2025").run()
    next(item for item in app.multiselect if item.label == "Source tables to locate").set_value(
        ["Profit or loss"]).run()
    assert not app.exception
    assert next(item for item in app.button
                if item.label == "Locate candidate pages").disabled
    consent = _discovery_consent(app)
    consent.check().run()
    assert not next(item for item in app.button
                    if item.label == "Locate candidate pages").disabled


def test_model_page_location_filters_hallucinated_pages_and_table_names(tmp_path, monkeypatch):
    path = _pdf(tmp_path)
    seen = []

    class Response:
        def __init__(self, content):
            self.content = [
                {"year_evidence": "2025 column", "scope_evidence": "Group column", **item}
                for item in content
            ]

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"candidates": self.content})}}]}

    replies = [
        Response([
            {"physical_page": 3, "table": "Insurance contract balances", "evidence": "Insurance contracts 2025", "confidence": "High",
             "source_section": "financial_statements", "section_evidence": "Note 22 insurance contracts"},
            {"physical_page": 4, "table": "Insurance contract balances", "evidence": "Business Review insurance 2025",
             "source_section": "other", "section_evidence": "Business Review"},
            {"physical_page": 6, "table": "Insurance contract balances", "evidence": "Not in this image",
             "source_section": "financial_statements", "section_evidence": "Note 22 insurance contracts"},
            {"physical_page": 4, "table": "Made up table", "evidence": "Not requested",
             "source_section": "financial_statements", "section_evidence": "Note 22 insurance contracts"},
            {"physical_page": 5, "table": "Insurance contract balances", "evidence": "",
             "source_section": "financial_statements", "section_evidence": "Note 22 insurance contracts"},
        ]),
        Response([{ "physical_page": 6, "table": "Insurance contract balances",
                    "evidence": "Insurance contract liabilities 2025", "confidence": "Medium",
                    "source_section": "financial_statements", "section_evidence": "Note 22 insurance contracts"}]),
    ]

    def post(url, **kwargs):
        seen.append((url, kwargs))
        return replies.pop(0)

    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    candidates, failures = locate_model_pages(
        path, {**PILOT_FILINGS[0], "page_profit": 1}, first=2, last=9,
        tables=["Insurance contract balances"],
        base_url="https://api.moonshot.cn/v1", model="kimi-k2.6", api_key="test-key",
        pages_per_image=4,
    )
    assert failures == []
    assert [item["Physical PDF page"] for item in candidates] == [3, 6]
    assert len(seen) == 2
    assert seen[0][0].endswith("/v1/chat/completions")
    assert seen[0][1]["json"]["thinking"] == {"type": "disabled"}
    assert seen[0][1]["timeout"] == (10, 300)
    assert seen[0][1]["json"]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_yf_wrong_table_and_company_scope_leads_are_filtered_but_comparative_is_kept():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")

    def lead(page, table, evidence, section, *, year="2025 column", scope="Group total column"):
        return {
            "physical_page": page, "table": table, "source_section": "financial_statements",
            "section_evidence": section, "year_evidence": year,
            "scope_evidence": scope, "evidence": evidence, "confidence": "High",
        }

    candidates = [
        lead(72, "Financial investment classification", "Credit quality analysis: investment grade FVOCI", "Note 3 Financial risk management"),
        lead(73, "Financial investment classification", "Financial investments: non-investment grade", "Note 3 Credit quality"),
        lead(113, "Financial investment classification", "Financial investments: AC, FVOCI, FVPL and Total", "Note 19 Investments and derivatives"),
        lead(100, "Investment result analysis", "Other investment revenue continued", "Note 6 Net financial result"),
        lead(98, "Investment result analysis", "Net financial result; investment return total", "Note 6 Net financial result"),
        lead(98, "Insurance and reinsurance contracts", "Net financial result", "Note 6 Net financial result"),
        lead(124, "Insurance and reinsurance contracts", "Reinsurance contracts: 2025 movement total", "Note 22 Insurance and reinsurance contracts"),
        lead(125, "Insurance and reinsurance contracts", "Reinsurance contracts: comparative movement", "Note 22 Insurance and reinsurance contracts", year="2024 column"),
        lead(128, "Insurance and reinsurance contracts", "Assets for insurance acquisition cash flows", "Note 22 Insurance and reinsurance contracts"),
        lead(141, "Equity movement", "Capital and reserves: opening and closing", "Note 27 Capital and reserves", scope="The Company"),
        lead(31, "Equity movement", "Consolidated statement of changes in equity: opening and closing", "Consolidated statement of changes in equity"),
    ]
    found = _parse_candidates(
        json.dumps({"candidates": candidates}),
        [31, 72, 73, 98, 100, 113, 124, 125, 128, 141],
        ["Equity movement", "Investment result analysis", "Financial investment classification",
         "Insurance and reinsurance contracts"], filing,
    )
    assert {(item["Physical PDF page"], item["Table"]) for item in found} == {
        (31, "Equity movement"), (98, "Investment result analysis"), (100, "Investment result analysis"),
        (113, "Financial investment classification"),
        (124, "Insurance and reinsurance contracts"), (125, "Insurance and reinsurance contracts"),
    }


def test_page_lead_needs_either_filing_year_and_table_scope_evidence():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    base = {"physical_page": 113, "table": "Financial investment classification",
            "source_section": "financial_statements", "section_evidence": "Note 19 Investments and derivatives",
            "evidence": "Financial investments, AC, FVOCI and FVPL total",
            "year_evidence": "2025 column", "scope_evidence": "Group total column"}
    variants = [{**base, "year_evidence": "Financial statements for the year ended 2025"},
                {**base, "scope_evidence": "The Company"},
                {**base, "year_evidence": "2023 column"}]
    assert _parse_candidates(json.dumps({"candidates": variants}), [113],
                             ["Financial investment classification"], filing) == []
    note_without_scope = _parse_candidates(
        json.dumps({"candidates": [{**base, "scope_evidence": ""}]}), [113],
        ["Financial investment classification"], filing,
    )
    assert len(note_without_scope) == 1
    assert note_without_scope[0]["Confidence"] == "Medium"
    comparative = _parse_candidates(
        json.dumps({"candidates": [{**base, "year_evidence": "2024 column"}]}),
        [113], ["Financial investment classification"], filing,
    )
    assert comparative[0]["Table years"] == "2024"


def test_yf_note6_main_result_rows_are_not_lost_to_short_evidence():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    def lead(page, evidence):
        return {"physical_page": page, "table": "Investment result analysis",
                "source_section": "notes_to_financial_statements",
                "section_evidence": "Note 6 Net financial result",
                "year_evidence": "2025 column", "scope_evidence": "",
                "evidence": evidence, "confidence": "High"}
    found = _parse_candidates(json.dumps({"candidates": [
        lead(98, "Interest income; total investment return 2025"),
        lead(99, "Net financial result, insurance finance expenses 2025"),
        lead(100, "Other investment revenue continued 2025"),
    ]}), [98, 99, 100], ["Investment result analysis"], filing)
    assert [row["Physical PDF page"] for row in found] == [98, 99, 100]
    assert all(row["Confidence"] == "Medium" for row in found)


def test_page_map_carries_note_heading_to_next_image_without_becoming_evidence():
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    response = {"page_map": [
        {"physical_page": 98, "visible_heading": "Note 6 Net financial result"},
        {"physical_page": 100, "visible_heading": "Note 6 continued"},
    ], "candidates": []}
    headings = _page_headings(json.dumps(response), [97, 98])
    assert headings == ["p98: Note 6 Net financial result"]
    prompt = discovery_prompt(filing, [99, 100], ["Investment result analysis"],
                              "KPMG", headings)
    assert "p98: Note 6 Net financial result" in prompt
    assert "navigation clues only" in prompt


def test_discovery_uses_prior_image_heading_for_continuation(tmp_path, monkeypatch):
    path = _pdf(tmp_path, 4)
    filing = {**next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025"),
              "page_profit": 1}
    prompts = []
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}
    replies = [
        Response({"page_map": [{"physical_page": 2,
                                "visible_heading": "Note 6 Net financial result"}],
                  "candidates": []}),
        Response({"page_map": [], "candidates": []}),
    ]
    def post(url, **kwargs):
        prompts.append(kwargs["json"]["messages"][1]["content"][0]["text"])
        return replies.pop(0)
    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    candidates, failures = locate_model_pages(
        path, filing, first=1, last=4, tables=["Investment result analysis"],
        base_url="https://api.moonshot.cn/v1", model="kimi-k2.6", api_key="test-key",
        pages_per_image=2,
    )
    assert candidates == failures == []
    assert "p2: Note 6 Net financial result" in prompts[1]


def test_full_page_check_rejects_false_lead_and_recovers_heading_lead(tmp_path, monkeypatch):
    from threading import Barrier

    path = _pdf(tmp_path, 2)
    focused_barrier = Barrier(2)
    filing = {**next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025"),
              "page_profit": 1}
    def lead(page, year):
        return {"physical_page": page, "table": "Investment result analysis",
                "source_section": "notes_to_financial_statements",
                "section_evidence": "Note 7 Net financial result",
                "year_evidence": f"{year} table column", "scope_evidence": "Group",
                "evidence": "Interest income and net financial result total",
                "confidence": "High"}
    first_pass = {"page_map": [
        {"physical_page": 1, "visible_heading": "Note 7 Net financial result"},
        {"physical_page": 2, "visible_heading": "Note 7 Net financial result continued"}],
        "candidates": [lead(1, 2025)]}
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}
    def post(url, **kwargs):
        prompt = kwargs["json"]["messages"][1]["content"][0]["text"]
        if "FINAL SINGLE-PAGE CHECK" not in prompt:
            return Response(first_pass)
        focused_barrier.wait(timeout=5)
        return Response({"candidates": [lead(2, 2025)]}
                        if "physical PDF pages [2]" in prompt else {"candidates": []})
    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    found, failures = locate_model_pages(
        path, filing, first=1, last=2, tables=["Investment result analysis"],
        base_url="https://example.com/v1", model="another-vision-model",
        api_key="test", pages_per_image=2, verify_pages=True,
    )
    assert failures == []
    assert [(row["Physical PDF page"], row["Table"]) for row in found] == [
        (2, "Investment result analysis")]


def test_contract_page_is_classified_before_metric_extraction(tmp_path, monkeypatch):
    path = _pdf(tmp_path, 1)
    filing = {**next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025"),
              "page_profit": 1}
    prompts = []
    replies = [
        {"visible_tables": ["Insurance non-PAA remaining/incurred movement"],
         "table_heading": "Insurance contracts not measured under PAA",
         "year_evidence": "2025 table column", "scope_evidence": "Group"},
        {"records": []},
    ]
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}
    def post(url, **kwargs):
        prompts.append(kwargs["json"]["messages"][1]["content"][0]["text"])
        return Response(replies.pop(0))
    monkeypatch.setattr("hkifrs17.pdf.requests.post", post)
    result = extract_model_page(
        path, filing, 1, PILOT_FILINGS, base_url="https://example.com/v1",
        model="another-vision-model", api_key="test",
        metric_codes=set(TABLE_METRICS["Insurance and reinsurance contracts"]),
        table_names=["Insurance and reinsurance contracts"],
    )
    assert result.empty
    assert len(prompts) == 2
    assert "INS_NONPAA_NET_OPEN" in prompts[1]
    assert "REINS_NONPAA_NET_OPEN" not in prompts[1]


def test_yf_front_matter_is_not_a_candidate_even_if_model_misclassifies_it(tmp_path, monkeypatch):
    path = _pdf(tmp_path, 4)

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"candidates": [{
                "physical_page": 3, "table": "Insurance revenue note",
                "source_section": "financial_statements",
                "section_evidence": "Note 5 insurance revenue",
                "year_evidence": "2025 column",
                "scope_evidence": "Group column",
                "evidence": "Insurance revenue 2025", "confidence": "High",
            }]})}}]}

    monkeypatch.setattr("hkifrs17.locator.requests.post", lambda *args, **kwargs: Response())
    candidates, failures = locate_model_pages(
        path, PILOT_FILINGS[0], first=1, last=4, tables=["Insurance revenue note"],
        base_url="https://api.example.org/v1", model="vision", api_key="test-key",
        pages_per_image=4,
    )
    assert candidates == []
    assert failures == []


def test_failed_discovery_group_is_reported_without_retry(tmp_path, monkeypatch):
    path = _pdf(tmp_path, 4)
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        raise requests.exceptions.ReadTimeout("model did not respond")

    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    candidates, failures = locate_model_pages(
        path, PILOT_FILINGS[0], first=1, last=4, tables=["Insurance revenue note"],
        base_url="https://api.example.org/v1", model="vision", api_key="test-key",
        pages_per_image=4,
    )
    assert candidates == []
    assert len(failures) == len(calls) == 1
    assert "PDF pages 1–4" in failures[0]


def test_candidate_needs_original_page_confirmation_before_extraction(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app_pages" / "01_extract.py"),
                            default_timeout=30).run()
    next(item for item in app.multiselect if item.label == "Source tables to locate").set_value(
        ["Insurance and reinsurance contracts"]).run()
    next(item for item in app.text_input if item.label == "Vision model").set_value("fake-vision")
    next(item for item in app.text_input if item.label == "API key").set_value("fake-key")
    next(item for item in app.number_input if item.label == "First physical PDF page to scan").set_value(97)
    next(item for item in app.number_input if item.label == "Last physical PDF page to scan").set_value(99)
    app.run()
    candidate = {"Physical PDF page": 97, "Table": "Insurance and reinsurance contracts",
                 "Visible evidence": "Note 5 Insurance revenue", "Confidence": "High"}
    from unittest.mock import patch
    def legacy_locator(path, filing, *, first, last, tables, base_url, model, api_key,
                       pages_per_image, fast_kimi, read_timeout, progress, diagnostics, verify_pages, use_text_navigation, status):
        assert verify_pages
        assert filing["auditor_template"] == "KPMG"
        return [candidate], []

    _discovery_consent(app).check().run()
    with patch("hkifrs17.locator.locate_model_pages", side_effect=legacy_locator):
        next(item for item in app.button if item.label == "Locate candidate pages").click().run()
    assert not app.exception
    assert app.session_state["confirmed_discovery_v11_YF_2025"] == []
    assert storage.load_confirmed_pages("YF_2025", storage.pdf_path(storage.filing_by_id("YF_2025"))) == []
    next(item for item in app.button if item.label == "Confirm all reviewed table pages").click().run()
    assert not app.exception
    assert (97, "Insurance and reinsurance contracts") in app.session_state["confirmed_discovery_v11_YF_2025"]
    assert (97, "Insurance and reinsurance contracts") in storage.load_confirmed_pages(
        "YF_2025", storage.pdf_path(storage.filing_by_id("YF_2025")))


def test_one_confirmation_adds_all_reviewed_table_pages_to_extraction(tmp_path, monkeypatch):
    from unittest.mock import patch
    monkeypatch.setattr(storage, "DATA", tmp_path)

    app = AppTest.from_file(str(Path(__file__).parents[1] / "app_pages" / "01_extract.py"),
                            default_timeout=30).run()
    next(item for item in app.multiselect if item.label == "Source tables to locate").set_value(
        ["Profit or loss"]).run()
    next(item for item in app.text_input if item.label == "Vision model").set_value("fake-vision")
    next(item for item in app.text_input if item.label == "API key").set_value("fake-key")
    next(item for item in app.number_input if item.label == "First physical PDF page to scan").set_value(97)
    next(item for item in app.number_input if item.label == "Last physical PDF page to scan").set_value(99)
    app.run()
    first_candidate = {"Physical PDF page": 97, "Table": "Profit or loss",
                       "Visible evidence": "Statement of profit or loss", "Confidence": "High"}
    _discovery_consent(app).check().run()
    with patch("hkifrs17.locator.locate_model_pages", return_value=([first_candidate], [])):
        next(item for item in app.button if item.label == "Locate candidate pages").click().run()
    next(item for item in app.multiselect if item.label == "Source tables to locate").set_value(
        ["Profit or loss", "Insurance and reinsurance contracts"]).run()
    second_candidate = {"Physical PDF page": 99, "Table": "Insurance and reinsurance contracts",
                        "Visible evidence": "Note 5 insurance revenue", "Confidence": "Medium"}
    _discovery_consent(app).check().run()
    with patch("hkifrs17.locator.locate_model_pages", return_value=([second_candidate], [])):
        next(item for item in app.button if item.label == "Locate candidate pages").click().run()
    assert not app.exception
    assert any(item.label == "Choose a table to preview" for item in app.selectbox)
    next(item for item in app.text_input if item.label == "Profit or loss").set_value("97, 98")
    app.run()
    next(item for item in app.button if item.label == "Confirm all reviewed table pages").click().run()
    assert not app.exception
    selected = set(map(tuple, app.session_state["confirmed_discovery_v11_YF_2025"]))
    assert {(97, "Profit or loss"), (98, "Profit or loss"),
            (99, "Insurance and reinsurance contracts")} <= selected
    saved = set(storage.load_confirmed_pages("YF_2025", storage.pdf_path(storage.filing_by_id("YF_2025"))))
    assert {(97, "Profit or loss"), (98, "Profit or loss"),
            (99, "Insurance and reinsurance contracts")} <= saved
    next(item for item in app.text_input if item.label == "Profit or loss").set_value("97, 98, 96")
    app.run()
    assert set(storage.load_confirmed_pages("YF_2025", storage.pdf_path(storage.filing_by_id("YF_2025")))) == saved


