"""English report navigation and chart coverage adapted from annual-report Step 7."""

from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd

from .catalog import INSURER_CHART_GROUPS, METRIC_BY_CODE
from .charts import analytical_ratio_rows
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


def module_company_disclosure_notes(module_id: str, companies) -> list[str]:
    """Keep source-specific explanations tied to displayed insurers."""
    names = set(companies)
    notes = []
    if module_id == "inv_return" and "Sun Life Hong Kong" in names:
        notes.append("Sun Life Hong Kong: investment return uses net investment income.")
    if module_id == "csm_maturity_table" and "FWD Life Bermuda" in names:
        notes.append(
            "FWD Life Bermuda: the disclosed over-10-years bucket is retained; "
            "the mainland template's 10–20 and over-20 buckets are not inferred."
        )
    return notes


EXCLUDED_SOURCE_IDS = frozenset({"exp_struct", "csm_equity"})
# Retain source cells and extraction coverage while removing these displays.
HIDDEN_REPORT_MODULE_IDS = frozenset({"nb_margin_trend"})
EXCLUDED_CHART_METRIC_CODES = frozenset({"INV_RETURN_TOTAL", "NET_INV_RESULT_TOTAL"})
NET_RESULT_REPORTED_LABELS = {
    "FWD Life Bermuda": "Net investment result",
    "Sun Life Hong Kong": "Net investment result",
    "YF Life": "Net financial result",
}
RATIO_MODULE_LABELS = {
    "csm_ratio": ("Insurance CSM / matching fulfilment cash flows",),
    "csm_ratio_trend": ("CSM amortization ratio", "New business CSM / CSM release"),
    "six_dimensional_charts": (
        "Return on average equity", "Insurance CSM year-on-year growth",
        "Equity / total assets", "Equity year-on-year growth",
    ),
}


def financial_performance_ratio_table(rows: pd.DataFrame, companies: list[str],
                                      periods: list[str]) -> pd.DataFrame:
    """Show the four selected ratios by insurer and year, including missing cells."""
    selected_periods = sorted({str(period) for period in periods})
    headers = [f"{pd.Timestamp(period).year}YE" for period in selected_periods]
    columns = ["Company", "Indicator", *headers]
    if not companies:
        return pd.DataFrame(columns=columns)
    output = []
    for company in companies:
        company_rows = rows.loc[rows["Company"].eq(company)
                                & rows["Period end"].astype(str).isin(selected_periods)]
        scopes = list(dict.fromkeys(
            str(scope).title() for scope in company_rows["Scope"].dropna()
            if str(scope).strip()
        )) or [""]
        base_name = re.sub(r"\s*\((?:Company|Consolidated)\)$", "", company,
                           flags=re.IGNORECASE)
        for scope in scopes:
            scoped_rows = (company_rows.loc[company_rows["Scope"].astype(str).str.lower()
                                            .eq(scope.lower())]
                           if scope else company_rows)
            values, _ = analytical_ratio_rows(scoped_rows)
            label = f"{base_name} ({scope})" if scope else base_name
            for indicator in RATIO_MODULE_LABELS["six_dimensional_charts"]:
                entry = {"Company": label, "Indicator": indicator}
                for period, header in zip(selected_periods, headers):
                    match = values.loc[
                        values["Period"].eq(period) & values["Metric"].eq(indicator),
                        "Amount",
                    ] if not values.empty else pd.Series(dtype=float)
                    entry[header] = (f"{float(match.iloc[0]):.2f}%" if len(match) == 1
                                     else "Unavailable")
                output.append(entry)
    return pd.DataFrame(output, columns=columns)
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
    "csm_bal", "csm_ratio", "nb_csm", "nb_lost",
    "confidence_level", "hk_insurance_revenue_detail", "inv_return", "inv_profit",
    "hk_investment",
    "hk_financial_position", "hk_csm", "hk_reinsurance_csm_release",
})
COMPANY_YEAR_COMPARISON_IDS = frozenset({
    "inc_total", "exp_total", "perf_total", "net_profit",
    "inv_return", "inv_profit", "oci_profit", "total_profit", "asset_trend",
    "csm_bal", "csm_ratio", "nb_csm", "nb_lost",
})
HOVER_ONLY_LABEL_MODULE_IDS = frozenset({
    "asset_struct",
})
STACKED_AMOUNT_MODULE_IDS = frozenset({
    "prof_2025", "prof_2024", "exp_1",
})
# These are reported subtotals of the plotted components. Plotting them as
# another stack segment would count the underlying amounts twice.
STACKED_AMOUNT_TOTAL_CODES = {
    "prof_2025": frozenset({"INS_SERVICE_RESULT"}),
    "prof_2024": frozenset({"INS_SERVICE_RESULT"}),
}
TABLE_MODULE_IDS = frozenset({
    "summary_table", "confidence_level", "csm_rollforward_table",
    "equity_movement_table",
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
INVESTMENT_COMPONENT_MODULES = {
    "inv_return": ReportModule(
        "inv_return_components", "Key financial statement analysis", "Investment",
        "Investment return components", ("INV_RETURN", "NET_INV_INCOME"),
    ),
    "inv_profit": ReportModule(
        "inv_profit_components", "Key financial statement analysis", "Investment",
        "Investment result components", ("NET_INV_RESULT",),
    ),
}
CSM_ROLLFORWARD_MODULE = ReportModule(
    "csm_rollforward_table", "Key financial statement analysis", "CSM",
    "CSM balance roll-forward table",
    ("CSM_OPEN", "CSM_NEW", "CSM_FINANCE_CHANGE",
     "CSM_ESTIMATE_CHANGE", "CSM_RELEASE", "CSM_CLOSE"),
)
NEW_BUSINESS_RATIOS_MODULE = ReportModule(
    "nb_value_ratios", "Key financial statement analysis", "New business",
    "New business value ratios (CSM margin / loss ratio / RA ratio)",
    ("NB_INS_PROFIT_CSM", "NB_INS_PROFIT_PV_IN", "NB_INS_ONEROUS_LOSS",
     "NB_INS_ONEROUS_PV_IN", "NB_INS_PROFIT_RA", "NB_INS_ONEROUS_RA"),
    "ratio",
)
NET_ASSETS_MODULE = ReportModule(
    "equity_balance_comparison", "Key financial statement analysis", "Equity",
    "Net Assets", ("EQUITY",),
)
EQUITY_MOVEMENT_TABLE_MODULE = ReportModule(
    "equity_movement_table", "Key financial statement analysis", "Equity",
    "Net assets movement detail table",
    ("EQUITY_OPEN", "PROFIT", "OCI_TOTAL", "EQUITY_DIVIDENDS",
     "EQUITY_NEW_CAPITAL", "EQUITY_OTHER", "EQUITY"),
)


def _source_modules_with_components():
    for module in SOURCE_REPORT_MODULES:
        if module.module_id in HIDDEN_REPORT_MODULE_IDS:
            continue
        if module.module_id == "equity_trend":
            yield NET_ASSETS_MODULE
            yield EQUITY_MOVEMENT_TABLE_MODULE
        yield module
        if module.module_id == "csm_table":
            yield CSM_ROLLFORWARD_MODULE
        if module.module_id == "nb_lost":
            yield NEW_BUSINESS_RATIOS_MODULE
        if module.module_id in INVESTMENT_COMPONENT_MODULES:
            yield INVESTMENT_COMPONENT_MODULES[module.module_id]


REPORT_MODULES = tuple(_source_modules_with_components()) + SUPPLEMENTARY_MODULES
MOVEMENT_MODULE_IDS = frozenset(
    module.module_id for module in REPORT_MODULES
    if "movement" in module.title.lower()
)
LATEST_YEAR_CHART_IDS = MOVEMENT_MODULE_IDS | LATEST_YEAR_IDS | {
    "csm_maturity_table", "csm_rollforward_table",
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
    """Put disclosed rate forms on separate, year-adjacent tenor rows."""
    selected_periods = sorted({str(period) for period in periods})
    leading = ["Company", "Currency / portfolio", "Disclosed rate", "Value form", "Year"]
    if rows.empty or not companies or not selected_periods:
        return pd.DataFrame(columns=leading)

    # A new insurer can reuse the same rate-code grammar without a display rule
    # based on its name. The available tenor columns come from the selected data.
    pattern = re.compile(
        r"^DISCOUNT_(?P<scope>.+)_(?P<tenor>\d+(?:\.\d+)?[DWMY])_"
        r"(?P<basis>PREMIUM_UP_TO|SPOT_LOW|SPOT_HIGH|PREMIUM|ILP|RF)$"
    )
    basis_labels = {
        "RF": ("Risk-free spot rate", "Point"),
        "ILP": ("Spot rate with illiquidity premium", "Point"),
        "PREMIUM": ("Illiquidity premium", "Point"),
        "PREMIUM_UP_TO": ("Illiquidity premium", "Upper limit"),
        "SPOT_LOW": ("Adjusted spot rate", "Range"),
        "SPOT_HIGH": ("Adjusted spot rate", "Range"),
    }
    rates = rows.loc[
        rows["Company"].isin(companies)
        & rows["Period end"].astype(str).isin(selected_periods)
        & rows["Metric code"].astype(str).str.startswith("DISCOUNT_")
    ].copy()
    rates["Rate"] = pd.to_numeric(rates["Value (millions)"], errors="coerce")
    rates = rates.dropna(subset=["Rate"])
    if "Value status" in rates:
        rates = rates.loc[rates["Value status"].eq("Reported")]
    parsed = []
    for _, row in rates.iterrows():
        match = pattern.fullmatch(str(row["Metric code"]))
        if not match:
            continue
        item = row.to_dict()
        item.update(match.groupdict())
        label, value_form = basis_labels[item["basis"]]
        item["Disclosed rate"] = label
        item["Value form"] = value_form
        source = str(row.get("Source label", "")).lower()
        if "except rmb np" in source and "rmb ul" in source:
            item["Currency / portfolio"] = "Except RMB NP / RMB UL"
        elif "rmb np" in source and "rmb ul" in source:
            item["Currency / portfolio"] = "RMB NP / RMB UL"
        elif item["scope"] == "OTHER_PORTFOLIOS":
            item["Currency / portfolio"] = "Other portfolios"
        else:
            item["Currency / portfolio"] = item["scope"].replace("_", " ")
        parsed.append(item)
    if not parsed:
        return pd.DataFrame(columns=leading)
    detail = pd.DataFrame(parsed)
    detail["Reporting scope"] = (detail["Scope"].fillna("").astype(str).str.strip().str.title()
                                  if "Scope" in detail else "")

    def tenor_key(tenor: str) -> float:
        number, unit = float(tenor[:-1]), tenor[-1]
        return number * {"D": 1 / 365, "W": 7 / 365, "M": 1 / 12, "Y": 1}[unit]

    tenors = sorted(detail["tenor"].unique(), key=lambda tenor: (tenor_key(tenor), tenor))
    output = []
    for company in companies:
        base_name = re.sub(r"\s*\((?:Company|Consolidated)\)$", "", company,
                           flags=re.IGNORECASE)
        company_rates = detail.loc[detail["Company"].eq(company)]
        key_columns = ["Reporting scope", "Currency / portfolio", "Disclosed rate", "Value form"]
        keys = company_rates[key_columns].drop_duplicates().copy()
        scope_order = dict(enumerate(company_rates["Reporting scope"].drop_duplicates()))
        portfolio_order = dict(enumerate(company_rates["Currency / portfolio"].drop_duplicates()))
        keys["_scope_order"] = keys["Reporting scope"].map({value: rank for rank, value in scope_order.items()})
        keys["_portfolio_order"] = keys["Currency / portfolio"].map(
            {value: rank for rank, value in portfolio_order.items()}
        )
        keys["_basis_order"] = keys["Disclosed rate"].map({
            "Risk-free spot rate": 0, "Illiquidity premium": 1,
            "Spot rate with illiquidity premium": 2, "Adjusted spot rate": 3,
        }).fillna(9)
        keys = keys.sort_values(["_scope_order", "_portfolio_order", "_basis_order"],
                                kind="stable")
        for _, key in keys.iterrows():
            subset = company_rates.loc[
                company_rates["Reporting scope"].eq(key["Reporting scope"])
                & company_rates["Currency / portfolio"].eq(key["Currency / portfolio"])
                & company_rates["Disclosed rate"].eq(key["Disclosed rate"])
                & company_rates["Value form"].eq(key["Value form"])
            ]
            scope = key["Reporting scope"]
            company_label = f"{base_name} ({scope})" if scope else base_name
            for period in selected_periods:
                year_rates = subset.loc[subset["Period end"].astype(str).eq(period)]
                entry = {"Company": company_label,
                         "Currency / portfolio": key["Currency / portfolio"],
                         "Disclosed rate": key["Disclosed rate"],
                         "Value form": key["Value form"],
                         "Year": f"{pd.Timestamp(period).year}YE"}
                for tenor in tenors:
                    tenor_rates = year_rates.loc[year_rates["tenor"].eq(tenor)]
                    if key["Value form"] == "Range":
                        lower = tenor_rates.loc[tenor_rates["basis"].eq("SPOT_LOW"), "Rate"]
                        upper = tenor_rates.loc[tenor_rates["basis"].eq("SPOT_HIGH"), "Rate"]
                        entry[tenor] = (f"{lower.iloc[0]:.2f}%–{upper.iloc[0]:.2f}%"
                                        if len(lower) == len(upper) == 1
                                        and lower.iloc[0] <= upper.iloc[0]
                                        else "Not disclosed")
                    elif len(tenor_rates) == 1:
                        value = f"{tenor_rates['Rate'].iloc[0]:.2f}%"
                        entry[tenor] = (f"Up to {value}" if key["Value form"] == "Upper limit"
                                        else value)
                    else:
                        entry[tenor] = "Not disclosed"
                output.append(entry)
    return pd.DataFrame(output, columns=[*leading, *tenors])


def confidence_level_summary(rows: pd.DataFrame, companies: list[str],
                             periods: list[str]) -> pd.DataFrame:
    """Keep insurers without a disclosed numerical RA confidence level visible."""
    selected_periods = sorted({str(period) for period in periods})
    headers = [f"{pd.Timestamp(period).year}YE" for period in selected_periods]
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
            matching = company_rows.loc[
                company_rows["Period end"].astype(str).eq(period)
                & company_rows["Metric code"].eq("RA_CONFIDENCE_PCT")
            ]
            values = pd.to_numeric(matching["Value (millions)"], errors="coerce").dropna()
            entry[header] = (f"{float(values.iloc[0]):g}%" if len(values) == 1
                             else "Not disclosed")
        output.append(entry)
    return pd.DataFrame(output, columns=["Company", *headers])


def report_modules_for_rows(rows: pd.DataFrame) -> tuple[ReportModule, ...]:
    """Omit charts whose selected data would repeat another chart exactly."""
    hidden_ids = COMPARATIVE_MOVEMENT_IDS
    if rows.empty:
        return tuple(module for module in REPORT_MODULES
                     if module.module_id not in hidden_ids)
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
        if module.module_id not in hidden_ids
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
    retained_in_source = {
        code for item in SOURCE_REPORT_MODULES
        if item.module_id in HIDDEN_REPORT_MODULE_IDS
        for code in item.metrics
    }
    if not (amount_codes - EXCLUDED_CHART_METRIC_CODES).issubset(
        displayed | retained_in_source
    ):
        raise ValueError("Some disclosed amount indicators have no report module or source inventory.")


validate_report_modules()
