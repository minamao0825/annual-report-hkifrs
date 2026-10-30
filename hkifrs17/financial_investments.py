"""Reconciled year-end financial investments by HKFRS 9 measurement category."""

from __future__ import annotations

import math

import altair as alt
import pandas as pd

from .charts import KPMG_INK, _company_panel_width, _report_chart_theme
from .fx import year_end_usd_hkd


COMPONENTS = {
    "FIN_ASSET_AC": ("AC", "Financial investments at amortised cost"),
    "FIN_ASSET_AC_DEBT": ("AC", "Debt securities"),
    "FIN_ASSET_AC_LOANS": ("AC", "Loans and receivables"),
    "FIN_ASSET_FVOCI_DEBT": ("FVOCI", "Debt securities"),
    "FIN_ASSET_FVOCI_EQUITY": ("FVOCI", "Equity securities"),
    "FIN_ASSET_FVTPL_DEBT": ("FVTPL", "Debt securities"),
    "FIN_ASSET_FVTPL_EQUITY": ("FVTPL", "Equity securities"),
    "FIN_ASSET_FVTPL_FUNDS": ("FVTPL", "Investment funds / unit trusts"),
    "FIN_ASSET_FVTPL_INTEREST": ("FVTPL", "Fixed and variable interest investments"),
    "FIN_ASSET_FVTPL_TRUST_EQUITY": ("FVTPL", "Unit trusts and equities"),
    "FIN_ASSET_FVTPL_PARTNERSHIPS": ("FVTPL", "Limited partnerships"),
    "FIN_ASSET_FVTPL_MORTGAGES": ("FVTPL", "Mortgage loan investments"),
    "FIN_ASSET_FVTPL_LOANS": ("FVTPL", "Loans and receivables"),
    "FIN_ASSET_FVTPL_UNLISTED_EQ_OTHER": ("FVTPL", "Unlisted equity and other securities"),
    "FIN_ASSET_FVTPL_DERIVATIVES": ("FVTPL", "Derivative financial instruments"),
}
CATEGORY_COLORS = {"AC": "#1E49E2", "FVOCI": "#00B8F5", "FVTPL": "#B497FF"}
_COLUMNS = [
    "Document ID", "Company", "Scope", "Period", "Currency", "Metric code",
    "Category", "Asset class", "Amount", "Derivation", "Stack order",
    "Reported total",
]


def financial_investment_rows(records: pd.DataFrame, companies: list[str],
                              periods: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Only return groups whose disclosed components sum to the reported total."""
    if records.empty:
        return pd.DataFrame(columns=_COLUMNS), []
    selected = records.loc[
        records["Company"].isin(companies) & records["Period end"].isin(periods)
        & records["Review status"].eq("Verified")
        & records["Value status"].isin(("Reported", "Derived from disclosed items"))
    ]
    output: list[dict] = []
    issues: list[str] = []
    for identity, group in selected.groupby(
        ["Document ID", "Company", "Scope", "Period end", "Currency"],
        sort=False, dropna=False,
    ):
        document, company, scope, period, currency = map(str, identity)
        parts = group.loc[group["Metric code"].isin(COMPONENTS)].copy()
        if parts.empty:
            continue
        # The aggregate AC metric is a fallback for filings without class detail.
        if parts["Metric code"].isin(("FIN_ASSET_AC_DEBT", "FIN_ASSET_AC_LOANS")).any():
            parts = parts.loc[~parts["Metric code"].eq("FIN_ASSET_AC")]
        totals = group.loc[group["Metric code"].eq("FIN_ASSET_TOTAL"), "Value (millions)"]
        if len(totals) != 1:
            issues.append(f"{company} {period[:4]}: a reported financial-investment total is unavailable; the stack is omitted.")
            continue
        total = float(totals.iloc[0])
        values = pd.to_numeric(parts["Value (millions)"], errors="coerce")
        if values.isna().any() or not math.isclose(float(values.sum()), total, rel_tol=0, abs_tol=0.00001):
            issues.append(f"{company} {period[:4]}: the asset-class items do not reconcile to the reported investment total; the stack is omitted.")
            continue
        for _, item in parts.iterrows():
            code = str(item["Metric code"])
            category, asset_class = COMPONENTS[code]
            if company == "Sun Life Hong Kong" and code == "FIN_ASSET_FVOCI_DEBT":
                asset_class = "Fixed and variable interest investments"
            elif company == "FWD Life Bermuda" and code == "FIN_ASSET_AC_LOANS":
                asset_class = "Loans and deposits"
            output.append({
                "Document ID": document, "Company": company, "Scope": scope,
                "Period": period, "Currency": currency, "Metric code": code,
                "Category": category, "Asset class": asset_class,
                "Amount": float(item["Value (millions)"]),
                "Derivation": ("Sum of disclosed line items" if item["Value status"] == "Derived from disclosed items"
                               else "Directly disclosed"),
                "Stack order": list(COMPONENTS).index(code),
                "Reported total": total,
            })
    return pd.DataFrame(output, columns=_COLUMNS), issues


def financial_investment_chart(rows: pd.DataFrame, companies: list[str], *,
                               display_mode: str = "Native currencies", unit: str = "millions",
                               decimals: int = 0, transparent: bool = True,
                               ) -> tuple[alt.TopLevelMixin | None, list[str]]:
    """One three-category amount stack per insurer/year."""
    if rows.empty:
        return None, []
    plot = rows.loc[rows["Company"].isin(companies)].copy()
    excluded: list[str] = []
    if display_mode == "HKD converted":
        for year in sorted(plot.loc[plot["Currency"].eq("USD"), "Period"].str[:4].unique()):
            mask = plot["Currency"].eq("USD") & plot["Period"].str.startswith(year)
            info = year_end_usd_hkd(int(year))
            if info is None:
                excluded.extend(plot.loc[mask, "Company"].unique().tolist())
                plot = plot.loc[~mask].copy()
                continue
            plot.loc[mask, "Amount"] *= float(info[0])
            plot.loc[mask, "Currency"] = "HKD"
    if plot.empty:
        return None, list(dict.fromkeys(excluded))
    if unit == "billions":
        plot["Amount"] /= 1000
    plot["Panel"] = (
        plot["Company"] + " (" + plot["Scope"].str.title() + ") · " + plot["Currency"]
    )
    plot["Period label"] = plot["Period"].str[:4] + "YE"
    # Aggregate the reconciled asset-class source rows before plotting: the
    # chart and its hover show measurement categories only.
    plot = plot.groupby(
        ["Company", "Scope", "Period", "Currency", "Panel", "Period label", "Category"],
        as_index=False, sort=False,
    )["Amount"].sum()
    plot["Stack order"] = plot["Category"].map(
        {category: index for index, category in enumerate(CATEGORY_COLORS)}
    )
    panel_order = list(dict.fromkeys(
        panel for company in companies for panel in plot.loc[plot["Company"].eq(company), "Panel"]
    ))
    years = sorted(plot["Period label"].unique())
    legend_order = [category for category in CATEGORY_COLORS if category in set(plot["Category"])]
    legend_colors = [CATEGORY_COLORS[category] for category in legend_order]
    plot["Label midpoint"] = 0.0
    plot["Share (%)"] = 0.0
    plot["Percent label"] = ""
    panel_maximum = plot.groupby(["Panel", "Period label"])["Amount"].sum()
    common_maximum = float(panel_maximum.max()) if display_mode == "HKD converted" else None
    for (panel, period), group in plot.groupby(["Panel", "Period label"], sort=False):
        total = float(group["Amount"].sum())
        axis_maximum = (common_maximum if common_maximum is not None else
                        float(panel_maximum.loc[(panel, period)]))
        cumulative = 0.0
        for index, item in group.sort_values("Stack order").iterrows():
            amount = float(item["Amount"])
            plot.at[index, "Label midpoint"] = cumulative + amount / 2
            share = 100 * amount / total if total else 0.0
            plot.at[index, "Share (%)"] = share
            # Match other component charts: labels sit inside sufficiently large
            # segments; very small amounts remain available in the hover.
            if share >= 5 and axis_maximum > 0 and amount / axis_maximum * 300 >= 16:
                plot.at[index, "Percent label"] = f"{share:.0f}%"
            cumulative += amount
    x = alt.X("Period label:N", sort=years, title=None,
              scale=alt.Scale(paddingInner=0.5, paddingOuter=0.45),
              axis=alt.Axis(labelAngle=0, labelLimit=90))
    base = alt.Chart(plot)
    bars = base.mark_bar(
        width=alt.RelativeBandSize(0.9), opacity=0.94,
        cornerRadiusTopLeft=2, cornerRadiusTopRight=2,
    ).encode(
        x=x,
        y=alt.Y("Amount:Q", stack="zero",
                title=f"{'HKD' if display_mode == 'HKD converted' else 'Original currency'} {unit}",
                scale=alt.Scale(zero=True), axis=alt.Axis(format="~s")),
        color=alt.Color(
            "Category:N",
            scale=alt.Scale(domain=legend_order, range=legend_colors),
            legend=alt.Legend(orient="bottom", direction="vertical", title=None,
                              labelLimit=1000, columns=1),
        ),
        order=alt.Order("Stack order:Q", sort="ascending"),
        tooltip=[
            alt.Tooltip("Company:N"), alt.Tooltip("Period label:N", title="Period"),
            alt.Tooltip("Category:N", title="Measurement category"),
            alt.Tooltip("Amount:Q", format=f",.{max(decimals, 1)}f", title=f"Amount ({unit})"),
            alt.Tooltip("Share (%):Q", format=".1f", title="Share of total (%)"),
            alt.Tooltip("Currency:N"),
        ],
    )
    labels = base.mark_text(
        fontSize=9, fontWeight="bold", baseline="middle", tooltip=False,
    ).encode(
        x=x,
        y=alt.Y("Label midpoint:Q", stack=None),
        text=alt.Text("Percent label:N"),
        color=alt.condition(alt.datum.Category == "AC",
                            alt.value("#FFFFFF"), alt.value(KPMG_INK)),
    )
    width, spacing = _company_panel_width(len(panel_order))
    chart = alt.layer(bars, labels, data=plot).properties(width=width, height=300).facet(
        facet=alt.Facet("Panel:N", sort=panel_order, title=None,
                        header=alt.Header(labelPadding=14)),
        columns=len(panel_order), spacing=spacing,
    ).resolve_scale(x="independent", y="shared" if display_mode == "HKD converted" else "independent")
    return _report_chart_theme(chart, transparent=transparent), list(dict.fromkeys(excluded))


def financial_investment_notes(rows: pd.DataFrame) -> list[str]:
    if rows.empty:
        return []
    amounts = []
    sun = rows.loc[
        rows["Company"].eq("Sun Life Hong Kong")
        & rows["Metric code"].eq("FIN_ASSET_FVTPL_INTEREST")
    ]
    for period, group in sun.groupby("Period", sort=True):
        amounts.append(f"{group['Amount'].iloc[0]:,.0f} HKD millions ({period[:4]}YE)")
    if not amounts:
        return []
    joined = amounts[0] if len(amounts) == 1 else (
        ", ".join(amounts[:-1]) + " and " + amounts[-1]
    )
    return [
        f"Sun Life Hong Kong: FVTPL amount{'s' if len(amounts) > 1 else ''} of "
        f"{joined} {'are each' if len(amounts) > 1 else 'is'} summed from six "
        "disclosed Note 21 lines rather than a separately reported subtotal; "
        "AC is not separately disclosed in Note 21."
    ]
