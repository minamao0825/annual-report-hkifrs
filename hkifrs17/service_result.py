"""Five-item insurance service result bridge in each filing's statement currency."""

from __future__ import annotations

import math

import pandas as pd


SERVICE_RESULT_COMPONENTS = (
    "Net Reinsurance Result",
    "PAA and Other Insurance Service Impacts",
    "Changes in Risk Adjustment for Non-financial Risk",
    "Release of Contractual Service Margin (CSM)",
    "Recognition and Reversal of Loss Components",
)

_COMMON_CODES = frozenset({
    "INS_SERVICE_RESULT", "REINS_RESULT", "REV_RA_RELEASE",
    "REV_CSM_SERVICE", "INS_EXP_ONEROUS",
})
_METHOD_CODES = frozenset({
    "REV_PAA_TOTAL", "INS_EXP_PAA", "REV_NONPAA_TOTAL", "INS_EXP_NONPAA",
})
_OUTPUT_COLUMNS = (
    "Document ID", "Company", "Scope", "Period end", "Period", "Currency",
    "Metric", "Amount", "Stack order", "Calculation detail", "Reported total",
    "Bridge basis",
)


def _number(value: float) -> str:
    return f"{value:,.3f}".replace("-", "−")


def _close(left: float, right: float) -> bool:
    # Source disclosures range from whole millions to single currency units.
    return math.isclose(left, right, rel_tol=0, abs_tol=0.001001)


def service_result_component_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Return complete, reconciled five-part bridges; never mix filing scopes.

    FWD and Sun Life disclose both method subtotals. Their PAA net result is
    revenue plus the signed expense, and the other effect is decomposed from
    disclosed non-PAA revenue and expense subtotals. YF does not disclose a
    separate PAA expense/result: its combined PAA-and-other item is explicitly
    a balancing residual. YF's onerous-contract note records a *liability*
    movement, whose sign is reversed for its profit-or-loss contribution.
    """
    if frame.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    output: list[dict] = []
    keys = ["Document ID", "Company", "Scope", "Period end", "Currency"]
    relevant = frame.loc[frame["Metric code"].isin(
        _COMMON_CODES | _METHOD_CODES | {"INS_REVENUE", "INS_EXPENSE"}
    )]
    for identity, group in relevant.groupby(keys, sort=False, dropna=False):
        if group["Metric code"].duplicated().any():
            continue
        cells = group.set_index("Metric code")
        company = str(identity[1])
        required = _COMMON_CODES if company == "YF Life" else _COMMON_CODES | _METHOD_CODES
        if not required.issubset(cells.index):
            continue
        values = pd.to_numeric(cells["Value (millions)"], errors="coerce")
        if not all(math.isfinite(float(values[code])) for code in required):
            continue
        value = lambda code: float(values[code])
        reported = value("INS_SERVICE_RESULT")
        reinsurance = value("REINS_RESULT")
        risk = value("REV_RA_RELEASE")
        csm = value("REV_CSM_SERVICE")
        loss = value("INS_EXP_ONEROUS")
        loss_label = str(cells.loc["INS_EXP_ONEROUS", "Source label"]).lower()
        liability_movement = "carrying-amount analysis" in loss_label
        if liability_movement:
            loss = -loss

        if {"INS_REVENUE", "INS_EXPENSE"}.issubset(cells.index):
            statement_total = value("INS_REVENUE") + value("INS_EXPENSE") + reinsurance
            if not _close(statement_total, reported):
                continue

        if company == "YF Life":
            paa_other = reported - reinsurance - risk - csm - loss
            bridge_basis = "derived combined residual"
            combined_detail = (
                f"Derived combined residual {_number(paa_other)} {identity[4]} million "
                "= reported insurance service result "
                "− net reinsurance result − risk adjustment change − CSM release "
                "− loss component. YF does not separately disclose PAA net result."
            )
        else:
            paa_revenue = value("REV_PAA_TOTAL")
            paa_expense = value("INS_EXP_PAA")
            nonpaa_revenue = value("REV_NONPAA_TOTAL")
            nonpaa_expense = value("INS_EXP_NONPAA")
            paa_net = paa_revenue + paa_expense
            other = nonpaa_revenue + nonpaa_expense - risk - csm - loss
            paa_other = paa_net + other
            if not _close(paa_revenue + paa_expense + nonpaa_revenue
                          + nonpaa_expense + reinsurance, reported):
                continue
            bridge_basis = "disclosed method subtotals"
            combined_detail = (
                f"Amounts in {identity[4]} millions: PAA net {_number(paa_net)} "
                f"= PAA revenue {_number(paa_revenue)} "
                f"+ PAA expense {_number(paa_expense)}; other effects {_number(other)} "
                f"= non-PAA revenue {_number(nonpaa_revenue)} + non-PAA expense "
                f"{_number(nonpaa_expense)} − risk adjustment {_number(risk)} "
                f"− CSM release {_number(csm)} − loss component {_number(loss)}. "
                "Method subtotals are disclosed; other effects are calculated."
            )

        amounts = (reinsurance, paa_other, risk, csm, loss)
        if not _close(sum(amounts), reported):
            continue
        details = (
            "Disclosed net reinsurance result.",
            combined_detail,
            "Disclosed risk adjustment change for non-financial risk.",
            "Disclosed CSM recognised for services provided.",
            ("Insurance liability movement sign reversed for its result contribution."
             if liability_movement else "Disclosed signed onerous-contract loss and reversal."),
        )
        for order, (label, amount, detail) in enumerate(zip(
                SERVICE_RESULT_COMPONENTS, amounts, details)):
            output.append(dict(zip(keys, identity)) | {
                "Period": str(identity[3]), "Metric": label, "Amount": amount,
                "Stack order": order, "Calculation detail": detail,
                "Reported total": reported, "Bridge basis": bridge_basis,
            })
    return pd.DataFrame(output, columns=_OUTPUT_COLUMNS)


def service_result_notes(rows: pd.DataFrame, *, include_overview: bool = True) -> list[str]:
    """Explain the combined segment's provenance below either chart."""
    if rows.empty:
        return []
    notes = (["Five signed components sum to the reported insurance service result; hover for amounts and calculation details."]
             if include_overview else [])
    for company in ("FWD Life Bermuda", "Sun Life Hong Kong"):
        if (rows["Company"].eq(company) & rows["Bridge basis"].eq("disclosed method subtotals")).any():
            notes.append(
                f"{company}: the combined segment can be traced to disclosed PAA "
                "revenue and expense and non-PAA revenue and expense. The other effect "
                "is calculated after removing risk adjustment, CSM release and loss components."
            )
    yf = rows.loc[
        rows["Company"].eq("YF Life")
        & rows["Metric"].eq(SERVICE_RESULT_COMPONENTS[1])
    ]
    if not yf.empty:
        amounts = ", ".join(
            f"{str(row['Period'])[:4]}: HKD {_number(float(row['Amount']))} million"
            for _, row in yf.sort_values("Period").iterrows()
        )
        notes.append(
            "YF: the PAA and other segment is a formula-derived combined residual "
            f"({amounts}); it is not a separately disclosed PAA net result."
        )
    return notes
