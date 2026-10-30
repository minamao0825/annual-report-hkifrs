"""Hybrid navigation learns vocabulary without trusting historical page mappings."""

import json
from pathlib import Path

import fitz

from hkifrs17.extraction_plan import TABLE_METRICS
from hkifrs17.locator import _parse_candidates, locate_model_pages
from hkifrs17.page_radar import (
    Experience, build_navigation, guided_groups, learn_experience,
    navigation_pairs, navigation_prompt, saved_experience,
)
from hkifrs17.storage import ROOT


FILING = {"legal_entity": "Example Life Limited", "scope": "Company",
          "period_end": "2025-12-31", "page_profit": 1}


def make_pdf(path, texts):
    with fitz.open() as doc:
        for text in texts:
            page = doc.new_page()
            page.insert_textbox(fitz.Rect(35, 35, 550, 800), text, fontsize=9)
        doc.save(path)
    return path


def note(title, rows="Claims paid 1,234 2,345\nRisk adjustment 3,456 4,567", scope="Company only"):
    return (f"NOTES TO THE FINANCIAL STATEMENTS\n22 {title}\n{scope}\n"
            f"Year ended 31 December 2025\nHKD thousands\n{rows}\n"
            "This numeric note table contains reported opening and closing balances.")


def test_first_sixty_summaries_are_capped_and_physically_numbered(tmp_path):
    text = "CONTENTS\nStatement of financial position 6\n" + "Directory words " * 110
    path = make_pdf(tmp_path / "directory.pdf", [text] * 61)
    plan = build_navigation(path, FILING, 1, 61, ["Financial position"], Experience())
    assert "---PHYSICAL PDF PAGE 60---" in plan.front_text
    assert "---PHYSICAL PDF PAGE 61---" not in plan.front_text
    for item in plan.front_text.split("---PHYSICAL PDF PAGE ")[1:]:
        assert len(item.split("---\n", 1)[1].rstrip()) <= 1200
    prompt = navigation_prompt(plan, FILING, 1, 61, ["Financial position"])
    assert "printed-to-physical page offsets" in prompt
    assert "not blindly trust" in prompt
    assert "Company" in prompt


def test_front_matter_is_brief_but_contents_and_audited_titles_stay_visible(tmp_path):
    contents = "CONTENTS\nStatement of cash flows 32\n" + "Directory words " * 90
    business = "Business Review (continued)\n" + "Operating performance and investment commentary " * 35
    cash = "Consolidated statement of cash flows\n" + "Current year cash flow table 2025 HKD 1,234 2,345 " * 30
    policy = "Material accounting policies (continued)\nStatement of compliance\n" + "Recognition and measurement policy prose " * 35
    policy_ocr_typo = policy.replace("Material", "Materia")
    path = make_pdf(tmp_path / "frontmatter.pdf", [contents] + [business] * 25 + [cash] + [policy_ocr_typo] + [policy] * 32)
    filing = {**FILING, "page_profit": 27, "scope": "Consolidated"}
    plan = build_navigation(path, filing, 27, 60, ["Cash flows"], Experience())
    sections = {int(piece.split("---\n", 1)[0]): piece.split("---\n", 1)[1]
                for piece in plan.front_text.split("---PHYSICAL PDF PAGE ")[1:]}
    assert len(sections) == 60
    assert "Directory words" in sections[1] and len(sections[1]) > 700
    assert "Business Review" in sections[2] and len(sections[2]) < 100
    assert "cash flow table" in sections[27] and len(sections[27]) > 700
    assert "Accounting policies" in sections[28] and len(sections[28]) < 100
    assert "Accounting policies" in sections[34] and len(sections[34]) < 100
    assert all(len(value.rstrip()) <= 1200 for value in sections.values())
    assert (27, "Cash flows") in {(lead.page, lead.table) for lead in plan.leads}


def test_radar_starts_at_page_21_requires_all_groups_and_follows_company_scope(tmp_path):
    title = "INSURANCE CONTRACTS NOT MEASURED UNDER PAA"
    rows = "Remaining coverage 1,234 2,345\nIncurred claims 3,456 4,567"
    texts = [""] * 19 + [note(title, rows)]
    texts += [note(title, rows, "Consolidated"), note(title, rows),
              note(title, "Remaining coverage 1,234 2,345\nOther balances 3,456 4,567")]
    path = make_pdf(tmp_path / "scope.pdf", texts)
    target = "Insurance non-PAA remaining/incurred movement"
    company = build_navigation(path, FILING, 1, 23, [target], Experience())
    assert [lead.page for lead in company.leads] == [22]
    group = build_navigation(path, {**FILING, "scope": "Consolidated"}, 1, 23, [target], Experience())
    assert [lead.page for lead in group.leads] == [21]


def test_issued_insurance_does_not_take_held_reinsurance_or_paa_substring(tmp_path):
    rows = "Remaining coverage 1,234 2,345\nIncurred claims 3,456 4,567"
    path = make_pdf(tmp_path / "population.pdf", [""] * 20 + [
        note("Reinsurance contracts held NOT MEASURED UNDER PAA", rows),
        note("Insurance contracts NOT MEASURED UNDER PAA", rows),
        note("Insurance contracts MEASURED UNDER PAA", rows),
    ])
    targets = ["Insurance non-PAA remaining/incurred movement",
               "Insurance PAA remaining/incurred movement"]
    plan = build_navigation(path, FILING, 1, 23, targets, Experience())
    assert {(x.page, x.table) for x in plan.leads} == {(22, targets[0]), (23, targets[1])}


def test_saved_source_labels_teach_new_rows_without_values_years_or_pages(tmp_path):
    target = "Investment result analysis"
    codes = TABLE_METRICS[target]
    records = [
        {"Review status": "Verified", "Value status": "Reported", "PDF page": 777,
         "Document ID": "OLD_2024", "Period end": "2024-12-31", "Metric code": codes[i],
         "Source label": "Note 48 " + label + "; 2024 comparative, 999,123"}
        for i, label in enumerate(["Portfolio yield bridge", "Policyholder surplus transfer"])
    ]
    records += [{**records[0], "Review status": "Pending", "Source label": "Unreviewed invented vocabulary"},
                {**records[0], "Value status": "Derived from disclosed items", "Source label": "Derived invented vocabulary"}]
    learned = learn_experience(records)
    assert learned.record_count == 2 and learned.document_count == 1
    aliases = " ".join(learned.aliases(target))
    assert not any(word in aliases for word in ["777", "48", "2024", "999", "invented"])
    path = make_pdf(tmp_path / "newtitle.pdf", [""] * 20 + [note("NET FINANCIAL RESULT",
                    "Portfolio yield bridge 1,234 2,345\nPolicyholder surplus transfer 3,456 4,567")])
    assert build_navigation(path, FILING, 1, 21, [target], Experience()).leads == ()
    plan = build_navigation(path, FILING, 1, 21, [target], learned)
    assert [lead.page for lead in plan.leads] == [21]
    assert "777" not in navigation_prompt(plan, FILING, 1, 21, [target])


def test_guided_groups_keep_image_pages_neighbours_and_missing_target_fallback():
    assert guided_groups(1, 12, ["A"], {(7, "A")}, (2, 11), 2) == [[2], [6, 7], [8], [11]]
    assert sum(map(len, guided_groups(1, 12, ["A", "B"], {(7, "A")}, (), 2))) == 12
    assert navigation_pairs(json.dumps({"navigation": [
        {"physical_page": 7, "table": "A"}, {"physical_page": 0, "table": "A"},
        {"physical_page": True, "table": "A"}, {"physical_page": 9, "table": "Unknown"},
    ]}), 1, 12, ["A"]) == {(7, "A")}


def test_replacing_pdf_invalidates_local_index(tmp_path):
    path = make_pdf(tmp_path / "replace.pdf", ["scanned"])
    assert build_navigation(path, FILING, 1, 1, ["Cash flows"], Experience()).readable_pages == 0
    path.unlink()
    make_pdf(path, ["STATEMENT OF CASH FLOWS\n" + "Current-year numerical table with cash movements. " * 5])
    assert build_navigation(path, FILING, 1, 1, ["Cash flows"], Experience()).readable_pages == 1


def test_company_candidate_rejects_group_only_evidence():
    base = {"physical_page": 21, "table": "Insurance revenue note",
            "source_section": "notes_to_financial_statements", "section_evidence": "Note 22 Insurance revenue",
            "year_evidence": "2025 table column", "scope_evidence": "Group column only",
            "evidence": "Insurance revenue and CSM", "confidence": "High"}
    assert _parse_candidates(json.dumps({"candidates": [base]}), [21], ["Insurance revenue note"], FILING) == []


def test_real_fwd_radar_covers_measurement_discount_and_main_statement_pages():
    path = ROOT / "disclosures/pilot/FWD_Bermuda_Audited_Financial_Statement_2025.pdf"
    targets = ["Profit or loss", "Financial position", "Cash flows",
               "Insurance and reinsurance contracts", "Discount rates and illiquidity premiums"]
    plan = build_navigation(path, FILING, 8, 118, targets)
    pairs = {(lead.page, lead.table) for lead in plan.leads}
    assert {(8, targets[0]), (10, targets[1]), (14, targets[2]), (15, targets[2]),
            (65, targets[3]), (71, targets[3]), (79, targets[4])} <= pairs
    assert plan.experience.record_count == saved_experience().record_count > 0
    assert sum(map(len, guided_groups(8, 118, targets, pairs, plan.image_pages, 2))) < 111


def test_text_leads_need_current_page_image_evidence_and_navigation_failure_falls_back(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "model.pdf", ["STATEMENT OF FINANCIAL POSITION\n" +
                    "This is a numeric 2025 table for the Company with total assets. " * 6] + [""] * 3)
    calls, diagnostics = [], []

    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}

    def post(*args, **kwargs):
        content = kwargs["json"]["messages"][1]["content"]
        calls.append(content)
        if isinstance(content, str):
            return Response({"navigation": [{"physical_page": 1, "table": "Financial position"}]})
        return Response({"candidates": []})

    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    found, errors = locate_model_pages(path, FILING, first=1, last=4, tables=["Financial position"],
                                      base_url="https://example.com/v1", model="vision", api_key="test",
                                      verify_pages=True, diagnostics=diagnostics)
    assert found == errors == []
    assert isinstance(calls[0], str)
    assert any("FINAL SINGLE-PAGE CHECK" in item[0]["text"] for item in calls[1:])

    calls.clear()
    def failed_text(*args, **kwargs):
        content = kwargs["json"]["messages"][1]["content"]
        calls.append(content)
        return Response({"bad": []}) if isinstance(content, str) else Response({"candidates": []})
    monkeypatch.setattr("hkifrs17.locator.requests.post", failed_text)
    locate_model_pages(path, FILING, first=1, last=4, tables=["Financial position"],
                       base_url="https://example.com/v1", model="vision", api_key="test",
                       diagnostics=diagnostics)
    assert any(row["Decision"] == "Full visual scan fallback" for row in diagnostics)
    assert len(calls) == 2  # One failed text response, one original four-page image; no retry.


def test_rejected_guided_leads_recover_target_in_full_visual_fallback(tmp_path, monkeypatch):
    body = "This readable page contains explanatory background for the financial statements. " * 5
    path = make_pdf(tmp_path / "recovery.pdf", ["STATEMENT OF FINANCIAL POSITION\n" + body] + [body] * 7)
    diagnostics = []
    candidate = {"physical_page": 7, "table": "Financial position",
                 "source_section": "financial_statements",
                 "section_evidence": "Statement of financial position",
                 "year_evidence": "2025 table column", "scope_evidence": "Company column",
                 "evidence": "Statement of financial position: Total assets", "confidence": "High"}

    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}

    def post(*args, **kwargs):
        content = kwargs["json"]["messages"][1]["content"]
        if isinstance(content, str):
            return Response({"navigation": [{"physical_page": 1, "table": "Financial position"}]})
        prompt = content[0]["text"]
        found = "physical PDF pages [7, 8]" in prompt or "physical PDF pages [7]" in prompt
        return Response({"candidates": [candidate] if found else []})

    monkeypatch.setattr("hkifrs17.locator.requests.post", post)
    found, errors = locate_model_pages(path, FILING, first=1, last=8, tables=["Financial position"],
                                      pages_per_image=2, base_url="https://example.com/v1",
                                      model="vision", api_key="test", verify_pages=True,
                                      diagnostics=diagnostics)
    assert errors == []
    assert [row["Physical PDF page"] for row in found] == [7]
    assert any(row["Decision"] == "No qualified guided result; full visual scan fallback" for row in diagnostics)
