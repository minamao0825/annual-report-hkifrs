"""Small local stores for a single-machine demonstration."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

import pandas as pd

from .catalog import PILOT_FILINGS
from .data import (COLUMNS, check_candidates, empty_records, normalize_records,
                   reconciliation_checks, standardize_hkd, verified_records)

REVIEW_WORKFLOW_VERSION = 4
from .checks import PLAN_COLUMNS, normalize_plan, require_resolved_checks


ROOT = Path(__file__).resolve().parents[1]
DISCLOSURES = ROOT / "disclosures"
DATA = ROOT / "data"
UPLOADS_FILE = DATA / "uploaded_filings.json"
PUBLISHED_FILE = DATA / "published_records.xlsx"
EXTERNAL_FILINGS_FILE = DATA / "external_filings.json"


def all_filings() -> list[dict]:
    uploaded = json.loads(UPLOADS_FILE.read_text(encoding="utf-8")) if UPLOADS_FILE.exists() else []
    external = json.loads(EXTERNAL_FILINGS_FILE.read_text(encoding="utf-8")) if EXTERNAL_FILINGS_FILE.exists() else []
    return [*PILOT_FILINGS, *uploaded, *external]


def filing_by_id(document_id: str) -> dict:
    item = next((item for item in all_filings() if item["document_id"] == document_id), None)
    if item is None:
        raise ValueError(f"Unknown filing: {document_id}")
    return item


def pdf_path(filing: dict) -> Path:
    folder = "pilot" if filing["document_id"] in {item["document_id"] for item in PILOT_FILINGS} else "uploads"
    filename = Path(filing["pdf_file"]).name
    return DISCLOSURES / folder / filename


def register_upload(pdf_bytes: bytes, *, filename: str, company: str, legal_entity: str,
                    scope: str, period_end: str, currency: str, source_unit: str,
                    auditor_template: str = "") -> dict:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a PDF.")
    from datetime import date
    date.fromisoformat(period_end)
    if auditor_template:
        from .source_templates import AUDITOR_TEMPLATES
        if auditor_template not in AUDITOR_TEMPLATES:
            raise ValueError("Choose a supported auditor layout template.")
    document_id = "UP_" + uuid4().hex[:10].upper()
    safe_name = document_id + ".pdf"
    target = DISCLOSURES / "uploads" / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf_bytes)
    item = {
        "document_id": document_id,
        "company_id": document_id,
        "company": company.strip(),
        "legal_entity": legal_entity.strip(),
        "scope": scope,
        "period_end": period_end,
        "currency": currency,
        "source_unit": source_unit,
        "auditor_template": auditor_template,
        "pdf_file": safe_name,
        "original_filename": Path(filename).name,
        "page_profit": 0,
        "page_balance": 0,
        "page_cashflow": 0,
        "page_csm": 0,
        "note": "Uploaded filing; statement pages and figures require review.",
    }
    existing = json.loads(UPLOADS_FILE.read_text(encoding="utf-8")) if UPLOADS_FILE.exists() else []
    existing.append(item)
    DATA.mkdir(parents=True, exist_ok=True)
    UPLOADS_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return item


def _record_file(stage: str, document_id: str) -> Path:
    if not document_id.replace("_", "").isalnum():
        raise ValueError("Invalid document ID.")
    return DATA / stage / (document_id + ".xlsx")


def _plan_file(stage: str, document_id: str) -> Path:
    return _record_file(stage, document_id).with_suffix(".json")


def load_check_plan(document_id: str, stage: str = "drafts") -> pd.DataFrame:
    filing_by_id(document_id)
    path = _plan_file(stage, document_id)
    frame = pd.DataFrame(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else pd.DataFrame(columns=PLAN_COLUMNS)
    return normalize_plan(frame, all_filings(), {document_id})


def save_check_plan(document_id: str, frame: pd.DataFrame, stage: str = "drafts") -> None:
    if stage != "drafts":
        raise ValueError("Only the draft check plan can be edited.")
    plan = normalize_plan(frame, all_filings(), {document_id})
    path = _plan_file(stage, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.to_json(orient="records", indent=2), encoding="utf-8")


def plans_for_records(records: pd.DataFrame, stage: str) -> pd.DataFrame:
    ids = records["Document ID"].unique().tolist() if not records.empty else []
    return pd.concat([load_check_plan(document_id, stage) for document_id in ids], ignore_index=True) if ids else pd.DataFrame(columns=PLAN_COLUMNS)


def _atomic_excel(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".records_", suffix=".xlsx", dir=path.parent)
    os.close(handle)
    try:
        with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
            frame[COLUMNS].to_excel(writer, sheet_name="Records", index=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_draft(document_id: str, frame: pd.DataFrame) -> None:
    filing_by_id(document_id)
    records = normalize_records(frame, all_filings())
    if not records["Document ID"].eq(document_id).all():
        raise ValueError("The draft contains a different document ID.")
    _atomic_excel(records, _record_file("drafts", document_id))


def load_draft(document_id: str) -> pd.DataFrame:
    path = _record_file("drafts", document_id)
    if not path.exists():
        return empty_records()
    return normalize_records(pd.read_excel(path, sheet_name="Records"), all_filings())


def _page_selection_file(document_id: str) -> Path:
    filing_by_id(document_id)
    return DATA / "page_selections" / (document_id + ".json")


def save_confirmed_pages(document_id: str, path: Path, pairs: list[tuple[int, str]]) -> None:
    """Keep human-confirmed physical pages available after page navigation/restart."""
    from .extraction_plan import TABLE_METRICS
    from .pdf import page_count
    total = page_count(path)
    cleaned = sorted({(int(page), str(table)) for page, table in pairs})
    if any(page < 1 or page > total or table not in TABLE_METRICS for page, table in cleaned):
        raise ValueError("Confirmed table pages must exist in this PDF and use supported table names.")
    stat = path.stat()
    target = _page_selection_file(document_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"source": [str(path), stat.st_size, stat.st_mtime_ns],
                                  "pairs": cleaned}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_confirmed_pages(document_id: str, path: Path) -> list[tuple[int, str]]:
    target = _page_selection_file(document_id)
    if not target.exists() or not path.exists():
        return []
    saved = json.loads(target.read_text(encoding="utf-8"))
    stat = path.stat()
    if saved.get("source") != [str(path), stat.st_size, stat.st_mtime_ns]:
        return []
    return [(int(page), str(table)) for page, table in saved.get("pairs", [])]


def load_source_audit(document_id: str) -> list[dict]:
    filing_by_id(document_id)
    target = DATA / "source_audits" / (document_id + ".json")
    return json.loads(target.read_text(encoding="utf-8")) if target.exists() else []


def save_source_audit(document_id: str, items: list[dict]) -> None:
    filing_by_id(document_id)
    target = DATA / "source_audits" / (document_id + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    prior = {(item["Period end"], item["Metric code"]): item
             for item in load_source_audit(document_id)}
    prior.update({(item["Period end"], item["Metric code"]): item for item in items})
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(list(prior.values()), ensure_ascii=False, indent=2,
                                    default=str), encoding="utf-8")
    os.replace(temporary, target)


def approve_draft(document_id: str) -> int:
    records = load_draft(document_id)
    if records.empty:
        raise ValueError("There is no draft to approve.")
    if records["Review status"].eq("Pending").any():
        raise ValueError("Review or exclude every Pending source cell before sending it to Step 3.")
    verified = verified_records(records, all_filings())
    if verified.empty:
        raise ValueError("Verify at least one reported source cell before approval.")
    from .pdf import page_count
    path = pdf_path(filing_by_id(document_id))
    if not path.exists():
        raise ValueError("The source PDF is missing.")
    total_pages = page_count(path)
    if verified["PDF page"].astype(int).gt(total_pages).any():
        raise ValueError("A verified source page is outside the PDF.")
    plan = load_check_plan(document_id)
    _atomic_excel(records, _record_file("approved", document_id))
    target = _plan_file("approved", document_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(plan.to_json(orient="records", indent=2), encoding="utf-8")
    return len(verified)


def stage_draft_for_checks(document_id: str) -> int:
    """Send extracted candidates to Step 3 without assigning a review verdict."""
    records = load_draft(document_id)
    candidates = check_candidates(records, all_filings())
    if candidates.empty:
        raise ValueError("Extract at least one numeric source cell before Step 3.")
    from .pdf import page_count
    path = pdf_path(filing_by_id(document_id))
    if not path.exists():
        raise ValueError("The source PDF is missing.")
    if candidates["PDF page"].astype(int).gt(page_count(path)).any():
        raise ValueError("A source page is outside the PDF.")
    plan = load_check_plan(document_id)
    _atomic_excel(records, _record_file("approved", document_id))
    target = _plan_file("approved", document_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(plan.to_json(orient="records", indent=2), encoding="utf-8")
    return len(candidates)


def save_approved_check_plan(document_id: str, frame: pd.DataFrame) -> None:
    """Step 3 owns reconciliation assessments after source-cell approval."""
    if document_id not in approved_ids():
        raise ValueError("Send source cells from Step 2 to Step 3 first.")
    plan = normalize_plan(frame, all_filings(), {document_id})
    target = _plan_file("approved", document_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(plan.to_json(orient="records", indent=2), encoding="utf-8")


def approved_ids() -> list[str]:
    folder = DATA / "approved"
    return sorted(p.stem for p in folder.glob("*.xlsx")) if folder.exists() else []


def load_approved(document_id: str) -> pd.DataFrame:
    path = _record_file("approved", document_id)
    if not path.exists():
        return empty_records()
    return normalize_records(pd.read_excel(path, sheet_name="Records"), all_filings())


def apply_confirmed_repairs(document_id: str, repairs: list[dict]) -> pd.DataFrame:
    """Apply unique double-read numeric corrections with a durable before/after trail."""
    if not repairs:
        return load_approved(document_id)
    from .review_flow import source_scope_issue
    approved = load_approved(document_id)
    draft = load_draft(document_id)
    keys = [(item["Period end"], item["Metric code"]) for item in repairs]
    if len(keys) != len(set(keys)):
        raise ValueError("Automatic repair candidates contain duplicate source cells.")
    for item in repairs:
        mask = (approved["Period end"].eq(item["Period end"])
                & approved["Metric code"].eq(item["Metric code"]))
        if mask.sum() != 1:
            raise ValueError("The source cell for an automatic repair is no longer unique.")
        row = approved.loc[mask].iloc[0]
        if (int(row["PDF page"]) != item["PDF page"]
                or float(row["Original value"]) != item["Old value"]
                or source_scope_issue(str(row["Metric code"]), str(row["Source label"]),
                                      str(row.get("Column heading", "")))):
            raise ValueError("The source cell changed or its contract scope is unresolved; no repair was applied.")
        approved.loc[mask, "Original value"] = item["New value"]
        approved.loc[mask, "Reviewer note"] = (
            approved.loc[mask, "Reviewer note"].astype(str)
            + f" Auto-corrected from {item['Old value']} to {item['New value']}; "
            + item["Reason"])
        draft_mask = (draft["Period end"].eq(item["Period end"])
                      & draft["Metric code"].eq(item["Metric code"])
                      & draft["Original value"].eq(item["Old value"]))
        if draft_mask.sum() == 1:
            draft.loc[draft_mask, "Original value"] = item["New value"]
            draft.loc[draft_mask, "Reviewer note"] = (
                draft.loc[draft_mask, "Reviewer note"].astype(str)
                + f" Auto-corrected from {item['Old value']} to {item['New value']}; "
                + item["Reason"])
    approved = normalize_records(approved, all_filings())
    draft = normalize_records(draft, all_filings()) if not draft.empty else draft
    approved_path = _record_file("approved", document_id)
    draft_path = _record_file("drafts", document_id)
    before_approved = approved_path.read_bytes()
    before_draft = draft_path.read_bytes() if draft_path.exists() else None
    try:
        _atomic_excel(approved, approved_path)
        if not draft.empty:
            _atomic_excel(draft, draft_path)
    except Exception:
        approved_path.write_bytes(before_approved)
        if before_draft is None:
            draft_path.unlink(missing_ok=True)
        else:
            draft_path.write_bytes(before_draft)
        raise
    history = DATA / "history"
    history.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (history / f"auto_source_repairs_{document_id}_{stamp}.json").write_text(
        json.dumps(repairs, ensure_ascii=False, indent=2), encoding="utf-8")
    return approved


def load_published() -> pd.DataFrame:
    if not PUBLISHED_FILE.exists():
        return empty_records()
    return normalize_records(pd.read_excel(PUBLISHED_FILE, sheet_name="Records"), all_filings())


def integration_status() -> dict:
    """Identify whether the shared cross-insurer snapshot matches published data."""
    metadata_path = DATA / "integrated_metadata.json"
    integrated_path = DATA / "integrated_records.xlsx"
    if not metadata_path.exists() or not integrated_path.exists():
        return {"current": False, "integrated_at_utc": "", "cells": 0}
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(PUBLISHED_FILE.read_bytes()).hexdigest() if PUBLISHED_FILE.exists() else ""
    return {**metadata, "current": bool(source_hash) and source_hash == metadata.get("published_sha256")}


def load_integrated() -> pd.DataFrame:
    if not integration_status()["current"]:
        return empty_records()
    return standardize_hkd(normalize_records(pd.read_excel(DATA / "integrated_records.xlsx", sheet_name="Records"), all_filings()))


def integrate_published(document_ids: list[str] | None = None) -> int:
    """Materialise one reviewed, multi-insurer dataset for the analysis pages."""
    published = load_published()
    if published.empty:
        raise ValueError("Publish at least one reviewed filing in Step 3 before integration.")
    if document_ids is not None:
        selected = set(document_ids)
        available = set(published["Document ID"])
        if not selected or not selected.issubset(available):
            raise ValueError("Select at least one published filing for integration.")
        published = published[published["Document ID"].isin(selected)].copy()
    verified = verified_records(published, all_filings())
    if len(verified) != len(published):
        raise ValueError("The published store contains a cell that is not Verified and Reported.")
    keys = ["Document ID", "Period end", "Metric code"]
    if verified.duplicated(keys).any():
        raise ValueError("The published store contains conflicting source cells.")
    checks = reconciliation_checks(verified, all_filings(), plans_for_records(verified, "published"), automatic=True)
    require_resolved_checks(checks, automatic=True)
    ordered = verified.sort_values(["Company", "Document ID", "Period end", "Metric code"]).reset_index(drop=True)
    _atomic_excel(standardize_hkd(ordered), DATA / "integrated_records.xlsx")
    metadata = {
        "published_sha256": hashlib.sha256(PUBLISHED_FILE.read_bytes()).hexdigest(),
        "integrated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "integrated_epoch": time.time(),
        "document_ids": sorted(ordered["Document ID"].unique().tolist()),
        "cells": len(ordered),
        "insurers": int(ordered["Company ID"].nunique()),
    }
    (DATA / "integrated_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return len(ordered)


def publish_selected(document_ids: list[str], *, checked_candidates: bool = False) -> int:
    """Replace matching cells and preserve all unrelated published filings."""
    if not document_ids:
        raise ValueError("Select an approved workbook.")
    filings = all_filings()
    select = check_candidates if checked_candidates else verified_records
    incoming = pd.concat([select(load_approved(i), filings) for i in document_ids], ignore_index=True)
    if incoming.empty:
        raise ValueError("The selected workbooks contain no verified reported cells.")
    keys = ["Document ID", "Period end", "Metric code"]
    if incoming.duplicated(keys).any():
        raise ValueError("Selected workbooks contain conflicting duplicate cells.")
    check_plan = plans_for_records(incoming, "approved")
    checks = reconciliation_checks(incoming, filings, check_plan,
                                   verified_only=not checked_candidates, automatic=True)
    require_resolved_checks(checks, automatic=True)
    from .checks import automatic_arithmetic_checks
    from .review_flow import per_cell_checks
    from .source_audit import source_results
    for document_id, group in incoming.groupby("Document ID"):
        source = pdf_path(filing_by_id(document_id))
        pages = {page for page, _ in load_confirmed_pages(document_id, source)}
        source_checks = source_results(group, source, load_source_audit(document_id))
        cell_checks = per_cell_checks(
            group, checks[checks["Document ID"].eq(document_id)],
            automatic_arithmetic_checks(group, filings, check_plan,
                                        verified_only=not checked_candidates),
            allow_pending=checked_candidates, confirmed_pages=pages,
            source_audit=source_checks)
        bad = cell_checks[cell_checks["Cell result"].eq("Investigate")]
        if not bad.empty:
            first = bad.iloc[0]
            raise ValueError(f"{len(bad)} source cells need investigation; first: "
                             f"{first['Period end']} {first['Metric code']} "
                             f"PDF p.{first['Physical PDF page']}; "
                             f"image check: {first['PDF image check']}.")
    if checked_candidates:
        for document_id in document_ids:
            pending = incoming["Document ID"].eq(document_id) & incoming["Review status"].eq("Pending")
            filing = filing_by_id(document_id)
            current_year = str(filing["period_end"])[:4]
            needs_audit_label = pending & incoming["Audit status"].isin(("", "Check source"))
            incoming.loc[needs_audit_label, "Audit status"] = incoming.loc[needs_audit_label, "Period end"].apply(
                lambda period: "Audited statement" if str(period)[:4] == current_year
                else f"Comparative in {current_year} statement")
            incoming.loc[pending, "Review status"] = "Verified"
        incoming = normalize_records(incoming, filings)
    current = load_published()
    # Publishing a reviewed filing replaces its entire previous published
    # snapshot, so a newly Excluded cell cannot survive from an older version.
    if not current.empty:
        current = current[~current["Document ID"].isin(document_ids)]
    combined = normalize_records(
        incoming if current.empty else pd.concat([current, incoming], ignore_index=True),
        filings,
    )
    if PUBLISHED_FILE.exists():
        history = DATA / "history"
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (history / f"published_{stamp}.xlsx").write_bytes(PUBLISHED_FILE.read_bytes())
    old_published = PUBLISHED_FILE.read_bytes() if PUBLISHED_FILE.exists() else None
    integrated_file = DATA / "integrated_records.xlsx"
    metadata_file = DATA / "integrated_metadata.json"
    old_integrated = integrated_file.read_bytes() if integrated_file.exists() else None
    old_metadata = metadata_file.read_bytes() if metadata_file.exists() else None
    old_plans = {document_id: (_plan_file("published", document_id).read_bytes()
                               if _plan_file("published", document_id).exists() else None)
                 for document_id in document_ids}
    _atomic_excel(combined, PUBLISHED_FILE)
    for document_id in document_ids:
        source = _plan_file("approved", document_id)
        target = _plan_file("published", document_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    try:
        integrate_published()
    except Exception:
        for target, old in ((PUBLISHED_FILE, old_published),
                            (integrated_file, old_integrated),
                            (metadata_file, old_metadata)):
            if old is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(old)
        for document_id, old in old_plans.items():
            target = _plan_file("published", document_id)
            if old is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(old)
        raise
    return len(incoming)
