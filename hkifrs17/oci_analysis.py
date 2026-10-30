"""Comparable OCI presentation without inferring an asset-liability match rate."""

from __future__ import annotations

import math

import altair as alt
import pandas as pd

from .charts import KPMG_BRIGHT_CHART_COLORS, KPMG_INK, _company_panel_width, _report_chart_theme
from .fx import year_end_usd_hkd
from .investment_note import investment_note_rows


ASSET_LABEL = "Asset-side OCI"
LIABILITY_LABEL = "Insurance and reinsurance finance OCI"
_COMPONENTS = (ASSET_LABEL, LIABILITY_LABEL)
_CODES = (
    "OCI_FVOCI_DEBT", "OCI_FVOCI_RECYCLE", "OCI_INS_FINANCE",
    "OCI_REINS_FINANCE", "FIN_ASSET_FVOCI_DEBT", "TOTAL_ASSETS",
)
_COLUMNS = (
    "Company", "Scope", "Period end", "Year", "Original currency",
    "USD/HKD rate", "FX rate date", "Asset basis", "FVOCI debt balance",
    "Total assets", "FVOCI share (%)", "Asset-side OCI",
    "Insurance-finance OCI", "Original asset OCI", "Original liability OCI",
)


def _single_amount(group: pd.DataFrame, code: str) -> float | None:
    values = pd.to_numeric(
        group.loc[group["Metric code"].eq(code), "Value (millions)"], errors="coerce"
    ).dropna()
    if len(values) != 1 or not math.isfinite(float(values.iloc[0])):
        return None
    return float(values.iloc[0])


def _both(group: pd.DataFrame, left: str, right: str) -> float | None:
    first, second = _single_amount(group, left), _single_amount(group, right)
    return first + second if first is not None and second is not None else None


def oci_comparison_rows(records: pd.DataFrame) -> pd.DataFrame:
    """One row per filing/year, with signed OCI flows and year-end balances in HKD."""
    if records.empty:
        return pd.DataFrame(columns=_COLUMNS)
    note_rows = investment_note_rows(records, "return_components")
    note_rows = note_rows.loc[
        note_rows["Metric"].eq("Amounts recognised in OCI")
    ] if not note_rows.empty else note_rows
    lookup = {
        (str(row["Document ID"]), str(row["Period end"]), str(row["Scope"])):
        float(row["Amount"])
        for _, row in note_rows.iterrows()
    }
    relevant = records.loc[records["Metric code"].isin(_CODES)].copy()
    output = []
    keys = ["Document ID", "Company", "Scope", "Period end", "Currency"]
    for identity, group in relevant.groupby(keys, sort=False, dropna=False):
        document, company, scope, period, currency = map(str, identity)
        year = str(period)[:4]
        if company == "YF Life":
            asset = lookup.get((document, period, scope))
            asset_basis = "Total investment return recognised in OCI"
        else:
            asset = _both(group, "OCI_FVOCI_DEBT", "OCI_FVOCI_RECYCLE")
            asset_basis = "FVOCI fair-value movement and P&L reclassification"
        liability = _both(group, "OCI_INS_FINANCE", "OCI_REINS_FINANCE")
        fvoci = _single_amount(group, "FIN_ASSET_FVOCI_DEBT")
        total_assets = _single_amount(group, "TOTAL_ASSETS")
        share = (100 * fvoci / total_assets
                 if fvoci is not None and total_assets is not None and total_assets > 0
                 else None)
        if currency == "HKD":
            rate, rate_date = 1.0, period
        elif currency == "USD":
            info = year_end_usd_hkd(int(year))
            rate, rate_date = (info[0], info[1]) if info else (None, None)
        else:
            rate, rate_date = None, None
        converted = lambda value: value * rate if value is not None and rate is not None else None
        output.append({
            "Company": company, "Scope": scope, "Period end": period, "Year": year,
            "Original currency": currency, "USD/HKD rate": rate, "FX rate date": rate_date,
            "Asset basis": asset_basis, "FVOCI debt balance": converted(fvoci),
            "Total assets": converted(total_assets), "FVOCI share (%)": share,
            "Asset-side OCI": converted(asset), "Insurance-finance OCI": converted(liability),
            "Original asset OCI": asset, "Original liability OCI": liability,
        })
    return pd.DataFrame(output, columns=_COLUMNS).sort_values(
        ["Company", "Period end"], kind="stable"
    ).reset_index(drop=True) if output else pd.DataFrame(columns=_COLUMNS)


def oci_comparison_chart(rows: pd.DataFrame, companies: list[str],
                         periods: list[str], *, transparent: bool = True) -> alt.TopLevelMixin | None:
    """Two signed annual bars per insurer; absent source cells create no bar."""
    if rows.empty:
        return None
    selected = rows.loc[
        rows["Company"].isin(companies) & rows["Period end"].isin(periods)
    ]
    points = []
    for _, row in selected.iterrows():
        for component, field, original_field in (
            (ASSET_LABEL, "Asset-side OCI", "Original asset OCI"),
            (LIABILITY_LABEL, "Insurance-finance OCI", "Original liability OCI"),
        ):
            if pd.isna(row[field]):
                continue
            points.append({
                "Company": f"{row['Company']} ({str(row['Scope']).title()}) · HKD",
                "Year": row["Year"], "Component": component,
                "HKD millions": float(row[field]),
                "Original millions": float(row[original_field]),
                "Original currency": row["Original currency"],
            })
    if not points:
        return None
    plot = pd.DataFrame(points)
    plot["Label midpoint"] = plot["HKD millions"] / 2
    plot["Value label"] = plot["HKD millions"].map(lambda value: f"{value:,.1f}")
    span = max(0.0, float(plot["HKD millions"].max())) - min(
        0.0, float(plot["HKD millions"].min())
    )
    if span > 0:
        too_short = plot["HKD millions"].abs() * 270 / (span * 1.25) < 12
        plot.loc[too_short, "Value label"] = ""
    order = [
        f"{company} ({str(selected.loc[selected['Company'].eq(company), 'Scope'].iloc[0]).title()}) · HKD"
        for company in companies if company in set(selected["Company"])
    ]
    years = sorted(plot["Year"].unique())
    x = alt.X(
        "Year:N", sort=years, title=None,
        scale=alt.Scale(paddingInner=0.5, paddingOuter=0.45),
        axis=alt.Axis(labelAngle=0, labelLimit=90),
    )
    offset = alt.XOffset(
        "Component:N", sort=list(_COMPONENTS),
        scale=alt.Scale(paddingInner=0, paddingOuter=0),
    )
    y = alt.Y(
        "HKD millions:Q", title="HKD millions", scale=alt.Scale(zero=True),
        axis=alt.Axis(format="~s"),
    )
    color = alt.Color(
        "Component:N", sort=list(_COMPONENTS), title=None,
        scale=alt.Scale(domain=list(_COMPONENTS), range=list(KPMG_BRIGHT_CHART_COLORS[:2])),
        legend=alt.Legend(orient="bottom", direction="vertical",
                          title=None, labelLimit=1000, columns=1),
    )
    bars = alt.Chart(plot).mark_bar(
        width=alt.RelativeBandSize(1.0), opacity=0.94,
    ).encode(x=x, xOffset=offset, y=y, color=color, tooltip=[
        alt.Tooltip("Company:N"), alt.Tooltip("Year:N"),
        alt.Tooltip("Component:N"),
        alt.Tooltip("HKD millions:Q", format="+,.3f"),
        alt.Tooltip("Original millions:Q", format="+,.3f"),
        alt.Tooltip("Original currency:N"),
    ])
    labels = alt.Chart(plot).mark_text(
        fontSize=9, fontWeight="bold", baseline="middle", color=KPMG_INK,
        tooltip=False,
    ).encode(
        x=x, xOffset=offset,
        y=alt.Y("Label midpoint:Q", stack=None),
        text="Value label:N",
    )
    panel_width, spacing = _company_panel_width(len(order))
    chart = (bars + labels).properties(width=panel_width, height=270).facet(
        facet=alt.Facet("Company:N", sort=order, title=None,
                        header=alt.Header(labelPadding=14)),
        columns=len(order), spacing=spacing,
    ).resolve_scale(y="shared")
    return _report_chart_theme(chart, transparent=transparent)


def oci_comparison_table(rows: pd.DataFrame, companies: list[str],
                         periods: list[str]) -> pd.DataFrame:
    """Keep balance shares separate from signed annual flow amounts."""
    columns = ["Company", "Year", "FVOCI debt balance (HKD m)",
               "Total assets (HKD m)", "FVOCI debt / total assets",
               "Asset-side OCI (HKD m)", "Insurance-finance OCI (HKD m)"]
    if rows.empty:
        return pd.DataFrame(columns=columns)
    selected = rows.loc[rows["Company"].isin(companies) & rows["Period end"].isin(periods)]
    selected = selected.assign(_order=selected["Company"].map({name: i for i, name in enumerate(companies)}))
    selected = selected.sort_values(["_order", "Period end"], kind="stable")
    amount = lambda x: f"{float(x):+,.3f}" if pd.notna(x) else "Not available"
    balance = lambda x: f"{float(x):,.3f}" if pd.notna(x) else "Not available"
    result = []
    for _, row in selected.iterrows():
        result.append({
            "Company": f"{row['Company']} ({str(row['Scope']).title()})",
            "Year": row["Year"],
            "FVOCI debt balance (HKD m)": balance(row["FVOCI debt balance"]),
            "Total assets (HKD m)": balance(row["Total assets"]),
            "FVOCI debt / total assets": (
                f"{float(row['FVOCI share (%)']):.2f}%"
                if pd.notna(row["FVOCI share (%)"]) else "Not available"
            ),
            "Asset-side OCI (HKD m)": amount(row["Asset-side OCI"]),
            "Insurance-finance OCI (HKD m)": amount(row["Insurance-finance OCI"]),
        })
    return pd.DataFrame(result, columns=columns)


def oci_comparison_wide_table(rows: pd.DataFrame, companies: list[str],
                              periods: list[str]) -> pd.DataFrame:
    """Put existing annual balances, shares and OCI flows across company columns."""
    selected = rows.loc[
        rows["Company"].isin(companies) & rows["Period end"].isin(periods)
    ]
    if selected.empty:
        return pd.DataFrame(columns=["Item"])

    identities = [
        (company, scope)
        for company in companies
        for scope in selected.loc[selected["Company"].eq(company), "Scope"].drop_duplicates()
    ]
    labels = {identity: f"{identity[0]} ({str(identity[1]).title()})"
              for identity in identities}
    selected_periods = sorted(selected["Period end"].astype(str).unique())
    measures = (
        ("FVOCI debt / total assets", "FVOCI share (%)", "share"),
        ("FVOCI debt balance", "FVOCI debt balance", "balance"),
        ("Total assets", "Total assets", "balance"),
        ("Asset-side OCI", "Asset-side OCI", "amount"),
        ("Insurance-finance OCI", "Insurance-finance OCI", "amount"),
    )
    result = []
    for title, field, kind in measures:
        for period in selected_periods:
            year = period[:4]
            label = (f"{title} ({year}YE)" if kind == "share" else
                     f"{title} ({year}, HKD m)" if kind == "amount" else
                     f"{title} ({year}YE, HKD m)")
            entry = {"Item": label}
            for identity in identities:
                matching = selected.loc[
                    selected["Company"].eq(identity[0])
                    & selected["Scope"].eq(identity[1])
                    & selected["Period end"].astype(str).eq(period), field
                ].dropna()
                if len(matching) != 1:
                    entry[labels[identity]] = "Not available"
                    continue
                value = float(matching.iloc[0])
                entry[labels[identity]] = (
                    f"{value:.2f}%" if kind == "share" else
                    f"{value:+,.3f}" if kind == "amount" else
                    f"{value:,.3f}"
                )
            result.append(entry)
    return pd.DataFrame(result, columns=["Item", *labels.values()])


def oci_comparison_notes(rows: pd.DataFrame, companies: list[str],
                         periods: list[str], *, include_scale_note: bool = True) -> list[str]:
    """Explain scope, units, and absent bars for the active selection."""
    selected = rows.loc[rows["Company"].isin(companies) & rows["Period end"].isin(periods)]
    if selected.empty:
        return []
    notes = [
        "Annual OCI amounts are flows; FVOCI debt securities and total assets are year-end balances. "
        "FVOCI debt share = FVOCI debt balance / total assets.",
    ]
    if include_scale_note:
        notes.insert(0, "This OCI chart and table use HKD millions in every display mode. "
                        "Company panels share one vertical amount scale.")
    for company in ("FWD Life Bermuda", "Sun Life Hong Kong"):
        if company in set(selected["Company"]):
            notes.append(f"{company}: asset-side OCI includes FVOCI fair-value movement and "
                         "the P&L reclassification; the latter is shown separately in its source statement.")
    if "YF Life" in set(selected["Company"]):
        notes.append("YF asset-side OCI is total investment return recognised in OCI, "
                     "a broader basis than FVOCI debt movement alone.")
    for company in companies:
        group = selected.loc[selected["Company"].eq(company)]
        for field, label in (("Asset-side OCI", "asset-side OCI"),
                             ("Insurance-finance OCI", "insurance and reinsurance finance OCI")):
            missing = group.loc[group[field].isna(), "Year"].tolist()
            if missing:
                notes.append(f"{company}: {label} is unavailable for {', '.join(missing)}; "
                             "the corresponding bars and table values are left absent, not set to zero.")
    notes.append("The comparison illustrates accounting OCI offsets; it does not measure duration or cash-flow matching.")
    return notes
