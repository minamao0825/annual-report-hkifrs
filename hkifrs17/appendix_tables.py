"""Source-aware annual appendix tables for insurance service and new business."""

from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from .data import standardize_hkd


@dataclass(frozen=True)
class _Identity:
    company: str
    scope: str
    label: str


_EXPENSE_ITEMS = (
    ("Incurred claims and service expenses", "INS_EXP_CLAIMS"),
    ("Amortisation of insurance acquisition cash flows", "INS_EXP_ACQ_AMORT"),
    ("Onerous contract losses and reversals", "INS_EXP_ONEROUS"),
    ("Changes in fulfilment cash flows for incurred claims", "INS_EXP_LIC"),
)
_APPENDIX_CODES = frozenset({
    "INS_REVENUE", "INS_EXPENSE", "INS_SERVICE_RESULT", "REINS_RESULT",
    "INS_EXP_NONPAA", "INS_EXP_PAA", "INS_GROSS_RESULT",
    "REV_CSM_SERVICE", "REV_RA_RELEASE", "REV_EXPECTED_CLAIMS",
    "REV_ACQ_RECOVERY", "REV_POLICYHOLDER_TAX", "REV_NONPAA_TOTAL",
    "REV_PAA_TOTAL", *(code for _, code in _EXPENSE_ITEMS),
    "NB_INS_PROFIT_CSM", "NB_INS_ONEROUS_LOSS", "NB_INS_PROFIT_PV_IN",
    "NB_INS_ONEROUS_PV_IN", "CSM_NEW", "CSM_RELEASE",
})


def _identities(rows: pd.DataFrame, companies: list[str]) -> list[_Identity]:
    output = []
    for company in companies:
        selected = rows.loc[rows["Company"].eq(company)]
        for scope in dict.fromkeys(selected["Scope"].dropna().astype(str)):
            name = company if company.endswith(f" ({scope})") else f"{company} ({scope})"
            output.append(_Identity(company, scope, name))
    return output


def _filing(rows: pd.DataFrame, identity: _Identity, period: str) -> pd.DataFrame:
    selected = rows.loc[
        rows["Company"].eq(identity.company)
        & rows["Scope"].astype(str).eq(identity.scope)
        & rows["Period end"].astype(str).eq(period)
    ]
    if selected.empty:
        return selected.iloc[0:0]
    if selected["Document ID"].nunique() > 1:
        coverage = selected.loc[selected["Metric code"].isin(_APPENDIX_CODES)].groupby(
            "Document ID", sort=False,
        )["Metric code"].nunique()
        if coverage.empty or (coverage == coverage.max()).sum() != 1:
            return selected.iloc[0:0]
        selected = selected.loc[selected["Document ID"].eq(coverage.idxmax())]
    return selected


def _value(filing: pd.DataFrame, code: str) -> float | None:
    cells = filing.loc[filing["Metric code"].eq(code)]
    if len(cells) != 1:
        return None
    if str(cells.iloc[0]["Value status"]) not in {
        "Reported", "Derived from disclosed items",
    }:
        return None
    amount = pd.to_numeric(cells.iloc[0]["Value (millions)"], errors="coerce")
    return float(amount) if pd.notna(amount) and math.isfinite(float(amount)) else None


def _sum(filing: pd.DataFrame, *codes: str) -> float | None:
    values = [_value(filing, code) for code in codes]
    return sum(values) if all(value is not None for value in values) else None


def _currency(filing: pd.DataFrame, mode: str) -> str:
    if mode == "HKD converted":
        return "HKD"
    currencies = filing.loc[filing["Currency"].isin(["HKD", "USD"]),
                            "Currency"].dropna().astype(str).unique()
    return str(currencies[0]) if len(currencies) == 1 else "Source currency"


def _factor(filing: pd.DataFrame, mode: str) -> float | None:
    if mode != "HKD converted":
        return 1.0
    currencies = filing.loc[filing["Currency"].isin(["HKD", "USD"]),
                            "Currency"].dropna().astype(str).unique()
    if len(currencies) != 1:
        return None
    if currencies[0] == "HKD":
        return 1.0
    if currencies[0] != "USD":
        return None
    rates = pd.to_numeric(filing.loc[filing["Currency"].eq("USD"),
                                     "USD/HKD rate"], errors="coerce").dropna().unique()
    return float(rates[0]) if len(rates) == 1 and math.isfinite(float(rates[0])) else None


def _amount(value: float | None, factor: float | None, unit: str,
            decimals: int, marker: str = "") -> str:
    if value is None:
        return "Not disclosed"
    if factor is None:
        return "FX unavailable"
    scaled = value * factor / (1000 if unit == "billions" else 1)
    if abs(scaled) < .5 * 10 ** (-decimals):
        scaled = 0.0
    digits = f"{abs(scaled):,.{decimals}f}"
    return (f"({digits})" if scaled < 0 else digits) + marker


def _percent(value: float | None, marker: str = "†") -> str:
    return "Not available" if value is None or not math.isfinite(value) else f"{value:.1f}%{marker}"


def _all_method_expenses(filing: pd.DataFrame) -> tuple[dict[str, float], bool] | None:
    """Orient a full-population liability movement to P&L only if it reconciles."""
    if _value(filing, "INS_EXP_NONPAA") is not None or _value(filing, "INS_EXP_PAA") is not None:
        return None
    total = _value(filing, "INS_EXPENSE")
    values = {code: _value(filing, code) for _, code in _EXPENSE_ITEMS}
    if total is None or any(value is None for value in values.values()):
        return None
    source_sum = sum(values.values())
    tolerance = max(.001001, abs(total) * 1e-8)
    if math.isclose(source_sum, -total, abs_tol=tolerance):
        return {code: -value for code, value in values.items()}, True
    if math.isclose(source_sum, total, abs_tol=tolerance):
        return values, False
    return None


def _columns(rows: pd.DataFrame, identities: list[_Identity], period: str,
             mode: str) -> tuple[list[str], dict[str, pd.DataFrame]]:
    columns = []
    filings = {}
    for identity in identities:
        filing = _filing(rows, identity, period)
        label = f"{identity.label} · {_currency(filing, mode)}"
        columns.append(label)
        filings[label] = filing
    return columns, filings


def insurance_service_appendix_tables(
    rows: pd.DataFrame, companies: list[str], periods: list[str], *,
    display_mode: str = "Native currencies", unit: str = "millions", decimals: int = 1,
) -> dict[str, pd.DataFrame]:
    """Keep disclosed method splits separate from all-method expense movements."""
    if rows.empty or not companies or not periods:
        return {}
    source = standardize_hkd(rows) if display_mode == "HKD converted" else rows
    identities = _identities(source, companies)
    output = {}
    for period in sorted(set(map(str, periods))):
        columns, filings = _columns(source, identities, period, display_mode)
        if not columns:
            continue
        result: list[dict] = []

        def add(label: str, code: str | None = None, *, kind: str = "detail",
                calculator=None, method_expense: bool = False,
                all_method_expense: bool = False) -> None:
            entry = {"Item": label, "_kind": kind}
            for column, filing in filings.items():
                if kind == "section":
                    entry[column] = ""
                    continue
                if all_method_expense:
                    oriented = _all_method_expenses(filing)
                    value = oriented[0].get(code) if oriented else None
                    marker = "‡" if oriented and oriented[1] and value is not None else ""
                elif method_expense and _value(filing, "INS_EXP_NONPAA") is None:
                    value, marker = None, ""
                elif calculator:
                    value, marker = calculator(filing), "†"
                else:
                    value, marker = _value(filing, code), ""
                entry[column] = _amount(value, _factor(filing, display_mode),
                                        unit, decimals, marker)
            result.append(entry)

        add("Contracts not measured under PAA · insurance revenue", kind="section")
        for label, code in (
            ("CSM recognised for services", "REV_CSM_SERVICE"),
            ("Risk adjustment release", "REV_RA_RELEASE"),
            ("Expected claims and service expenses", "REV_EXPECTED_CLAIMS"),
            ("Recovery of acquisition cash flows", "REV_ACQ_RECOVERY"),
            ("Policyholder taxes charged", "REV_POLICYHOLDER_TAX"),
            ("Non-PAA insurance revenue", "REV_NONPAA_TOTAL"),
        ):
            add(label, code, kind="subtotal" if code == "REV_NONPAA_TOTAL" else "detail")
        add("Contracts not measured under PAA · service expenses", kind="section")
        for label, code in _EXPENSE_ITEMS:
            add(label, code, method_expense=True)
        add("Non-PAA insurance service expenses", "INS_EXP_NONPAA", kind="subtotal")
        add("Non-PAA service result", kind="subtotal",
            calculator=lambda f: _sum(f, "REV_NONPAA_TOTAL", "INS_EXP_NONPAA"))
        add("Contracts measured under PAA", kind="section")
        add("PAA insurance revenue", "REV_PAA_TOTAL")
        add("PAA insurance service expenses", "INS_EXP_PAA")
        add("PAA service result", kind="subtotal",
            calculator=lambda f: _sum(f, "REV_PAA_TOTAL", "INS_EXP_PAA"))
        if any(_all_method_expenses(filing) is not None for filing in filings.values()):
            add("All-method insurance service expense detail", kind="section")
            for label, code in _EXPENSE_ITEMS:
                add(label, code, all_method_expense=True)
        add("All insurance contracts and reinsurance", kind="section")
        add("Insurance revenue", "INS_REVENUE")
        add("Insurance service expenses", "INS_EXPENSE")
        add("Insurance service result before reinsurance", kind="subtotal",
            calculator=lambda f: _sum(f, "INS_REVENUE", "INS_EXPENSE"))
        add("Net reinsurance service result", "REINS_RESULT")
        add("Net insurance service result", "INS_SERVICE_RESULT", kind="total")
        output[period] = pd.DataFrame(result, columns=["Item", *columns, "_kind"])
    return output


def new_business_appendix_tables(
    rows: pd.DataFrame, companies: list[str], periods: list[str], *,
    display_mode: str = "Native currencies", unit: str = "millions", decimals: int = 1,
) -> dict[str, pd.DataFrame]:
    """Use matched insurance-only new-business inputs and native-currency ratios."""
    if rows.empty or not companies or not periods:
        return {}
    source = standardize_hkd(rows) if display_mode == "HKD converted" else rows
    identities = _identities(source, companies)
    output = {}
    for period in sorted(set(map(str, periods))):
        columns, filings = _columns(source, identities, period, display_mode)
        if not columns:
            continue
        result: list[dict] = []
        def add(label: str, measure, *, kind: str = "detail", ratio: bool = False) -> None:
            entry = {"Item": label, "_kind": kind}
            for column, filing in filings.items():
                value, marker = measure(filing, column)
                entry[column] = (_percent(value, marker) if ratio else
                                 _amount(value, _factor(filing, display_mode),
                                         unit, decimals, marker))
            result.append(entry)

        add("New profitable insurance contracts: CSM",
            lambda f, _: (_magnitude(_value(f, "NB_INS_PROFIT_CSM")), ""))

        def growth(filing: pd.DataFrame, column: str) -> tuple[float | None, str]:
            now = _value(filing, "NB_INS_PROFIT_CSM")
            identity = identities[columns.index(column)]
            prior = f"{int(period[:4])-1}{period[4:]}"
            old = _value(_filing(source, identity, prior), "NB_INS_PROFIT_CSM")
            return ((100 * (abs(now) / abs(old) - 1)
                     if now is not None and old not in (None, 0) else None), "†")

        add("New-business CSM year-on-year growth", growth, ratio=True)
        add("Initial loss component from new onerous business",
            lambda f, _: (-_magnitude(_value(f, "NB_INS_ONEROUS_LOSS"))
                          if _value(f, "NB_INS_ONEROUS_LOSS") is not None else None, ""))

        def inflows(filing: pd.DataFrame, _: str) -> tuple[float | None, str]:
            profitable = _value(filing, "NB_INS_PROFIT_PV_IN")
            onerous = _value(filing, "NB_INS_ONEROUS_PV_IN")
            return ((abs(profitable) + abs(onerous)
                     if profitable is not None and onerous is not None else None), "†")

        add("Total PV of future cash inflows from new business", inflows)

        def margin(filing: pd.DataFrame, column: str) -> tuple[float | None, str]:
            csm = _value(filing, "NB_INS_PROFIT_CSM")
            loss = _value(filing, "NB_INS_ONEROUS_LOSS")
            denominator, _ = inflows(filing, column)
            return ((100 * (abs(csm) - abs(loss)) / denominator
                     if csm is not None and loss is not None and denominator else None), "†")

        add("New business IFRS profit margin", margin, kind="total", ratio=True)

        def replenishment(filing: pd.DataFrame, _: str) -> tuple[float | None, str]:
            new = _value(filing, "CSM_NEW")
            release = _value(filing, "CSM_RELEASE")
            return ((100 * abs(new) / abs(release)
                     if new is not None and release not in (None, 0) else None), "†")

        add("CSM replenishment ratio (new CSM / CSM released)",
            replenishment, ratio=True)
        output[period] = pd.DataFrame(result, columns=["Item", *columns, "_kind"])
    return output


def _magnitude(value: float | None) -> float | None:
    return abs(value) if value is not None else None
