"""Investment-note bridges for the three reviewed 2024–2025 filings.

The note cells below are kept separate from the canonical profit-or-loss
records: FWD and YF notes include OCI, whereas Sun Life Note 10 does not.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd


RETURN_COMPONENTS = (
    "Interest revenue / income",
    "Other investment income and gains/(losses)",
    "Impairment and write-offs",
    "Amounts recognised in OCI",
)
RESULT_COMPONENTS = (
    "Total investment return / net investment income",
    "Insurance contract finance result",
    "Reinsurance contract finance result",
    "Investment-contract liability movement",
)
RESULT_REPRESENTATION = (
    "Amounts recognised in profit or loss",
    "Amounts recognised in OCI",
)
TOTAL_LABELS = {
    "return_total": "Investment return / net investment income",
    "result_total": "Net investment / financial result",
    "return_pl_total": "Investment return / net investment income",
    "finance_pl_total": "Net insurance and reinsurance finance result",
    "result_pl_total": "Net investment / financial result",
}
PL_VIEWS = frozenset({
    "return_pl_total", "return_pl_components", "finance_pl_total",
    "result_pl_total", "result_pl_components",
})
NET_FINANCE_FORMULA = (
    "Formula: Net insurance and reinsurance finance result (P&L) = "
    "insurance contract finance result (P&L) + reinsurance contract finance result (P&L). "
    "Negative values are net finance expenses."
)
NET_INVESTMENT_FORMULA = (
    "Formula: Reported net investment result (P&L) = investment return / net investment income (P&L) "
    "+ insurance contract finance result (P&L) + reinsurance contract finance result (P&L) "
    "+ investment-contract liability movement (where separately presented)."
)
def net_investment_explanations(companies) -> list[str]:
    """Show each insurer's presentation difference only while it is selected."""
    names = set(companies)
    notes = []
    for company in ("FWD Life Bermuda", "YF Life"):
        if company in names:
            notes.append(
                f"{company}: the three-line subtotal is higher than the reported P&L result "
                "because the investment-contract liability movement is negative."
            )
    if "Sun Life Hong Kong" in names:
        notes.append(
            "Sun Life Hong Kong: the investment-contract liability movement is already "
            "included within net investment income, so it is not added again."
        )
    return notes
_NOTE_FILE = Path(__file__).resolve().parents[1] / "data" / "investment_note_components.json"
_COLUMNS = (
    "Document ID", "Company", "Scope", "Period end", "Period", "Currency",
    "Metric", "Amount", "Stack order", "Reported total", "Calculation detail",
    "Presentation basis", "Note reference", "View",
)


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0, abs_tol=0.001001)


def _number(value: float) -> str:
    return f"{value:,.3f}".replace("-", "−")


def _validated_notes(frame: pd.DataFrame):
    if frame.empty:
        return
    notes = json.loads(_NOTE_FILE.read_text(encoding="utf-8"))
    lookup = {(item["document_id"], item["period"]): item for item in notes}
    keys = ["Document ID", "Company", "Scope", "Period end", "Currency"]
    for identity, group in frame.groupby(keys, sort=False, dropna=False):
        note = lookup.get((str(identity[0]), str(identity[3])))
        if note is None or tuple(note[field] for field in (
                "document_id", "company", "scope", "period", "currency")) != (
                str(identity[0]), str(identity[1]), str(identity[2]), str(identity[3]), str(identity[4])):
            continue
        cells = group.loc[group["Metric code"].isin({
            "INV_RETURN", "NET_INV_INCOME", "INS_FINANCE_PL", "REINS_FINANCE_PL",
            "NET_INV_RESULT", "INV_RETURN_TOTAL", "NET_INV_RESULT_TOTAL",
        })]
        if cells["Metric code"].duplicated().any():
            continue
        cells = cells.set_index("Metric code")
        return_code = "NET_INV_INCOME" if identity[1] == "Sun Life Hong Kong" else "INV_RETURN"
        required = {return_code, "INS_FINANCE_PL", "REINS_FINANCE_PL", "NET_INV_RESULT"}
        if not required.issubset(cells.index):
            continue
        if "Review status" in cells and not cells.loc[list(required), "Review status"].eq("Verified").all():
            continue
        values = pd.to_numeric(cells["Value (millions)"], errors="coerce")
        if not all(math.isfinite(float(values[code])) for code in required):
            continue
        current = note["return"]
        result = note["result"]
        is_sun = identity[1] == "Sun Life Hong Kong"
        if is_sun:
            other = sum(float(current[code]) for code in (
                "dividend_other", "gains", "liability_within_income", "subsidiary_dividend"
            ))
            impairment = float(current["credit_loss_reversal"]) + float(current["write_off"])
            return_parts = (float(current["interest"]), other, impairment)
            return_detail = (
                "Total interest income in Note 10.",
                "Dividend and other income + realised/unrealised gains + the investment-contract "
                f"liability movement + subsidiary dividend = {_number(other)} {identity[4]} million. "
                "FVTOCI/FVTPL are instrument categories, not OCI.",
                "Expected-credit-loss reversal plus write-off in Note 10.",
            )
        else:
            return_parts = tuple(float(current[code]) for code in (
                "interest", "other", "impairment", "oci"
            ))
            return_detail = (
                "Interest revenue disclosed in the investment result note.",
                "Other investment revenue or gains/(losses) in the investment result note.",
                "Net impairment loss on financial assets in the investment result note.",
                "Investment return recognised in OCI, separate from P&L investment return.",
            )
        return_pl = sum(return_parts[:3])
        if not _close(return_pl, float(values[return_code])) or not _close(
                sum(return_parts), float(current["total"])):
            continue
        result_parts = tuple(float(result[code]) for code in (
            "investment_return", "insurance_finance", "reinsurance_finance"
        ))
        if not is_sun:
            result_parts += (float(result["investment_contract_liabilities"]),)
        result_pl = float(values["NET_INV_RESULT"])
        liability_outside_return = 0.0 if is_sun else result_parts[3]
        pl_parts = (return_pl, float(values["INS_FINANCE_PL"]),
                    float(values["REINS_FINANCE_PL"]))
        if not is_sun:
            pl_parts += (liability_outside_return,)
        if not all((
            _close(result_parts[0], float(current["total"])),
            _close(sum(result_parts), float(result["total"])),
            _close(sum(pl_parts), result_pl),
        )):
            continue
        # Only compare canonical note totals from the *same filing*. The YF
        # 2024 note rows below intentionally use the 2025 filing's comparative
        # presentation, which includes an investment OCI line omitted in the
        # standalone 2024 note's investment-return subtotal.
        if note["source_document_id"] == note["document_id"]:
            for code, total in (("INV_RETURN_TOTAL", current["total"]),
                                ("NET_INV_RESULT_TOTAL", result["total"])):
                if code in values and pd.notna(values[code]) and not _close(float(values[code]), float(total)):
                    break
            else:
                yield identity, note, return_parts, return_detail, result_parts, result_pl, pl_parts
        else:
            yield identity, note, return_parts, return_detail, result_parts, result_pl, pl_parts


def investment_note_rows(frame: pd.DataFrame, view: str) -> pd.DataFrame:
    """Return source-checked total bars and signed stacks for one note view."""
    if view not in {"return_total", "return_components", "result_total",
                    "result_components", "result_representation"} | PL_VIEWS:
        raise ValueError(f"Unknown investment note view: {view}")
    output: list[dict] = []
    for identity, note, return_parts, return_detail, result_parts, result_pl, pl_parts in _validated_notes(frame):
        is_sun = identity[1] == "Sun Life Hong Kong"
        basis = "Profit or loss only" if is_sun or view in PL_VIEWS else "Profit or loss and OCI"
        investment_return_total = float(note["return"]["total"])
        result_total = float(note["result"]["total"])
        if view == "return_pl_total":
            labels = (TOTAL_LABELS[view],)
            amounts = (sum(return_parts[:3]),)
            details = ("Investment return or net investment income recognised in profit or loss; OCI excluded.",)
            total = amounts[0]
        elif view == "return_pl_components":
            labels = RETURN_COMPONENTS[:3]
            amounts = return_parts[:3]
            details = return_detail[:3]
            total = sum(amounts)
        elif view == "finance_pl_total":
            labels = (TOTAL_LABELS[view],)
            amounts = (pl_parts[1] + pl_parts[2],)
            details = ("Signed insurance plus reinsurance contract finance results in profit or loss; OCI excluded.",)
            total = amounts[0]
        elif view == "result_pl_total":
            labels = (TOTAL_LABELS[view],)
            amounts = (result_pl,)
            details = ("Reported net investment / financial result in profit or loss; OCI excluded.",)
            total = result_pl
        elif view == "result_pl_components":
            labels = RESULT_COMPONENTS[:3] if is_sun else RESULT_COMPONENTS
            amounts = pl_parts
            details = (
                "Investment return or net investment income recognised in profit or loss.",
                "Insurance contract finance result recognised in profit or loss.",
                "Reinsurance contract finance result recognised in profit or loss.",
            ) + (() if is_sun else (
                "Separately disclosed movement in investment-contract liabilities.",
            ))
            total = result_pl
        elif view == "return_total":
            labels = (TOTAL_LABELS[view],)
            amounts = (investment_return_total,)
            details = ("Total from the investment result note; Sun Life Note 10 is P&L only."
                       if is_sun else "Total investment return in the note, including investment OCI.",)
            total = investment_return_total
        elif view == "return_components":
            labels = RETURN_COMPONENTS[:3] if is_sun else RETURN_COMPONENTS
            amounts = return_parts
            details = return_detail
            total = investment_return_total
        elif view == "result_total":
            labels = (TOTAL_LABELS[view],)
            amounts = (result_total,)
            details = ("Net investment result in Sun Life Note 10 and the P&L statement."
                       if is_sun else "Net investment / financial result from the note, including OCI.",)
            total = result_total
        elif view == "result_components":
            labels = RESULT_COMPONENTS[:3] if is_sun else RESULT_COMPONENTS
            amounts = result_parts
            details = (
                "Investment return note total; Sun Life's is net investment income in P&L." if is_sun
                else "Total investment return including OCI.",
                "Total insurance contract finance result on the same note basis.",
                "Total reinsurance contract finance result on the same note basis.",
            ) + (() if is_sun else (
                "Separately disclosed movement in investment-contract liabilities.",
            ))
            total = result_total
        else:
            if is_sun:
                continue  # Note 10 does not present a P&L/OCI result split.
            labels = RESULT_REPRESENTATION
            amounts = (result_pl, result_total - result_pl)
            disclosed_oci = note["result"].get("oci_result")
            if disclosed_oci is not None and not _close(float(disclosed_oci), amounts[1]):
                continue
            details = (
                "Reported net investment / financial result in the profit-or-loss statement.",
                ("Separately disclosed in this insurer's net investment result note."
                 if disclosed_oci is not None else
                 "Calculated as note total less the reported P&L result; "
                 "the note does not label this as a separate subtotal."),
            )
            total = result_total
        if not _close(sum(amounts), total):
            continue
        for order, (label, amount, detail) in enumerate(zip(labels, amounts, details)):
            output.append(dict(zip(("Document ID", "Company", "Scope", "Period end", "Currency"), identity)) | {
                "Period": str(identity[3]), "Metric": label, "Amount": amount,
                "Stack order": order, "Reported total": total,
                "Calculation detail": detail, "Presentation basis": basis,
                "Note reference": note["note"], "View": view,
            })
    return pd.DataFrame(output, columns=_COLUMNS)


def investment_note_captions(rows: pd.DataFrame) -> list[str]:
    """Explain the unlike note presentations outside the chart tooltip."""
    if rows.empty:
        return []
    names = set(rows["Company"])
    views = set(rows["View"])
    if views in ({"finance_pl_total"}, {"result_pl_total"}):
        return []
    if views.issubset(PL_VIEWS):
        captions = []
        if "result_pl_components" in views:
            for company in ("FWD Life Bermuda", "YF Life"):
                if company in names:
                    captions.append(
                        f"{company}: the investment-contract liability movement is shown "
                        "separately in the P&L result composition."
                    )
        if "Sun Life Hong Kong" in names:
            captions.append("Sun Life's investment-contract liability movement is already within net investment income.")
        return captions
    captions = []
    for company in ("FWD Life Bermuda", "YF Life"):
        if company in names:
            captions.append(
                f"{company}: note totals include amounts recognised in OCI; "
                "the separate P&L/OCI chart reconciles those totals."
            )
    if "YF Life" in names:
        captions.append("In the P&L/OCI representation, YF's OCI result portion is calculated as the Note 6 total less its reported P&L result; it is not a separately labelled note subtotal.")
    if "Sun Life Hong Kong" in names:
        captions.append(
            "Sun Life Note 10 presents P&L only. FVTOCI and FVTPL are instrument categories, not OCI. "
            "Its investment-contract liability movement is already within net investment income."
        )
    if ((rows["Company"].eq("YF Life") & rows["Period"].eq("2024-12-31")).any()):
        captions.append(
            "YF 2024 uses the comparative in its 2025 Note 6, which includes investment OCI; "
            "the standalone 2024 note presented a different investment-return total."
        )
    return captions
