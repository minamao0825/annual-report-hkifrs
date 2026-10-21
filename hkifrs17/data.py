"""Canonical records, unit conversion, and publication checks."""

from __future__ import annotations

from datetime import date
import math

import pandas as pd

from .catalog import METRIC_BY_CODE
from .fx import year_end_usd_hkd


COLUMNS = [
    "Document ID", "Company ID", "Company", "Legal entity", "Scope", "Period end",
    "Metric code", "Metric", "Section", "Original value", "Source unit", "Currency",
    "Value (millions)", "Value status", "PDF page", "Source label", "Audit status",
    "Review status", "Reviewer note",
]
REVIEW_STATUSES = ("Pending", "Verified", "Excluded")
VALUE_STATUSES = ("Reported", "Not disclosed", "Not applicable")
UNIT_FACTORS = {
    "HKD": ("HKD", 1e-6),
    "HKD thousands": ("HKD", 1e-3),
    "HKD millions": ("HKD", 1.0),
    "USD": ("USD", 1e-6),
    "USD thousands": ("USD", 1e-3),
    "USD millions": ("USD", 1.0),
    "percent": ("%", 1.0),
}


def empty_records() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def as_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(float(value)) else None
    raw = str(value).strip().replace(",", "")
    if raw in {"", "-", "—"}:
        return None
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    try:
        numeric = float(raw)
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def normalize_records(frame: pd.DataFrame, filings: list[dict]) -> pd.DataFrame:
    """Validate source identity and recompute chart values from reviewed originals."""
    if frame is None or frame.empty:
        return empty_records()
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
    documents = {item["document_id"]: item for item in filings}
    result = frame[COLUMNS].copy().reset_index(drop=True)
    for idx, row in result.iterrows():
        document_id = str(row["Document ID"]).strip()
        document = documents.get(document_id)
        if document is None:
            raise ValueError(f"Row {idx + 2}: unknown document ID {document_id!r}.")
        code = str(row["Metric code"]).strip()
        metric = METRIC_BY_CODE.get(code)
        if metric is None:
            raise ValueError(f"Row {idx + 2}: unknown metric code {code!r}.")
        period = str(row["Period end"]).strip()
        try:
            period_date = date.fromisoformat(period)
        except ValueError as exc:
            raise ValueError(f"Row {idx + 2}: invalid period end.") from exc
        document_date = date.fromisoformat(document["period_end"])
        if period_date.month != document_date.month or period_date.day != document_date.day:
            raise ValueError(f"Row {idx + 2}: period end does not match this filing's year end.")
        if period_date.year > document_date.year or period_date.year < document_date.year - 1:
            raise ValueError(f"Row {idx + 2}: only the current year and comparative year are supported.")
        unit = str(row["Source unit"]).strip()
        if unit not in UNIT_FACTORS:
            raise ValueError(f"Row {idx + 2}: unsupported source unit {unit!r}.")
        currency, factor = UNIT_FACTORS[unit]
        if metric.kind == "rate" and unit != "percent":
            raise ValueError(f"Row {idx + 2}: percentage disclosure requires source unit 'percent'.")
        if metric.kind != "rate" and currency != document["currency"]:
            raise ValueError(f"Row {idx + 2}: unit currency conflicts with the filing.")
        status = str(row["Value status"]).strip()
        review = str(row["Review status"]).strip()
        if status not in VALUE_STATUSES or review not in REVIEW_STATUSES:
            raise ValueError(f"Row {idx + 2}: invalid value or review status.")
        original = as_number(row["Original value"])
        if status == "Reported" and original is None:
            raise ValueError(f"Row {idx + 2}: a reported item needs a numeric original value.")
        if status != "Reported" and original is not None:
            raise ValueError(f"Row {idx + 2}: a non-reported item must have a blank value.")
        raw_page = row["PDF page"]
        if status != "Reported" and (pd.isna(raw_page) or str(raw_page).strip() == ""):
            page = None
        else:
            try:
                page = int(raw_page)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Row {idx + 2}: invalid PDF page.") from exc
            if page < 1:
                raise ValueError(f"Row {idx + 2}: PDF page must be positive.")
        if review == "Verified" and not str(row["Source label"]).strip():
            raise ValueError(f"Row {idx + 2}: verified items need a source label.")
        if review == "Verified" and (pd.isna(row["Audit status"]) or str(row["Audit status"]).strip() in {"", "Check source"}):
            raise ValueError(f"Row {idx + 2}: confirm the source audit status before verification.")
        result.at[idx, "Document ID"] = document_id
        result.at[idx, "Company ID"] = document["company_id"]
        result.at[idx, "Company"] = document["company"]
        result.at[idx, "Legal entity"] = document["legal_entity"]
        result.at[idx, "Scope"] = document["scope"]
        result.at[idx, "Metric code"] = code
        result.at[idx, "Metric"] = metric.label
        result.at[idx, "Section"] = metric.section
        result.at[idx, "Period end"] = period
        result.at[idx, "Original value"] = original
        result.at[idx, "Currency"] = currency
        result.at[idx, "Value (millions)"] = original * factor if original is not None else None
        result.at[idx, "PDF page"] = page
        result.at[idx, "Review status"] = review
        result.at[idx, "Value status"] = status
        result.at[idx, "Source unit"] = unit
        for column in ("Source label", "Audit status", "Reviewer note"):
            result.at[idx, column] = "" if pd.isna(row[column]) else str(row[column]).strip()
    keys = ["Document ID", "Period end", "Metric code"]
    if result.duplicated(keys).any():
        raise ValueError("Duplicate document / period / metric cells must be resolved before saving.")
    return result


def standardize_hkd(result: pd.DataFrame) -> pd.DataFrame:
    """Add a derived HKD comparison value without changing the source schema."""
    if result.empty:
        return result.copy().assign(**{"HKD value (millions)": pd.Series(dtype=float),
                                      "USD/HKD rate": pd.Series(dtype=float),
                                      "FX rate date": pd.Series(dtype=str),
                                      "FX source": pd.Series(dtype=str)})
    result = result.copy()
    # Preserve source currency and units. This separate presentation value is
    # recomputed on every import/integration from the matching calendar year.
    result["HKD value (millions)"] = pd.NA
    result["USD/HKD rate"] = pd.NA
    result["FX rate date"] = ""
    result["FX source"] = ""
    money = result["Currency"].isin(["HKD", "USD"]) & result["Value (millions)"].notna()
    hkd = money & result["Currency"].eq("HKD")
    result.loc[hkd, "HKD value (millions)"] = result.loc[hkd, "Value (millions)"]
    for year in sorted({int(value[:4]) for value in result.loc[money & result["Currency"].eq("USD"), "Period end"]}):
        rate_info = year_end_usd_hkd(year)
        if rate_info is None:
            continue
        rate, day, source = rate_info
        usd = money & result["Currency"].eq("USD") & result["Period end"].str.startswith(str(year))
        result.loc[usd, "HKD value (millions)"] = result.loc[usd, "Value (millions)"] * rate
        result.loc[usd, "USD/HKD rate"] = rate
        result.loc[usd, "FX rate date"] = day
        result.loc[usd, "FX source"] = source
    result["HKD value (millions)"] = pd.to_numeric(result["HKD value (millions)"], errors="coerce")
    result["USD/HKD rate"] = pd.to_numeric(result["USD/HKD rate"], errors="coerce")
    return result.astype({"HKD value (millions)": "float64", "USD/HKD rate": "float64"})


def verified_records(frame: pd.DataFrame, filings: list[dict]) -> pd.DataFrame:
    rows = normalize_records(frame, filings)
    return rows[(rows["Review status"] == "Verified") & (rows["Value status"] == "Reported")].copy()


def reconciliation_checks(frame: pd.DataFrame, filings: list[dict], plan: pd.DataFrame | None = None,
                          *, verified_only: bool = False) -> pd.DataFrame:
    from .checks import evaluate_checks
    return evaluate_checks(frame, filings, plan, verified_only=verified_only)
