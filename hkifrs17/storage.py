"""Small local stores for a single-machine demonstration."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

import pandas as pd

from .catalog import PILOT_FILINGS
from .data import COLUMNS, empty_records, normalize_records, reconciliation_checks, standardize_hkd, verified_records
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
                    scope: str, period_end: str, currency: str, source_unit: str) -> dict:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a PDF.")
    from datetime import date
    date.fromisoformat(period_end)
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


def approve_draft(document_id: str) -> int:
    records = load_draft(document_id)
    if records.empty:
        raise ValueError("There is no draft to approve.")
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
    checks = reconciliation_checks(records, all_filings(), plan, verified_only=True)
    require_resolved_checks(checks)
    _atomic_excel(records, _record_file("approved", document_id))
    target = _plan_file("approved", document_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(plan.to_json(orient="records", indent=2), encoding="utf-8")
    return len(verified)


def approved_ids() -> list[str]:
    folder = DATA / "approved"
    return sorted(p.stem for p in folder.glob("*.xlsx")) if folder.exists() else []


def load_approved(document_id: str) -> pd.DataFrame:
    path = _record_file("approved", document_id)
    if not path.exists():
        return empty_records()
    return normalize_records(pd.read_excel(path, sheet_name="Records"), all_filings())


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


def integrate_published() -> int:
    """Materialise one reviewed, multi-insurer dataset for the analysis pages."""
    published = load_published()
    if published.empty:
        raise ValueError("Publish at least one reviewed filing in Step 3 before integration.")
    verified = verified_records(published, all_filings())
    if len(verified) != len(published):
        raise ValueError("The published store contains a cell that is not Verified and Reported.")
    keys = ["Document ID", "Period end", "Metric code"]
    if verified.duplicated(keys).any():
        raise ValueError("The published store contains conflicting source cells.")
    checks = reconciliation_checks(verified, all_filings(), plans_for_records(verified, "published"))
    require_resolved_checks(checks)
    ordered = verified.sort_values(["Company", "Document ID", "Period end", "Metric code"]).reset_index(drop=True)
    _atomic_excel(standardize_hkd(ordered), DATA / "integrated_records.xlsx")
    metadata = {
        "published_sha256": hashlib.sha256(PUBLISHED_FILE.read_bytes()).hexdigest(),
        "integrated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "cells": len(ordered),
        "insurers": int(ordered["Company ID"].nunique()),
    }
    (DATA / "integrated_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return len(ordered)


def publish_selected(document_ids: list[str]) -> int:
    """Replace matching cells and preserve all unrelated published filings."""
    if not document_ids:
        raise ValueError("Select an approved workbook.")
    incoming = pd.concat([verified_records(load_approved(i), all_filings()) for i in document_ids], ignore_index=True)
    if incoming.empty:
        raise ValueError("The selected workbooks contain no verified reported cells.")
    keys = ["Document ID", "Period end", "Metric code"]
    if incoming.duplicated(keys).any():
        raise ValueError("Selected workbooks contain conflicting duplicate cells.")
    checks = reconciliation_checks(incoming, all_filings(), plans_for_records(incoming, "approved"))
    require_resolved_checks(checks)
    current = load_published()
    # Publishing a reviewed filing replaces its entire previous published
    # snapshot, so a newly Excluded cell cannot survive from an older version.
    if not current.empty:
        current = current[~current["Document ID"].isin(document_ids)]
    combined = normalize_records(
        incoming if current.empty else pd.concat([current, incoming], ignore_index=True),
        all_filings(),
    )
    if PUBLISHED_FILE.exists():
        history = DATA / "history"
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (history / f"published_{stamp}.xlsx").write_bytes(PUBLISHED_FILE.read_bytes())
    _atomic_excel(combined, PUBLISHED_FILE)
    for document_id in document_ids:
        source = _plan_file("approved", document_id)
        target = _plan_file("published", document_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return len(incoming)
