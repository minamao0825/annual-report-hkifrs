"""Page discovery must produce reviewable leads, never trusted page mappings."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
import requests
from streamlit.testing.v1 import AppTest

from hkifrs17.catalog import PILOT_FILINGS
from hkifrs17.locator import contact_sheet_png, locate_model_pages, page_groups, parse_physical_pages


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
    with pytest.raises(ValueError, match="outside the PDF"):
        contact_sheet_png(path, [5])


def test_manual_page_review_accepts_multiple_pages_and_reports_invalid_entries():
    assert parse_physical_pages("26, 27, 26，28", 100) == ([26, 27, 28], [])
    assert parse_physical_pages("0, 101, p.5, 3", 100) == ([3], ["0", "101", "p.5"])


def test_step1_starts_with_model_location_without_duplicate_page_browsers():
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app_pages" / "01_extract.py"),
                            default_timeout=30).run()
    assert not app.exception
    assert not app.toggle
    assert not any(item.type == "image" for item in app._tree)
    assert next(item for item in app.button if item.label == "Locate candidate pages")
    assert next(item for item in app.button if item.label == "Extract all confirmed tables").disabled


def test_model_page_location_filters_hallucinated_pages_and_table_names(tmp_path, monkeypatch):
    path = _pdf(tmp_path)
    seen = []

    class Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"candidates": self.content})}}]}

    replies = [
        Response([
            {"physical_page": 3, "table": "Insurance contract balances", "evidence": "Insurance contracts 2025", "confidence": "High"},
            {"physical_page": 6, "table": "Insurance contract balances", "evidence": "Not in this image"},
            {"physical_page": 4, "table": "Made up table", "evidence": "Not requested"},
            {"physical_page": 5, "table": "Insurance contract balances", "evidence": ""},
        ]),
        Response([{ "physical_page": 6, "table": "Insurance contract balances",
                    "evidence": "Insurance contract liabilities 2025", "confidence": "Medium"}]),
    ]

    def post(url, **kwargs):
        seen.append((url, kwargs))
        return replies.pop(0)

    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    candidates, failures = locate_model_pages(
        path, PILOT_FILINGS[0], first=2, last=9, tables=["Insurance contract balances"],
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


def test_candidate_needs_original_page_confirmation_before_extraction():
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app_pages" / "01_extract.py"),
                            default_timeout=30).run()
    next(item for item in app.selectbox if item.label == "Discovery focus").set_value(
        "Revenue, expense and investments").run()
    next(item for item in app.text_input if item.label == "Vision model").set_value("fake-vision")
    next(item for item in app.text_input if item.label == "API key").set_value("fake-key")
    next(item for item in app.number_input if item.label == "First physical PDF page to scan").set_value(97)
    next(item for item in app.number_input if item.label == "Last physical PDF page to scan").set_value(99)
    app.run()
    app.checkbox[0].check().run()
    candidate = {"Physical PDF page": 97, "Table": "Insurance revenue note",
                 "Visible evidence": "Note 5 Insurance revenue", "Confidence": "High"}
    from unittest.mock import patch
    with patch("hkifrs17.locator.locate_model_pages", return_value=([candidate], [])):
        next(item for item in app.button if item.label == "Locate candidate pages").click().run()
    assert not app.exception
    assert "confirmed_discovery_YF_2025" not in app.session_state
    assert next(item for item in app.button if item.label == "Extract all confirmed tables").disabled
    next(item for item in app.button if item.label == "Confirm all reviewed table pages").click().run()
    assert not app.exception
    assert (97, "Insurance revenue note") in app.session_state["confirmed_discovery_YF_2025"]
    assert next(item for item in app.button if item.label == "Extract all confirmed tables").disabled


def test_one_confirmation_adds_all_reviewed_table_pages_to_extraction():
    from unittest.mock import patch

    app = AppTest.from_file(str(Path(__file__).parents[1] / "app_pages" / "01_extract.py"),
                            default_timeout=30).run()
    next(item for item in app.text_input if item.label == "Vision model").set_value("fake-vision")
    next(item for item in app.text_input if item.label == "API key").set_value("fake-key")
    next(item for item in app.number_input if item.label == "First physical PDF page to scan").set_value(97)
    next(item for item in app.number_input if item.label == "Last physical PDF page to scan").set_value(99)
    app.run()
    app.checkbox[0].check().run()
    first_candidate = {"Physical PDF page": 97, "Table": "Profit or loss",
                       "Visible evidence": "Statement of profit or loss", "Confidence": "High"}
    with patch("hkifrs17.locator.locate_model_pages", return_value=([first_candidate], [])):
        next(item for item in app.button if item.label == "Locate candidate pages").click().run()
    next(item for item in app.selectbox if item.label == "Discovery focus").set_value(
        "Revenue, expense and investments").run()
    app.checkbox[0].check().run()
    second_candidate = {"Physical PDF page": 99, "Table": "Insurance revenue note",
                        "Visible evidence": "Note 5 insurance revenue", "Confidence": "Medium"}
    with patch("hkifrs17.locator.locate_model_pages", return_value=([second_candidate], [])):
        next(item for item in app.button if item.label == "Locate candidate pages").click().run()
    assert not app.exception
    assert any(item.label == "Choose a table to preview" for item in app.selectbox)
    next(item for item in app.text_input if item.label == "Profit or loss").set_value("97, 98")
    app.run()
    next(item for item in app.button if item.label == "Confirm all reviewed table pages").click().run()
    assert not app.exception
    selected = set(map(tuple, app.session_state["confirmed_discovery_YF_2025"]))
    assert {(97, "Profit or loss"), (98, "Profit or loss"), (99, "Insurance revenue note")} <= selected
    next(item for item in app.checkbox if item.label.startswith("Send all 3 confirmed table-page")).check().run()
    assert not next(item for item in app.button if item.label == "Extract all confirmed tables").disabled
    next(item for item in app.text_input if item.label == "Profit or loss").set_value("97, 98, 96")
    app.run()
    assert next(item for item in app.button if item.label == "Extract all confirmed tables").disabled
