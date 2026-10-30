"""Reconciled insurance CSM roll-forward waterfalls."""

from __future__ import annotations

import math

import altair as alt
import pandas as pd

from .charts import KPMG_INK, _company_panel_width, _report_chart_theme
from .fx import year_end_usd_hkd
from .oci_analysis import _single_amount
from .oci_waterfall import _amount_label


_MOVEMENTS = (
    ("CSM_NEW", "New business", "CSM on contracts initially recognised"),
    ("CSM_ESTIMATE_CHANGE", "Estimates", "Changes in estimates"),
    ("CSM_FINANCE_CHANGE", "Finance", "Finance income or expenses on CSM"),
    ("CSM_RELEASE", "Release", "CSM recognised for services"),
)
PRE_RELEASE_CSM_CODES = (
    "CSM_NEW", "CSM_ESTIMATE_CHANGE", "CSM_FINANCE_CHANGE",
)
PRE_RELEASE_CSM_LABELS = {
    "CSM_NEW": "New business CSM",
    "CSM_ESTIMATE_CHANGE": "Changes in estimates",
    "CSM_FINANCE_CHANGE": "Finance change on CSM",
}
PRE_RELEASE_CSM_COLORS = {
    "New business CSM": "#00338D",
    "Changes in estimates": "#00AEEF",
    "Finance change on CSM": "#B48AFE",
}
_BAR_COLORS = {
    "Opening": "#00338D",
    "Increase": "#FF3290",
    "Decrease": "#1E49E2",
    "Closing": "#7213EA",
}
_COLUMNS = [
    "Document ID", "Company", "Scope", "Period end", "Year", "Currency",
    "Opening", "Movements", "Calculated remainder", "Closing",
]


def csm_waterfall_rows(records: pd.DataFrame, companies: list[str],
                       periods: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Build one bridge per filing and period, omitting incomplete or conflicting inputs."""
    if records.empty:
        return pd.DataFrame(columns=_COLUMNS), []
    selected = records.loc[
        records["Company"].isin(companies) & records["Period end"].isin(periods)
        & records["Currency"].isin(("HKD", "USD"))
    ]
    output: list[dict] = []
    issues: list[str] = []
    keys = ["Document ID", "Company", "Scope", "Period end", "Currency"]
    for identity, group in selected.groupby(keys, sort=False, dropna=False):
        document, company, scope, period, currency = map(str, identity)
        year = period[:4]
        opening = _single_amount(group, "CSM_OPEN")
        closing = _single_amount(group, "CSM_CLOSE")
        movements = []
        missing = []
        for code, short, full in _MOVEMENTS:
            amount = _single_amount(group, code)
            if amount is None:
                missing.append(short)
            else:
                movements.append({"Step": short, "Line item": full, "Amount": amount})
        if opening is None or closing is None or missing:
            missing = (["Opening CSM"] if opening is None else []) + missing + (
                ["Closing CSM"] if closing is None else []
            )
            issues.append(f"{company} {year}: CSM waterfall unavailable; missing "
                          + ", ".join(missing) + ".")
            continue
        if opening < 0 or closing < 0:
            issues.append(f"{company} {year}: CSM balances have an unresolved sign; the waterfall is omitted.")
            continue
        net = _single_amount(group, "CSM_NET_MOVEMENT")
        difference = closing - opening
        tolerance = max(0.00001, abs(difference) * 1e-8)
        if net is not None and not math.isclose(net, difference, rel_tol=0, abs_tol=tolerance):
            issues.append(f"{company} {year}: reported net CSM movement does not reconcile to "
                          "opening and closing balances; the waterfall is omitted.")
            continue
        remainder = difference - sum(item["Amount"] for item in movements)
        if abs(remainder) <= tolerance:
            remainder = 0.0
        else:
            movements.append({
                "Step": "Other*", "Line item": "Other CSM movements (calculated remainder)",
                "Amount": remainder,
            })
        output.append({
            "Document ID": document, "Company": company, "Scope": scope,
            "Period end": period, "Year": year, "Currency": currency,
            "Opening": opening, "Movements": movements,
            "Calculated remainder": remainder, "Closing": closing,
        })
    return pd.DataFrame(output, columns=_COLUMNS), issues


def csm_waterfall_chart(rows: pd.DataFrame, companies: list[str], *,
                        display_mode: str = "Native currencies", unit: str = "millions",
                        decimals: int = 0, transparent: bool = True,
                        show_labels: bool = True,
                        ) -> tuple[alt.TopLevelMixin | None, list[str]]:
    """Show signed CSM changes from opening to closing, one panel per insurer."""
    if rows.empty:
        return None, []
    divisor = 1000.0 if unit == "billions" else 1.0
    points: list[dict] = []
    excluded: list[str] = []
    panel_order: list[str] = []
    for company in companies:
        for _, row in rows.loc[rows["Company"].eq(company)].iterrows():
            currency = str(row["Currency"])
            rate = 1.0
            if display_mode == "HKD converted" and currency == "USD":
                info = year_end_usd_hkd(int(row["Year"]))
                if info is None:
                    excluded.append(f"{company} {row['Year']}")
                    continue
                rate = float(info[0])
            shown_currency = "HKD" if display_mode == "HKD converted" else currency
            panel = f"{company} ({str(row['Scope']).title()}) · {shown_currency}"
            panel_order.append(panel)
            steps = [
                ("Open", "Opening insurance CSM", float(row["Opening"])),
                *((item["Step"], item["Line item"], float(item["Amount"]))
                  for item in row["Movements"]),
                ("Close", "Closing insurance CSM", float(row["Closing"])),
            ]
            running = 0.0
            for index, (step, line_item, original) in enumerate(steps):
                is_closing = index == len(steps) - 1
                start = 0.0 if index == 0 or is_closing else running
                end = original if index == 0 or is_closing else running + original
                if not is_closing:
                    running = end
                amount = original * rate / divisor
                bar_type = ("Opening" if index == 0 else "Closing" if is_closing
                            else "Increase" if original > 0 else "Decrease" if original < 0
                            else None)
                points.append({
                    "Panel": panel, "Year": row["Year"], "Step": step,
                    "Step order": index, "Next step": steps[index + 1][0] if not is_closing else None,
                    "Has next step": not is_closing, "Line item": line_item,
                    "Bar type": bar_type, "Lower": min(start, end) * rate / divisor,
                    "Upper": max(start, end) * rate / divisor, "End": end * rate / divisor,
                    "Amount": amount, "Value label": _amount_label(amount, decimals),
                    "Display currency": shown_currency, "Original amount": original,
                    "Original currency": currency,
                })
    if not points:
        return None, excluded
    plot = pd.DataFrame(points)
    panel_order = list(dict.fromkeys(panel_order))
    sort = alt.SortField(field="Step order", order="ascending")
    x = alt.X("Step:N", sort=sort, title=None,
              axis=alt.Axis(labelAngle=-45, labelFontSize=9, labelLimit=110,
                            labelOverlap=False, labelSeparation=0))
    y_title = (f"{plot['Display currency'].iloc[0]} {unit}"
               if plot["Display currency"].nunique() == 1 else f"Amount ({unit})")
    y = alt.Y("Upper:Q", title=y_title, scale=alt.Scale(zero=True),
              axis=alt.Axis(format="~s"))
    color = alt.Color("Bar type:N", title=None,
                      scale=alt.Scale(domain=list(_BAR_COLORS),
                                      range=list(_BAR_COLORS.values())),
                      legend=alt.Legend(orient="bottom", direction="horizontal", columns=4))
    base = alt.Chart(plot)
    tooltip = [
        alt.Tooltip("Panel:N", title="Insurer"), alt.Tooltip("Year:N"),
        alt.Tooltip("Line item:N"),
        alt.Tooltip("Amount:Q", format=",.3f", title=f"Amount ({unit})"),
        alt.Tooltip("Display currency:N"),
        alt.Tooltip("Original amount:Q", format=",.3f", title="Original amount (millions)"),
        alt.Tooltip("Original currency:N"),
    ]
    bars = base.transform_filter(alt.datum.Amount != 0).mark_bar(
        size=28, opacity=0.94,
    ).encode(x=x, y=y, y2="Lower:Q", color=color, tooltip=tooltip)
    connectors = base.transform_filter(alt.datum["Has next step"]).mark_rule(
        color="#A7B0BE", strokeWidth=1,
    ).encode(x=alt.X("Step:N", sort=sort, bandPosition=1),
             x2=alt.X2("Next step:N", bandPosition=0), y=alt.Y("End:Q", title=None))
    layers = [connectors, bars]
    if show_labels:
        zero = base.transform_filter(alt.datum.Amount == 0).mark_tick(
            size=26, thickness=2, color="#B8C0CC",
        ).encode(x=x, y=alt.Y("End:Q", title=None), tooltip=tooltip)
        positive = base.transform_filter(alt.datum.Amount > 0).mark_text(
            dy=-8, fontSize=9, fontWeight="bold", color=KPMG_INK,
        ).encode(x=x, y=alt.Y("End:Q", title=None), text="Value label:N")
        negative = base.transform_filter(alt.datum.Amount < 0).mark_text(
            dy=11, fontSize=9, fontWeight="bold", color=KPMG_INK,
        ).encode(x=x, y=alt.Y("End:Q", title=None), text="Value label:N")
        layers.extend([zero, positive, negative])
    width, spacing = _company_panel_width(len(panel_order))
    chart = alt.layer(*layers).properties(width=width, height=330).facet(
        facet=alt.Facet("Panel:N", sort=panel_order, title=None,
                        header=alt.Header(labelPadding=14)),
        columns=len(panel_order), spacing=spacing,
    ).resolve_scale(x="independent",
                    y="shared" if display_mode == "HKD converted" else "independent")
    return _report_chart_theme(chart, transparent=transparent), excluded


def csm_waterfall_notes(rows: pd.DataFrame) -> list[str]:
    if rows.empty:
        return []
    notes = ["Opening CSM + signed movements = closing CSM. Pink and blue show increases "
             "and decreases; navy and purple show the opening and closing balances."]
    for _, row in rows.iterrows():
        if row["Calculated remainder"]:
            notes.append(
                f"{row['Company']} ({str(row['Scope']).title()}) {row['Year']}YE: Other* "
                "is a calculated remainder (closing − opening − the four displayed "
                "movements), not a separately disclosed CSM item."
            )
    return notes


def csm_pre_release_rows(records: pd.DataFrame, companies: list[str],
                         periods: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Keep only complete three-item insurance CSM movements before release."""
    if records.empty:
        return records.copy(), []
    selected = records.loc[
        records["Company"].isin(companies) & records["Period end"].isin(periods)
        & records["Currency"].isin(("HKD", "USD"))
    ]
    groups = []
    issues = []
    for (_, company, _, period, _), group in selected.groupby(
            ["Document ID", "Company", "Scope", "Period end", "Currency"],
            sort=False, dropna=False):
        values = [_single_amount(group, code) for code in PRE_RELEASE_CSM_CODES]
        if any(value is None for value in values):
            issues.append(f"{company} {str(period)[:4]}YE: pre-release CSM mix unavailable; "
                          "one or more of new business, estimates and finance changes are not disclosed.")
            continue
        if not any(value != 0 for value in values):
            issues.append(f"{company} {str(period)[:4]}YE: all three disclosed pre-release "
                          "CSM movements are zero; a percentage mix is unavailable.")
            continue
        groups.append(group.loc[group["Metric code"].isin(PRE_RELEASE_CSM_CODES)])
    return (pd.concat(groups, ignore_index=True) if groups
            else selected.iloc[0:0].copy()), issues


def csm_pre_release_combined_chart(
        records: pd.DataFrame, companies: list[str], *,
        display_mode: str = "Native currencies", unit: str = "millions",
        tracked_company: str | None = None, transparent: bool = True,
        show_labels: bool = True,
        ) -> tuple[alt.TopLevelMixin | None, list[str], str]:
    """Compare complete pre-release CSM movement stacks on one currency axis."""
    if records.empty:
        return None, [], ""
    periods = records["Period end"].astype(str).unique()
    if len(periods) != 1:
        raise ValueError("A combined pre-release CSM chart requires one reporting period.")
    currencies = set(records["Currency"].astype(str))
    convert_to_hkd = display_mode == "HKD converted" or len(currencies) > 1
    shown_currency = "HKD" if convert_to_hkd else next(iter(currencies))
    divisor = 1000.0 if unit == "billions" else 1.0
    data = []
    excluded = []
    for company in companies:
        company_rows = records.loc[records["Company"].eq(company)]
        for (_, scope, period, currency), group in company_rows.groupby(
                ["Document ID", "Scope", "Period end", "Currency"],
                sort=False, dropna=False):
            if group["Metric code"].nunique() != len(PRE_RELEASE_CSM_CODES):
                excluded.append(f"{company} {str(period)[:4]}YE: incomplete pre-release CSM mix.")
                continue
            rate = 1.0
            if convert_to_hkd and currency == "USD":
                rate_info = year_end_usd_hkd(int(str(period)[:4]))
                if rate_info is None:
                    excluded.append(f"{company} {str(period)[:4]}YE: USD/HKD rate unavailable; "
                                    "the amount bar is omitted.")
                    continue
                rate = float(rate_info[0])
            amounts = [_single_amount(group, code) for code in PRE_RELEASE_CSM_CODES]
            if any(amount is None for amount in amounts):
                excluded.append(f"{company} {str(period)[:4]}YE: incomplete pre-release CSM mix.")
                continue
            denominator = sum(abs(amount) for amount in amounts)
            if denominator == 0:
                continue
            positive = negative = 0.0
            for order, (code, original) in enumerate(zip(PRE_RELEASE_CSM_CODES, amounts)):
                amount = original * rate / divisor
                share = 100 * abs(original) / denominator
                if amount >= 0:
                    midpoint = positive + amount / 2
                    positive += amount
                else:
                    midpoint = negative + amount / 2
                    negative += amount
                data.append({
                    "Company": company, "Insurer": f"{company} ({str(scope).title()})",
                    "Scope": str(scope), "Period label": f"{str(period)[:4]}YE",
                    "Component": PRE_RELEASE_CSM_LABELS[code], "Amount": amount,
                    "Share (%)": share, "Percent label": f"{share:.0f}%" if share >= 5 else "",
                    "Label midpoint": midpoint, "Stack order": order,
                    "Currency": shown_currency, "Unit": unit,
                    "Original amount (millions)": original,
                    "Original currency": str(currency),
                })
    if not data:
        return None, excluded, shown_currency
    chart_rows = pd.DataFrame(data)
    # Labels need enough vertical room on the shared amount axis, even when a
    # component's share is large relative to its own company's movements.
    extents = chart_rows.assign(
        positive=chart_rows["Amount"].clip(lower=0),
        negative=chart_rows["Amount"].clip(upper=0),
    ).groupby("Insurer")[["positive", "negative"]].sum()
    axis_span = 1.15 * (extents["positive"].max() - extents["negative"].min())
    minimum_label_amount = axis_span * 20 / 330
    chart_rows.loc[chart_rows["Amount"].abs() < minimum_label_amount, "Percent label"] = ""
    panel_order = list(dict.fromkeys(
        label for company in companies
        for label in chart_rows.loc[chart_rows["Company"].eq(company), "Insurer"]
    ))
    x = alt.X("Insurer:N", sort=panel_order, title=None,
              axis=alt.Axis(labelAngle=0, labelLimit=190, labelPadding=12))
    y = alt.Y("Amount:Q", stack="zero", title=f"{shown_currency} {unit}",
              axis=alt.Axis(format="~s"))
    color = alt.Color(
        "Component:N",
        scale=alt.Scale(
            domain=list(PRE_RELEASE_CSM_COLORS),
            range=list(PRE_RELEASE_CSM_COLORS.values()),
        ),
        legend=alt.Legend(title=None, orient="bottom", direction="horizontal",
                          symbolType="square", symbolStrokeWidth=0, labelLimit=220),
    )
    tooltip = [
        alt.Tooltip("Insurer:N"), alt.Tooltip("Period label:N", title="Period"),
        alt.Tooltip("Component:N"),
        alt.Tooltip("Amount:Q", title=f"Amount ({shown_currency} {unit})", format=",.2f"),
        alt.Tooltip("Share (%):Q", title="Share of absolute movements (%)", format=".1f"),
        alt.Tooltip("Original amount (millions):Q", format=",.3f"),
        alt.Tooltip("Original currency:N"),
    ]
    bars = alt.Chart(chart_rows).mark_bar(size=72, opacity=0.94).encode(
        x=x, y=y, color=color,
        order=alt.Order("Stack order:Q", sort="ascending"),
        tooltip=tooltip,
    )
    if tracked_company:
        bars = bars.encode(opacity=alt.condition(
            alt.datum.Company == tracked_company, alt.value(1), alt.value(0.42),
        ))
    layers = [bars]
    if show_labels:
        labels = alt.Chart(chart_rows).mark_text(
            fontSize=11, fontWeight="bold", baseline="middle", tooltip=False,
        ).encode(
            x=x, y=alt.Y("Label midpoint:Q", stack=None),
            text="Percent label:N",
            color=alt.condition(alt.datum.Component == "New business CSM",
                                alt.value("#FFFFFF"), alt.value(KPMG_INK)),
        )
        if tracked_company:
            labels = labels.encode(opacity=alt.condition(
                alt.datum.Company == tracked_company, alt.value(1), alt.value(0.42),
            ))
        layers.append(labels)
    chart = alt.layer(*layers).properties(width=920, height=330)
    return _report_chart_theme(chart, transparent=transparent), excluded, shown_currency


_TABLE_METRICS = (
    ("Opening CSM", "CSM_OPEN"),
    ("New business CSM", "CSM_NEW"),
    ("CSM finance change", "CSM_FINANCE_CHANGE"),
    ("CSM estimate change", "CSM_ESTIMATE_CHANGE"),
    ("CSM release", "CSM_RELEASE"),
    ("Closing CSM", "CSM_CLOSE"),
)
_TABLE_COLUMNS = [
    "Company", "Opening CSM", "New business CSM", "CSM finance change",
    "CSM estimate change", "CSM release", "Other movements*", "Closing CSM",
]


def csm_rollforward_table(records: pd.DataFrame, companies: list[str],
                          periods: list[str], *,
                          display_mode: str = "Native currencies",
                          unit: str = "millions") -> tuple[pd.DataFrame, list[str]]:
    """Show disclosed balances and changes, with a labelled reconciliation remainder."""
    if records.empty:
        return pd.DataFrame(columns=_TABLE_COLUMNS), []
    selected = records.loc[
        records["Company"].isin(companies) & records["Period end"].isin(periods)
        & records["Currency"].isin(("HKD", "USD"))
        & records["Metric code"].isin({code for _, code in _TABLE_METRICS}
                                      | {"CSM_NET_MOVEMENT"})
    ]
    bridges, bridge_issues = csm_waterfall_rows(selected, companies, periods)
    bridge_lookup = {
        (str(row["Document ID"]), str(row["Scope"]), str(row["Period end"]),
         str(row["Currency"])): row
        for _, row in bridges.iterrows()
    }
    divisor = 1000.0 if unit == "billions" else 1.0
    precision = 3 if unit == "billions" else 1
    rows = []
    issues = []
    for company in companies:
        company_rows = selected.loc[selected["Company"].eq(company)]
        for identity, group in company_rows.groupby(
                ["Document ID", "Scope", "Period end", "Currency"],
                sort=False, dropna=False):
            document, scope, period, currency = map(str, identity)
            rate = 1.0
            if display_mode == "HKD converted" and currency == "USD":
                rate_info = year_end_usd_hkd(int(period[:4]))
                if rate_info is None:
                    issues.append(f"{company} {period[:4]}: USD/HKD rate unavailable; table row omitted.")
                    continue
                rate = float(rate_info[0])
            shown_currency = "HKD" if display_mode == "HKD converted" else currency

            def cell(value: float | None) -> str:
                if value is None:
                    return "Not disclosed"
                displayed = value * rate / divisor
                return (f"({abs(displayed):,.{precision}f})" if displayed < 0
                        else f"{displayed:,.{precision}f}")

            values = {label: _single_amount(group, code) for label, code in _TABLE_METRICS}
            bridge = bridge_lookup.get((document, scope, period, currency))
            row = {
                "Company": f"{company} ({scope.title()}) · {shown_currency}",
                **{label: cell(value) for label, value in values.items()},
                "Other movements*": cell(
                    float(bridge["Calculated remainder"]) if bridge is not None else None
                ),
            }
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=_TABLE_COLUMNS), issues
    issues.extend(bridge_issues)
    return pd.DataFrame(rows, columns=_TABLE_COLUMNS), issues
