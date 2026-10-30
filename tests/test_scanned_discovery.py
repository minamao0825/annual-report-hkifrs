"""Real YF scan regressions and bounded, non-serial model request scheduling."""

import json
from pathlib import Path
import re
from threading import Barrier, Lock

import fitz
import pytest

from hkifrs17.catalog import PILOT_FILINGS
from hkifrs17.locator import _parse_candidates, locate_model_pages
from hkifrs17.ocr_index import OCRIndex, scanned_text_index
from hkifrs17.page_radar import Experience, Lead, Navigation, build_navigation, saved_experience
from hkifrs17.source_templates import verified_table_options
from hkifrs17.storage import ROOT, pdf_path


YF = next(row for row in PILOT_FILINGS if row["document_id"] == "YF_2025")


def candidate(page, table, evidence, section, year="2025", scope=""):
    return {"physical_page": page, "table": table, "evidence": evidence,
            "section_evidence": section, "source_section": "notes_to_financial_statements",
            "year_evidence": year, "scope_evidence": scope, "confidence": "High"}


def test_exact_four_digit_year_and_consolidated_cash_flow_heading_are_valid():
    row = candidate(32, "Cash flows", "Cash flows from operating activities; Net cash from operating activities",
                    "Consolidated statement of cash flows")
    found = _parse_candidates(json.dumps({"candidates": [row]}), [32], ["Cash flows"], YF)
    assert len(found) == 1
    assert found[0]["Reporting-year evidence"] == "2025"
    assert "Consolidated" in found[0]["Scope evidence"]
    row["year_evidence"] = "2024"
    comparative = _parse_candidates(json.dumps({"candidates": [row]}), [32], ["Cash flows"], YF)
    assert len(comparative) == 1
    assert comparative[0]["Table years"] == "2024"
    row["year_evidence"] = "2023"
    rejected = []
    assert _parse_candidates(json.dumps({"candidates": [row]}), [32], ["Cash flows"], YF, rejected) == []
    assert "report/comparative-year" in rejected[0]["reason"]


def test_numbered_note_without_word_note_retains_scope_confirmation():
    row = candidate(120, "Insurance and reinsurance contracts",
                    "Analysis by remaining coverage and incurred claims; net closing balance",
                    "22 Insurance and reinsurance contracts (continued)")
    found = _parse_candidates(json.dumps({"candidates": [row]}), [120], [row["table"]], YF)
    assert len(found) == 1
    assert found[0]["Confidence"] == "Medium"
    assert "confirm filing scope" in found[0]["Scope evidence"]


def test_yf_investment_components_100_101_102_belong_to_same_note():
    table = "Investment result analysis"
    rows = [candidate(100, table, "Other investment revenue: Net gains on debt and equity securities", "6 Net financial result (continued)"),
            candidate(101, table, "Other investment revenue continued; Total other investment revenue", "6 Net financial result (continued)"),
            candidate(102, table, "Net impairment loss on financial assets: debt securities", "6 Net financial result (continued)")]
    found = _parse_candidates(json.dumps({"candidates": rows}), [100, 101, 102], [table], YF)
    assert [row["Physical PDF page"] for row in found] == [100, 101, 102]
    rows[2]["section_evidence"] = "3 Credit quality analysis"
    assert _parse_candidates(json.dumps({"candidates": [rows[2]]}), [102], [table], YF) == []


def test_real_yf_ocr_words_recover_reported_missing_tables(monkeypatch):
    raw = json.loads((Path(__file__).parent / "fixtures/yf_2025_ocr_excerpt.json").read_text(encoding="utf-8"))
    index = OCRIndex(tuple((int(n), text) for n, text in raw.items()), cached=True)
    monkeypatch.setattr("hkifrs17.ocr_index.scanned_text_index", lambda *args, **kwargs: index)
    plan = build_navigation(pdf_path(YF), YF, 27, 133, verified_table_options("KPMG"), use_ocr=True)
    pairs = {(lead.page, lead.table) for lead in plan.leads}
    assert {(32, "Cash flows"), (33, "Cash flows"),
            *((n, "Investment result analysis") for n in [98, 99, 100, 101, 102]),
            *((n, "Insurance and reinsurance contracts") for n in [119, 120, 122, 124, 126, 129, 130]),
            (133, "Discount rates and illiquidity premiums")} <= pairs
    assert plan.ocr_cached


def test_ocr_cache_reuses_same_pdf_and_invalidates_changed_bytes(tmp_path, monkeypatch):
    import os
    if os.name != "nt": pytest.skip("Windows OCR adapter")
    path = tmp_path / "scan.pdf"
    def make(text):
        with fitz.open() as doc:
            doc.new_page().insert_text((40, 60), text)
            doc.save(path)
    make("first")
    calls = []
    def batch(manifest):
        calls.append(manifest)
        return [{"page": row["page"], "text": "Consolidated statement of cash flows 2025"}
                for row in json.loads(manifest.read_text(encoding="utf-8"))]
    monkeypatch.setattr("hkifrs17.ocr_index._windows_batch", batch)
    cache = tmp_path / "cache"
    first = scanned_text_index(path, [1], cache_dir=cache)
    second = scanned_text_index(path, [1], cache_dir=cache)
    assert first.pages == second.pages and second.cached and len(calls) == 1
    path.unlink()
    make("different source bytes")
    assert not scanned_text_index(path, [1], cache_dir=cache).cached
    assert len(calls) == 2


def test_guided_checks_batch_full_images_merge_same_page_targets_and_run_concurrently(tmp_path, monkeypatch):
    path = tmp_path / "test.pdf"
    with fitz.open() as doc:
        for _ in range(8): doc.new_page()
        doc.save(path)
    targets = ["Cash flows", "Financial position"]
    leads = tuple(Lead(n, t, "OCR title", "Current file main statement", "Consolidated")
                  for n in [2, 3, 5] for t in targets)
    plan = Navigation("current PDF contents", leads, (), 8, (), "Consolidated", "Current main statement", Experience(), ocr_pages=8)
    monkeypatch.setattr("hkifrs17.discovery_runtime.build_navigation", lambda *a, **kw: plan)
    renders = []
    def render(path, pages, rotations):
        renders.extend(pages)
        return b"image"
    monkeypatch.setattr("hkifrs17.locator.contact_sheet_png", render)
    first_wave, lock, count = Barrier(3), Lock(), 0
    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}
    def post(url, **kwargs):
        nonlocal count
        content = kwargs["json"]["messages"][1]["content"]
        if isinstance(content, str): return Response({"navigation": []})
        prompt = content[0]["text"]
        assert "FINAL SINGLE-PAGE CHECK" in prompt
        pages = json.loads(re.search(r"physical PDF pages (\[[^]]+\])", prompt)[1])
        assert len([x for x in content if x["type"] == "image_url"]) == len(pages)
        with lock:
            count += 1
            wave = count <= 3
        if wave: first_wave.wait(timeout=5)
        rows = [candidate(n, t, "Total assets" if t == targets[1] else "Cash flows from operating activities",
                          "Consolidated statement of financial position" if t == targets[1] else "Consolidated statement of cash flows",
                          scope="Consolidated") for n in pages for t in targets]
        return Response({"candidates": rows})
    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    diagnostics = []
    found, failures = locate_model_pages(path, {**YF, "page_profit": 1}, first=1, last=8,
        tables=targets, base_url="https://example.com/v1", model="vision", api_key="secret-not-logged",
        pages_per_image=2, verify_pages=True, diagnostics=diagnostics)
    assert failures == [] and {row["Table"] for row in found} == set(targets)
    assert count == 3  # Six original pages in three batches; no preliminary image pass.
    assert len(renders) == len(set(renders)) == 6
    assert diagnostics[-1]["Model requests"] == 4  # One text navigation + three image requests.
    assert "secret-not-logged" not in json.dumps(diagnostics)
