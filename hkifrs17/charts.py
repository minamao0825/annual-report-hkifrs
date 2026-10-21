"""Source-aware financial visualisations for reviewed primary and note cells."""

from __future__ import annotations

import re

import altair as alt
import pandas as pd

from .catalog import METRIC_BY_CODE
from .fx import year_end_usd_hkd


BLUE = "#00338D"
COBALT = "#1E49E2"
YEAR_BLUE = "#76D2FF"
CYAN = "#00B8F5"
PURPLE = "#7213EA"
GREEN = "#008A78"
PINK = "#FD349C"
PALETTE = [BLUE, CYAN, PURPLE, GREEN, PINK]
# Same bright bar palette and responsive one-row company panels as the
# solvency platform's Step 7 charts.
KPMG_BRIGHT_CHART_COLORS = (
    "#FFA3DA", "#00B8F5", "#FD349C", "#269924", "#ACEAFF",
    "#B497FF", "#63EBB2", "#00C0AE", "#F1C44D",
)
KPMG_INK = "#0C233C"
YEAR_COLORS = {"2024YE": YEAR_BLUE, "2025YE": COBALT}


def period_label(period: str) -> str:
    """Keep source dates intact while showing a compact financial-year label."""
    value = str(period)
    if len(value) >= 10 and value[4:5] == "-":
        return f"{value[:4]}YE"
    return value


def _report_chart_theme(chart: alt.TopLevelMixin, *, transparent: bool = True) -> alt.TopLevelMixin:
    background = "transparent" if transparent else "#FFFFFF"
    return (
        chart.properties(background=background)
        .configure(font="Arial")
        .configure_view(fill=background, strokeOpacity=0)
        .configure_axis(grid=False, domain=False, ticks=False,
                        labelFont="Arial", labelFontSize=10, labelColor=KPMG_INK,
                        titleFont="Arial", titleFontSize=11, titleColor=KPMG_INK)
        .configure_legend(labelFont="Arial", labelFontSize=11, labelColor=KPMG_INK,
                          titleFont="Arial", titleColor=KPMG_INK,
                          symbolType="square", symbolSize=100)
        .configure_header(labelFont="Arial", labelColor=BLUE,
                          labelFontSize=12, labelFontWeight="bold")
    )


def _company_panel_width(count: int) -> tuple[int, int]:
    """Match the solvency platform's one-row facets and shrinking panel width."""
    if count <= 1:
        return 760, 22
    spacing = 5 if count >= 10 else 8 if count >= 6 else 12 if count >= 4 else 22
    return max(52, (1120 - spacing * (count - 1)) // count), spacing


def _company_scope_label(name: str, scope: str) -> str:
    """Place the disclosed scope after the insurer name, before any currency."""
    normalized = {"company": "Company", "consolidated": "Consolidated"}.get(
        str(scope).strip().lower()
    )
    if normalized is None:
        return str(name)
    company, separator, currency = str(name).partition(" · ")
    company = re.sub(r"\s*\((?:Company|Consolidated)\)$", "", company,
                     flags=re.IGNORECASE)
    return f"{company} ({normalized}){separator}{currency}"


def frame_peer_company_panels(
    chart: alt.TopLevelMixin | None, *, tracked_company: str | None = None,
    tracked_scopes: tuple[str, ...] = (),
) -> alt.TopLevelMixin | None:
    """Frame company facets and tint the selected insurer's plotting panel."""
    if chart is None or not isinstance(chart, alt.FacetChart):
        return chart
    facet_field = str(chart.facet.shorthand).split(":", 1)[0]
    if facet_field not in {"Company", "Panel"}:
        return chart

    framed = chart
    framed.config.view = alt.ViewConfig(
        fill="transparent", stroke="#D8DCE5", strokeWidth=1, strokeOpacity=1,
    )
    if tracked_company and tracked_scopes:
        tracked_entities = {
            _company_scope_label(tracked_company, scope).split(" · ")[0]
            for scope in tracked_scopes
        }
        records = chart.data.to_dict("records") if isinstance(chart.data, pd.DataFrame) else []
        tracked_panels = sorted({
            str(row[facet_field]) for row in records
            if facet_field in row
            and str(row[facet_field]).split(" · ")[0] in tracked_entities
        })
        if tracked_panels and isinstance(framed.spec, alt.LayerChart):
            # A single aggregate row draws one backdrop per matching facet.
            backdrop = (alt.Chart()
                        .transform_filter(alt.FieldOneOfPredicate(
                            field=facet_field, oneOf=tracked_panels,
                        ))
                        .transform_aggregate(panel_rows="count()", groupby=[facet_field])
                        .mark_rect(fill=BLUE, fillOpacity=0.07,
                                   stroke=BLUE, strokeWidth=1.8)
                        .encode(x=alt.value(0), x2=alt.value(framed.spec.width),
                                y=alt.value(0), y2=alt.value(framed.spec.height)))
            framed.spec.layer.insert(0, backdrop)
    return framed


def _expense_display_rows(rows: pd.DataFrame, mode: str | None) -> pd.DataFrame:
    """Change expense chart signs without changing the accounting source rows."""
    if mode is None:
        return rows
    if mode not in {"magnitude", "contribution"}:
        raise ValueError(f"Unknown expense display mode: {mode}")
    rows = rows.copy()
    rows["Accounting signed amount"] = rows["Amount"]
    if mode == "magnitude":
        rows["Amount"] = rows["Amount"].abs()
    else:
        # YF's expense detail uses the positive liability-movement sign;
        # FWD and Sun use the negative P&L expense sign.
        yf_movement = rows["Company"].eq("YF Life")
        rows.loc[~yf_movement, "Amount"] *= -1
    return rows


def _stack_percent_label(share: float) -> str:
    """Keep small segments in the tooltip and round visible shares to integers."""
    return f"{share:.0f}%" if abs(share) >= 10 else ""


def _hide_colliding_labels(rows: pd.DataFrame, *, label_column: str,
                           metrics: list[str], periods: list[str],
                           company_order: list[str] | None, stacked: bool,
                           period_colors: bool, shared_y: bool,
                           font_size: int, chart_height: int) -> pd.DataFrame:
    """Keep centered labels only when their bars and neighboring labels fit."""
    rows = rows.copy()
    panel_width = (760 if company_order is None else
                   _company_panel_width(len(company_order))[0]) * 0.9
    period_index = {period: index for index, period in enumerate(periods)}
    metric_index = {metric: index for index, metric in enumerate(metrics)}
    step = panel_width / (len(periods) + 0.4)
    band_width = step * 0.5

    def y_span(panel: pd.DataFrame) -> float:
        if stacked:
            bar_keys = (["Company"] if "Company" in panel else []) + ["Period label"]
            grouped = panel.groupby(bar_keys, sort=False)["Amount"]
            upper = max(0.0, float(grouped.apply(
                lambda values: values.clip(lower=0).sum()
            ).max()))
            lower = min(0.0, float(grouped.apply(
                lambda values: values.clip(upper=0).sum()
            ).min()))
        else:
            upper = max(0.0, float(panel["Amount"].max()))
            lower = min(0.0, float(panel["Amount"].min()))
        return upper - lower

    shared_span = y_span(rows) if company_order is None or shared_y else None
    panels = ([(None, rows)] if company_order is None else
              rows.groupby("Company", sort=False, dropna=False))
    for _, panel in panels:
        span = shared_span if shared_span is not None else y_span(panel)
        if span <= 0:
            rows.loc[panel.index, label_column] = ""
            continue
        candidates = []
        for index, row in panel.iterrows():
            label = str(row[label_column])
            if not label:
                continue
            amount_height = abs(float(row["Amount"])) * chart_height / (span * 1.25)
            period_number = period_index.get(row["Period label"])
            metric_number = metric_index.get(row["Metric"])
            if (amount_height < max(10, font_size * 1.1)
                    or period_number is None or metric_number is None):
                rows.at[index, label_column] = ""
                continue
            band_position = (0.5 if stacked or period_colors else
                             (metric_number + 0.5) / len(metrics))
            x = (period_number + 0.45) * step + band_position * band_width
            y = float(row["Label midpoint"]) * chart_height / (span * 1.25)
            label_width = len(label) * font_size * 0.62 + 3
            label_height = font_size * 1.4
            if x - label_width / 2 < 0 or x + label_width / 2 > panel_width:
                rows.at[index, label_column] = ""
                continue
            candidates.append((amount_height, index, x, y,
                               label_width, label_height))
        kept = []
        for _, index, x, y, width, height in sorted(candidates, reverse=True):
            if any(abs(x - other_x) < (width + other_width) / 2 + 3
                   and abs(y - other_y) < (height + other_height) / 2 + 3
                   for other_x, other_y, other_width, other_height in kept):
                rows.at[index, label_column] = ""
            else:
                kept.append((x, y, width, height))
    return rows


def _grouped_period_bars(rows: pd.DataFrame, metric_order: list[str], *,
                         periods: list[str], unit_title: str, company_order: list[str] | None = None,
                         show_labels: bool = True, decimals: int = 1,
                         transparent: bool = True, stacked: bool = False,
                         percentage_labels: bool = False,
                         color_by_period: bool = False,
                         alternative_metric_labels: bool = False,
                         shared_y: bool = False) -> alt.TopLevelMixin | None:
    """Period on x, separate indicator bars; optionally facet one panel per company."""
    rows = rows.dropna(subset=["Amount"]).copy().reset_index(drop=True)
    if rows.empty:
        return None
    present = [label for label in metric_order if label in set(rows["Metric"])]
    if not present:
        return None
    if company_order is not None and {"Company", "Scope"}.issubset(rows.columns):
        source_names = rows["Company"].astype(str).copy()
        rows["Company"] = [
            _company_scope_label(name, scope)
            for name, scope in zip(source_names, rows["Scope"])
        ]
        company_order = list(dict.fromkeys(
            display_name
            for name in company_order
            for display_name in rows.loc[source_names.eq(name), "Company"]
        ))
    rows["Period label"] = rows["Period"].map(period_label)
    display_periods = [period_label(period) for period in periods]
    chart_height = 300 if company_order is None else 270
    percent_suffix = "%" if unit_title.endswith("(%)") else ""
    rows["Value label"] = rows["Amount"].map(
        lambda value: f"{value:,.{decimals}f}{percent_suffix}"
    )
    colors = [KPMG_BRIGHT_CHART_COLORS[index % len(KPMG_BRIGHT_CHART_COLORS)]
              for index in range(len(present))]
    period_scale = alt.Scale(paddingInner=0.5, paddingOuter=0.45)
    x = alt.X("Period label:N", sort=display_periods, title=None, scale=period_scale,
              axis=alt.Axis(labelAngle=0, labelLimit=90))
    x_offset = alt.XOffset("Metric:N", sort=present)
    y = alt.Y("Amount:Q", title=unit_title, stack="zero" if stacked else None,
              scale=alt.Scale(zero=True),
              axis=alt.Axis(format=",.2~f" if shared_y else "~s"))
    legend = alt.Legend(orient="bottom", direction="vertical",
                        title=None, labelLimit=1000, columns=1)
    period_colors = color_by_period and (len(present) == 1 or alternative_metric_labels)
    if not percentage_labels:
        rows["Label midpoint"] = rows["Amount"] / 2
        if stacked:
            # Vega stacks by this explicit series order. Match that order when
            # locating labels, with independent positive and negative stacks.
            rows["Stack order"] = rows["Metric"].map(
                {metric: index for index, metric in enumerate(present)}
            )
            rows["Share (%)"] = 0.0
            rows["Percent label"] = ""
            group_keys = [column for column in ("Company", "Document ID", "Period")
                          if column in rows]
            for _, group in rows.groupby(group_keys, sort=False, dropna=False):
                positive = negative = 0.0
                denominator = float(group["Amount"].abs().sum())
                for index, amount in group.sort_values("Stack order")["Amount"].items():
                    share = 100 * amount / denominator if denominator else 0.0
                    rows.at[index, "Share (%)"] = share
                    rows.at[index, "Percent label"] = _stack_percent_label(share)
                    if amount >= 0:
                        rows.at[index, "Label midpoint"] = positive + amount / 2
                        positive += amount
                    else:
                        rows.at[index, "Label midpoint"] = negative + amount / 2
                        negative += amount
    if show_labels:
        font_size = (9 if stacked else
                     8 if len(company_order or []) >= 4 or len(present) >= 5 else 10)
        rows = _hide_colliding_labels(
            rows, label_column="Percent label" if stacked else "Value label",
            metrics=present, periods=display_periods, company_order=company_order,
            stacked=stacked, period_colors=period_colors, shared_y=shared_y,
            font_size=font_size, chart_height=chart_height,
        )
    if period_colors:
        color = alt.Color(
            "Period label:N",
            scale=alt.Scale(domain=display_periods,
                            range=[YEAR_COLORS.get(period, KPMG_BRIGHT_CHART_COLORS[index % len(KPMG_BRIGHT_CHART_COLORS)])
                                   for index, period in enumerate(display_periods)]),
            legend=legend,
        )
    else:
        color = alt.Color("Metric:N", scale=alt.Scale(domain=present, range=colors), legend=legend)
    tooltip = ["Company:N", "Period:N", "Metric:N", alt.Tooltip("Amount:Q", format=",.2f"),
               "Currency:N", "Source:N"] if "Company" in rows else [
                   "Period:N", "Metric:N", alt.Tooltip("Amount:Q", format=",.2f"), "Source:N"]
    if "USD/HKD rate" in rows:
        tooltip.extend([alt.Tooltip("USD/HKD rate:Q", format=".4f"), "FX rate date:N"])
    if "Original source amount (millions)" in rows:
        tooltip.extend([
            alt.Tooltip("Original source amount (millions):Q", format=",.3f"),
            "Original source currency:N",
        ])
    if "Accounting signed amount" in rows:
        tooltip.append(alt.Tooltip("Accounting signed amount:Q", format=",.2f",
                                   title="Signed amount (chart unit)"))
    if stacked:
        share_title = ("Share of absolute components (%)" if not percentage_labels
                       else "Share (%)")
        tooltip.insert(-1, alt.Tooltip("Share (%):Q", title=share_title,
                                       format=".1f"))
    bar_encoding = dict(x=x, y=y, color=color, tooltip=tooltip)
    if "Stack order" in rows:
        bar_encoding["order"] = alt.Order("Stack order:Q", sort="ascending")
    if not stacked and not period_colors:
        bar_encoding["xOffset"] = x_offset
    bars = alt.Chart(rows).mark_bar(
        width=alt.RelativeBandSize(0.9), opacity=0.94,
        cornerRadiusTopLeft=2, cornerRadiusTopRight=2,
    ).encode(**bar_encoding)
    layers = [bars]
    if show_labels:
        label_encoding = dict(x=x, y=alt.Y("Label midpoint:Q", stack=None),
                              text="Percent label:N" if stacked else "Value label:N")
        if period_colors:
            label_encoding["color"] = alt.condition(
                alt.datum["Period label"] == "2025YE",
                alt.value("#FFFFFF"), alt.value(KPMG_INK),
            )
        elif not stacked:
            label_encoding["xOffset"] = x_offset
        text_style = dict(fontSize=font_size, fontWeight="bold",
                          baseline="middle", tooltip=False)
        if not period_colors:
            text_style["color"] = KPMG_INK
        labels = alt.Chart(rows).mark_text(**text_style).encode(
            **label_encoding,
        )
        layers.append(labels)
    base = alt.layer(*layers).properties(height=chart_height)
    if company_order is None:
        return _report_chart_theme(base, transparent=transparent)
    width, spacing = _company_panel_width(len(company_order))
    base = base.properties(width=width)
    faceted = base.facet(
        facet=alt.Facet("Company:N", sort=company_order, title=None,
                        header=alt.Header(labelPadding=14)),
        columns=len(company_order), spacing=spacing,
    ).resolve_scale(y="shared" if shared_y else "independent")
    return _report_chart_theme(faceted, transparent=transparent)


def figure_rows(frame: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy().assign(Period=pd.Series(dtype=str), Amount=pd.Series(dtype=float),
                                   Source=pd.Series(dtype=str))
    rows = frame[frame["Metric code"].isin(codes)].copy()
    if rows.empty:
        return rows.assign(Period=pd.Series(dtype=str), Amount=pd.Series(dtype=float), Source=pd.Series(dtype=str))
    rows["Period"] = rows["Period end"].astype(str)
    rows["Amount"] = pd.to_numeric(rows["Value (millions)"], errors="coerce")
    rows["Source"] = rows.apply(lambda row: f"PDF p.{int(row['PDF page'])} · {row['Source label']}", axis=1)
    return rows


def _use_reported_company_labels(rows: pd.DataFrame,
                                 labels: dict[str, str] | None) -> pd.DataFrame:
    """Use each statement's line name in the legend and source hover."""
    if not labels or rows.empty or "Company" not in rows:
        return rows
    rows = rows.copy()
    for company, label in labels.items():
        matching = rows["Company"].eq(company)
        rows.loc[matching, "Metric"] = label
        rows.loc[matching, "Source"] = rows.loc[matching, "PDF page"].map(
            lambda page: f"PDF p.{int(page)} · Statement of profit or loss: {label}"
        )
    return rows


def period_bars(frame: pd.DataFrame, codes: list[str], *, unit_title: str | None = None,
                stacked: bool = False, color_by_period: bool = False,
                show_labels: bool = True,
                reported_labels: dict[str, str] | None = None,
                display_label: str | None = None,
                alternative_metric_labels: bool = False,
                expense_mode: str | None = None) -> alt.Chart | None:
    rows = _use_reported_company_labels(figure_rows(frame, codes), reported_labels)
    if rows.empty:
        return None
    rows = _expense_display_rows(rows, expense_mode)
    if display_label is not None:
        rows["Metric"] = display_label
    order = (list(dict.fromkeys(rows["Metric"])) if reported_labels or display_label else
             [METRIC_BY_CODE[code].label for code in codes])
    return _grouped_period_bars(rows, order, periods=sorted(rows["Period"].unique()),
                                unit_title=unit_title or f"{rows['Currency'].iloc[0]} millions",
                                stacked=stacked, color_by_period=color_by_period,
                                show_labels=show_labels,
                                alternative_metric_labels=alternative_metric_labels)


def tax_profit_bars(
    frame: pd.DataFrame, *, companies: list[str] | None = None,
    periods: list[str] | None = None, display_mode: str = "Native currencies",
    unit: str = "millions", show_labels: bool = True, decimals: int = 1,
    transparent: bool = True,
) -> tuple[alt.TopLevelMixin | None, list[str]]:
    """Pair pre-tax and after-tax profit; place the tax rate above each year."""
    rows = figure_rows(frame, ["PBT", "TAX_EXPENSE", "PROFIT"])
    if companies is not None:
        rows = rows[rows["Company"].isin(companies)].copy()
    if periods is not None:
        rows = rows[rows["Period"].isin(periods)].copy()
    rows = rows.dropna(subset=["Amount"])
    if rows.empty:
        return None, []

    excluded: list[str] = []
    if companies is not None and display_mode == "HKD converted":
        rows, excluded = _convert_peer_amounts(rows)
    if rows.empty:
        return None, excluded
    if unit == "billions":
        rows["Amount"] /= 1000

    rows["Panel"] = rows.apply(
        lambda row: _company_scope_label(
            f"{row['Company']} · {row['Currency']}", row["Scope"]
        ), axis=1,
    )
    shown_periods = sorted(rows["Period"].unique()) if periods is None else periods
    rows["Period label"] = rows["Period"].map(period_label)
    period_order = [period_label(period) for period in shown_periods]

    group_keys = ["Panel", "Period"]
    amounts = rows.pivot_table(index=group_keys, columns="Metric code",
                               values="Amount", aggfunc="first")
    rates = pd.DataFrame(columns=[*group_keys, "Rate (%)", "Tax amount", "Pre-tax amount"])
    if {"PBT", "TAX_EXPENSE"}.issubset(amounts.columns):
        valid = amounts["PBT"].gt(0) & amounts["TAX_EXPENSE"].notna()
        rates = amounts.loc[valid, ["PBT", "TAX_EXPENSE"]].reset_index()
        rates["Rate (%)"] = -100 * rates["TAX_EXPENSE"] / rates["PBT"]
        rates["Rate label"] = rates["Rate (%)"].map(lambda value: f"{value:.1f}%")
        rates["Tax amount"] = rates["TAX_EXPENSE"]
        rates["Pre-tax amount"] = rates["PBT"]
        rates["Period label"] = rates["Period"].map(period_label)
        if "Original source amount (millions)" in rows:
            original = rows.pivot_table(
                index=group_keys, columns="Metric code",
                values="Original source amount (millions)", aggfunc="first",
            )
            rates["Original pre-tax amount (millions)"] = [
                original.loc[(panel, period), "PBT"]
                for panel, period in zip(rates["Panel"], rates["Period"])
            ]
            rates["Original tax amount (millions)"] = [
                original.loc[(panel, period), "TAX_EXPENSE"]
                for panel, period in zip(rates["Panel"], rates["Period"])
            ]
            rates["Original source currency"] = [
                rows.loc[rows["Panel"].eq(panel) & rows["Period"].eq(period),
                         "Original source currency"].iloc[0]
                for panel, period in zip(rates["Panel"], rates["Period"])
            ]

    bars = rows[rows["Metric code"].isin(["PBT", "PROFIT"])].copy()
    if bars.empty:
        return None, excluded
    bars["Metric"] = bars["Metric code"].map({"PBT": "Profit before tax", "PROFIT": "Profit"})
    bars["Value label"] = bars["Amount"].map(lambda value: f"{value:,.{decimals}f}")
    bars["Label midpoint"] = bars["Amount"] / 2
    bars["Row kind"] = "bar"
    rates["Row kind"] = "rate"
    for panel, panel_bars in bars.groupby("Panel", sort=False):
        panel_rates = rates["Panel"].eq(panel) if not rates.empty else pd.Series(dtype=bool)
        if rates.empty or not panel_rates.any():
            continue
        upper = max(0.0, float(panel_bars["Amount"].max()))
        lower = min(0.0, float(panel_bars["Amount"].min()))
        span = max(upper - lower, 1.0)
        rates.loc[panel_rates, "Label anchor"] = upper + 0.14 * span
        rates.loc[panel_rates, "Headroom"] = upper + 0.28 * span

    x = alt.X("Period label:N", sort=period_order, title=None,
              scale=alt.Scale(paddingInner=0.42, paddingOuter=0.3),
              axis=alt.Axis(labelAngle=0))
    unit_title = (f"{'HKD' if display_mode == 'HKD converted' else 'Original currency'} {unit}"
                  if companies is not None else f"{bars['Currency'].iloc[0]} {unit}")
    y = alt.Y("Amount:Q", title=unit_title,
              scale=alt.Scale(zero=True), axis=alt.Axis(format="~s"))
    color = alt.Color(
        "Metric:N", scale=alt.Scale(domain=["Profit before tax", "Profit"],
                                     range=[COBALT, "#B497FF"]),
        legend=alt.Legend(title=None, orient="bottom", direction="horizontal"),
    )
    combined = pd.concat([bars, rates], ignore_index=True)
    common = alt.Chart(combined)
    bar_base = common.transform_filter(alt.datum["Row kind"] == "bar").encode(
        x=x, xOffset=alt.XOffset("Metric:N", sort=["Profit before tax", "Profit"]),
    )
    bar_tooltip = ["Company:N", "Period:N", "Metric:N",
                   alt.Tooltip("Amount:Q", title=f"{unit.title()}", format=",.2f"),
                   "Currency:N", "Source:N"]
    if "Original source amount (millions)" in bars:
        bar_tooltip.extend([
            alt.Tooltip("Original source amount (millions):Q", format=",.3f"),
            "Original source currency:N",
        ])
    layers = [bar_base.mark_bar(width=alt.RelativeBandSize(0.88), opacity=0.96,
                                cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
        y=y, color=color,
        tooltip=bar_tooltip,
    )]
    if show_labels:
        layers.append(bar_base.mark_text(fontSize=9, fontWeight="bold",
                                         baseline="middle", tooltip=False).encode(
            y=alt.Y("Label midpoint:Q", title=unit_title), text="Value label:N",
            color=alt.condition(alt.datum["Metric"] == "Profit before tax",
                                alt.value("#FFFFFF"), alt.value(KPMG_INK)),
        ))
    if not rates.empty:
        rate_base = common.transform_filter(alt.datum["Row kind"] == "rate").encode(x=x)
        rate_tooltip = ["Period:N", alt.Tooltip("Pre-tax amount:Q", format=",.2f"),
                        alt.Tooltip("Tax amount:Q", format=",.2f"),
                        alt.Tooltip("Rate (%):Q", format=".1f")]
        if "Original pre-tax amount (millions)" in rates:
            rate_tooltip.extend([
                alt.Tooltip("Original pre-tax amount (millions):Q", format=",.3f"),
                alt.Tooltip("Original tax amount (millions):Q", format=",.3f"),
                "Original source currency:N",
            ])
        layers.append(rate_base.mark_text(fontSize=12, fontWeight="bold",
                                          color="#B0006D", baseline="bottom").encode(
            y=alt.Y("Label anchor:Q", title=unit_title), text="Rate label:N",
            tooltip=rate_tooltip,
        ))
        layers.append(rate_base.mark_point(opacity=0, size=1, tooltip=False).encode(
            y=alt.Y("Headroom:Q", title=unit_title),
        ))

    base = alt.layer(*layers, data=combined).properties(height=300 if companies is None else 270)
    if companies is None:
        return _report_chart_theme(base.properties(width=650), transparent=transparent), excluded
    source_names = rows["Company"].astype(str)
    panel_order = list(dict.fromkeys(
        panel for company in companies
        for panel in rows.loc[source_names.eq(company), "Panel"]
    ))
    width, spacing = _company_panel_width(len(panel_order))
    chart = base.properties(width=width).facet(
        facet=alt.Facet("Panel:N", sort=panel_order, title=None,
                        header=alt.Header(labelPadding=14)),
        columns=len(panel_order), spacing=spacing,
    ).resolve_scale(y="shared" if display_mode == "HKD converted" else "independent")
    return _report_chart_theme(chart, transparent=transparent), excluded


def _period_rate_lines(rows: pd.DataFrame, metric_order: list[str], *,
                       periods: list[str], company_order: list[str] | None = None,
                       transparent: bool = True) -> alt.TopLevelMixin | None:
    """Draw one rate series per disclosed tenor across year ends."""
    rows = rows.dropna(subset=["Amount"]).copy()
    if rows.empty:
        return None
    present = [metric for metric in metric_order if metric in set(rows["Metric"])]
    if not present:
        return None
    if company_order is not None and {"Company", "Scope"}.issubset(rows.columns):
        source_names = rows["Company"].astype(str).copy()
        rows["Company"] = [
            _company_scope_label(name, scope)
            for name, scope in zip(source_names, rows["Scope"])
        ]
        company_order = list(dict.fromkeys(
            display_name
            for name in company_order
            for display_name in rows.loc[source_names.eq(name), "Company"]
        ))
    rows["Period label"] = rows["Period"].map(period_label)
    display_periods = [period_label(period) for period in periods]
    color = alt.Color(
        "Metric:N", sort=present,
        scale=alt.Scale(
            domain=present,
            range=[KPMG_BRIGHT_CHART_COLORS[index % len(KPMG_BRIGHT_CHART_COLORS)]
                   for index in range(len(present))],
        ),
        legend=alt.Legend(orient="bottom", direction="vertical", title=None,
                          labelLimit=1000, columns=1),
    )
    tooltip = ["Period:N", "Metric:N",
               alt.Tooltip("Amount:Q", title="Rate (%)", format=".2f"), "Source:N"]
    if company_order is not None:
        tooltip.insert(0, "Company:N")
    chart = alt.Chart(rows).mark_line(point=True, strokeWidth=2.5).encode(
        x=alt.X("Period label:N", sort=display_periods, title=None,
                axis=alt.Axis(labelAngle=0, labelLimit=90)),
        y=alt.Y("Amount:Q", title="Spot rate (%)", scale=alt.Scale(zero=False)),
        color=color, tooltip=tooltip,
    ).properties(height=300 if company_order is None else 270)
    if company_order is None:
        return _report_chart_theme(chart, transparent=transparent)
    width, spacing = _company_panel_width(len(company_order))
    faceted = chart.properties(width=width).facet(
        facet=alt.Facet("Company:N", sort=company_order, title=None,
                        header=alt.Header(labelPadding=14)),
        columns=len(company_order), spacing=spacing,
    ).resolve_scale(y="shared")
    return _report_chart_theme(faceted, transparent=transparent)


def period_rate_lines(frame: pd.DataFrame, codes: list[str]) -> alt.TopLevelMixin | None:
    rows = figure_rows(frame, codes)
    if rows.empty:
        return None
    return _period_rate_lines(
        rows, [METRIC_BY_CODE[code].label for code in codes],
        periods=sorted(rows["Period"].unique()),
    )


_CSM_MATURITY_BUCKETS = (
    ("1Y", 1), ("1_5Y", 5), ("5_10Y", 10), ("GT10Y", None),
)


def csm_maturity_curve_rows(frame: pd.DataFrame, *, kind: str,
                            companies: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Derive cumulative shares from disclosed buckets and matching CSM totals."""
    if kind not in {"Insurance", "Reinsurance"}:
        raise ValueError("kind must be Insurance or Reinsurance")
    prefix = "CSM_MAT_INS_" if kind == "Insurance" else "CSM_MAT_REINS_"
    codes = [prefix + bucket for bucket, _ in _CSM_MATURITY_BUCKETS]
    total_code = ("INS_NONPAA_CSM_CLOSE" if kind == "Insurance"
                  else "REINS_NONPAA_CSM_CLOSE")
    rows = figure_rows(frame, [*codes, total_code])
    output: list[dict] = []
    complete: set[str] = set()
    if not rows.empty:
        rows = rows[rows["Company"].isin(companies)].dropna(subset=["Amount"])
        group_keys = ["Document ID", "Company", "Scope", "Period", "Currency"]
        for (_, company, scope, period, currency), group in rows.groupby(
                group_keys, sort=False, dropna=False):
            by_code = group.drop_duplicates("Metric code").set_index("Metric code")
            complete_grid = set(codes).issubset(by_code.index)
            if complete_grid:
                amounts = [float(by_code.at[code, "Amount"]) for code in codes]
                total = sum(amounts)
                # Preserve the sign convention of each filing's maturity note.
                if total == 0 or not (all(value >= 0 for value in amounts)
                                      or all(value <= 0 for value in amounts)):
                    continue
                dated_amounts = [
                    (year, amount, str(by_code.at[prefix + bucket, "Source"]))
                    for (bucket, year), amount in zip(_CSM_MATURITY_BUCKETS, amounts)
                    if year is not None
                ]
                over_ten = amounts[-1] / total
            else:
                # Some filings disclose a combined first-five-years balance only
                # through their closing CSM and later maturity buckets.
                needed = {prefix + "5_10Y", prefix + "GT10Y", total_code}
                if not needed.issubset(by_code.index):
                    continue
                later = [float(by_code.at[code, "Amount"])
                         for code in (prefix + "5_10Y", prefix + "GT10Y")]
                if not (all(value >= 0 for value in later)
                        or all(value <= 0 for value in later)):
                    continue
                sign = 1 if sum(later) > 0 else -1
                total = sign * abs(float(by_code.at[total_code, "Amount"]))
                first_five = total - sum(later)
                if total == 0 or first_five / total < -1e-9:
                    continue
                total_source = str(by_code.at[total_code, "Source"])
                later_sources = [str(by_code.at[code, "Source"])
                                 for code in (prefix + "5_10Y", prefix + "GT10Y")]
                derived_source = (
                    "Derived: closing CSM less disclosed 5–10Y and over-10Y buckets; "
                    + "; ".join([total_source, *later_sources])
                )
                dated_amounts = [
                    (5, first_five, derived_source),
                    (10, later[0], derived_source),
                ]
                over_ten = later[-1] / total
            complete.add(company)
            label = _company_scope_label(company, scope)
            base = {"Company": label, "Period": period, "Kind": kind,
                    "Currency": currency, "Over 10Y share": over_ten}
            output.append({**base, "Year": 0, "Cumulative share": 0.0,
                           "Cumulative amount": 0.0, "Source": "Start of projection"})
            cumulative = 0.0
            sources: list[str] = []
            for year, amount, source in dated_amounts:
                cumulative += amount
                sources.append(source)
                output.append({**base, "Year": year,
                               "Cumulative share": cumulative / total,
                               "Cumulative amount": cumulative,
                               "Source": source if not complete_grid else "; ".join(sources)})
    missing = [company for company in companies if company not in complete]
    return pd.DataFrame(output), missing


def csm_maturity_lines(frame: pd.DataFrame, *, kind: str,
                       companies: list[str], transparent: bool = True,
                       tracked_company: str | None = None,
                       ) -> tuple[alt.TopLevelMixin | None, list[str]]:
    """Compare cumulative recognition curves and label only outermost series."""
    rows, missing = csm_maturity_curve_rows(frame, kind=kind, companies=companies)
    if rows.empty:
        return None, missing
    order = list(dict.fromkeys(rows["Company"]))
    terminal = rows.loc[rows["Year"].eq(10), ["Company", "Cumulative share"]]
    terminal = terminal.sort_values(["Cumulative share", "Company"])
    lowest = str(terminal.iloc[0]["Company"])
    highest = str(terminal.iloc[-1]["Company"])
    rows["Outer line"] = ""
    rows.loc[rows["Company"].eq(highest) & rows["Year"].gt(0), "Outer line"] = "Highest"
    if lowest != highest:
        rows.loc[rows["Company"].eq(lowest) & rows["Year"].gt(0), "Outer line"] = "Lowest"
    rows["Share label"] = rows["Cumulative share"].map(lambda value: f"{value:.1%}")
    scale = alt.Scale(domain=order, range=[
        BLUE if company == tracked_company else
        KPMG_BRIGHT_CHART_COLORS[index % len(KPMG_BRIGHT_CHART_COLORS)]
        for index, company in enumerate(order)
    ])
    x = alt.X("Year:Q", title=None, scale=alt.Scale(domain=[0, 10]),
              axis=alt.Axis(values=[0, 1, 5, 10], labelAngle=0,
                            labelExpr="datum.value == 0 ? '0' : datum.value + 'Y'"))
    y = alt.Y("Cumulative share:Q", title="Cumulative CSM recognition (%)",
              scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format=".0%"))
    tooltip = ["Company:N", "Period:N", "Kind:N",
               alt.Tooltip("Year:Q", title="By year"),
               alt.Tooltip("Cumulative share:Q", title="Cumulative share", format=".1%"),
               alt.Tooltip("Cumulative amount:Q", title="Cumulative amount (millions)", format=",.2f"),
               "Currency:N",
               alt.Tooltip("Over 10Y share:Q", title="After 10 years", format=".1%"),
               "Source:N"]
    lines = alt.Chart(rows).mark_line(
        point=True, strokeWidth=2.5, strokeDash=[6, 4],
    ).encode(
        x=x, y=y, color=alt.Color("Company:N", scale=scale,
                                  legend=alt.Legend(orient="top", title=None,
                                                    labelLimit=1000, columns=3,
                                                    symbolType="stroke")),
        tooltip=tooltip,
    )
    highest_labels = alt.Chart(rows).transform_filter(
        alt.datum["Outer line"] == "Highest"
    ).mark_text(dy=-12, fontSize=10, fontWeight="bold").encode(
        x=x, y=y, text="Share label:N", color=alt.value("#000000"),
    )
    lowest_labels = alt.Chart(rows).transform_filter(
        alt.datum["Outer line"] == "Lowest"
    ).mark_text(dy=12, fontSize=10, fontWeight="bold").encode(
        x=x, y=y, text="Share label:N", color=alt.value("#000000"),
    )
    chart = alt.layer(lines, highest_labels, lowest_labels).properties(height=330)
    return _report_chart_theme(chart, transparent=transparent), missing


def _revenue_stack_rows(frame: pd.DataFrame, codes: list[str], *,
                        denominator_code: str | None, require_all: bool) -> pd.DataFrame:
    """Keep signed source amounts and calculate labels from a matching period."""
    rows = figure_rows(frame, codes)
    if rows.empty:
        return rows
    rows = rows.dropna(subset=["Amount"]).copy()
    denominator_lookup = {}
    if denominator_code is not None:
        totals = figure_rows(frame, [denominator_code]).dropna(subset=["Amount"])
        denominator_lookup = {
            (row["Document ID"], row["Period"]): float(row["Amount"])
            for _, row in totals.iterrows()
        }
    output = []
    for (document_id, period), group in rows.groupby(["Document ID", "Period"], sort=False):
        if require_all and set(group["Metric code"]) != set(codes):
            continue
        if group["Currency"].nunique() != 1:
            continue
        group = group.copy()
        group["Metric code"] = pd.Categorical(group["Metric code"], categories=codes, ordered=True)
        group = group.sort_values("Metric code")
        denominator = (denominator_lookup.get((document_id, period)) if denominator_code
                       else float(group["Amount"].sum()))
        if denominator is None or denominator <= 0:
            continue
        positive = negative = 0.0
        for _, row in group.iterrows():
            amount = float(row["Amount"])
            if amount >= 0:
                midpoint = positive + amount / 2
                positive += amount
            else:
                midpoint = negative + amount / 2
                negative += amount
            share = 100 * amount / denominator
            output.append({**row.to_dict(), "Share (%)": share,
                           "Percent label": _stack_percent_label(share),
                           "Label midpoint": midpoint,
                           "Stack order": codes.index(str(row["Metric code"]))})
    return pd.DataFrame(output)


def revenue_stack_bars(frame: pd.DataFrame, codes: list[str], *,
                       denominator_code: str | None = None,
                       require_all: bool = False) -> alt.TopLevelMixin | None:
    """Stack disclosed revenue components and label each signed share."""
    rows = _revenue_stack_rows(frame, codes, denominator_code=denominator_code,
                               require_all=require_all)
    if rows.empty:
        return None
    return _grouped_period_bars(
        rows, [METRIC_BY_CODE[code].label for code in codes],
        periods=sorted(rows["Period"].unique()),
        unit_title=f"{rows['Currency'].iloc[0]} millions", stacked=True,
        percentage_labels=True,
    )


RATIO_INPUTS = (
    ("Insurance service margin", ("INS_SERVICE_RESULT", "INS_REVENUE")),
    ("Effective tax charge / profit before tax", ("TAX_EXPENSE", "PBT")),
    ("Equity / total assets", ("EQUITY", "TOTAL_ASSETS")),
    ("Return on average equity", ("PROFIT", "EQUITY_OPEN", "EQUITY")),
    ("Insurance CSM year-on-year growth", ("CSM_OPEN", "CSM_CLOSE")),
    ("CSM release / opening CSM", ("CSM_RELEASE", "CSM_OPEN")),
    ("New business CSM / opening CSM", ("CSM_NEW", "CSM_OPEN")),
    ("New profitable contract CSM / PV inflows", ("NB_INS_PROFIT_CSM", "NB_INS_PROFIT_PV_IN")),
    ("Insurance CSM / matching fulfilment cash flows",
     ("INS_NONPAA_CSM_CLOSE", "INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE")),
    ("Investment yield", ("INV_YIELD",)),
    ("Equity year-on-year growth", ("EQUITY_OPEN", "EQUITY")),
)


def analytical_ratio_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute only ratios supported by matching, disclosed filing-period cells."""
    values = []
    gaps = []
    if frame.empty:
        return pd.DataFrame(values), pd.DataFrame(gaps)
    for period, group in frame.groupby("Period end", sort=True):
        numeric = group.dropna(subset=["Value (millions)"])
        lookup = dict(zip(numeric["Metric code"], pd.to_numeric(numeric["Value (millions)"], errors="coerce")))
        for label, required in RATIO_INPUTS:
            missing = [code for code in required if code not in lookup or pd.isna(lookup[code])]
            if missing:
                gaps.append({"Period": str(period), "Ratio": label, "Status": "Missing inputs",
                             "Detail": ", ".join(missing)})
                continue
            amount = None
            if label == "Insurance service margin" and lookup["INS_REVENUE"] != 0:
                amount = 100 * lookup["INS_SERVICE_RESULT"] / lookup["INS_REVENUE"]
            elif label == "Effective tax charge / profit before tax":
                if lookup["PBT"] > 0 and lookup["TAX_EXPENSE"] <= 0:
                    amount = -100 * lookup["TAX_EXPENSE"] / lookup["PBT"]
            elif label == "Equity / total assets" and lookup["TOTAL_ASSETS"] != 0:
                amount = 100 * lookup["EQUITY"] / lookup["TOTAL_ASSETS"]
            elif label == "Return on average equity":
                average = (lookup["EQUITY_OPEN"] + lookup["EQUITY"]) / 2
                if average != 0:
                    amount = 100 * lookup["PROFIT"] / average
            elif label == "Insurance CSM year-on-year growth" and lookup["CSM_OPEN"] != 0:
                amount = 100 * (abs(lookup["CSM_CLOSE"]) / abs(lookup["CSM_OPEN"]) - 1)
            elif label in {"CSM release / opening CSM", "New business CSM / opening CSM"}:
                source = numeric[numeric["Metric code"].isin(required)]
                if source["PDF page"].nunique() == 1 and lookup["CSM_OPEN"] != 0:
                    numerator = "CSM_RELEASE" if label.startswith("CSM release") else "CSM_NEW"
                    amount = 100 * abs(lookup[numerator]) / abs(lookup["CSM_OPEN"])
            elif label == "New profitable contract CSM / PV inflows" and lookup["NB_INS_PROFIT_PV_IN"] != 0:
                amount = 100 * abs(lookup["NB_INS_PROFIT_CSM"]) / abs(lookup["NB_INS_PROFIT_PV_IN"])
            elif label == "Insurance CSM / matching fulfilment cash flows":
                source = numeric[numeric["Metric code"].isin(required)]
                # Reconciliation components must come from the same physical
                # note page; unrelated CSM and cash-flow populations are not
                # combined merely because their metric codes are available.
                denominator = lookup["INS_NONPAA_PVFCF_CLOSE"] + lookup["INS_NONPAA_RA_CLOSE"]
                if source["PDF page"].nunique() == 1 and denominator != 0:
                    amount = 100 * abs(lookup["INS_NONPAA_CSM_CLOSE"]) / abs(denominator)
            elif label == "Investment yield":
                amount = lookup["INV_YIELD"]
            elif label == "Equity year-on-year growth" and lookup["EQUITY_OPEN"] != 0:
                amount = 100 * (lookup["EQUITY"] - lookup["EQUITY_OPEN"]) / abs(lookup["EQUITY_OPEN"])
            if amount is None:
                gaps.append({"Period": str(period), "Ratio": label, "Status": "Missing inputs",
                             "Detail": "Denominator, tax sign or source basis is unsuitable"})
                continue
            values.append({"Period": str(period), "Metric": label, "Amount": float(amount),
                           "Source": "Derived within one filing from " + " / ".join(required)})
    return pd.DataFrame(values), pd.DataFrame(gaps)


def analytical_ratio_bars(frame: pd.DataFrame) -> tuple[alt.TopLevelMixin | None, pd.DataFrame]:
    values, gaps = analytical_ratio_rows(frame)
    if values.empty:
        return None, gaps
    chart = _grouped_period_bars(values, [item[0] for item in RATIO_INPUTS],
                                 periods=sorted(values["Period"].unique()), unit_title="Ratio (%)")
    return chart, gaps


def financial_performance_trends(
    frame: pd.DataFrame, labels: list[str],
) -> tuple[alt.TopLevelMixin | None, pd.DataFrame, pd.DataFrame]:
    """Show each performance ratio on its own scale across filing periods."""
    values, gaps = analytical_ratio_rows(frame)
    gaps = gaps[gaps["Ratio"].isin(labels)].copy() if not gaps.empty else gaps
    if values.empty:
        return None, gaps, values
    values = values[values["Metric"].isin(labels)].copy()
    if values.empty:
        return None, gaps, values
    periods = sorted(values["Period"].unique())
    values["Period label"] = values["Period"].map(period_label)
    values["Value label"] = values["Amount"].map(lambda amount: f"{amount:,.1f}%")
    values["Zero"] = 0.0
    x = alt.X("Period label:N", sort=[period_label(period) for period in periods],
              title=None, axis=alt.Axis(labelAngle=0))
    y = alt.Y("Amount:Q", title="Ratio (%)", scale=alt.Scale(zero=True),
              axis=alt.Axis(format=".1f"))
    base = alt.Chart(values)
    zero = base.mark_rule(color="#B5C0CC", strokeDash=[3, 3]).encode(y="Zero:Q")
    line = base.mark_line(color=COBALT, strokeWidth=2).encode(x=x, y=y)
    points = base.mark_circle(color=COBALT, size=95).encode(
        x=x, y=y,
        tooltip=["Period:N", "Metric:N", alt.Tooltip("Amount:Q", title="Ratio (%)", format=".2f"), "Source:N"],
    )
    numbers = base.mark_text(color=KPMG_INK, dy=-12, fontSize=10).encode(
        x=x, y=y, text="Value label:N",
    )
    paired_page = len(labels) <= 2
    chart = alt.layer(zero, line, points, numbers).properties(
        width=650 if paired_page else 440, height=155 if paired_page else 145,
    ).facet(
        facet=alt.Facet("Metric:N", sort=labels, title=None,
                        header=alt.Header(labelFontSize=12, labelLimit=440)),
        columns=1 if paired_page else 2, spacing=20,
    ).resolve_scale(y="independent")
    return _report_chart_theme(chart), gaps, values


def financial_performance_peer_dots(
    frame: pd.DataFrame, labels: list[str], *, companies: list[str],
    periods: list[str], transparent: bool = True,
) -> tuple[alt.TopLevelMixin | None, pd.DataFrame, pd.DataFrame]:
    """Compare insurers within each ratio, connecting two selected periods."""
    output = []
    missing = []
    for company in companies:
        company_rows = frame[
            frame["Company"].eq(company) & frame["Period end"].astype(str).isin(periods)
        ]
        values, gaps = analytical_ratio_rows(company_rows)
        if not values.empty:
            values = values[values["Metric"].isin(labels)].copy()
            if not values.empty:
                values["Company"] = company
                scope_by_period = dict(zip(company_rows["Period end"].astype(str),
                                           company_rows["Scope"]))
                values["Scope"] = values["Period"].map(scope_by_period)
                values["Company label"] = [
                    _company_scope_label(company, scope)
                    for scope in values["Scope"]
                ]
                output.append(values)
        if not gaps.empty:
            gaps = gaps[gaps["Ratio"].isin(labels)].copy()
            if not gaps.empty:
                gaps["Company"] = company
                missing.append(gaps)
    gap_frame = pd.concat(missing, ignore_index=True) if missing else pd.DataFrame()
    if not output:
        return None, gap_frame, pd.DataFrame()
    ratio_rows = pd.concat(output, ignore_index=True)
    ratio_rows["Period label"] = ratio_rows["Period"].map(period_label)
    shown_periods = [period for period in periods if period in set(ratio_rows["Period"])]
    period_labels = [period_label(period) for period in shown_periods]
    company_order = list(dict.fromkeys(
        label for company in companies
        for label in ratio_rows.loc[ratio_rows["Company"].eq(company), "Company label"]
    ))
    x = alt.X("Amount:Q", title="Ratio (%)", scale=alt.Scale(zero=True),
              axis=alt.Axis(format=".1f"))
    y = alt.Y("Company label:N", sort=company_order, title=None,
              axis=alt.Axis(labelLimit=300))
    base = alt.Chart(ratio_rows)
    layers = []
    if len(shown_periods) == 2:
        links = base.transform_aggregate(
            first="min(Amount)", last="max(Amount)",
            groupby=["Metric", "Company label"],
        ).mark_rule(color="#AAB8C7", strokeWidth=2).encode(
            x=alt.X("first:Q", title="Ratio (%)", scale=alt.Scale(zero=True)),
            x2="last:Q", y=y,
        )
        layers.append(links)
    dots = base.mark_circle(size=115, opacity=0.95).encode(
        x=x, y=y,
        color=alt.Color(
            "Period label:N",
            scale=alt.Scale(
                domain=period_labels,
                range=[YEAR_COLORS.get(label, KPMG_BRIGHT_CHART_COLORS[index % len(KPMG_BRIGHT_CHART_COLORS)])
                       for index, label in enumerate(period_labels)],
            ),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
        tooltip=["Company:N", "Scope:N", "Period:N", "Metric:N",
                 alt.Tooltip("Amount:Q", title="Ratio (%)", format=".2f"), "Source:N"],
    )
    layers.append(dots)
    chart = alt.layer(*layers).properties(
        width=480 if len(labels) <= 2 else 670,
        height=max(125, len(company_order) * 35),
    ).facet(
        facet=alt.Facet("Metric:N", sort=labels, title=None,
                        header=alt.Header(labelFontSize=12, labelLimit=670)),
        columns=1, spacing=18,
    ).resolve_scale(x="independent")
    return _report_chart_theme(chart, transparent=transparent), gap_frame, ratio_rows


def ratio_module_period_bars(frame: pd.DataFrame, labels: list[str], *,
                             color_by_period: bool = False,
                             show_labels: bool = True) -> tuple[alt.TopLevelMixin | None, pd.DataFrame]:
    values, gaps = analytical_ratio_rows(frame)
    selected_gaps = gaps[gaps["Ratio"].isin(labels)].copy() if not gaps.empty else gaps
    if values.empty:
        return None, selected_gaps
    values = values[values["Metric"].isin(labels)].copy()
    if values.empty:
        return None, selected_gaps
    chart = _grouped_period_bars(values, labels, periods=sorted(values["Period"].unique()),
                                 unit_title="Ratio (%)", color_by_period=color_by_period,
                                 show_labels=show_labels)
    return chart, selected_gaps


def peer_ratio_module_panels(frame: pd.DataFrame, labels: list[str], *, companies: list[str],
                             periods: list[str], show_labels: bool = True, decimals: int = 1,
                             transparent: bool = True,
                             color_by_period: bool = False) -> tuple[alt.TopLevelMixin | None, pd.DataFrame]:
    output = []
    missing = []
    for company in companies:
        company_rows = frame[frame["Company"].eq(company) & frame["Period end"].isin(periods)]
        values, gaps = analytical_ratio_rows(company_rows)
        if not values.empty:
            values = values[values["Metric"].isin(labels)].copy()
            if not values.empty:
                values["Company"] = company
                scope_by_period = dict(zip(company_rows["Period end"].astype(str),
                                           company_rows["Scope"]))
                values["Scope"] = values["Period"].map(scope_by_period)
                values["Currency"] = "%"
                output.append(values)
        if not gaps.empty:
            gaps = gaps[gaps["Ratio"].isin(labels)].copy()
            if not gaps.empty:
                gaps["Company"] = company
                missing.append(gaps)
    gap_frame = pd.concat(missing, ignore_index=True) if missing else pd.DataFrame()
    if not output:
        return None, gap_frame
    ratio_rows = pd.concat(output, ignore_index=True)
    order = [company for company in companies if company in set(ratio_rows["Company"])]
    return _grouped_period_bars(
        ratio_rows, labels, periods=periods, unit_title="Ratio (%)",
        company_order=order, show_labels=show_labels, decimals=decimals,
        transparent=transparent, color_by_period=color_by_period,
    ), gap_frame


def peer_rate_panels(frame: pd.DataFrame, codes: list[str], *, companies: list[str],
                     periods: list[str], show_labels: bool = True, decimals: int = 1,
                     transparent: bool = True,
                     color_by_period: bool = False) -> alt.TopLevelMixin | None:
    """Percent disclosures are never currency converted or scaled as amounts."""
    rows = figure_rows(frame, codes)
    if rows.empty:
        return None
    rows = rows[rows["Company"].isin(companies) & rows["Period"].isin(periods)].copy()
    if rows.empty:
        return None
    order = [company for company in companies if company in set(rows["Company"])]
    return _grouped_period_bars(
        rows, [METRIC_BY_CODE[code].label for code in codes], periods=periods,
        unit_title="Percentage points (%)", company_order=order,
        show_labels=show_labels, decimals=decimals, transparent=transparent,
        color_by_period=color_by_period,
    )


def peer_rate_line_panels(frame: pd.DataFrame, codes: list[str], *, companies: list[str],
                          periods: list[str], transparent: bool = True) -> alt.TopLevelMixin | None:
    rows = figure_rows(frame, codes)
    if rows.empty:
        return None
    rows = rows[rows["Company"].isin(companies) & rows["Period"].isin(periods)].copy()
    if rows.empty:
        return None
    order = [company for company in companies if company in set(rows["Company"])]
    return _period_rate_lines(
        rows, [METRIC_BY_CODE[code].label for code in codes],
        periods=periods, company_order=order, transparent=transparent,
    )


def _convert_peer_amounts(rows: pd.DataFrame, *, midpoint: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """Apply each observation's own year-end rate to USD amounts."""
    rows = rows.copy()
    rows["Original source amount (millions)"] = rows["Amount"]
    rows["Original source currency"] = rows["Currency"]
    rows["USD/HKD rate"] = pd.to_numeric(rows.get("USD/HKD rate"), errors="coerce") if "USD/HKD rate" in rows else float("nan")
    rows["FX rate date"] = rows.get("FX rate date", "")
    excluded: list[str] = []
    for year in sorted({int(period[:4]) for period in rows.loc[rows["Currency"].eq("USD"), "Period"]}):
        mask = rows["Currency"].eq("USD") & rows["Period"].str.startswith(str(year))
        info = year_end_usd_hkd(year)
        if info is None:
            excluded.extend(rows.loc[mask, "Company"].tolist())
            rows = rows.loc[~mask].copy()
            continue
        rate, day, _ = info
        rows.loc[mask, "Amount"] = rows.loc[mask, "Amount"] * rate
        if midpoint:
            rows.loc[mask, "Label midpoint"] = rows.loc[mask, "Label midpoint"] * rate
        rows.loc[mask, "Currency"] = "HKD"
        rows.loc[mask, "USD/HKD rate"] = rate
        rows.loc[mask, "FX rate date"] = day
    rows = rows.loc[rows["Currency"].eq("HKD")].copy()
    return rows, list(dict.fromkeys(excluded))


def peer_group_panels(frame: pd.DataFrame, codes: list[str], *, companies: list[str],
                      periods: list[str], display_mode: str = "Native currencies",
                      unit: str = "millions",
                      show_labels: bool = True, decimals: int = 1,
                      transparent: bool = True, stacked: bool = False,
                      color_by_period: bool = False,
                      reported_labels: dict[str, str] | None = None,
                      display_label: str | None = None,
                      alternative_metric_labels: bool = False,
                      expense_mode: str | None = None) -> tuple[alt.TopLevelMixin | None, list[str]]:
    """One period-by-indicator chart per insurer; keep currencies explicit."""
    rows = _use_reported_company_labels(figure_rows(frame, codes), reported_labels)
    if rows.empty:
        return None, []
    rows = rows[rows["Company"].isin(companies) & rows["Period"].isin(periods)].copy()
    if rows.empty:
        return None, []
    if display_label is not None:
        rows["Metric"] = display_label
    excluded: list[str] = []
    if display_mode == "HKD converted":
        rows, excluded = _convert_peer_amounts(rows)
    if rows.empty:
        return None, excluded
    if unit == "billions":
        rows["Amount"] /= 1000
    rows = _expense_display_rows(rows, expense_mode)
    rows["Company"] = rows["Company"] + " · " + rows["Currency"]
    panel_order = [company + " · " + (
        "HKD" if display_mode == "HKD converted" else str(frame.loc[frame["Company"].eq(company), "Currency"].iloc[0]))
        for company in companies if company in set(rows["Company"].str.split(" · ").str[0])]
    chart = _grouped_period_bars(
        rows, (list(dict.fromkeys(rows["Metric"])) if reported_labels or display_label else
               [METRIC_BY_CODE[code].label for code in codes]), periods=periods,
        unit_title=f"{'HKD' if display_mode == 'HKD converted' else 'Original currency'} {unit}",
        company_order=panel_order, show_labels=show_labels, decimals=decimals,
        transparent=transparent, stacked=stacked, color_by_period=color_by_period,
        alternative_metric_labels=alternative_metric_labels,
        shared_y=display_mode == "HKD converted",
    )
    return chart, excluded


def company_year_comparison_bars(
    frame: pd.DataFrame, codes: list[str], *, companies: list[str],
    periods: list[str], display_mode: str = "Native currencies",
    unit: str = "millions", show_labels: bool = True,
    decimals: int = 1, transparent: bool = True,
    label_font_size: int = 11, bar_width: int = 36,
    axis_label_padding: int = 10,
    reported_labels: dict[str, str] | None = None,
    ratio_label: str | None = None,
    expense_mode: str | None = None,
) -> tuple[alt.TopLevelMixin | None, list[str], str]:
    """Pair the latest two year ends for each insurer with a signed YoY callout."""
    selected_periods = sorted({str(period) for period in periods})[-2:]
    excluded: list[str] = []
    if ratio_label is None:
        rows = _use_reported_company_labels(figure_rows(frame, codes), reported_labels)
        rows = rows.loc[
            rows["Company"].isin(companies) & rows["Period"].isin(selected_periods)
        ].copy()
        if rows.empty:
            return None, [], ""
        # Two names can identify the same investment subtotal. Plot it once.
        priority = {code: index for index, code in enumerate(codes)}
        rows["Metric priority"] = rows["Metric code"].map(priority)
        rows = rows.sort_values("Metric priority", kind="stable").drop_duplicates(
            ["Company", "Scope", "Period"], keep="first"
        )
        if display_mode == "HKD converted":
            rows, excluded = _convert_peer_amounts(rows)
    else:
        output = []
        for company in companies:
            company_rows = frame.loc[
                frame["Company"].eq(company)
                & frame["Period end"].astype(str).isin(selected_periods)
            ]
            values, gaps = analytical_ratio_rows(company_rows)
            if not gaps.empty:
                unavailable = gaps.loc[gaps["Ratio"].eq(ratio_label), "Period"]
                excluded.extend(f"{company} {period_label(period)}" for period in unavailable)
            if values.empty:
                continue
            values = values.loc[values["Metric"].eq(ratio_label)].copy()
            if values.empty:
                continue
            scopes = company_rows.drop_duplicates("Period end").set_index("Period end")["Scope"]
            values["Company"] = company
            values["Scope"] = values["Period"].map(scopes)
            values["Currency"] = "%"
            output.append(values)
        rows = pd.concat(output, ignore_index=True) if output else pd.DataFrame()
    if rows.empty:
        return None, excluded, ""
    if unit == "billions" and ratio_label is None:
        rows["Amount"] /= 1000
    rows = _expense_display_rows(rows, expense_mode)
    rows["Period label"] = rows["Period"].map(period_label)
    rows["Company label"] = [
        _company_scope_label(name, scope)
        for name, scope in zip(rows["Company"], rows["Scope"])
    ]
    company_order = list(dict.fromkeys(
        label for company in companies
        for label in rows.loc[rows["Company"].eq(company), "Company label"]
    ))
    display_periods = [period_label(period) for period in selected_periods]
    colors = [YEAR_COLORS.get(period, KPMG_BRIGHT_CHART_COLORS[index % len(KPMG_BRIGHT_CHART_COLORS)])
              for index, period in enumerate(display_periods)]
    suffix = "%" if ratio_label is not None else ""
    rows["Value label"] = rows["Amount"].map(
        lambda value: f"{value:,.{decimals}f}{suffix}"
    )

    span = max(float(rows["Amount"].max()), 0.0) - min(float(rows["Amount"].min()), 0.0)
    padding = max(span * 0.08, 0.01)
    changes = []
    if len(selected_periods) == 2:
        for (label, currency), group in rows.groupby(
                ["Company label", "Currency"], sort=False, dropna=False):
            pair = group.set_index("Period label")
            if not set(display_periods).issubset(pair.index):
                continue
            previous = float(pair.loc[display_periods[0], "Amount"])
            current = float(pair.loc[display_periods[1], "Amount"])
            if abs(previous) < 1e-12:
                continue
            change = 100 * (current - previous) / abs(previous)
            arrow = "↗" if change > 0 else "↘" if change < 0 else "→"
            changes.append({
                "Company label": label, "Currency": currency,
                "Comparison Y": max(0.0, previous, current) + padding,
                "Change pct": change,
                "Change label": f"{arrow} {abs(change):.1f}%",
            })
    change_rows = pd.DataFrame(changes)
    summary = ""
    if changes:
        positive = sum(item["Change pct"] > 0 for item in changes)
        negative = sum(item["Change pct"] < 0 for item in changes)
        summary = (f"{display_periods[-1]} vs {display_periods[0]}: "
                   f"{positive} increased, {negative} decreased. "
                   "Change uses (current − prior) / |prior|; zero or missing prior values have no percentage.")

    def panel(panel_rows: pd.DataFrame, panel_changes: pd.DataFrame,
              panel_currency: str, width: int | str) -> alt.LayerChart:
        panel_order = [label for label in company_order
                       if label in set(panel_rows["Company label"])]
        # The width control changes the whole pair; offset bands fill it edge
        # to edge so the two years for one company always touch.
        group_padding = max(0.35, min(0.85, 0.96 - bar_width * 0.0086))
        x = alt.X("Company label:N", sort=panel_order, title=None,
                  scale=alt.Scale(paddingInner=group_padding, paddingOuter=0.15),
                  axis=alt.Axis(labelAngle=0, labelLimit=300,
                                labelOverlap=False, labelPadding=axis_label_padding))
        x_offset = alt.XOffset(
            "Period label:N", sort=display_periods,
            scale=alt.Scale(paddingInner=0, paddingOuter=0),
        )
        y_title = "Ratio (%)" if ratio_label is not None else f"{panel_currency} {unit}"
        y = alt.Y("Amount:Q", title=y_title, scale=alt.Scale(zero=True),
                  axis=alt.Axis(format=",.2~f"))
        color = alt.Color(
            "Period label:N", scale=alt.Scale(domain=display_periods, range=colors),
            legend=alt.Legend(orient="top", direction="horizontal", title=None,
                              labelLimit=1000, columns=len(display_periods)),
        )
        tooltip = ["Company label:N", "Period label:N", "Metric:N",
                   alt.Tooltip("Amount:Q", format=",.3f", title=y_title),
                   "Currency:N", "Source:N"]
        if "Accounting signed amount" in panel_rows:
            tooltip.append(alt.Tooltip("Accounting signed amount:Q", format=",.3f",
                                       title="Signed amount (chart unit)"))
        if "USD/HKD rate" in panel_rows:
            tooltip.extend([alt.Tooltip("USD/HKD rate:Q", format=".4f"), "FX rate date:N"])
        if "Original source amount (millions)" in panel_rows:
            tooltip.extend([
                alt.Tooltip("Original source amount (millions):Q", format=",.3f"),
                "Original source currency:N",
            ])
        bars = alt.Chart(panel_rows).mark_bar(
            width=alt.RelativeBandSize(1), opacity=0.96,
        ).encode(
            x=x, xOffset=x_offset, y=y, color=color, tooltip=tooltip,
        )
        layers = [bars]
        if show_labels:
            for positive, offset in ((True, -7), (False, 10)):
                labels = panel_rows.loc[
                    panel_rows["Amount"].ge(0) if positive else panel_rows["Amount"].lt(0)
                ]
                if not labels.empty:
                    layers.append(alt.Chart(labels).mark_text(
                        dy=offset, fontSize=label_font_size,
                        fontWeight="bold", color=KPMG_INK,
                    ).encode(x=x, xOffset=x_offset, y=alt.Y("Amount:Q", title=None),
                             text="Value label:N"))
            if not panel_changes.empty:
                layers.append(alt.Chart(panel_changes).mark_text(
                    fontSize=label_font_size + 1,
                    fontWeight="bold", baseline="bottom", dy=-3,
                ).encode(
                    x=x, y=alt.Y("Comparison Y:Q", title=None), text="Change label:N",
                    color=alt.condition(alt.datum["Change pct"] >= 0,
                                        alt.value(PINK), alt.value(GREEN)),
                    tooltip=["Company label:N", alt.Tooltip("Change pct:Q", format="+.1f")],
                ))
        return alt.layer(*layers).properties(height=420, width=width)

    currencies = list(dict.fromkeys(rows["Currency"].astype(str)))
    if display_mode == "Native currencies" and len(currencies) > 1:
        panels = []
        for currency in currencies:
            panel_rows = rows.loc[rows["Currency"].eq(currency)]
            panel_changes = (change_rows.loc[change_rows["Currency"].eq(currency)]
                             if not change_rows.empty else change_rows)
            panels.append(panel(panel_rows, panel_changes, currency, 510).properties(title=currency))
        base = alt.hconcat(*panels, spacing=24).resolve_scale(y="independent")
    else:
        base = panel(rows, change_rows, currencies[0], "container")
    return _report_chart_theme(base, transparent=transparent), excluded, summary


def peer_revenue_stack_panels(frame: pd.DataFrame, codes: list[str], *,
                              companies: list[str], periods: list[str],
                              denominator_code: str | None = None,
                              require_all: bool = False,
                              display_mode: str = "Native currencies",
                              unit: str = "millions", transparent: bool = True,
                              ) -> tuple[alt.TopLevelMixin | None, list[str]]:
    """Show signed component amounts and percentages on matching insurer panels."""
    rows = _revenue_stack_rows(frame, codes, denominator_code=denominator_code,
                               require_all=require_all)
    if rows.empty:
        return None, []
    rows = rows[rows["Company"].isin(companies) & rows["Period"].isin(periods)].copy()
    if rows.empty:
        return None, []
    excluded: list[str] = []
    if display_mode == "HKD converted":
        rows, excluded = _convert_peer_amounts(rows, midpoint=True)
    if rows.empty:
        return None, excluded
    if unit == "billions":
        rows[["Amount", "Label midpoint"]] /= 1000
    rows["Company"] = rows["Company"] + " · " + rows["Currency"]
    panel_order = [company + " · " + (
        "HKD" if display_mode == "HKD converted" else
        str(frame.loc[frame["Company"].eq(company), "Currency"].iloc[0]))
        for company in companies if company in set(rows["Company"].str.split(" · ").str[0])]
    chart = _grouped_period_bars(
        rows, [METRIC_BY_CODE[code].label for code in codes], periods=periods,
        unit_title=f"{'HKD' if display_mode == 'HKD converted' else 'Original currency'} {unit}",
        company_order=panel_order, show_labels=True, transparent=transparent,
        stacked=True, percentage_labels=True,
        shared_y=display_mode == "HKD converted",
    )
    return chart, excluded


def peer_ratio_panels(frame: pd.DataFrame, *, companies: list[str], periods: list[str],
                      show_labels: bool = True, decimals: int = 1,
                      transparent: bool = True) -> alt.TopLevelMixin | None:
    """Three within-filing ratios across periods, with one panel per insurer."""
    source_codes = ["INS_REVENUE", "INS_SERVICE_RESULT", "INS_LIABS", "TOTAL_ASSETS", "REINS_ASSETS"]
    source = figure_rows(frame, source_codes)
    if source.empty:
        return None
    source = source[source["Company"].isin(companies) & source["Period"].isin(periods)]
    if source.empty:
        return None
    index = ["Document ID", "Company", "Scope", "Period", "Currency"]
    pivot = source.pivot_table(index=index, columns="Metric code", values="Amount", aggfunc="first").reset_index()
    definitions = (
        ("Insurance service margin", "INS_SERVICE_RESULT", "INS_REVENUE"),
        ("Insurance liabilities / assets", "INS_LIABS", "TOTAL_ASSETS"),
        ("Reinsurance assets / insurance liabilities", "REINS_ASSETS", "INS_LIABS"),
    )
    rows = []
    for label, numerator, denominator in definitions:
        if numerator not in pivot or denominator not in pivot:
            continue
        valid = pivot[pivot[numerator].notna() & pivot[denominator].notna() & pivot[denominator].ne(0)]
        for _, source_row in valid.iterrows():
            rows.append({"Company": source_row["Company"], "Period": source_row["Period"],
                         "Scope": source_row["Scope"],
                         "Metric": label, "Amount": 100 * source_row[numerator] / source_row[denominator],
                         "Currency": source_row["Currency"],
                         "Source": f"Derived from {numerator} / {denominator}"})
    if not rows:
        return None
    ratio_rows = pd.DataFrame(rows)
    order = [company for company in companies if company in set(ratio_rows["Company"])]
    return _grouped_period_bars(
        ratio_rows, [item[0] for item in definitions], periods=periods,
        unit_title="Ratio (%)", company_order=order,
        show_labels=show_labels, decimals=decimals, transparent=transparent,
    )


def component_bars(frame: pd.DataFrame, period_end: str, codes: list[str]) -> alt.Chart | None:
    """Show disclosed signed components without inventing a residual category."""
    rows = frame[frame["Period end"].eq(period_end) & frame["Metric code"].isin(codes)].copy()
    if rows.empty:
        return None
    rows["Direction"] = rows["Value (millions)"].apply(lambda value: "Positive" if value >= 0 else "Negative")
    order = [METRIC_BY_CODE[code].label for code in codes]
    rows["Source"] = rows.apply(lambda row: f"PDF p.{int(row['PDF page'])} · {row['Source label']}", axis=1)
    return (
        alt.Chart(rows).mark_bar(cornerRadiusEnd=3)
        .encode(y=alt.Y("Metric:N", sort=order, title=None),
                x=alt.X("Value (millions):Q", title=f"{rows['Currency'].iloc[0]} millions"),
                color=alt.Color("Direction:N", scale=alt.Scale(domain=["Positive", "Negative"], range=[BLUE, PINK]), legend=None),
                tooltip=["Metric:N", alt.Tooltip("Value (millions):Q", format=",.2f"), "Source:N"])
        .properties(height=max(300, 50 * rows["Metric code"].nunique()))
    )


def note_movement_bridge(frame: pd.DataFrame, period_end: str, codes: tuple[str, str, str, str]) -> alt.Chart | None:
    rows = frame[frame["Period end"].eq(period_end) & frame["Metric code"].isin(codes)].copy()
    values = dict(zip(rows["Metric code"], rows["Value (millions)"]))
    if not all(code in values for code in codes):
        return None
    opening, pl_oci, cash, closing = (float(values[code]) for code in codes)
    bars = []
    current = 0.0
    labels = ("Opening", "Profit or loss and OCI", "Cash flows", "Closing")
    for order, (code, amount) in enumerate(zip(codes, (opening, pl_oci, cash, closing))):
        is_total = order in (0, 3)
        start = 0.0 if is_total else current
        end = amount if is_total else current + amount
        bars.append({"Order": order, "Component": labels[order],
                     "Start": min(start, end), "End": max(start, end), "Amount": amount,
                     "Direction": "Total" if is_total else ("Positive" if amount >= 0 else "Negative")})
        if order < 3:
            current = end
    data = pd.DataFrame(bars)
    return (
        alt.Chart(data).mark_bar(size=55, cornerRadius=3)
        .encode(x=alt.X("Component:N", sort=list(data["Component"]), title=None, axis=alt.Axis(labelAngle=-25)),
                y=alt.Y("Start:Q", title=f"{rows['Currency'].iloc[0]} millions"), y2="End:Q",
                color=alt.Color("Direction:N", scale=alt.Scale(domain=["Positive", "Negative", "Total"], range=[CYAN, PINK, BLUE]), legend=None),
                tooltip=["Component:N", alt.Tooltip("Amount:Q", format=",.2f")])
        .properties(height=350)
    )


def insurance_bridge(frame: pd.DataFrame, year: str = "2025") -> alt.Chart | None:
    rows = figure_rows(frame, ["INS_REVENUE", "INS_EXPENSE", "REINS_RESULT", "INS_SERVICE_RESULT"])
    rows = rows[rows["Period"].str.startswith(year)]
    values = dict(zip(rows["Metric code"], rows["Amount"]))
    if not all(code in values for code in ("INS_REVENUE", "INS_EXPENSE", "REINS_RESULT", "INS_SERVICE_RESULT")):
        return None
    cumulative = 0.0
    bars = []
    for order, (code, label) in enumerate((
        ("INS_REVENUE", "Revenue"), ("INS_EXPENSE", "Service expenses"),
        ("REINS_RESULT", "Reinsurance"),
    )):
        amount = float(values[code])
        end = cumulative + amount
        bars.append({"Order": order, "Component": label, "Start": min(cumulative, end),
                     "End": max(cumulative, end), "Amount": amount,
                     "Direction": "Positive" if amount >= 0 else "Negative"})
        cumulative = end
    bars.append({"Order": 3, "Component": "Service result", "Start": 0,
                 "End": float(values["INS_SERVICE_RESULT"]), "Amount": float(values["INS_SERVICE_RESULT"]),
                 "Direction": "Total"})
    data = pd.DataFrame(bars)
    return (
        alt.Chart(data)
        .mark_bar(size=55, cornerRadius=3)
        .encode(
            x=alt.X("Component:N", sort=list(data["Component"]), title=None),
            y=alt.Y("Start:Q", title=f"{rows['Currency'].iloc[0]} millions"),
            y2="End:Q",
            color=alt.Color("Direction:N", scale=alt.Scale(domain=["Positive", "Negative", "Total"], range=[CYAN, PINK, BLUE]), legend=None),
            tooltip=["Component:N", alt.Tooltip("Amount:Q", format=",.2f")],
        )
        .properties(height=350)
    )


def peer_margin(frame: pd.DataFrame, period_end: str) -> alt.Chart | None:
    rows = frame[frame["Period end"].eq(period_end) & frame["Metric code"].isin(["INS_REVENUE", "INS_SERVICE_RESULT"])]
    if rows.empty:
        return None
    pivot = rows.pivot_table(index=["Document ID", "Company", "Scope", "Currency"], columns="Metric code", values="Value (millions)", aggfunc="first").reset_index()
    if not {"INS_REVENUE", "INS_SERVICE_RESULT"}.issubset(pivot.columns):
        return None
    pivot = pivot[pivot["INS_REVENUE"].notna() & pivot["INS_SERVICE_RESULT"].notna() & pivot["INS_REVENUE"].ne(0)].copy()
    if pivot.empty:
        return None
    pivot["Insurance service margin (%)"] = 100 * pivot["INS_SERVICE_RESULT"] / pivot["INS_REVENUE"]
    pivot = pivot.sort_values("Insurance service margin (%)", ascending=False)
    return (
        alt.Chart(pivot)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("Insurance service margin (%):Q", title="Insurance service result / insurance revenue (%)"),
            y=alt.Y("Company:N", sort=list(pivot["Company"]), title=None),
            color=alt.Color("Company:N", scale=alt.Scale(range=PALETTE), legend=None),
            tooltip=["Company:N", "Scope:N", "Currency:N", alt.Tooltip("Insurance service margin (%):Q", format=".1f")],
        )
        .properties(height=max(220, 65 * len(pivot)))
    )


def peer_ratio(frame: pd.DataFrame, period_end: str, numerator: str, denominator: str,
               title: str) -> alt.Chart | None:
    """Compare a within-filing ratio; neither currency conversion nor cross-scope joins occur."""
    rows = frame[frame["Period end"].eq(period_end) & frame["Metric code"].isin((numerator, denominator))]
    if rows.empty:
        return None
    pivot = rows.pivot_table(index=["Document ID", "Company", "Scope", "Currency"],
                             columns="Metric code", values="Value (millions)", aggfunc="first").reset_index()
    if not {numerator, denominator}.issubset(pivot.columns):
        return None
    pivot = pivot[pivot[numerator].notna() & pivot[denominator].notna() & pivot[denominator].ne(0)].copy()
    if pivot.empty:
        return None
    pivot["Ratio (%)"] = 100 * pivot[numerator] / pivot[denominator]
    pivot = pivot.sort_values("Ratio (%)", ascending=False)
    return (
        alt.Chart(pivot).mark_bar(cornerRadiusEnd=4)
        .encode(x=alt.X("Ratio (%):Q", title=title),
                y=alt.Y("Company:N", sort=list(pivot["Company"]), title=None),
                color=alt.Color("Company:N", scale=alt.Scale(range=PALETTE), legend=None),
                tooltip=["Company:N", "Scope:N", "Currency:N", alt.Tooltip("Ratio (%):Q", format=".1f")])
        .properties(height=max(220, 65 * len(pivot)))
    )


def peer_amounts(frame: pd.DataFrame, period_end: str, code: str) -> tuple[alt.Chart | None, list[str]]:
    rows = frame[frame["Period end"].eq(period_end) & frame["Metric code"].eq(code)].copy()
    if rows.empty:
        return None, []
    rows["Original source amount (millions)"] = rows["Value (millions)"]
    rows["Original source currency"] = rows["Currency"]
    rate_info = year_end_usd_hkd(int(period_end[:4]))
    usd = rows["Currency"].eq("USD")
    excluded = rows.loc[usd, "Company"].tolist() if rate_info is None else []
    if rate_info is None:
        rows = rows.loc[~usd].copy()
    else:
        rows.loc[usd, "Value (millions)"] = rows.loc[usd, "Value (millions)"] * rate_info[0]
        rows.loc[usd, "Currency"] = "HKD"
    rows = rows.loc[rows["Currency"].eq("HKD")].copy()
    if rows.empty:
        return None, excluded
    rows = rows.sort_values("Value (millions)", ascending=False)
    chart = (
        alt.Chart(rows)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("Value (millions):Q", title="HKD millions"),
            y=alt.Y("Company:N", sort=list(rows["Company"]), title=None),
            color=alt.Color("Company:N", scale=alt.Scale(range=PALETTE), legend=None),
            tooltip=["Company:N", "Scope:N", "Currency:N",
                     alt.Tooltip("Value (millions):Q", format=",.1f"),
                     alt.Tooltip("Original source amount (millions):Q", format=",.3f"),
                     "Original source currency:N"],
        )
        .properties(height=max(220, 65 * len(rows)))
    )
    return chart, excluded
