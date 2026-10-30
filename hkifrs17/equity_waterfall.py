"""Equity bridges from opening to closing reported balances."""

from __future__ import annotations

import math

import altair as alt
import pandas as pd

from .charts import KPMG_INK, _company_panel_width, _report_chart_theme
from .fx import year_end_usd_hkd
from .oci_analysis import _single_amount
from .oci_waterfall import _amount_label


_MOVEMENTS = (
    ("PROFIT", "Net profit", "Profit for the year"),
    ("OCI_TOTAL", "OCI", "Other comprehensive income"),
    ("EQUITY_DIVIDENDS", "Dividends", "Dividends paid"),
    ("EQUITY_NEW_CAPITAL", "New capital", "Share capital issued"),
    ("EQUITY_OTHER", "Other disclosed", "Other disclosed equity movements"),
)
_COLORS = {
    "Opening": "#00338D",
    "Increase": "#FF3290",
    "Decrease": "#1E49E2",
    "Closing": "#7213EA",
}
_COLUMNS = ["Document ID", "Company", "Scope", "Period end", "Year",
            "Currency", "Opening", "Movements", "Missing items", "Remainder", "Closing"]


def equity_waterfall_rows(records: pd.DataFrame, companies: list[str],
                          periods: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Keep source identities separate and identify every calculated balancing item."""
    if records.empty:
        return pd.DataFrame(columns=_COLUMNS), []
    selected = records.loc[
        records["Company"].isin(companies) & records["Period end"].isin(periods)
        & records["Currency"].isin(("HKD", "USD"))
    ]
    output, issues = [], []
    keys = ["Document ID", "Company", "Scope", "Period end", "Currency"]
    for identity, group in selected.groupby(keys, sort=False, dropna=False):
        document, company, scope, period, currency = map(str, identity)
        year = period[:4]
        opening, closing = (_single_amount(group, code)
                            for code in ("EQUITY_OPEN", "EQUITY"))
        if opening is None or closing is None:
            missing = [label for label, value in (("opening equity", opening),
                                                  ("closing equity", closing)) if value is None]
            issues.append(f"{company} {year}: equity waterfall unavailable; missing "
                          + ", ".join(missing) + ".")
            continue
        movements, missing = [], []
        for code, short, full in _MOVEMENTS:
            value = _single_amount(group, code)
            if value is None:
                missing.append(full)
            else:
                movements.append({"Step": short, "Line item": full,
                                  "Amount": value, "Calculated": False})
        # Profit and OCI establish the annual comprehensive-income bridge.
        # A missing one cannot be replaced with an unlabelled residual.
        if any(label in missing for label in ("Profit for the year", "Other comprehensive income")):
            issues.append(f"{company} {year}: equity waterfall unavailable; missing "
                          + ", ".join(label for label in missing if label in
                                      ("Profit for the year", "Other comprehensive income")) + ".")
            continue
        remainder = closing - opening - sum(item["Amount"] for item in movements)
        tolerance = max(1e-6, abs(closing) * 1e-9)
        if math.isclose(remainder, 0.0, rel_tol=0, abs_tol=tolerance):
            remainder = 0.0
        else:
            movements.append({"Step": "Remainder*", "Line item":
                              "Calculated unallocated reconciliation remainder",
                              "Amount": remainder, "Calculated": True})
        output.append({"Document ID": document, "Company": company, "Scope": scope,
                       "Period end": period, "Year": year, "Currency": currency,
                       "Opening": opening, "Movements": movements,
                       "Missing items": missing, "Remainder": remainder,
                       "Closing": closing})
    return pd.DataFrame(output, columns=_COLUMNS), issues


def equity_waterfall_chart(rows: pd.DataFrame, companies: list[str], *,
                           display_mode: str = "Native currencies",
                           unit: str = "millions", decimals: int = 0,
                           transparent: bool = True,
                           show_labels: bool = True,
                           height: int = 330,
                           ) -> tuple[alt.TopLevelMixin | None, list[str]]:
    if rows.empty:
        return None, []
    divisor = 1000.0 if unit == "billions" else 1.0
    points, excluded, panel_order = [], [], []
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
            steps = [("Open", "Opening equity", float(row["Opening"])),
                     *((item["Step"], item["Line item"], float(item["Amount"]))
                       for item in row["Movements"]),
                     ("Close", "Closing equity", float(row["Closing"]))]
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
                    "Step order": index,
                    "Next step": steps[index + 1][0] if not is_closing else None,
                    "Has next step": not is_closing, "Line item": line_item,
                    "Bar type": bar_type, "Lower": min(start, end) * rate / divisor,
                    "Upper": max(start, end) * rate / divisor,
                    "End": end * rate / divisor, "Amount": amount,
                    "Value label": _amount_label(amount, decimals),
                    "Show label": abs(original) >= max(abs(row["Opening"]), abs(row["Closing"])) * .005,
                    "Display currency": shown_currency,
                    "Original amount": original, "Original currency": currency,
                })
    if not points:
        return None, excluded
    plot = pd.DataFrame(points)
    panel_order = list(dict.fromkeys(panel_order))
    sort = alt.SortField(field="Step order", order="ascending")
    x = alt.X("Step:N", sort=sort, title=None,
              axis=alt.Axis(labelAngle=-45, labelFontSize=9,
                            labelLimit=110, labelOverlap=False, labelSeparation=0))
    y_title = (f"{plot['Display currency'].iloc[0]} {unit}"
               if plot["Display currency"].nunique() == 1 else f"Amount ({unit})")
    y = alt.Y("Upper:Q", title=y_title, scale=alt.Scale(zero=True),
              axis=alt.Axis(format="~s"))
    color = alt.Color("Bar type:N", title=None,
                      scale=alt.Scale(domain=list(_COLORS), range=list(_COLORS.values())),
                      legend=alt.Legend(orient="bottom", direction="horizontal", columns=4))
    base = alt.Chart(plot)
    tooltip = [alt.Tooltip("Panel:N", title="Insurer"), alt.Tooltip("Year:N"),
               alt.Tooltip("Line item:N"),
               alt.Tooltip("Amount:Q", format=",.3f", title=f"Amount ({unit})"),
               alt.Tooltip("Display currency:N"),
               alt.Tooltip("Original amount:Q", format=",.3f", title="Original amount (millions)"),
               alt.Tooltip("Original currency:N")]
    bars = base.transform_filter(alt.datum.Amount != 0).mark_bar(
        size=28, opacity=.94,
    ).encode(x=x, y=y, y2="Lower:Q", color=color, tooltip=tooltip)
    connectors = base.transform_filter(alt.datum["Has next step"]).mark_rule(
        color="#A7B0BE", strokeWidth=1,
    ).encode(x=alt.X("Step:N", sort=sort, bandPosition=1),
             x2=alt.X2("Next step:N", bandPosition=0),
             y=alt.Y("End:Q", title=None))
    layers = [connectors, bars]
    if show_labels:
        zero = base.transform_filter(alt.datum.Amount == 0).mark_tick(
            size=26, thickness=2, color="#B8C0CC",
        ).encode(x=x, y=alt.Y("End:Q", title=None), tooltip=tooltip)
        positive = base.transform_filter((alt.datum.Amount > 0) & alt.datum["Show label"]).mark_text(
            dy=-8, fontSize=9, fontWeight="bold", color=KPMG_INK,
        ).encode(x=x, y=alt.Y("End:Q", title=None), text="Value label:N")
        negative = base.transform_filter((alt.datum.Amount < 0) & alt.datum["Show label"]).mark_text(
            dy=11, fontSize=9, fontWeight="bold", color=KPMG_INK,
        ).encode(x=x, y=alt.Y("End:Q", title=None), text="Value label:N")
        layers.extend([zero, positive, negative])
    width, spacing = _company_panel_width(len(panel_order))
    chart = alt.layer(*layers).properties(width=width, height=height).facet(
        facet=alt.Facet("Panel:N", sort=panel_order, title=None,
                        header=alt.Header(labelPadding=14)),
        columns=len(panel_order), spacing=spacing,
    ).resolve_scale(x="independent",
                    y="shared" if display_mode == "HKD converted" else "independent")
    return _report_chart_theme(chart, transparent=transparent), excluded


def equity_waterfall_notes(rows: pd.DataFrame) -> list[str]:
    if rows.empty:
        return []
    notes = ["Opening equity + profit + OCI + disclosed movements + any "
             "calculated remainder* = closing equity; the remainder is not separately disclosed."]
    for _, row in rows.iterrows():
        identity = f"{row['Company']}: {row['Year']}YE"
        if row["Missing items"]:
            notes.append(identity + " — omitted undisclosed lines: "
                         + ", ".join(row["Missing items"]) + ".")
        if row["Remainder"]:
            notes.append(identity + f" — remainder* {row['Remainder']:+,.3f} "
                         f"{row['Currency']} million; underlying components are unidentified.")
    return notes


_TABLE_ITEMS = (
    ("Profit for the year", "PROFIT"),
    ("Other comprehensive income", "OCI_TOTAL"),
    ("Dividends paid", "EQUITY_DIVIDENDS"),
    ("Share capital issued", "EQUITY_NEW_CAPITAL"),
    ("Other disclosed equity movements", "EQUITY_OTHER"),
)


def equity_movement_table(records: pd.DataFrame, companies: list[str],
                          periods: list[str], *, display_mode: str = "Native currencies",
                          unit: str = "millions", decimals: int = 0,
                          ) -> tuple[pd.DataFrame, list[str]]:
    """Present the latest selected filing's bridge without inventing missing lines."""
    labels = ["No.", "Item"]
    if records.empty or not periods:
        return pd.DataFrame(columns=labels), []
    latest = max(map(str, periods))
    relevant = records.loc[
        records["Company"].isin(companies) & records["Period end"].astype(str).eq(latest)
        & records["Currency"].isin(("HKD", "USD"))
    ]
    columns: dict[str, list[str]] = {}
    issues: list[str] = []
    divisor = 1000.0 if unit == "billions" else 1.0
    for company in companies:
        company_rows = relevant.loc[relevant["Company"].eq(company)]
        for identity, group in company_rows.groupby(
                ["Document ID", "Scope", "Currency"], sort=False, dropna=False):
            _, scope, currency = map(str, identity)
            rate = 1.0
            if display_mode == "HKD converted" and currency == "USD":
                info = year_end_usd_hkd(int(latest[:4]))
                if info is None:
                    issues.append(f"{company} {latest[:4]}: USD/HKD rate unavailable; table column omitted.")
                    continue
                rate = float(info[0])
            shown_currency = "HKD" if display_mode == "HKD converted" else currency
            header = f"{company} ({scope.title()}) · {shown_currency}"
            values = {code: _single_amount(group, code)
                      for code in ("EQUITY_OPEN", "EQUITY", *
                                   (item[1] for item in _TABLE_ITEMS))}

            def cell(value: float | None) -> str:
                return ("Not disclosed" if value is None
                        else _amount_label(value * rate / divisor, decimals))

            movements = [values[code] for _, code in _TABLE_ITEMS]
            opening, closing = values["EQUITY_OPEN"], values["EQUITY"]
            total = closing - opening if opening is not None and closing is not None else None
            remainder = (total - sum(value for value in movements if value is not None)
                         if total is not None and all(values[code] is not None
                                                      for code in ("PROFIT", "OCI_TOTAL"))
                         else None)
            if remainder is not None and math.isclose(
                    remainder, 0.0, rel_tol=0, abs_tol=max(1e-6, abs(closing) * 1e-9)):
                remainder = 0.0
            columns[header] = [*(cell(value) for value in movements),
                               cell(remainder), cell(total)]
    if not columns:
        return pd.DataFrame(columns=labels), issues
    items = [label for label, _ in _TABLE_ITEMS]
    items.extend(["Unallocated reconciliation remainder*", "Net assets movement"])
    table = pd.DataFrame({"No.": [*map(str, range(1, len(items))),
                                  f"{len(items)} = sum(1–{len(items)-1})"],
                          "Item": items, **columns})
    return table, issues
