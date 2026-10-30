"""Like-for-like ratios from contracts initially recognised in the year."""

from __future__ import annotations

import math

import altair as alt
import pandas as pd

from .charts import BLUE, COBALT, PINK, PURPLE, _company_scope_label, _report_chart_theme, period_label


RATIO_TITLES = (
    "New business CSM margin",
    "New business loss ratio",
    "New business risk adjustment ratio",
)
RATIO_EXPLANATION = (
    "CSM margin = |new profitable-contract CSM| / |profitable-contract PV inflows|; "
    "loss ratio = −|initial loss on new onerous contracts| / |onerous-contract PV inflows|; "
    "risk adjustment ratio = (|profitable-contract RA| + |onerous-contract RA|) "
    "/ (|profitable-contract PV inflows| + |onerous-contract PV inflows|). "
    "All inputs are from initially recognised non-PAA insurance contracts "
    "in the same filing and year; reinsurance is excluded."
)
RATIO_INPUTS = {
    RATIO_TITLES[0]: ("NB_INS_PROFIT_CSM", "NB_INS_PROFIT_PV_IN"),
    RATIO_TITLES[1]: ("NB_INS_ONEROUS_LOSS", "NB_INS_ONEROUS_PV_IN"),
    RATIO_TITLES[2]: (
        "NB_INS_PROFIT_RA", "NB_INS_ONEROUS_RA",
        "NB_INS_PROFIT_PV_IN", "NB_INS_ONEROUS_PV_IN",
    ),
}
RATIO_COLORS = {
    RATIO_TITLES[0]: ("#95E5FF", COBALT),
    RATIO_TITLES[1]: ("#FFD6EB", PINK),
    RATIO_TITLES[2]: ("#E3CFFB", PURPLE),
}
ROW_COLUMNS = (
    "Company", "Company label", "Scope", "Period", "Period label", "Currency",
    "Ratio", "Ratio (%)", "Numerator", "PV inflows",
)
IFRS_MARGIN_INPUTS = (
    "NB_INS_PROFIT_CSM", "NB_INS_ONEROUS_LOSS",
    "NB_INS_PROFIT_PV_IN", "NB_INS_ONEROUS_PV_IN",
)
IFRS_MARGIN_EXPLANATION = (
    "New business IFRS profit margin = (new-business CSM − initial loss component "
    "from new onerous business) / total present value of future cash inflows "
    "from new business × 100%. The denominator combines the profitable and "
    "onerous non-PAA insurance-contract columns in the same filing and year; "
    "reinsurance is excluded. Source signs are converted to magnitudes for "
    "CSM, loss component and inflows."
)
IFRS_MARGIN_COLUMNS = (
    "Company", "Insurer", "Period", "Year", "Currency", "Margin (%)",
    "NBCSM", "NBLC", "Total PV inflows",
)


def new_business_ratio_rows(
    frame: pd.DataFrame, companies: list[str], periods: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Require matching initial-recognition columns; missing is never zero."""
    rows = []
    gaps = []
    input_codes = {code for inputs in RATIO_INPUTS.values() for code in inputs}
    for company in companies:
        for period in periods:
            filing = frame.loc[
                frame["Company"].eq(company)
                & frame["Period end"].astype(str).eq(period)
                & frame["Metric code"].isin(input_codes)
            ]
            if filing.empty:
                continue
            if filing["Document ID"].nunique() != 1:
                gaps.append(f"{company} {period_label(period)}: multiple filings in the selection")
                continue
            values = {}
            for code in input_codes:
                matches = filing.loc[filing["Metric code"].eq(code), "Value (millions)"]
                if len(matches) != 1:
                    continue
                value = pd.to_numeric(matches.iloc[0], errors="coerce")
                if pd.notna(value) and math.isfinite(float(value)):
                    values[code] = float(value)

            scope = str(filing["Scope"].iloc[0])
            currency = str(filing["Currency"].iloc[0])
            for ratio, inputs in RATIO_INPUTS.items():
                missing = [code for code in inputs if code not in values]
                if missing:
                    gaps.append(f"{company} {period_label(period)} · {ratio}: unavailable {', '.join(missing)}")
                    continue
                if ratio == RATIO_TITLES[0]:
                    numerator = abs(values["NB_INS_PROFIT_CSM"])
                    denominator = abs(values["NB_INS_PROFIT_PV_IN"])
                elif ratio == RATIO_TITLES[1]:
                    numerator = -abs(values["NB_INS_ONEROUS_LOSS"])
                    denominator = abs(values["NB_INS_ONEROUS_PV_IN"])
                else:
                    numerator = (abs(values["NB_INS_PROFIT_RA"])
                                 + abs(values["NB_INS_ONEROUS_RA"]))
                    denominator = (abs(values["NB_INS_PROFIT_PV_IN"])
                                   + abs(values["NB_INS_ONEROUS_PV_IN"]))
                if denominator == 0:
                    gaps.append(f"{company} {period_label(period)} · {ratio}: zero PV inflows")
                    continue
                rows.append({
                    "Company": company,
                    "Company label": _company_scope_label(company, scope),
                    "Scope": scope,
                    "Period": period,
                    "Period label": period_label(period),
                    "Currency": currency,
                    "Ratio": ratio,
                    "Ratio (%)": 100 * numerator / denominator,
                    "Numerator": numerator,
                    "PV inflows": denominator,
                })
    return pd.DataFrame(rows, columns=ROW_COLUMNS), gaps


def new_business_ratio_chart(
    rows: pd.DataFrame, ratio: str, *, companies: list[str], periods: list[str],
    tracked_company: str | None = None, decimals: int = 1,
    show_labels: bool = True, transparent: bool = True, show_mean: bool = True,
    height: int = 170,
) -> tuple[alt.TopLevelMixin | None, float | None]:
    """Group year bars by insurer, with a latest-year peer mean and tracking tint."""
    selected = rows.loc[rows["Ratio"].eq(ratio)].copy()
    if selected.empty:
        return None, None
    company_labels = [
        selected.loc[selected["Company"].eq(company), "Company label"].iloc[0]
        for company in companies if selected["Company"].eq(company).any()
    ]
    period_labels = [period_label(period) for period in periods
                     if selected["Period"].eq(period).any()]
    light, dark = RATIO_COLORS[ratio]
    period_colors = [light] * max(0, len(period_labels) - 1) + [dark]
    latest_period = periods[-1] if periods else None
    current = selected.loc[selected["Period"].eq(latest_period), "Ratio (%)"]
    mean = float(current.mean()) if show_mean and not current.empty else None
    selected["Value label"] = selected["Ratio (%)"].map(
        lambda value: f"{value:.{decimals}f}%"
    )
    selected["Label center"] = selected["Ratio (%)"] / 2
    selected["Inside label"] = (
        selected["Ratio (%)"].abs() >= 0.18 * selected["Ratio (%)"].abs().max()
    ) & selected["Ratio (%)"].ne(0)

    # Keep insurer groups distinct while letting the paired bars grow and
    # shrink with the chart container. The category tick stays at their centre.
    company_padding = (0.92 if len(company_labels) == 1 else
                       0.70 if len(company_labels) == 2 else
                       0.55 if len(company_labels) == 3 else 0.50)
    x = alt.X("Company label:N", sort=company_labels,
              scale=alt.Scale(paddingInner=company_padding, paddingOuter=0.2),
              axis=alt.Axis(title=None, labelAngle=0, labelLimit=190,
                            labelAlign="center", labelColor=BLUE,
                            labelFontWeight="bold"))
    year_offset = alt.XOffset("Period label:N", sort=period_labels,
                              scale=alt.Scale(paddingInner=0, paddingOuter=0))
    y = alt.Y("Ratio (%):Q", scale=alt.Scale(zero=True),
              axis=alt.Axis(title="Ratio (%)", format=".0f"))
    base = alt.Chart(selected)
    layers = []
    if tracked_company and selected["Company"].eq(tracked_company).any():
        backdrop = selected.loc[selected["Company"].eq(tracked_company)].drop_duplicates("Company label")
        layers.append(
            alt.Chart(backdrop).mark_rect(fill=COBALT, fillOpacity=0.07,
                                          stroke=COBALT, strokeWidth=1.4)
            .encode(x=x, y=alt.value(0), y2=alt.value(height))
        )
    mean_chart = None
    if mean is not None:
        mean_chart = alt.Chart(pd.DataFrame({
            "Mean": [mean],
            "Mean label": [f"{period_label(latest_period)}\nAvg {mean:.1f}%"],
            "Mean detail": [f"{period_label(latest_period)} mean {mean:.1f}%"],
        }))
        layers.append(
            mean_chart.mark_rule(color=dark, strokeDash=[7, 5], strokeWidth=1.5)
            .encode(y="Mean:Q", tooltip=alt.Tooltip("Mean detail:N", title="Average"))
        )
    layers.append(base.mark_bar().encode(
        x=x, xOffset=year_offset, y=y,
        color=alt.Color("Period label:N", sort=period_labels,
                        scale=alt.Scale(domain=period_labels, range=period_colors),
                        legend=alt.Legend(title=None, orient="right", offset=8)),
        tooltip=[
            alt.Tooltip("Company label:N", title="Insurer"),
            alt.Tooltip("Period label:N", title="Year"),
            alt.Tooltip("Ratio (%):Q", title="Ratio (%)", format=".2f"),
            alt.Tooltip("Numerator:Q", title="Numerator", format=",.3f"),
            alt.Tooltip("PV inflows:Q", title="PV inflows", format=",.3f"),
            alt.Tooltip("Currency:N", title="Filing currency"),
        ],
    ))
    if show_labels:
        inside = selected.loc[selected["Inside label"]]
        if not inside.empty:
            layers.append(
                alt.Chart(inside).mark_text(baseline="middle", fontSize=10,
                                            fontWeight="bold")
                .encode(x=x, xOffset=year_offset, y="Label center:Q",
                        text="Value label:N",
                        color=alt.condition(
                            alt.datum["Period label"] == period_labels[-1],
                            alt.value("white"), alt.value(BLUE),
                        ))
            )
        for positive, dy in ((True, -9), (False, 10)):
            outside = selected.loc[
                ~selected["Inside label"]
                & (selected["Ratio (%)"].ge(0) if positive
                   else selected["Ratio (%)"].lt(0))
            ]
            if not outside.empty:
                layers.append(
                    alt.Chart(outside).mark_text(dy=dy, fontSize=10, color=BLUE)
                    .encode(x=x, xOffset=year_offset, y="Ratio (%):Q",
                            text="Value label:N")
                )
    if mean_chart is not None:
        layers.append(
            mean_chart.mark_text(align="left", baseline="top", dx=6, dy=4,
                                 lineBreak="\n", fontSize=10,
                                 fontWeight="bold", color=dark)
            .encode(x=alt.value(0), y="Mean:Q", text="Mean label:N")
        )
    chart = alt.layer(*layers).properties(width="container", height=height)
    return _report_chart_theme(chart, transparent=transparent), mean


def new_business_ifrs_margin_rows(
    frame: pd.DataFrame, companies: list[str], periods: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Calculate the requested margin from four matched disclosure cells."""
    rows: list[dict] = []
    gaps: list[str] = []
    for company in companies:
        for period in periods:
            filing = frame.loc[
                frame["Company"].eq(company)
                & frame["Period end"].astype(str).eq(str(period))
                & frame["Metric code"].isin(IFRS_MARGIN_INPUTS)
            ]
            if filing.empty:
                continue
            if filing["Document ID"].nunique() != 1 or filing["Scope"].nunique() != 1:
                gaps.append(f"{company} {period_label(period)}: multiple filings or scopes in the selection")
                continue
            values: dict[str, float] = {}
            for code in IFRS_MARGIN_INPUTS:
                cells = filing.loc[filing["Metric code"].eq(code), "Value (millions)"]
                if len(cells) != 1:
                    continue
                value = pd.to_numeric(cells.iloc[0], errors="coerce")
                if pd.notna(value) and math.isfinite(float(value)):
                    values[code] = float(value)
            missing = [code for code in IFRS_MARGIN_INPUTS if code not in values]
            if missing:
                gaps.append(f"{company} {period_label(period)}: unavailable {', '.join(missing)}")
                continue
            inflows = abs(values["NB_INS_PROFIT_PV_IN"]) + abs(values["NB_INS_ONEROUS_PV_IN"])
            if inflows <= 0:
                gaps.append(f"{company} {period_label(period)}: zero total PV inflows")
                continue
            csm = abs(values["NB_INS_PROFIT_CSM"])
            loss = abs(values["NB_INS_ONEROUS_LOSS"])
            rows.append({
                "Company": company,
                "Insurer": _company_scope_label(company, str(filing["Scope"].iloc[0])),
                "Period": str(period),
                "Year": period_label(period),
                "Currency": str(filing["Currency"].iloc[0]),
                "Margin (%)": 100 * (csm - loss) / inflows,
                "NBCSM": csm,
                "NBLC": loss,
                "Total PV inflows": inflows,
            })
    return pd.DataFrame(rows, columns=IFRS_MARGIN_COLUMNS), gaps


def new_business_ifrs_margin_chart(
    rows: pd.DataFrame, *, companies: list[str], periods: list[str],
    tracked_company: str | None = None, decimals: int = 2,
    show_labels: bool = True, transparent: bool = True,
) -> alt.TopLevelMixin | None:
    """Responsive, company-colored yearly margin lines."""
    if rows.empty:
        return None
    selected = rows.copy()
    year_order = [period_label(period) for period in periods]
    insurer_order = [
        selected.loc[selected["Company"].eq(company), "Insurer"].iloc[0]
        for company in companies if selected["Company"].eq(company).any()
    ]
    palette = ("#C81728", COBALT, "#FD72BD", "#008A78", PURPLE)
    color_scale = alt.Scale(
        domain=insurer_order,
        range=[palette[index % len(palette)] for index in range(len(insurer_order))],
    )
    color = alt.Color(
        "Insurer:N", scale=color_scale,
        legend=alt.Legend(title=None, orient="top", direction="horizontal",
                          columns=3, offset=18, symbolType="circle",
                          symbolStrokeWidth=0, labelLimit=180),
    )
    no_legend_color = alt.Color("Insurer:N", scale=color_scale, legend=None)
    opacity = (alt.condition(alt.datum.Company == tracked_company,
                             alt.value(1), alt.value(0.28))
               if tracked_company and tracked_company in set(selected["Company"])
               else alt.value(1))
    selected["Value label"] = selected["Margin (%)"].map(
        lambda value: f"{value:,.{decimals}f}%"
    )
    x = alt.X("Year:N", sort=year_order, title=None,
              axis=alt.Axis(labelAngle=0, labelLimit=95))
    y = alt.Y("Margin (%):Q", title="New business IFRS profit margin (%)",
              scale=alt.Scale(zero=False), axis=alt.Axis(format=".1f"))
    tooltip = [
        alt.Tooltip("Insurer:N"),
        alt.Tooltip("Year:N"),
        alt.Tooltip("Margin (%):Q", format=".2f"),
        alt.Tooltip("NBCSM:Q", format=",.3f"),
        alt.Tooltip("NBLC:Q", format=",.3f"),
        alt.Tooltip("Total PV inflows:Q", format=",.3f"),
        alt.Tooltip("Currency:N", title="Filing currency"),
    ]
    base = alt.Chart(selected)
    layers = [
        base.mark_line(strokeWidth=2.5, strokeDash=[5, 4], point=False)
        .encode(x=x, y=y, color=color, opacity=opacity, tooltip=tooltip),
        base.mark_circle(size=80)
        .encode(x=x, y=y, color=no_legend_color, opacity=opacity, tooltip=tooltip),
    ]
    if show_labels:
        layers.append(
            base.mark_text(fontSize=10, fontWeight="bold", dy=-12, tooltip=False)
            .encode(x=x, y=y, text="Value label:N", color=no_legend_color,
                    opacity=opacity)
        )
    chart = alt.layer(*layers).properties(
        width="container", height=300,
        padding={"top": 12, "right": 16, "bottom": 8, "left": 8},
    )
    return _report_chart_theme(chart, transparent=transparent)
