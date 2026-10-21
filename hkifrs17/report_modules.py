"""English report navigation and chart coverage adapted from annual-report Step 7."""

from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd

from .catalog import INSURER_CHART_GROUPS, METRIC_BY_CODE
from .metric_blueprint import CHART_REQUIREMENTS


@dataclass(frozen=True)
class ReportModule:
    module_id: str
    section: str
    subsection: str
    title: str
    metrics: tuple[str, ...]
    kind: str = "amount"
    note: str = ""


EXCLUDED_SOURCE_IDS = frozenset({"exp_struct", "csm_equity"})
EXCLUDED_CHART_METRIC_CODES = frozenset({"INV_RETURN_TOTAL", "NET_INV_RESULT_TOTAL"})
NET_RESULT_REPORTED_LABELS = {
    "FWD Life Bermuda": "Net investment result",
    "Sun Life Hong Kong": "Net investment result",
    "YF Life": "Net financial result",
}
RATIO_MODULE_LABELS = {
    "csm_ratio": ("Insurance CSM / matching fulfilment cash flows",),
    "csm_ratio_trend": ("CSM release / opening CSM", "New business CSM / opening CSM"),
    "nb_margin_trend": ("New profitable contract CSM / PV inflows",),
    "six_dimensional_charts": (
        "Return on average equity", "Insurance CSM year-on-year growth",
        "Equity / total assets", "Investment yield", "Equity year-on-year growth",
    ),
}
PERFORMANCE_RATIO_PAGE_GROUPS = (
    ("Return and CSM growth", (
        "Return on average equity", "Insurance CSM year-on-year growth",
    )),
    ("Equity ratios", (
        "Equity / total assets", "Equity year-on-year growth",
    )),
)
YEAR_COLORED_MODULE_IDS = frozenset({
    "inc_total", "net_profit", "exp_total", "perf_total", "oci_profit",
    "total_profit", "asset_trend",
    "csm_bal", "csm_ratio", "nb_csm", "nb_lost", "nb_margin_trend",
    "confidence_level", "hk_insurance_revenue_detail", "inv_return", "inv_profit",
    "hk_investment",
    "hk_financial_position", "hk_csm", "hk_reinsurance_csm_release",
})
COMPANY_YEAR_COMPARISON_IDS = frozenset({
    "inc_total", "exp_total", "perf_total", "net_profit",
    "inv_return", "inv_profit", "oci_profit", "total_profit", "asset_trend",
    "csm_bal", "csm_ratio", "nb_csm", "nb_lost", "nb_margin_trend",
})
HOVER_ONLY_LABEL_MODULE_IDS = frozenset({
    "csm_trans", "nb_struct", "asset_struct", "report_detail", "nbv_table",
})
STACKED_AMOUNT_MODULE_IDS = frozenset({
    "prof_2025", "prof_2024", "uw_profit", "oci_deep",
})
# These are reported subtotals of the plotted components. Plotting them as
# another stack segment would count the underlying amounts twice.
STACKED_AMOUNT_TOTAL_CODES = {
    "prof_2025": frozenset({"INS_SERVICE_RESULT"}),
    "prof_2024": frozenset({"INS_SERVICE_RESULT"}),
    "uw_profit": frozenset({"INS_FINANCE_TOTAL", "REINS_FINANCE_TOTAL"}),
}
TABLE_MODULE_IDS = frozenset({
    "summary_table", "confidence_level",
})
LATEST_YEAR_IDS = frozenset({"prof_2025", "oci_year_lat", "csm_comp_lat"})
PRIOR_YEAR_IDS = frozenset({"prof_2024", "oci_year_pre", "csm_comp_pre"})


def _source_section(section: str) -> str:
    if section in {"Financial results", "Financial position", "New business"}:
        return "Key financial statement analysis"
    if section == "Performance indicators":
        return "Key performance indicators"
    return section


def _source_subsection(section: str, subsection: str) -> str:
    if section in {"Key disclosures", "Performance indicators", "Appendix"} or subsection == "Overview":
        return "All"
    if subsection == "Initial recognition":
        return "New business"
    return subsection


SOURCE_REPORT_MODULES = tuple(
    ReportModule(
        item.source_id, _source_section(item.section),
        _source_subsection(item.section, item.subsection), item.hk_title,
        item.metrics,
        "ratio" if item.source_id in RATIO_MODULE_LABELS else "rate" if item.source_id in {
            "discount_rate", "confidence_level",
        } else "amount",
        item.note,
    )
    for item in CHART_REQUIREMENTS if item.source_id not in EXCLUDED_SOURCE_IDS
)

# Retain HK-specific disclosures added after the source Step 7 inventory,
# without repeating a source module's indicator under another chart title.
_source_codes = {code for item in SOURCE_REPORT_MODULES for code in item.metrics}
SUPPLEMENTARY_MODULES = tuple(
    ReportModule(
        "hk_" + group.lower().replace(" ", "_").replace("-", "_"),
        "HKFRS 17 supplementary disclosures", group, group,
        tuple(code for code in codes
              if code not in _source_codes | EXCLUDED_CHART_METRIC_CODES),
    )
    for group, codes in INSURER_CHART_GROUPS
    if any(code not in _source_codes | EXCLUDED_CHART_METRIC_CODES for code in codes)
)
REPORT_MODULES = SOURCE_REPORT_MODULES + SUPPLEMENTARY_MODULES
MOVEMENT_MODULE_IDS = frozenset(
    module.module_id for module in REPORT_MODULES
    if "movement" in module.title.lower()
)
LATEST_YEAR_CHART_IDS = MOVEMENT_MODULE_IDS | LATEST_YEAR_IDS | {
    "nb_struct", "csm_maturity_table",
}
COMPARATIVE_MOVEMENT_IDS = frozenset(
    module.module_id for module in REPORT_MODULES
    if module.module_id in MOVEMENT_MODULE_IDS
    and module.title.lower().startswith("comparative")
)


def stacked_component_metrics(module: ReportModule) -> tuple[str, ...]:
    """Return mutually additive detail, omitting reported totals from stacks."""
    return tuple(code for code in module.metrics
                 if code not in STACKED_AMOUNT_TOTAL_CODES.get(module.module_id, ()))


def module_rows(rows: pd.DataFrame, module: ReportModule) -> pd.DataFrame:
    """Keep prior-year modules genuinely comparative; never relabel 2025 data."""
    if module.module_id == "prof_mix":
        selected = rows[rows["Metric code"].isin(module.metrics)].copy()
        if selected.empty:
            return selected
        return selected.groupby(["Document ID", "Period end"], group_keys=False).filter(
            lambda group: set(group["Metric code"]) == set(module.metrics)
        )
    if rows.empty or module.module_id not in LATEST_YEAR_IDS | PRIOR_YEAR_IDS:
        return rows
    years = sorted({str(period)[:4] for period in rows["Period end"]})
    if not years:
        return rows.iloc[0:0]
    current = years[-1]
    target = str(int(current) - 1) if module.module_id in PRIOR_YEAR_IDS else current
    return rows[rows["Period end"].astype(str).str.startswith(target)].copy()


def movement_chart_rows(rows: pd.DataFrame, module: ReportModule) -> pd.DataFrame:
    """Plot latest-year modules only for their latest selected year."""
    if rows.empty or module.module_id not in LATEST_YEAR_CHART_IDS:
        return rows
    latest_year = max(rows["Period end"].astype(str).str[:4])
    return rows[rows["Period end"].astype(str).str.startswith(latest_year)].copy()


def discount_rate_summary(rows: pd.DataFrame, companies: list[str],
                          periods: list[str]) -> pd.DataFrame:
    """Summarize disclosed tenor ranges without combining currencies or bases."""
    selected_periods = sorted({str(period) for period in periods}, reverse=True)
    month_names = ("January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December")
    headers = []
    for period in selected_periods:
        date = pd.Timestamp(period)
        headers.append(f"{date.day} {month_names[date.month - 1]} {date.year}")
    if rows.empty:
        return pd.DataFrame(columns=["Company", *headers])
    codes = rows["Metric code"].astype(str)
    parsed = codes.str.extract(r"^DISCOUNT_(CNY|HKD|USD)_(1Y|5Y|10Y|15Y|20Y)_(RF|ILP)$")
    rates = rows.loc[parsed[0].notna()].copy()
    if not rates.empty:
        rates[["Rate currency", "Tenor", "Basis"]] = parsed.loc[parsed[0].notna()].to_numpy()
        rates["Rate"] = pd.to_numeric(rates["Value (millions)"], errors="coerce")
        rates = rates.dropna(subset=["Rate"])
    output = []
    for company in companies:
        company_rows = rows.loc[rows["Company"].eq(company)]
        scopes = list(dict.fromkeys(
            str(scope).title() for scope in company_rows["Scope"].dropna()
            if str(scope).strip()
        ))
        base_name = re.sub(r"\s*\((?:Company|Consolidated)\)$", "", company,
                           flags=re.IGNORECASE)
        label = f"{base_name} ({' / '.join(scopes)})" if scopes else company
        entry = {"Company": label}
        for period, header in zip(selected_periods, headers):
            selected = rates.loc[
                rates["Company"].eq(company) & rates["Period end"].astype(str).eq(period)
            ] if not rates.empty else rates
            lines = []
            for currency in ("CNY", "HKD", "USD"):
                for basis, basis_label in (("RF", "Risk-free"),
                                           ("ILP", "With illiquidity premium")):
                    values = selected.loc[
                        selected["Rate currency"].eq(currency) & selected["Basis"].eq(basis),
                        "Rate",
                    ] if not selected.empty else pd.Series(dtype=float)
                    if values.empty:
                        continue
                    lower, upper = float(values.min()), float(values.max())
                    rate_range = (f"{lower:.2f}%" if abs(lower - upper) < 1e-9 else
                                  f"{lower:.2f}%–{upper:.2f}%")
                    lines.append(f"{currency} · {basis_label}: {rate_range}")
            entry[header] = "\n".join(lines) if lines else "Not disclosed"
        output.append(entry)
    return pd.DataFrame(output, columns=["Company", *headers])


def report_modules_for_rows(rows: pd.DataFrame) -> tuple[ReportModule, ...]:
    """Omit charts whose selected data would repeat another chart exactly."""
    if rows.empty:
        return tuple(module for module in REPORT_MODULES
                     if module.module_id not in COMPARATIVE_MOVEMENT_IDS)
    note = rows.loc[rows["Metric code"].eq("INS_REVENUE_NOTE_TOTAL"),
                    ["Document ID", "Period end", "Value (millions)"]]
    statement = rows.loc[rows["Metric code"].eq("INS_REVENUE"),
                         ["Document ID", "Period end", "Value (millions)"]]
    matched = note.merge(statement, on=["Document ID", "Period end"], how="left",
                         suffixes=("_note", "_statement"))
    repeated_revenue_total = (
        not matched.empty
        and matched["Value (millions)_statement"].notna().all()
        and (pd.to_numeric(matched["Value (millions)_note"], errors="coerce")
             - pd.to_numeric(matched["Value (millions)_statement"], errors="coerce"))
            .abs().le(1e-6).all()
    )
    return tuple(
        module for module in REPORT_MODULES
        if module.module_id not in COMPARATIVE_MOVEMENT_IDS
        and not (module.module_id == "hk_insurance_revenue_detail" and repeated_revenue_total)
        and not (module.module_id == "prof_mix" and module_rows(rows, module).empty)
    )


def missing_metrics(rows: pd.DataFrame, module: ReportModule) -> list[str]:
    present = set(rows["Metric code"]) if not rows.empty else set()
    return [METRIC_BY_CODE[code].label for code in module.metrics if code not in present]


def investment_result_reconciliation(rows: pd.DataFrame) -> pd.DataFrame:
    """Bridge the reviewed profit-or-loss lines in their statement currency."""
    columns = ["Company", "Period", "Currency", "Investment return / income",
               "Insurance finance", "Reinsurance finance",
               "Investment-contract liability movement", "Reported net result"]
    if rows.empty:
        return pd.DataFrame(columns=columns)
    relevant = rows[rows["Metric code"].isin({
        "INV_RETURN", "NET_INV_INCOME", "INS_FINANCE_PL", "REINS_FINANCE_PL",
        "NET_INV_RESULT",
    })]
    output = []
    for (company, scope, period, currency), group in relevant.groupby(
            ["Company", "Scope", "Period end", "Currency"], sort=False, dropna=False):
        amounts = group.set_index("Metric code")["Value (millions)"]
        start_code = "INV_RETURN" if "INV_RETURN" in amounts else "NET_INV_INCOME"
        required = {start_code, "INS_FINANCE_PL", "REINS_FINANCE_PL", "NET_INV_RESULT"}
        if not required.issubset(amounts.index) or group["Metric code"].duplicated().any():
            continue
        start, insurance, reinsurance, result = (
            float(amounts[code]) for code in
            (start_code, "INS_FINANCE_PL", "REINS_FINANCE_PL", "NET_INV_RESULT")
        )
        if not all(pd.notna(value) for value in (start, insurance, reinsurance, result)):
            continue
        liability = result - start - insurance - reinsurance
        if abs(liability) < 1e-7:
            liability = 0.0
        def number(value: float) -> str:
            return f"{value:,.6f}".rstrip("0").rstrip(".")
        scope_name = str(scope).title()
        output.append({
            "Company": f"{company} ({scope_name})",
            "Period": f"{str(period)[:4]}YE", "Currency": currency,
            "Investment return / income": number(start),
            "Insurance finance": number(insurance),
            "Reinsurance finance": number(reinsurance),
            "Investment-contract liability movement": number(liability),
            "Reported net result": number(result),
        })
    return pd.DataFrame(output, columns=columns).sort_values(
        ["Company", "Period"], kind="stable"
    ) if output else pd.DataFrame(columns=columns)


def validate_report_modules() -> None:
    ids = [item.module_id for item in REPORT_MODULES]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate report module ID.")
    amount_codes = {code for code, item in METRIC_BY_CODE.items() if item.kind != "rate"}
    displayed = {code for item in REPORT_MODULES for code in item.metrics}
    if not (amount_codes - EXCLUDED_CHART_METRIC_CODES).issubset(displayed):
        raise ValueError("Some disclosed amount indicators have no report module.")


validate_report_modules()
