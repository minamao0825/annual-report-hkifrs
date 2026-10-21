"""Comparable Financial Highlights ratios from reviewed filing cells."""

from __future__ import annotations

import math
import json
from pathlib import Path

import pandas as pd


HIGHLIGHT_COLUMNS = (
    ("Net assets growth", "Closing net assets / Opening net assets − 1"),
    ("Net profit growth", "Current year profit / Prior year profit − 1"),
    ("CSM growth", "Current year closing CSM / Prior year closing CSM − 1"),
    ("New business CSM growth", "Current year new business CSM / Prior year new business CSM − 1"),
    ("CSM amortization ratio", "CSM amortization / CSM before amortization"),
    ("CSM replenishment ratio", "New business CSM / CSM amortization"),
    ("Insurance service revenue growth", "Current year revenue / Prior year revenue − 1"),
    ("Net insurance contract liabilities growth", "Current year net liabilities / Prior year net liabilities − 1"),
)


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return 100 * (current / prior - 1)


def _net_liability(values: dict[str, float]) -> float | None:
    # Statement balances use positive liabilities and positive assets.
    if "INS_LIABS" not in values or "INS_ASSETS" not in values:
        return None
    return values["INS_LIABS"] - values["INS_ASSETS"]


def _source_comparatives() -> list[dict]:
    """PDF-checked cells used only by Financial Highlights, with audit provenance."""
    path = Path(__file__).resolve().parents[1] / "data" / "financial_highlights_source_cells.json"
    return json.loads(path.read_text(encoding="utf-8"))


def financial_highlights_source_rows(companies: list[str], current_period: str) -> pd.DataFrame:
    """Show the supplemental PDF cells and audit basis used for this table."""
    prior_period = f"{int(current_period[:4]) - 1}{current_period[4:]}"
    rows = [cell for cell in _source_comparatives()
            if cell["company"] in companies and cell["period"] in {prior_period, current_period}]
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    return frame.rename(columns={
        "company": "Company", "period": "Period", "metric_code": "Metric code",
        "value_millions": "Value (millions)", "source_document": "Source filing",
        "pdf_page": "PDF page", "source_label": "Source label",
        "audit_status": "Audit status", "scope": "Scope", "currency": "Currency",
    })


def financial_highlights_table(records: pd.DataFrame, companies: list[str],
                               current_period: str, *,
                               include_source_comparatives: bool = False) -> pd.DataFrame:
    """Use like-scope, like-currency periods only; missing inputs stay blank."""
    prior_period = f"{int(current_period[:4]) - 1}{current_period[4:]}"
    supplements = _source_comparatives() if include_source_comparatives else []
    output = []
    for company in companies:
        company_rows = records[records["Company"].eq(company)]
        if not company_rows["Period end"].astype(str).eq(current_period).any():
            continue
        values = {}
        identities = {}
        for period in (prior_period, current_period):
            group = company_rows[company_rows["Period end"].astype(str).eq(period)]
            numeric = group.copy()
            numeric["Value (millions)"] = pd.to_numeric(numeric["Value (millions)"], errors="coerce")
            numeric = numeric.dropna(subset=["Value (millions)"])
            values[period] = dict(zip(numeric["Metric code"], numeric["Value (millions)"]))
            monetary = group[group["Currency"].ne("%")]
            identities[period] = set(zip(monetary["Scope"], monetary["Currency"]))
            for cell in supplements:
                if cell["company"] == company and cell["period"] == period:
                    # Supplemental cells never replace reviewed canonical cells.
                    values[period].setdefault(cell["metric_code"], cell["value_millions"])
                    identities[period].add((cell["scope"], cell["currency"]))
            # Some insurers disclose CSM releases by transition category.
            # Add only the two matching insurance CSM components.
            if "CSM_RELEASE" not in values[period] and all(
                code in values[period] for code in ("INS_CSM_FV_RELEASE", "INS_CSM_OTHER_RELEASE")
            ):
                values[period]["CSM_RELEASE"] = (
                    values[period]["INS_CSM_FV_RELEASE"] + values[period]["INS_CSM_OTHER_RELEASE"]
                )
        now, previous = values[current_period], values[prior_period]
        comparable = (len(identities[current_period]) == 1 and
                      identities[current_period] == identities[prior_period])
        if not comparable:
            previous = {}
        equity = _growth(now.get("EQUITY"), now.get("EQUITY_OPEN"))
        profit = _growth(now.get("PROFIT"), previous.get("PROFIT"))
        csm = _growth(abs(now["CSM_CLOSE"]) if "CSM_CLOSE" in now else None,
                      abs(previous["CSM_CLOSE"]) if "CSM_CLOSE" in previous else None)
        nb_csm = _growth(abs(now["CSM_NEW"]) if "CSM_NEW" in now else None,
                         abs(previous["CSM_NEW"]) if "CSM_NEW" in previous else None)
        close = abs(now["CSM_CLOSE"]) if "CSM_CLOSE" in now else None
        release = abs(now["CSM_RELEASE"]) if "CSM_RELEASE" in now else None
        new = abs(now["CSM_NEW"]) if "CSM_NEW" in now else None
        amortization = (100 * release / (close + release)
                        if close is not None and release is not None and close + release else None)
        persistence = (100 * new / release if new is not None and release else None)
        revenue = _growth(now.get("INS_REVENUE"), previous.get("INS_REVENUE"))
        net_liability = _growth(_net_liability(now), _net_liability(previous))
        row = {"Company": company}
        for (label, _), value in zip(HIGHLIGHT_COLUMNS, (
            equity, profit, csm, nb_csm, amortization, persistence, revenue, net_liability,
        )):
            row[label] = round(value) if value is not None and math.isfinite(value) else None
        output.append(row)
    return pd.DataFrame(output, columns=["Company", *(label for label, _ in HIGHLIGHT_COLUMNS)])
