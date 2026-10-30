"""Focused regression checks for the three-step source and reconciliation flow."""

from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from hkifrs17.catalog import PILOT_FILINGS
from hkifrs17.checks import automatic_arithmetic_checks, default_plan
from hkifrs17.data import COLUMNS, LEGACY_COLUMNS, check_candidates, normalize_records, reconciliation_checks
from hkifrs17.demo import demo_records
from hkifrs17.review import (read_review_workbook, source_review_workbook_bytes,
                             step3_workbook_bytes, validate_step3_check_workbook,
                             read_manual_source_reviews)
from hkifrs17.review_flow import (confirm_source_rows, per_cell_checks, source_scope_issue,
                                  source_table_labels)
from hkifrs17.investigation import investigate_check_issues
from hkifrs17.storage import all_filings
from hkifrs17 import pdf, storage
from hkifrs17.source_audit import _check_observation, _fingerprint, pdf_stamp, source_results
from hkifrs17 import source_audit
from hkifrs17.scope_corroboration import statement_note_corroboration
from hkifrs17.vision_settings import (remember_page_input, remember_step1_input, restore_step1_inputs,
                                      shared_vision_settings)


def test_step1_model_settings_survive_page_widget_cleanup():
    state = {}
    restore_step1_inputs(state)
    state["extract_base_url"] = "https://api.moonshot.cn/v1"
    state["extract_model"] = "kimi-k2.6"
    state["extract_api_key"] = "session-only-key"
    state["extract_timeout"] = 420
    for field in ("base_url", "model", "api_key", "timeout"):
        remember_step1_input(state, field)
    for key in ("extract_base_url", "extract_model", "extract_api_key", "extract_timeout"):
        del state[key]
    settings = shared_vision_settings(state)
    assert settings["base_url"] == "https://api.moonshot.cn/v1"
    assert settings["model"] == "kimi-k2.6"
    assert settings["api_key"] == "session-only-key"
    assert settings["timeout"] == 420


def test_step3_can_restore_shared_model_settings_without_step1():
    state = {}
    restore_step1_inputs(state)
    state["step3_vision_model"] = "vision-model"
    state["step3_vision_api_key"] = "session-only-key"
    remember_page_input(state, "model", "step3_vision_model")
    remember_page_input(state, "api_key", "step3_vision_api_key")
    restore_step1_inputs(state)
    assert state["extract_model"] == "vision-model"
    assert state["extract_api_key"] == "session-only-key"

    state["step3_vision_model"] = ""
    remember_page_input(state, "model", "step3_vision_model")
    assert shared_vision_settings(state)["model"] == ""


def test_source_review_excel_needs_no_manual_pending_edit():
    filings = list(PILOT_FILINGS)
    filing = next(item for item in filings if item["document_id"] == "YF_2025")
    rows = demo_records("YF_2025").head(2)
    labels = source_table_labels(rows, [(27, "Profit or loss")])
    payload = source_review_workbook_bytes(rows, filings, labels)
    imported = read_review_workbook(payload, filings)
    assert imported["Review status"].eq("Pending").all()
    reviewed = confirm_source_rows(imported, list(range(len(imported))), filing, filings)
    assert reviewed["Review status"].eq("Verified").all()
    assert reviewed["Audit status"].ne("Check source").all()
    assert "Source table" in load_workbook(BytesIO(payload))["Records"].values.__iter__().__next__()


def test_legacy_records_excel_is_still_readable():
    rows = demo_records("YF_2025").head(1)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        rows[LEGACY_COLUMNS].to_excel(writer, sheet_name="Records", index=False)
    imported = read_review_workbook(output.getvalue(), list(PILOT_FILINGS))
    assert len(imported) == 1
    assert imported.iloc[0]["Column heading"] == ""


def test_cell_excel_has_formula_for_every_reviewed_cell():
    filings = list(PILOT_FILINGS)
    filing = next(item for item in filings if item["document_id"] == "YF_2025")
    rows = demo_records("YF_2025").head(2)
    rows = confirm_source_rows(rows, [0, 1], filing, filings)
    payload = step3_workbook_bytes(rows, filings, storage.load_check_plan("YF_2025"))
    workbook = load_workbook(BytesIO(payload), data_only=False)
    sheet = workbook["Cell checks"]
    assert sheet.max_row == len(rows) + 1
    assert all(sheet[f"I{position}"].data_type == "f" for position in range(2, sheet.max_row + 1))
    assert all(sheet[f"L{position}"].data_type == "f" for position in range(2, sheet.max_row + 1))
    assert workbook["Excel arithmetic"].max_row > 1
    assert "Investigation" in workbook.sheetnames
    validate_step3_check_workbook(payload, len(rows))
    sheet["I2"] = "Pass"
    changed = BytesIO()
    workbook.save(changed)
    with pytest.raises(ValueError, match="formula was removed"):
        validate_step3_check_workbook(changed.getvalue(), len(rows))


def test_step3_screens_each_cell_before_manual_rule_assessment():
    filings = list(PILOT_FILINGS)
    filing = next(item for item in filings if item["document_id"] == "YF_2025")
    rows = demo_records("YF_2025")
    rows = confirm_source_rows(rows, list(range(len(rows))), filing, filings)
    plan = default_plan(filings, {"YF_2025"})
    screen = automatic_arithmetic_checks(rows, filings, plan)
    target = screen[screen["Period end"].eq("2025-12-31") & screen["Check ID"].eq("REVENUE_NOTE")].iloc[0]
    assert target["Arithmetic result"] == "Missing source cells"
    assert target["Missing inputs"] == "INS_REVENUE_NOTE_TOTAL"
    final = reconciliation_checks(rows, filings, plan)
    assert final.loc[final["Check ID"].eq("REVENUE_NOTE"), "Result"].eq("Missing inputs").all()
    automatic_final = reconciliation_checks(rows, filings, plan, automatic=True)
    missing_rule = automatic_final[automatic_final["Period end"].eq("2025-12-31")
                                   & automatic_final["Check ID"].eq("REVENUE_NOTE")].iloc[0]
    assert missing_rule["Result"] == "Missing inputs"
    assert missing_rule["Detail"] == "Extract and verify each missing source field."
    assert automatic_final.loc[automatic_final["Check ID"].eq("CSM_ROLL"), "Result"].eq("Not evaluated").all()
    cell = per_cell_checks(rows, final, screen)
    revenue = cell[cell["Period end"].eq("2025-12-31") & cell["Metric code"].eq("INS_REVENUE")].iloc[0]
    assert revenue["Automatic arithmetic"] == "Investigate"
    assert "REVENUE_NOTE: Missing source cells" in revenue["Automatic rule results"]

    note = rows[rows["Period end"].eq("2025-12-31") & rows["Metric code"].eq("INS_REVENUE")].iloc[0].copy()
    note["Metric code"] = "INS_REVENUE_NOTE_TOTAL"
    note["PDF page"] = 97
    note["Source label"] = "Insurance revenue note total; 2025"
    combined = normalize_records(pd.concat([rows, pd.DataFrame([note])], ignore_index=True), filings)
    matched = automatic_arithmetic_checks(combined, filings, plan)
    assert matched.loc[matched["Period end"].eq("2025-12-31")
                       & matched["Check ID"].eq("REVENUE_NOTE"), "Arithmetic result"].iloc[0] == "Match"
    combined.loc[combined["Metric code"].eq("INS_REVENUE_NOTE_TOTAL"), "Original value"] += 1_000_000
    difference = automatic_arithmetic_checks(combined, filings, plan)
    assert difference.loc[difference["Period end"].eq("2025-12-31")
                          & difference["Check ID"].eq("REVENUE_NOTE"), "Arithmetic result"].iloc[0] == "Difference"


def test_automatic_investigation_flags_unit_page_year_and_contract_clues():
    filings = list(PILOT_FILINGS)
    filing = next(item for item in filings if item["document_id"] == "YF_2025")
    rows = confirm_source_rows(demo_records("YF_2025"),
                               list(range(len(demo_records("YF_2025")))), filing, filings)
    liability = rows[rows["Period end"].eq("2024-12-31")
                     & rows["Metric code"].eq("INS_LIABS")].iloc[0].copy()
    liability["Metric code"] = "INS_LIABS_NOTE_CLOSE"
    liability["Original value"] = 69618
    liability["PDF page"] = 14
    liability["Source label"] = "Insurance contract liabilities As at 31 December 2024"
    movement = rows[rows["Period end"].eq("2025-12-31")
                    & rows["Metric code"].eq("INS_LIABS")].iloc[0].copy()
    movement["Metric code"] = "CSM_NET_MOVEMENT"
    movement["PDF page"] = 126
    movement["Source label"] = "Net movement in CSM | Reinsurance contracts | 2024"
    combined = normalize_records(pd.concat([rows, pd.DataFrame([liability, movement])],
                                           ignore_index=True), filings)
    checks = reconciliation_checks(combined, filings,
                                   default_plan(filings, {"YF_2025"}), automatic=True)
    leads = investigate_check_issues(combined, checks, {27, 29, 119, 122})
    liability_lead = leads[leads["Period end"].eq("2024-12-31")
                           & leads["Check ID"].eq("LIABILITY_NOTE")].iloc[0]["Automatic leads"]
    assert "outside the confirmed table pages" in liability_lead
    assert "1,000 times" in liability_lead
    csm_lead = leads[leads["Period end"].eq("2025-12-31")
                     & leads["Check ID"].eq("CSM_ROLL")].iloc[0]["Automatic leads"]
    assert "source label says 2024" in csm_lead
    assert "reinsurance source" in csm_lead


def test_step2_approval_precedes_reconciliation(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(storage, "UPLOADS_FILE", tmp_path / "uploaded_filings.json")
    monkeypatch.setattr(storage, "PUBLISHED_FILE", tmp_path / "published_records.xlsx")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"test")
    monkeypatch.setattr(storage, "pdf_path", lambda filing: source)
    monkeypatch.setattr(pdf, "page_count", lambda path: 200)
    filings = list(PILOT_FILINGS)
    filing = next(item for item in filings if item["document_id"] == "YF_2025")
    draft = demo_records("YF_2025").head(2)
    storage.save_draft("YF_2025", draft)
    with pytest.raises(ValueError, match="Pending"):
        storage.approve_draft("YF_2025")
    reviewed = confirm_source_rows(draft, [0, 1], filing, filings)
    storage.save_draft("YF_2025", reviewed)
    assert storage.approve_draft("YF_2025") == 2
    assert len(storage.load_approved("YF_2025")) == 2


def test_pending_cells_enter_step3_and_publish_only_after_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(storage, "UPLOADS_FILE", tmp_path / "uploaded_filings.json")
    monkeypatch.setattr(storage, "PUBLISHED_FILE", tmp_path / "published_records.xlsx")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    monkeypatch.setattr(storage, "pdf_path", lambda filing: source)
    monkeypatch.setattr(pdf, "page_count", lambda path: 200)
    rows = demo_records("YF_2025")
    assert rows["Review status"].eq("Pending").all()
    storage.save_draft("YF_2025", rows)
    pages = sorted(rows["PDF page"].astype(int).unique())
    storage.save_confirmed_pages("YF_2025", source,
                                 [(page, "Profit or loss") for page in pages])
    plan = storage.load_check_plan("YF_2025")
    optional = ~plan["Check ID"].isin(("PRIMARY", "SERVICE", "BALANCE"))
    plan.loc[optional, "Assessment"] = "Not applicable"
    plan.loc[optional, "Reason"] = "No matching disclosed note fields in this pilot sample."
    method = plan["Check ID"].isin(("INS_LIABS_METHOD", "REINS_ASSETS_METHOD"))
    plan.loc[method, "Note reference"] = "Note 22, physical PDF p.120"
    storage.save_check_plan("YF_2025", plan)
    assert storage.stage_draft_for_checks("YF_2025") == len(rows)
    staged = check_candidates(storage.load_approved("YF_2025"), list(PILOT_FILINGS))
    assert staged["Review status"].eq("Pending").all()
    checks = reconciliation_checks(staged, list(PILOT_FILINGS), plan,
                                   verified_only=False, automatic=True)
    cells = per_cell_checks(staged, checks, allow_pending=True,
                            confirmed_pages=set(pages))
    assert cells["Cell result"].eq("Pass").all()
    workbook = load_workbook(BytesIO(step3_workbook_bytes(staged, list(PILOT_FILINGS),
                                                         plan, tuple(pages))))
    assert "Pending" in workbook["Cell checks"]["I2"].value
    assert workbook["Excel arithmetic"].max_row > 1
    with pytest.raises(ValueError, match="Not checked"):
        storage.publish_selected(["YF_2025"], checked_candidates=True)
    stamp = pdf_stamp(source)
    storage.save_source_audit("YF_2025", [
        {"Document ID": row["Document ID"], "Period end": row["Period end"],
         "Metric code": row["Metric code"], "PDF page": int(row["PDF page"]),
         "Source check": "Match", "Fingerprint": _fingerprint(row, stamp),
         "Reason": "Independent image reading matched."}
        for _, row in staged.iterrows()
    ])
    assert storage.publish_selected(["YF_2025"], checked_candidates=True) == len(rows)
    assert storage.load_published()["Review status"].eq("Verified").all()
    assert storage.integration_status()["current"]
    filing = storage.filing_by_id("YF_2025")
    wrong = pdf._row(filing, "INS_PAA_LIC_CLOSE", "2025-12-31", 994_533_981,
                     120, "Contracts not under PAA | Net closing balance | 2025", "HKD")
    storage.save_draft("YF_2025", pd.concat([rows, pd.DataFrame([wrong])], ignore_index=True))
    storage.save_confirmed_pages("YF_2025", source,
                                 [(page, "Profit or loss") for page in sorted(set(pages) | {120})])
    assert storage.stage_draft_for_checks("YF_2025") == len(rows) + 1
    with pytest.raises(ValueError, match="INS_PAA_LIC_CLOSE"):
        storage.publish_selected(["YF_2025"], checked_candidates=True)
    assert len(storage.load_published()) == len(rows)


def test_independent_image_reading_flags_amount_year_and_unit():
    row = demo_records("YF_2025").iloc[0].copy()
    row["Source row"] = "Insurance revenue"
    row["Column heading"] = "2025 Total"
    observed = {"observed_value": row["Original value"],
                "observed_unit": row["Source unit"], "observed_year": "2025",
                "observed_row": "Insurance revenue", "observed_column": "2025 Total",
                "observed_scope": row["Scope"],
                "scope_basis": "Inherited from primary statements",
                "evidence_box": "100,100,150,120",
                "confidence": "High"}
    assert _check_observation(row, observed)["Source check"] == "Match"
    for changed in ({"observed_value": float(row["Original value"]) + 100},
                    {"observed_year": "2024"}, {"observed_unit": "HKD millions"},
                    {"observed_column": "2024 Total"}):
        assert _check_observation(row, {**observed, **changed})["Source check"] == "Mismatch"
    assert _check_observation(row, {**observed, "confidence": "Low"})["Source check"] == "Unclear"
    assert _check_observation(row, {**observed, "evidence_box": ""})["Source check"] == "Unclear"
    assert _check_observation(row, {**observed, "scope_basis": ""})["Source check"] == "Unclear"
    row["Source row"] = "Net opening balance"
    row["Column heading"] = ""
    row["Source label"] = "Net opening balance | Total $"
    wrong_row = {**observed, "observed_row": "Net closing balance", "observed_column": "Total $"}
    assert "source row differs" in _check_observation(row, wrong_row)["Reason"]
    wrong_column = {**observed, "observed_row": "Net opening balance", "observed_column": "PAA $"}
    assert "numeric column differs" in _check_observation(row, wrong_column)["Reason"]
    assert "non-PAA subtotal" in source_scope_issue(
        "REINS_NOTE_NET_CLOSE", "Net closing balance | Total | Reinsurance non-PAA")


def test_statement_note_match_needs_both_pdf_cells_and_scope_basis():
    rows = pd.DataFrame([
        {"Period end": "2025-12-31", "Metric code": "INS_REVENUE", "PDF page": 27,
         "Value (millions)": 100.0},
        {"Period end": "2025-12-31", "Metric code": "INS_REVENUE_NOTE_TOTAL", "PDF page": 80,
         "Value (millions)": 100.0},
    ])
    arithmetic = pd.DataFrame([{"Period end": "2025-12-31", "Check ID": "REVENUE_NOTE",
                                "Check": "Insurance revenue: statement vs note",
                                "Arithmetic result": "Match", "Difference (millions)": 0.0}])
    images = pd.DataFrame([
        {"Period end": "2025-12-31", "Metric code": "INS_REVENUE", "Source check": "Match",
         "Scope basis": "Explicit on this page"},
        {"Period end": "2025-12-31", "Metric code": "INS_REVENUE_NOTE_TOTAL",
         "Source check": "Mismatch", "Scope basis": ""},
    ])
    pending = statement_note_corroboration(rows, arithmetic, images)
    assert "still needs review" in pending.iloc[0]["Conclusion"]
    images.loc[1, "Source check"] = "Match"
    images.loc[1, "Scope basis"] = "Inherited from primary statements"
    confirmed = statement_note_corroboration(rows, arithmetic, images)
    assert confirmed.iloc[0]["Conclusion"].startswith("Corroborated")


def test_image_request_does_not_supply_stored_amount(monkeypatch):
    row = demo_records("YF_2025").head(1).copy()
    row.loc[:, "Original value"] = 9_876_543_210
    row.loc[:, "Source row"] = float("nan")
    row.loc[:, "Column heading"] = float("nan")
    shown = {}
    class Reply:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": '{"observations":[]}'}}]}
    def post(*args, **kwargs):
        shown["prompt"] = kwargs["json"]["messages"][1]["content"][0]["text"]
        return Reply()
    monkeypatch.setattr(source_audit.requests, "post", post)
    source_audit._request_page("fake-image", row, PILOT_FILINGS[0], 27,
                               base_url="https://example.com/v1", model="vision",
                               api_key="key", timeout=30)
    assert "9876543210" not in shown["prompt"]
    assert '"source_row_hint": "Insurance revenue"' in shown["prompt"]
    assert '"column_hint": ""' in shown["prompt"]
    assert "requested_scope" in shown["prompt"]
    assert "complete column path" in shown["prompt"]
    assert "PRIMARY financial-statement scope" in shown["prompt"]


def test_auto_repair_requires_two_matching_image_reads(monkeypatch, tmp_path):
    row = demo_records("YF_2025").head(1).copy()
    original = float(row.iloc[0]["Original value"])
    observation = {"observed_value": original + 100, "observed_unit": row.iloc[0]["Source unit"],
                   "observed_year": "2025", "observed_row": str(row.iloc[0]["Source label"]).split("|")[0],
                   "observed_column": "2025 Total", "observed_scope": row.iloc[0]["Scope"],
                   "scope_basis": "Inherited from primary statements",
                   "evidence_box": "100,100,150,120", "confidence": "High"}
    finding = _check_observation(row.iloc[0], observation)
    monkeypatch.setattr(source_audit, "_isolated_number", lambda *args, **kwargs: original + 100)
    repairs = source_audit.confirmed_amount_repairs(
        row, [finding], tmp_path / "unused.pdf", base_url="url", model="model", api_key="key")
    assert len(repairs) == 1 and repairs[0]["New value"] == original + 100
    monkeypatch.setattr(source_audit, "_isolated_number", lambda *args, **kwargs: original + 200)
    assert not source_audit.confirmed_amount_repairs(
        row, [finding], tmp_path / "unused.pdf", base_url="url", model="model", api_key="key")


def test_saved_image_check_invalidates_when_source_cell_changes(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-test")
    rows = demo_records("YF_2025").head(1).copy()
    row = rows.iloc[0]
    saved = [{"Document ID": row["Document ID"], "Period end": row["Period end"],
              "Metric code": row["Metric code"], "PDF page": int(row["PDF page"]),
              "Source check": "Match", "Fingerprint": _fingerprint(row, pdf_stamp(path))}]
    assert source_results(rows, path, saved).iloc[0]["Source check"] == "Match"
    rows.loc[:, "Original value"] = rows["Original value"] + 1
    assert source_results(rows, path, saved).iloc[0]["Source check"] == "Not checked"


def test_manual_excel_source_review_is_parallel_to_image_check(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-test")
    rows = demo_records("YF_2025").head(1)
    audits = source_results(rows, path, [])
    payload = step3_workbook_bytes(rows, list(PILOT_FILINGS),
                                   default_plan(list(PILOT_FILINGS), {"YF_2025"}),
                                   (27,), audits)
    workbook = load_workbook(BytesIO(payload))
    assert "PDF source checks" in workbook.sheetnames
    sheet = workbook["Manual source review"]
    row = rows.iloc[0]
    for column, value in {"F": row["Original value"], "G": row["Source unit"],
                          "H": "2025", "I": str(row["Source label"]).split("|")[0],
                          "J": "2025 Total", "K": row["Scope"],
                          "L": "Read the original PDF page and checked its row and column."}.items():
        sheet[f"{column}2"] = value
    edited = BytesIO()
    workbook.save(edited)
    result = read_manual_source_reviews(edited.getvalue(), rows, path)
    assert len(result) == 1 and result[0]["Source check"] == "Match"
    assert "Manual Excel" in result[0]["Reason"]


def test_double_read_repair_updates_draft_and_approved_with_history(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(storage, "UPLOADS_FILE", tmp_path / "uploaded_filings.json")
    rows = demo_records("YF_2025").head(1)
    storage.save_draft("YF_2025", rows)
    storage._atomic_excel(rows, tmp_path / "approved" / "YF_2025.xlsx")
    row = rows.iloc[0]
    old = float(row["Original value"])
    repair = {"Document ID": "YF_2025", "Period end": row["Period end"],
              "Metric code": row["Metric code"], "PDF page": int(row["PDF page"]),
              "Old value": old, "New value": old + 10,
              "Evidence box": "100,100,150,120",
              "Reason": "Full-page transcription and isolated numeric-cell crop agree."}
    updated = storage.apply_confirmed_repairs("YF_2025", [repair])
    assert updated.iloc[0]["Original value"] == old + 10
    assert storage.load_draft("YF_2025").iloc[0]["Original value"] == old + 10
    assert list((tmp_path / "history").glob("auto_source_repairs_*.json"))
    with pytest.raises(ValueError, match="changed"):
        storage.apply_confirmed_repairs("YF_2025", [repair])


def test_incomplete_model_json_retries_only_that_page(monkeypatch, tmp_path):
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    monkeypatch.setattr(pdf, "page_text", lambda *args: "readable")
    monkeypatch.setattr(pdf, "page_png", lambda *args, **kwargs: b"png")
    replies = [
        {"choices": [{"message": {"content": '{"records":[{"metric_code":"OCI_TOTAL","source_label":"oops'},
                      "finish_reason": "length"}]},
        {"choices": [{"message": {"content": '{"records":[]}'}, "finish_reason": "stop"}]},
    ]
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def post(*args, **kwargs):
        requests.append(kwargs["json"]["max_tokens"])
        return Response(replies[len(requests) - 1])

    monkeypatch.setattr(pdf.requests, "post", post)
    result = pdf.extract_model_page(Path(tmp_path / "unused.pdf"), filing, 28, list(PILOT_FILINGS),
                                    base_url="https://example.com/v1", model="vision", api_key="key",
                                    metric_codes={"OCI_TOTAL"}, table_names=["Comprehensive income"])
    assert result.empty
    assert len(requests) == 2
    assert requests[0] >= 2500
    assert requests[1] > requests[0]


def test_step_pages_render_with_existing_draft(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).parents[1]
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(storage, "UPLOADS_FILE", tmp_path / "uploaded_filings.json")
    monkeypatch.setattr(storage, "PUBLISHED_FILE", tmp_path / "published_records.xlsx")
    monkeypatch.setattr(storage, "DISCLOSURES",
                        Path("E:/KPMG/HKIFRS17/hk_ifrs17_platform/disclosures"))
    rows = demo_records("YF_2025").head(2)
    storage.save_draft("YF_2025", rows)
    step1 = AppTest.from_file(str(root / "app_pages" / "01_extract.py"), default_timeout=30).run()
    assert not step1.exception
    next(item for item in step1.text_input if item.label == "Vision model").set_value("fake-vision").run()
    next(item for item in step1.text_input if item.label == "API key").set_value("fake-key").run()
    assert step1.session_state["vision_shared_model"] == "fake-vision"
    assert step1.session_state["vision_shared_api_key"] == "fake-key"
    step2 = AppTest.from_file(str(root / "app_pages" / "02_review.py"), default_timeout=30).run()
    assert not step2.exception
    assert not any(item.label in {"OpenAI-compatible base URL", "Vision model", "API key"}
                   for item in step2.text_input)
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    storage.save_draft("YF_2025", confirm_source_rows(rows, [0, 1], filing, list(PILOT_FILINGS)))
    storage.approve_draft("YF_2025")
    step3 = AppTest.from_file(str(root / "app_pages" / "03_publish.py"), default_timeout=30).run()
    assert not step3.exception


def test_step3_image_check_requires_visible_model_connection(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).parents[1]
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(storage, "UPLOADS_FILE", tmp_path / "uploaded_filings.json")
    monkeypatch.setattr(storage, "PUBLISHED_FILE", tmp_path / "published_records.xlsx")
    monkeypatch.setattr(storage, "DISCLOSURES",
                        Path("E:/KPMG/HKIFRS17/hk_ifrs17_platform/disclosures"))
    filing = next(item for item in PILOT_FILINGS if item["document_id"] == "YF_2025")
    rows = demo_records("YF_2025").head(2)
    storage.save_draft("YF_2025", confirm_source_rows(rows, [0, 1], filing, list(PILOT_FILINGS)))
    storage.approve_draft("YF_2025")

    app = AppTest.from_file(str(root / "app_pages" / "03_publish.py"), default_timeout=30).run()
    assert not app.exception
    assert any("vision model, API key" in item.value for item in app.warning)
    assert any(item.label == "Awaiting image check" and item.value == "2" for item in app.metric)
    button = next(item for item in app.button if item.label == "Check PDF cells needing review")
    assert button.disabled

    next(item for item in app.text_input if item.label == "Vision model").set_value("vision-model").run()
    next(item for item in app.text_input if item.label == "API key").set_value("session-only-key").run()
    assert not app.exception
    assert app.session_state["vision_shared_model"] == "vision-model"
    assert app.session_state["vision_shared_api_key"] == "session-only-key"
    next(item for item in app.checkbox if item.label.startswith("Send 2 source cell")).check().run()
    assert not app.exception
    button = next(item for item in app.button if item.label == "Check PDF cells needing review")
    assert not button.disabled


def test_step2_selects_one_table_and_confirms_all(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).parents[1]
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(storage, "UPLOADS_FILE", tmp_path / "uploaded_filings.json")
    monkeypatch.setattr(storage, "DISCLOSURES",
                        Path("E:/KPMG/HKIFRS17/hk_ifrs17_platform/disclosures"))
    filing = storage.filing_by_id("YF_2025")
    source = storage.pdf_path(filing)
    storage.save_confirmed_pages("YF_2025", source, [(27, "Profit or loss"), (29, "Financial position")])
    draft = demo_records("YF_2025")
    draft = draft[draft["PDF page"].isin([27, 29])].copy()
    storage.save_draft("YF_2025", draft)

    app = AppTest.from_file(str(root / "app_pages" / "02_review.py"), default_timeout=30).run()
    assert not app.exception
    assert not any(item.label == "Physical PDF page to inspect" for item in app.selectbox)
    selector = next(item for item in app.selectbox if item.label == "Table to review")
    assert len(selector.options) == 2
    assert any(option.startswith("Profit or loss") for option in selector.options)
    assert any(option.startswith("Financial position") for option in selector.options)
    selector.set_value(next(option for option in selector.options
                            if option.startswith("Financial position"))).run()
    assert not app.exception
    button = next(item for item in app.button if item.label.startswith("Confirm all "))
    button.click().run()
    assert not app.exception
    assert storage.load_draft("YF_2025")["Review status"].eq("Verified").all()
