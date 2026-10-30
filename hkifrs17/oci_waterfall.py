"""Statement-line OCI waterfalls from profit to comprehensive income."""

from __future__ import annotations

import json
import math
from pathlib import Path

import altair as alt
import pandas as pd

from .charts import KPMG_INK, _company_panel_width, _report_chart_theme
from .fx import year_end_usd_hkd
from .oci_analysis import _single_amount


_SUPPLEMENT_FILE = Path(__file__).resolve().parents[1] / "data" / "oci_statement_supplements.json"
_SUPPLEMENTS = {
    (item["document_id"], item["period"], item["metric_code"]): item
    for item in json.loads(_SUPPLEMENT_FILE.read_text(encoding="utf-8"))
}

# Each layout follows the order of the reported comprehensive-income statement.
# An unreviewed insurer or year has no layout and is not assigned a synthetic zero.
_FWD_ITEMS = (
    ("OCI_FVOCI_DEBT", "FVOCI FV change", "Fair value gains/(losses) on debt securities at FVOCI", "Asset OCI"),
    ("OCI_FVOCI_RECYCLE", "FVOCI reclassified", "FVOCI debt securities transferred to profit or loss", "Asset OCI"),
    ("OCI_INS_FINANCE", "Insurance finance", "Net finance (expenses)/income from insurance contracts", "Insurance finance OCI"),
    ("OCI_REINS_FINANCE", "Reinsurance finance", "Net finance income/(expenses) from reinsurance contracts held", "Insurance finance OCI"),
    ("OCI_HEDGE", "Cash flow hedges", "Cash flow hedges", "Other OCI"),
    ("OCI_TAX", "OCI income tax", "Related income tax", "Other OCI"),
)
_SUN_ITEMS = (
    ("OCI_FVOCI_DEBT", "FVOCI FV change", "Change in fair value of investments measured at FVOCI", "Asset OCI"),
    ("OCI_FVOCI_RECYCLE", "FVOCI reclassified", "Reclassification adjustment on disposal of FVOCI investments", "Asset OCI"),
    ("OCI_TAX", "Deferred OCI tax", "Deferred tax arising from investment revaluation reserve", "Other OCI"),
)
_YF_ITEMS = (
    ("OCI_FAIR_VALUE_RESERVE", "FV reserve movement", "Net movement in the fair value reserve recognised in OCI", "Asset OCI"),
    ("OCI_HEDGE", "Cash flow hedges", "Cash flow hedge movement in the hedging reserve", "Other OCI"),
    ("OCI_FX_TRANSLATION", "FX translation", "Exchange differences on translation of foreign operations", "Other OCI"),
    ("OCI_INS_FINANCE", "Insurance finance", "Net finance expenses from insurance contracts", "Insurance finance OCI"),
    ("OCI_REINS_FINANCE", "Reinsurance finance", "Net finance income from reinsurance contracts", "Insurance finance OCI"),
    ("OCI_TAX", "Deferred OCI tax", "Net deferred tax impact recognised in OCI", "Other OCI"),
)
_LAYOUTS = {
    ("FWD Life Bermuda", "2024"): _FWD_ITEMS,
    ("FWD Life Bermuda", "2025"): _FWD_ITEMS,
    ("Sun Life Hong Kong", "2024"): _SUN_ITEMS,
    ("Sun Life Hong Kong", "2025"): _SUN_ITEMS + (
        ("OCI_ECL_ADJUSTMENT", "Expected credit loss", "Adjustment on expected credit loss", "Other OCI"),
    ),
    ("YF Life", "2024"): _YF_ITEMS,
    ("YF Life", "2025"): _YF_ITEMS,
}

_BAR_COLORS = {
    "Start": "#00338D",
    "Increase": "#FF3290",
    "Decrease": "#1E49E2",
    "End": "#7213EA",
}


def _amount_label(value: float, decimals: int) -> str:
    precision = decimals
    while value and round(value, precision) == 0 and precision < 3:
        precision += 1
    return f"{value:,.{precision}f}"


def oci_waterfall_rows(records: pd.DataFrame, companies: list[str],
                       periods: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Keep only complete statement-line bridges that reconcile to reported totals."""
    columns = [
        "Document ID", "Company", "Scope", "Period end", "Year", "Currency",
        "Net Profit", "Components", "OCI total", "Total Comprehensive Income",
        "Supplemental items",
    ]
    if records.empty:
        return pd.DataFrame(columns=columns), []
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
        layout = _LAYOUTS.get((company, year))
        if layout is None:
            issues.append(f"{company} {year}: the statement-line OCI layout has not been reviewed; the waterfall is omitted.")
            continue
        profit = _single_amount(group, "PROFIT")
        oci_total = _single_amount(group, "OCI_TOTAL")
        comprehensive = _single_amount(group, "COMPREHENSIVE_INCOME")
        if any(value is None for value in (profit, oci_total, comprehensive)):
            issues.append(f"{company} {year}: a reported profit, OCI, or comprehensive-income total is unavailable.")
            continue
        if not math.isclose(profit + oci_total, comprehensive, rel_tol=0, abs_tol=0.00001):
            issues.append(f"{company} {year}: profit plus OCI does not reconcile to comprehensive income.")
            continue
        components = []
        supplemental = []
        missing = []
        conflict = []
        for code, short_label, full_label, category in layout:
            value = _single_amount(group, code)
            supplement = _SUPPLEMENTS.get((document, period, code))
            if value is not None and supplement is not None and not math.isclose(
                    value, float(supplement["amount_millions"]), rel_tol=0, abs_tol=0.000001):
                conflict.append(short_label)
                continue
            if value is None and supplement is not None:
                if "Review status" in group and not group["Review status"].eq("Verified").all():
                    missing.append(short_label)
                    continue
                value = float(supplement["amount_millions"])
                supplemental.append(f"{full_label} (PDF p.{supplement['pdf_page']})")
            if value is None:
                missing.append(short_label)
                continue
            components.append({
                "Code": code, "Step": short_label, "Line item": full_label,
                "Category": category, "Amount": float(value),
            })
        if conflict:
            issues.append(f"{company} {year}: source values conflict for {', '.join(conflict)}; the waterfall is omitted.")
            continue
        if missing:
            issues.append(f"{company} {year}: statement items unavailable: {', '.join(missing)}; the waterfall is omitted.")
            continue
        if not math.isclose(sum(item["Amount"] for item in components), oci_total,
                            rel_tol=0, abs_tol=0.00001):
            issues.append(f"{company} {year}: statement items do not reconcile to reported OCI; the waterfall is omitted.")
            continue
        output.append({
            "Document ID": document, "Company": company, "Scope": scope,
            "Period end": period, "Year": year, "Currency": currency,
            "Net Profit": profit, "Components": components, "OCI total": oci_total,
            "Total Comprehensive Income": comprehensive,
            "Supplemental items": supplemental,
        })
    return pd.DataFrame(output, columns=columns), issues


def oci_waterfall_chart(rows: pd.DataFrame, companies: list[str], *,
                        display_mode: str = "Native currencies", unit: str = "millions",
                        decimals: int = 0, transparent: bool = True,
                        height: int = 330,
                        ) -> tuple[alt.TopLevelMixin | None, list[str]]:
    """Facet each insurer's reported profit-to-comprehensive-income waterfall."""
    if rows.empty:
        return None, []
    divisor = 1000.0 if unit == "billions" else 1.0
    points: list[dict] = []
    excluded: list[str] = []
    panel_order: list[str] = []
    for company in companies:
        group = rows.loc[rows["Company"].eq(company)]
        for _, row in group.iterrows():
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
                ("Net Profit", "Profit for the year", float(row["Net Profit"])),
                *((item["Step"], item["Line item"], item["Amount"])
                  for item in row["Components"]),
                ("Total Comprehensive Income", "Total comprehensive income for the year",
                 float(row["Total Comprehensive Income"])),
            ]
            running = 0.0
            for index, (step, line_item, original) in enumerate(steps):
                is_total = index == len(steps) - 1
                start = 0.0 if index == 0 or is_total else running
                end = original if index == 0 or is_total else running + original
                if not is_total:
                    running = end
                amount = original * rate / divisor
                bar_type = (
                    "Start" if index == 0 else "End" if is_total else
                    "Increase" if original > 0 else "Decrease" if original < 0 else None
                )
                points.append({
                    "Company": panel, "Year": row["Year"], "Step": step,
                    "Step number": str(index + 1), "Step order": index,
                    "Next step": str(index + 2) if not is_total else None,
                    "Has next step": not is_total,
                    "Line item": line_item,
                    "Bar type": bar_type,
                    "Lower": min(start, end) * rate / divisor,
                    "Upper": max(start, end) * rate / divisor,
                    "End": end * rate / divisor, "Amount": amount,
                    "Value label": _amount_label(amount, decimals),
                    "Display currency": shown_currency,
                    "Original amount": original, "Original currency": currency,
                })
    if not points:
        return None, excluded
    plot = pd.DataFrame(points)
    panel_order = list(dict.fromkeys(panel_order))
    order = alt.SortField(field="Step order", order="ascending")
    x = alt.X("Step number:N", sort=order, title="Statement item (see numbered items below)",
              axis=alt.Axis(labelAngle=0, labelFontSize=10))
    y = alt.Y("Upper:Q", title=f"{plot['Display currency'].iloc[0] if len(set(plot['Display currency'])) == 1 else 'Amount'} {unit}",
              scale=alt.Scale(zero=True), axis=alt.Axis(format="~s"))
    color = alt.Color("Bar type:N", title=None,
                      scale=alt.Scale(domain=list(_BAR_COLORS), range=list(_BAR_COLORS.values())),
                      legend=alt.Legend(orient="bottom", direction="horizontal",
                                        columns=4))
    base = alt.Chart(plot)
    tooltip = [
        alt.Tooltip("Company:N"), alt.Tooltip("Year:N"),
        alt.Tooltip("Line item:N"), alt.Tooltip("Amount:Q", format=",.3f",
                    title=f"Amount ({unit})"),
        alt.Tooltip("Display currency:N"),
        alt.Tooltip("Original amount:Q", format=",.3f", title="Original amount (millions)"),
        alt.Tooltip("Original currency:N"),
    ]
    bars = base.transform_filter(alt.datum.Amount != 0).mark_bar(
        size=28, opacity=0.94,
    ).encode(x=x, y=y, y2="Lower:Q", color=color, tooltip=tooltip)
    connectors = base.transform_filter(alt.datum["Has next step"]).mark_rule(
        color="#A7B0BE", strokeWidth=1,
    ).encode(
        x=alt.X("Step number:N", sort=order, bandPosition=1),
        x2=alt.X2("Next step:N", bandPosition=0),
        y=alt.Y("End:Q", title=None),
    )
    zero = base.transform_filter(alt.datum.Amount == 0).mark_tick(
        size=26, thickness=2, color="#B8C0CC",
    ).encode(x=x, y=alt.Y("End:Q", title=None), tooltip=tooltip)
    positive = base.transform_filter(alt.datum.Amount > 0).mark_text(
        dy=-8, fontSize=9, fontWeight="bold", color=KPMG_INK,
    ).encode(x=x, y=alt.Y("End:Q", title=None), text="Value label:N")
    negative = base.transform_filter(alt.datum.Amount < 0).mark_text(
        dy=11, fontSize=9, fontWeight="bold", color=KPMG_INK,
    ).encode(x=x, y=alt.Y("End:Q", title=None), text="Value label:N")
    zero_label = base.transform_filter(alt.datum.Amount == 0).mark_text(
        dy=-9, fontSize=9, color=KPMG_INK,
    ).encode(x=x, y=alt.Y("End:Q", title=None), text="Value label:N")
    width, spacing = _company_panel_width(len(panel_order))
    chart = alt.layer(connectors, bars, zero, positive, negative, zero_label).properties(
        width=width, height=height,
    ).facet(
        facet=alt.Facet("Company:N", sort=panel_order, title=None,
                        header=alt.Header(labelPadding=14)),
        columns=len(panel_order), spacing=spacing,
    ).resolve_scale(
        x="independent", y="shared" if display_mode == "HKD converted" else "independent",
    )
    return _report_chart_theme(chart, transparent=transparent), excluded


_KEY_LABELS = {
    "FVOCI FV change": "FVOCI fair value change",
    "FVOCI reclassified": "FVOCI reclassification",
    "Insurance finance": "Insurance finance OCI",
    "Reinsurance finance": "Reinsurance finance OCI",
    "FV reserve movement": "Fair value reserve movement",
    "FX translation": "Foreign currency translation",
}


def oci_waterfall_key(rows: pd.DataFrame, companies: list[str]) -> list[dict]:
    """Compact numbered statement-item keys in the same order as chart facets."""
    if rows.empty:
        return []
    keys = []
    for company in companies:
        for _, row in rows.loc[rows["Company"].eq(company)].iterrows():
            components = row["Components"]
            keys.append({
                "Company": company,
                "Scope": str(row["Scope"]).title(),
                "Year": str(row["Year"]),
                "End number": len(components) + 2,
                "Items": [(index, _KEY_LABELS.get(item["Step"], item["Step"]))
                          for index, item in enumerate(components, 2)],
                "Supplemental items": row["Supplemental items"],
            })
    return keys


def oci_waterfall_notes(rows: pd.DataFrame) -> list[str]:
    """Explain the statement-item bridge and separately transcribed inputs."""
    if rows.empty:
        return []
    notes = []
    for _, row in rows.iterrows():
        labels = ["Net Profit", *(item["Line item"] for item in row["Components"]),
                  "Total Comprehensive Income"]
        numbered = "; ".join(f"{index} {label}" for index, label in enumerate(labels, 1))
        notes.append(f"{row['Company']} ({str(row['Scope']).title()}) {row['Year']}YE — numbered items: {numbered}.")
    notes.append(
        "Net Profit + the OCI items disclosed in each insurer's comprehensive-income statement "
        "= Total Comprehensive Income. Net Profit is the navy start bar and Total Comprehensive Income "
        "is the purple end bar; pink and blue show increasing and decreasing OCI items. "
        "The items reconcile to reported OCI; "
        "no balancing residual or assumed zero is plotted."
    )
    for _, row in rows.iterrows():
        if row["Supplemental items"]:
            notes.append(
                f"{row['Company']} {row['Year']}: the following statement lines supplement the "
                "standardised source cells: " + "; ".join(row["Supplemental items"]) + "."
            )
    return notes
