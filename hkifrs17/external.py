"""Validated external workbook overlay shared by Steps 5 and 6."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import time

import pandas as pd

from .checks import RULE_BY_ID, evaluate_checks, normalize_plan
from .data import LEGACY_COLUMNS, NUMERIC_VALUE_STATUSES, empty_records, normalize_records
from .storage import DATA, EXTERNAL_FILINGS_FILE, all_filings, integration_status, load_integrated


EXTERNAL_RECORDS_FILE = DATA / "external_records.json"
EXTERNAL_IMPORTS_FILE = DATA / "external_imports.json"


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".external_", suffix=".json", dir=path.parent)
    os.close(handle)
    try:
        Path(temporary).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _new_profiles(frame: pd.DataFrame) -> list[dict]:
    known = {item["document_id"] for item in all_filings()}
    profiles = []
    for document_id, group in frame.groupby("Document ID", sort=False):
        document_id = str(document_id).strip()
        if document_id in known:
            continue
        if not document_id.replace("_", "").isalnum():
            raise ValueError(f"Invalid external document ID: {document_id!r}.")
        fields = ["Company ID", "Company", "Legal entity", "Scope", "Period end", "Currency"]
        for field in fields:
            if group[field].isna().any() or group[field].astype(str).str.strip().eq("").any():
                raise ValueError(f"{document_id}: missing {field}.")
        money = group[group["Source unit"].ne("percent")]
        for field in fields[:-2]:
            if group[field].astype(str).nunique() != 1:
                raise ValueError(f"{document_id}: conflicting {field} values.")
        if not money.empty and money["Currency"].astype(str).nunique() != 1:
            raise ValueError(f"{document_id}: conflicting Currency values.")
        periods = sorted(group["Period end"].astype(str).unique())
        if len({period[5:] for period in periods}) != 1:
            raise ValueError(f"{document_id}: reporting dates have different year ends.")
        source_unit = str(money.iloc[0]["Source unit"]) if not money.empty else "percent"
        profiles.append({
            "document_id": document_id,
            "company_id": str(group.iloc[0]["Company ID"]).strip(),
            "company": str(group.iloc[0]["Company"]).strip(),
            "legal_entity": str(group.iloc[0]["Legal entity"]).strip(),
            "scope": str(group.iloc[0]["Scope"]).strip(),
            "period_end": periods[-1],
            "currency": str(money.iloc[0]["Currency"]).strip() if not money.empty else "%",
            "source_unit": source_unit,
            "pdf_file": "",
            "note": "Imported external workbook; source PDF is not stored in the platform.",
        })
    return profiles


def validate_external_workbook(workbook_bytes: bytes) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    """Recompute canonical values and checks; never trust a workbook's Checks tab."""
    if not workbook_bytes.startswith(b"PK"):
        raise ValueError("Upload an .xlsx workbook with a Records sheet.")
    with pd.ExcelFile(BytesIO(workbook_bytes)) as workbook:
        if "Records" not in workbook.sheet_names:
            raise ValueError("The workbook needs a Records sheet.")
        raw = pd.read_excel(workbook, sheet_name="Records", dtype={"Document ID": str, "Period end": str})
        # Older reviewed workbooks predate the six optional image-evidence
        # columns. normalize_records keeps those fields blank rather than
        # inventing source evidence that the workbook does not contain.
        missing = set(LEGACY_COLUMNS) - set(raw.columns)
        if missing:
            raise ValueError("Records is missing columns: " + ", ".join(sorted(missing)))
        if raw.empty:
            raise ValueError("Records contains no source cells.")
        profiles = _new_profiles(raw)
        filings = [*all_filings(), *profiles]
        records = normalize_records(raw, filings)
        reported = records["Value status"].isin(NUMERIC_VALUE_STATUSES)
        if not records.loc[reported, "Review status"].eq("Verified").all():
            raise ValueError("Reported and derived cells must be Verified before import into analysis.")
        # Aligned workbooks may include blank Not disclosed rows so every
        # insurer has the same metric list. They are audit markers, not values.
        records = records.loc[reported].copy()
        if records.empty:
            raise ValueError("Records contains no verified reported values.")
        plan = None
        if "Check plan" in workbook.sheet_names:
            supplied = pd.read_excel(workbook, sheet_name="Check plan", dtype={"Document ID": str, "Period end": str}).fillna("")
            plan = normalize_plan(supplied, filings, set(records["Document ID"]))
        checks = evaluate_checks(records, filings, plan, verified_only=True)
        mandatory = {rule.id for rule in RULE_BY_ID.values() if rule.mandatory}
        blocking = checks[
            (checks["Result"].eq("Difference")) |
            (checks["Check ID"].isin(mandatory) & ~checks["Result"].eq("Pass"))
        ]
        if not blocking.empty:
            summary = blocking[["Document ID", "Period end", "Check ID", "Result"]].to_dict("records")
            raise ValueError(f"Resolve failed primary checks or differences before import: {summary}")
        return records, profiles, checks


def load_external() -> pd.DataFrame:
    if not EXTERNAL_RECORDS_FILE.exists():
        return empty_records()
    rows = pd.DataFrame(json.loads(EXTERNAL_RECORDS_FILE.read_text(encoding="utf-8")))
    return normalize_records(rows, all_filings())


def save_external_workbook(workbook_bytes: bytes) -> tuple[int, pd.DataFrame]:
    records, profiles, checks = validate_external_workbook(workbook_bytes)
    current = load_external()
    old_epoch = EXTERNAL_RECORDS_FILE.stat().st_mtime if EXTERNAL_RECORDS_FILE.exists() else 0.0
    import_times = (json.loads(EXTERNAL_IMPORTS_FILE.read_text(encoding="utf-8"))
                    if EXTERNAL_IMPORTS_FILE.exists() else {})
    for document_id in current["Document ID"].unique() if not current.empty else []:
        import_times.setdefault(str(document_id), old_epoch)
    if not current.empty:
        # A workbook is one complete filing snapshot. Old comparative cells
        # from that document must not survive a current-year-only replacement.
        current = current[~current["Document ID"].isin(records["Document ID"])].copy()
    combined = records if current.empty else pd.concat([current, records], ignore_index=True)
    combined = normalize_records(combined, [*all_filings(), *profiles])
    if profiles:
        prior = json.loads(EXTERNAL_FILINGS_FILE.read_text(encoding="utf-8")) if EXTERNAL_FILINGS_FILE.exists() else []
        _atomic_json(EXTERNAL_FILINGS_FILE, [*prior, *profiles])
    _atomic_json(EXTERNAL_RECORDS_FILE, combined.where(pd.notna(combined), None).to_dict("records"))
    for document_id in records["Document ID"].unique():
        import_times[str(document_id)] = time.time()
    _atomic_json(EXTERNAL_IMPORTS_FILE, import_times)
    return len(records), checks


def load_analysis_records() -> pd.DataFrame:
    """Use the latest reviewed snapshot for each filing on both report pages."""
    base = load_integrated()
    external = load_external()
    if external.empty:
        return base
    if base.empty:
        return external
    status = integration_status()
    integrated_file = DATA / "integrated_records.xlsx"
    integrated_epoch = status.get("integrated_epoch")
    if integrated_epoch is None:
        # Legacy integration metadata recorded the actual UTC build time but
        # not an epoch. A copied or downloaded workbook has a newer filesystem
        # mtime, which must not make an older integration replace a later import.
        stamp = str(status.get("integrated_at_utc") or "").strip()
        if stamp:
            built_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if built_at.tzinfo is None:
                built_at = built_at.replace(tzinfo=timezone.utc)
            integrated_epoch = built_at.timestamp()
        else:
            integrated_epoch = integrated_file.stat().st_mtime if integrated_file.exists() else 0.0
    integrated_epoch = float(integrated_epoch)
    old_epoch = EXTERNAL_RECORDS_FILE.stat().st_mtime if EXTERNAL_RECORDS_FILE.exists() else 0.0
    import_times = (json.loads(EXTERNAL_IMPORTS_FILE.read_text(encoding="utf-8"))
                    if EXTERNAL_IMPORTS_FILE.exists() else {})
    integrated_ids = set(base["Document ID"])
    newer_external = {
        document_id for document_id in set(external["Document ID"])
        if document_id not in integrated_ids or
        float(import_times.get(document_id, old_epoch)) > integrated_epoch
    }
    external = external[external["Document ID"].isin(newer_external)].copy()
    base = base[~base["Document ID"].isin(newer_external)].copy()
    if base.empty:
        return external
    if external.empty:
        return base
    return normalize_records(pd.concat([base, external], ignore_index=True), all_filings())
