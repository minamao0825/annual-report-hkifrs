"""Closing insurance CSM mix by categories disclosed in the transition note."""

from __future__ import annotations

import math

import altair as alt
import pandas as pd

from .charts import _company_panel_width, _report_chart_theme
from .fx import year_end_usd_hkd
from .oci_analysis import _single_amount


CATEGORIES = (
    ("INS_CSM_FV_CLOSE", "Fair value approach at transition", "#00338D"),
    ("INS_CSM_MOD_CLOSE", "Modified retrospective approach at transition", "#00AEEF"),
    ("INS_CSM_OTHER_CLOSE", "Other insurance contracts", "#7213EA"),
)
_COLUMNS = [
    "Company", "Panel", "Scope", "Period end", "Period label", "Category",
    "Status", "Share", "Plot share", "Midpoint", "Share label",
    "Amount", "Total", "Currency", "Unit", "Stack order",
]


def csm_transition_rows(records: pd.DataFrame, companies: list[str],
                        periods: list[str], *,
                        display_mode: str = "Native currencies",
                        unit: str = "millions") -> tuple[pd.DataFrame, list[str]]:
    """Require a complete insurance-only category split before plotting percentages."""
    if records.empty or not companies or not periods:
        return pd.DataFrame(columns=_COLUMNS), []
    selected = records.loc[
        records["Company"].isin(companies) & records["Period end"].isin(periods)
        & records["Currency"].isin(("HKD", "USD"))
    ]
    output: list[dict] = []
    issues: list[str] = []
    for company in companies:
        company_rows = selected.loc[selected["Company"].eq(company)]
        for period in sorted(periods, reverse=True):
            period_rows = company_rows.loc[company_rows["Period end"].eq(period)]
            if period_rows.empty:
                fallback = records.loc[records["Company"].eq(company)
                                       & records["Currency"].isin(("HKD", "USD"))]
                if fallback.empty:
                    continue
                latest = fallback.sort_values("Period end", ascending=False).iloc[0]
                currency = ("HKD" if display_mode == "HKD converted"
                            else str(latest["Currency"]))
                scope = str(latest["Scope"])
                output.append({
                    "Company": company,
                    "Panel": f"{company} ({scope.title()}) · {currency}",
                    "Scope": scope, "Period end": period,
                    "Period label": f"{period[:4]}YE", "Category": "Not disclosed",
                    "Status": "Not disclosed", "Share": None,
                    "Plot share": 100.0, "Midpoint": 50.0,
                    "Share label": "Not disclosed", "Amount": None,
                    "Total": None, "Currency": currency, "Unit": unit,
                    "Stack order": 0,
                })
                issues.append(f"{company} {period[:4]}YE: insurance CSM category data are unavailable.")
                continue
            for identity, group in period_rows.groupby(
                    ["Document ID", "Scope", "Currency"], sort=False, dropna=False):
                _, scope, currency = map(str, identity)
                shown_currency = currency
                factor = 1.0
                if display_mode == "HKD converted" and currency == "USD":
                    rate = year_end_usd_hkd(int(period[:4]))
                    if rate is not None:
                        factor = float(rate[0])
                        shown_currency = "HKD"
                    else:
                        issues.append(f"{company} {period[:4]}: USD/HKD rate unavailable; hover amounts remain in USD.")
                divisor = 1000.0 if unit == "billions" else 1.0
                panel = f"{company} ({scope.title()}) · {shown_currency}"
                common = {
                    "Company": company, "Panel": panel, "Scope": scope,
                    "Period end": period, "Period label": f"{period[:4]}YE",
                    "Currency": shown_currency, "Unit": unit,
                }
                total = _single_amount(group, "INS_NONPAA_CSM_CLOSE")
                amounts = [(code, label, _single_amount(group, code))
                           for code, label, _ in CATEGORIES]
                known = [value for _, _, value in amounts if value is not None]
                complete = bool(total is not None and total > 0 and known
                                and all(value >= 0 for value in known)
                                and math.isclose(sum(known), total, rel_tol=1e-6,
                                                 abs_tol=1e-5))
                if not complete:
                    issues.append(f"{company} {period[:4]}YE: a complete insurance CSM category split "
                                  "is not disclosed or does not reconcile to closing non-PAA insurance CSM.")
                    output.append({
                        **common, "Category": "Not disclosed", "Status": "Not disclosed",
                        "Share": None, "Plot share": 100.0, "Midpoint": 50.0,
                        "Share label": "Not disclosed", "Amount": None,
                        "Total": total * factor / divisor if total is not None else None,
                        "Stack order": 0,
                    })
                    continue
                running = 0.0
                for index, (_, label, amount) in enumerate(amounts):
                    if amount is None or amount == 0:
                        continue
                    share = 100.0 * amount / total
                    output.append({
                        **common, "Category": label, "Status": "Available",
                        "Share": share, "Plot share": share,
                        "Midpoint": running + share / 2,
                        "Share label": f"{share:.0f}%" if share >= 5 else "",
                        "Amount": amount * factor / divisor,
                        "Total": total * factor / divisor,
                        "Stack order": index,
                    })
                    running += share
    return pd.DataFrame(output, columns=_COLUMNS), issues


def csm_transition_chart(rows: pd.DataFrame, companies: list[str], *,
                         transparent: bool = True, show_labels: bool = True,
                         ) -> alt.TopLevelMixin | None:
    """One 100% horizontal bar per year and insurer; grey means unavailable."""
    if rows.empty:
        return None
    panels = list(dict.fromkeys(
        panel for company in companies
        for panel in rows.loc[rows["Company"].eq(company), "Panel"]
    ))
    if not panels:
        return None
    periods = sorted(rows["Period label"].unique(), reverse=True)
    width, spacing = _company_panel_width(len(panels))
    height = max(160, len(periods) * 72)
    base = alt.Chart(rows)
    x = alt.X("Plot share:Q", stack="zero", scale=alt.Scale(domain=[0, 100]),
              axis=alt.Axis(title="Share of closing insurance CSM (%)",
                            values=[0, 20, 40, 60, 80, 100], labelExpr="datum.value + '%'"))
    y = alt.Y("Period label:N", sort=periods, title=None,
              axis=alt.Axis(labelAngle=0, labelPadding=8))
    missing = base.transform_filter(alt.datum.Status == "Not disclosed").mark_bar(
        size=32, color="#CECECE",
    ).encode(x=x, y=y, tooltip=[alt.Tooltip("Period label:N", title="Year"),
                                alt.Tooltip("Status:N", title="Insurance CSM category split")])
    category_order = [label for _, label, _ in CATEGORIES]
    colors = [color for _, _, color in CATEGORIES]
    bars = base.transform_filter(alt.datum.Status == "Available").mark_bar(
        size=32, strokeWidth=0,
    ).encode(
        x=x, y=y,
        color=alt.Color("Category:N", scale=alt.Scale(domain=category_order, range=colors),
                        legend=alt.Legend(title=None, orient="bottom",
                                          symbolStrokeWidth=0, symbolType="square")),
        order=alt.Order("Stack order:Q", sort="ascending"),
        tooltip=[alt.Tooltip("Period label:N", title="Year"),
                 alt.Tooltip("Category:N", title="Insurance CSM category"),
                 alt.Tooltip("Share:Q", title="Share (%)", format=".1f"),
                 alt.Tooltip("Amount:Q", title="CSM amount", format=",.2f"),
                 alt.Tooltip("Total:Q", title="Closing insurance CSM", format=",.2f"),
                 alt.Tooltip("Currency:N"), alt.Tooltip("Unit:N")],
    )
    layers = [missing, bars]
    if show_labels:
        layers.append(base.transform_filter(alt.datum.Status == "Available")
                      .mark_text(color="white", fontSize=10, fontWeight="bold")
                      .encode(x=alt.X("Midpoint:Q", scale=alt.Scale(domain=[0, 100]),
                                    axis=None), y=y, text="Share label:N"))
    layers.append(base.transform_filter(alt.datum.Status == "Not disclosed")
                  .mark_text(color="white", fontSize=11, fontWeight="bold")
                  .encode(x=alt.X("Midpoint:Q", scale=alt.Scale(domain=[0, 100]),
                                axis=None), y=y, text="Share label:N"))
    chart = alt.layer(*layers).properties(width=width, height=height).facet(
        facet=alt.Facet("Panel:N", sort=panels, title=None,
                        header=alt.Header(labelPadding=13)),
        columns=len(panels), spacing=spacing,
    ).resolve_scale(x="shared", y="shared")
    return _report_chart_theme(chart, transparent=transparent)
