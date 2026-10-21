"""Responsive, source-aware small multiples for peer comparison."""

from __future__ import annotations

from itertools import groupby

import pandas as pd
import streamlit as st

from hkifrs17.charts import (company_year_comparison_bars, csm_maturity_lines, financial_performance_peer_dots, frame_peer_company_panels, peer_group_panels,
                            peer_ratio_module_panels, peer_revenue_stack_panels, tax_profit_bars)
from hkifrs17.data import standardize_hkd
from hkifrs17.demo import demo_records
from hkifrs17.external import load_analysis_records
from hkifrs17.fx import year_end_usd_hkd
from hkifrs17.highlights import financial_highlights_table
from hkifrs17.report_modules import (
    COMPANY_YEAR_COMPARISON_IDS, HOVER_ONLY_LABEL_MODULE_IDS,
    LATEST_YEAR_CHART_IDS,
    MOVEMENT_MODULE_IDS, PERFORMANCE_RATIO_PAGE_GROUPS, RATIO_MODULE_LABELS, REPORT_MODULES,
    NET_RESULT_REPORTED_LABELS,
    STACKED_AMOUNT_MODULE_IDS, STACKED_AMOUNT_TOTAL_CODES,
    YEAR_COLORED_MODULE_IDS, discount_rate_summary,
    investment_result_reconciliation, stacked_component_metrics,
    missing_metrics, module_rows, movement_chart_rows, report_modules_for_rows,
)
from hkifrs17.report_ui import (
    ALL_IN_SELECTION, back_cover, cover, print_controls, render_financial_highlights_table,
    render_discount_rate_table, render_report_table, sidebar_report_navigation, slug,
)


with st.container(key="report_screen_controls"):
    st.title("Peer comparison")
    st.caption("Step 6 · Period runs horizontally; each colored column represents an indicator. Each insurer has its own chart.")
    saved_records = load_analysis_records()
    if not saved_records.empty and not st.session_state.get("analysis_data_active", False):
        st.caption(f"{len(saved_records)} saved verified source cells are available. Choose Use saved verified data to display them in this session.")
        if st.button("Use saved verified data", key="step6_use_saved_data"):
            st.session_state["analysis_data_active"] = True
            st.session_state["peers_primary"] = REPORT_MODULES[0].section
            st.session_state["peers_secondary"] = "Profitability"
            st.session_state["peers_chart"] = ALL_IN_SELECTION
    active_records = (saved_records if st.session_state.get("analysis_data_active", False)
                      else saved_records.iloc[0:0].copy())
    preview = st.toggle(
        "Preview unpublished pilot transcriptions", value=False,
        help="Off by default. Preview figures are Pending and cannot be exported as reviewed data.",
    )
    records = standardize_hkd(demo_records() if preview else active_records)
    if preview:
        st.warning("Demo preview · Source transcriptions are Pending. This is not a published peer dataset.")
    elif not active_records.empty:
        st.caption(f"Loaded {len(active_records)} verified source cells in this session.")
    if records.empty:
        st.info("No dataset is active in this session. Complete review and integration in Steps 1–4, import a verified workbook in Step 5, choose saved verified data, or explicitly enable the demo preview.")
        st.stop()

    cohorts = sorted({str(period)[5:] for period in records["Period end"]})
    cohort_labels = {"12-31": "31 December year end", "06-30": "30 June year end"}
    with st.expander("Core configuration panel", expanded=False, key="peer_core_config"):
        first = st.columns([1, 1, 1])
        with first[0]:
            cohort = st.selectbox(
                "Year-end cohort", cohorts,
                index=cohorts.index("12-31") if "12-31" in cohorts else 0,
                format_func=lambda value: cohort_labels.get(value, value),
            )
        cohort_rows = records[records["Period end"].astype(str).str.endswith(cohort)].copy()
        with first[1]:
            scope = st.selectbox("Reporting scope", ["All scopes", "Company", "Consolidated"])
        if scope != "All scopes":
            cohort_rows = cohort_rows[cohort_rows["Scope"].eq(scope)]
        with first[2]:
            order_by = st.selectbox("Company order", ["Alphabetical", "Latest service margin"])

        company_options = sorted(cohort_rows["Company"].unique())
        if {"Sun Life Hong Kong", "Sun Life Hong Kong (Consolidated)"}.issubset(company_options):
            st.caption("Sun Life 2024 consolidated and 2025 company figures are separate chart identities because their reporting scopes differ.")
        period_options = sorted(cohort_rows["Period end"].astype(str).unique())
        second = st.columns([2, 2, 2])
        with second[0]:
            companies = st.multiselect("Displayed insurers", company_options, default=company_options)
        with second[1]:
            periods = st.multiselect("Comparison periods", period_options, default=period_options)
        with second[2]:
            tracking_options = [None, *companies]
            if st.session_state.get("step6_tracked_company") not in tracking_options:
                st.session_state["step6_tracked_company"] = companies[0] if companies else None
            tracked_company = st.selectbox(
                "Tracked insurer", tracking_options,
                format_func=lambda value: "None" if value is None else value,
                key="step6_tracked_company",
            )

        third = st.columns([1, 1, 1])
        with third[0]:
            display_mode = st.selectbox("Amount currency", ["HKD converted", "Native currencies"])
        with third[1]:
            unit = st.selectbox("Display unit", ["millions", "billions"])
        with third[2]:
            decimals = st.selectbox("Value label decimal places", [0, 1, 2], index=1)
        show_labels = True
        transparent = st.toggle("Transparent chart background", value=True)
        st.caption("Chart type: grouped columns · Horizontal axis: Period · Series and colors: indicators · Layout: one chart per insurer.")

        if display_mode == "HKD converted" and "USD" in set(cohort_rows["Currency"]):
            for year in sorted({int(period[:4]) for period in periods}):
                rate_info = year_end_usd_hkd(year)
                if rate_info is None:
                    st.warning(f"{year} USD/HKD year-end rate is not published or cannot be retrieved; USD amounts for that year are omitted.")
                else:
                    fx_rate, fx_date, fx_source = rate_info
                    st.caption(f"{year} USD/HKD: {fx_rate:.4f} · observation {fx_date} · Federal Reserve H.10 · {fx_source}")

    if not companies or not periods:
        st.info("Select at least one insurer and one period in the core configuration panel.")
        st.stop()

    rows = cohort_rows[
        cohort_rows["Company"].isin(companies) & cohort_rows["Period end"].astype(str).isin(periods)
    ].copy()
    if rows.empty:
        st.info("No reviewed cells match the selected companies and periods.")
        st.stop()
    tracked_scopes = tuple(cohort_rows.loc[
        cohort_rows["Company"].eq(tracked_company), "Scope"
    ].astype(str).unique()) if tracked_company else ()

    if order_by == "Latest service margin":
        latest = periods[-1]
        subset = rows[rows["Period end"].astype(str).eq(latest)]
        margin_inputs = subset[subset["Metric code"].isin(["INS_REVENUE", "INS_SERVICE_RESULT"])]
        pivot = margin_inputs.pivot_table(index="Company", columns="Metric code", values="Value (millions)", aggfunc="first")
        if {"INS_REVENUE", "INS_SERVICE_RESULT"}.issubset(pivot.columns):
            margins = (pivot["INS_SERVICE_RESULT"] / pivot["INS_REVENUE"].replace(0, float("nan"))).to_dict()
            companies = sorted(companies, key=lambda name: (
                pd.isna(margins.get(name)), -float(margins.get(name, 0)) if pd.notna(margins.get(name)) else 0, name
            ))

display_modules = tuple(
    module for module in report_modules_for_rows(rows)
    if module.section != "HKFRS 17 supplementary disclosures"
)
st.session_state.setdefault("peers_secondary", "Profitability")
all_mode, visible_modules = sidebar_report_navigation(
    display_modules, key="peers", heading="Peer report navigation",
)
full_report = print_controls("peers", all_mode=all_mode)
if full_report:
    cover(
        "HK IFRS 17 · Peer report",
        f"{periods[0]} to {periods[-1]} · {cohort_labels.get(cohort, cohort)}",
        f"Scope: {scope} · {len(companies)} insurers",
    )

with st.container(key="report_screen_summary"):
    coverage = rows[["Company", "Legal entity", "Scope", "Currency", "Period end", "Audit status"]].drop_duplicates()
    if coverage["Scope"].nunique() > 1:
        st.caption("This selection mixes company and consolidated statements. Use the scope filter for a like-scope view.")
    if display_mode == "Native currencies" and coverage["Currency"].nunique() > 1:
        st.caption("Amount panels show each insurer's original currency with independent scales. Select HKD converted for absolute peer comparisons.")
    elif display_mode == "HKD converted":
        st.caption(f"Each HKD amount chart uses one shared vertical scale across the selected insurers, in HKD {unit}.")
    if cohort == "06-30":
        st.caption("June and December financial years stay in separate cohorts.")

    st.caption("The charts below follow the sidebar selection. Choose All charts for the complete report. Movement charts show the latest selected year; each amount chart has one responsive panel per insurer.")


def _show_chart(chart, *, width: str = "stretch") -> None:
    framed = frame_peer_company_panels(
        chart, tracked_company=tracked_company, tracked_scopes=tracked_scopes,
    )
    st.altair_chart(framed, width=width)


def _render_module(module) -> None:
    data = module_rows(rows, module)
    plot_data = movement_chart_rows(data, module)
    plot_periods = (
        sorted(plot_data["Period end"].astype(str).unique())
        if module.module_id in LATEST_YEAR_CHART_IDS else periods
    )
    anchor = slug(module.module_id + " " + module.title)
    st.markdown(f'<div id="{anchor}"></div>', unsafe_allow_html=True)
    with st.container(key=f"report_visual_{module.module_id}"):
        if module.module_id not in {"csm_maturity_table", "summary_table", "six_dimensional_charts"}:
            st.markdown(f"#### {module.title}")
        if module.module_id == "summary_table":
            chart, excluded = peer_group_panels(
                data, ["TOTAL_LIABS", "EQUITY"], companies=companies, periods=periods,
                display_mode=display_mode, unit=unit,
                show_labels=True, decimals=decimals, transparent=transparent, stacked=True,
            )
            with st.container(key="report_figure_summary_table"):
                st.markdown(f"#### {module.title}")
                if excluded:
                    st.caption("USD amount panels with unavailable year-end rates: " + ", ".join(excluded))
                if chart is not None:
                    _show_chart(chart)
                st.caption(
                    "Balance-sheet composition · Total liabilities + equity = total assets. "
                    + ("HKD panels share one amount scale." if display_mode == "HKD converted"
                       else "Native-currency panels have independent amount scales.")
                )
            with st.container(key="report_table_summary_table"):
                st.markdown("**Financial Highlights table**")
                render_financial_highlights_table(
                    financial_highlights_table(cohort_rows, companies, periods[-1],
                                               include_source_comparatives=not preview), periods[-1],
                    tracked_company=tracked_company,
                )
                st.caption("Percentages are rounded to whole numbers. Grey cells mean a matching source input is unavailable.")
                if not preview and "Sun Life Hong Kong" in companies and periods[-1].startswith("2025"):
                    st.caption("Sun Life Hong Kong year-on-year figures use unaudited 2024 company comparatives in its 2025 filing; 2024 consolidated figures are excluded from this calculation.")
                if not preview and "YF Life" in companies:
                    st.caption("YF Life CSM amortization combines the fair-value-transition and other-contract CSM release lines in the insurance note.")
        elif module.module_id == "six_dimensional_charts":
            for group_number, (group_title, group_labels) in enumerate(PERFORMANCE_RATIO_PAGE_GROUPS, 1):
                with st.container(key=f"report_figure_six_dimensional_charts_group_{group_number}"):
                    st.markdown(f"#### {module.title}")
                    st.markdown(f"**{group_title}**")
                    chart, _gaps, _values = financial_performance_peer_dots(
                        data, list(group_labels), companies=companies,
                        periods=periods, transparent=transparent,
                    )
                    if chart is not None:
                        with st.container(horizontal_alignment="center", key=f"performance_ratio_chart_group_{group_number}"):
                            _show_chart(chart, width="content")
                    else:
                        st.caption("Missing inputs · Matching reviewed ratio components are unavailable.")
                    if group_number == 2:
                        st.caption("Hover for exact values. Ratios with missing inputs are omitted.")
                        if module.note:
                            st.caption(module.note)
            yield_chart, _gaps, _values = financial_performance_peer_dots(
                data, ["Investment yield"], companies=companies,
                periods=periods, transparent=transparent,
            )
            if yield_chart is not None:
                with st.container(key="report_figure_six_dimensional_charts_yield"):
                    st.markdown(f"#### {module.title} · Investment yield")
                    with st.container(horizontal_alignment="center", key="performance_ratio_chart_yield"):
                        _show_chart(yield_chart, width="content")
                    st.caption("Investment yield uses each insurer's disclosed rate; compare definitions before ranking insurers.")
        elif module.module_id in RATIO_MODULE_LABELS and module.module_id not in COMPANY_YEAR_COMPARISON_IDS:
            chart, _gaps = peer_ratio_module_panels(
                data, list(RATIO_MODULE_LABELS[module.module_id]), companies=companies,
                periods=periods,
                show_labels=show_labels and module.module_id != "six_dimensional_charts",
                decimals=decimals,
                transparent=transparent,
                color_by_period=module.module_id in YEAR_COLORED_MODULE_IDS,
            )
            if chart is not None:
                _show_chart(chart)
            else:
                st.caption("Missing inputs · Matching reviewed ratio components are unavailable for these insurers and periods.")
        elif module.module_id == "discount_rate":
            render_discount_rate_table(discount_rate_summary(data, companies, periods),
                                       tracked_company=tracked_company)
            st.caption("Each range spans the disclosed 1Y, 5Y, 10Y, 15Y and 20Y spot rates. "
                       "Currencies and risk-free versus illiquidity-premium assumptions are kept separate.")
        elif module.module_id == "confidence_level":
            cells = data[data["Metric code"].isin(module.metrics)]
            if not cells.empty:
                columns = ["Company", "Period end", "Metric", "Value (millions)", "Currency"]
                if display_mode == "HKD converted":
                    columns.append("HKD value (millions)")
                render_report_table(cells[[*columns, "PDF page"]],
                                    tracked_company=tracked_company)
        elif module.module_id == "csm_maturity_table":
            maturity = {
                kind: csm_maturity_lines(
                    plot_data, kind=kind, companies=companies, transparent=transparent,
                    tracked_company=tracked_company,
                )
                for kind in ("Insurance", "Reinsurance")
            }
            available = [kind for kind, (chart, _) in maturity.items() if chart is not None]
            for kind in ("Insurance", "Reinsurance"):
                chart, missing = maturity[kind]
                if chart is not None:
                    suffix = "_following" if kind != available[0] else ""
                    with st.container(key=f"report_figure_{module.module_id}_{kind.lower()}{suffix}"):
                        if kind == available[0]:
                            st.markdown(f"#### {module.title}")
                        st.markdown(f"**{kind} CSM**")
                        _show_chart(chart)
                        if kind == available[-1]:
                            st.caption(f"Latest available year shown: {max(plot_data['Period end'].astype(str))[:4]}YE. "
                                       "Lines show cumulative share through 1, 5 and 10 years where disclosed. "
                                       "A missing first-five-years split is derived from closing CSM and later buckets; "
                                       "the over-10-year bucket remains in the denominator and hover details.")
                            if module.note:
                                st.caption(module.note)
                        if missing:
                            st.caption(f"{kind} CSM · Matching maturity buckets and closing CSM unavailable for: "
                                       + ", ".join(missing) + ". Their disclosed cells remain in the table.")
                elif missing:
                    st.caption(f"{kind} CSM · Matching maturity buckets and closing CSM unavailable for: "
                               + ", ".join(missing) + ". Their disclosed cells remain in the table.")
            if not available:
                st.markdown(f"#### {module.title}")
        elif module.module_id in {"comp_1", "comp_2"}:
            is_method_split = module.module_id == "comp_1"
            chart, excluded = peer_revenue_stack_panels(
                data, list(module.metrics), companies=companies, periods=periods,
                denominator_code=None if is_method_split else "REV_NONPAA_TOTAL",
                require_all=is_method_split, display_mode=display_mode,
                unit=unit, transparent=transparent,
            )
            if excluded:
                st.caption("USD amount panels with unavailable year-end rates: " + ", ".join(excluded))
            if chart is not None:
                _show_chart(chart)
                st.caption(
                    "Percentage labels use each insurer's PAA + non-PAA revenue total. Hover for amounts and source pages."
                    if is_method_split else
                    "Percentage labels use each insurer's reported non-PAA revenue. Negative components extend below zero; hover for signed amounts and source pages."
                )
            else:
                st.caption("Missing inputs · Matching revenue components and totals are unavailable.")
        elif module.module_id in COMPANY_YEAR_COMPARISON_IDS:
            if module.module_id == "exp_total":
                st.caption("Expense magnitude is shown as a positive amount; the source statement reports it as a deduction. Hover for the signed amount.")
            comparison_labels, comparison_font_size, comparison_bar_width = show_labels, 11, 36
            if not all_mode:
                label_column, size_column, width_column = st.columns(3)
                with label_column:
                    comparison_labels = st.toggle(
                        "Show labels", value=show_labels,
                        key=f"step6_{module.module_id}_comparison_labels",
                    )
                with size_column:
                    comparison_font_size = st.slider(
                        "Label size", 8, 16, 11,
                        key=f"step6_{module.module_id}_comparison_font_size",
                    )
                with width_column:
                    comparison_bar_width = st.slider(
                        "Bar width", 18, 52, 36,
                        key=f"step6_{module.module_id}_comparison_bar_width",
                    )
            chart, excluded, summary = company_year_comparison_bars(
                data, list(module.metrics), companies=companies, periods=periods,
                display_mode=display_mode, unit=unit, show_labels=comparison_labels,
                decimals=decimals, transparent=transparent,
                label_font_size=comparison_font_size, bar_width=comparison_bar_width,
                axis_label_padding=30 if module.module_id == "exp_total" else 10,
                expense_mode="magnitude" if module.module_id == "exp_total" else None,
                reported_labels=(NET_RESULT_REPORTED_LABELS
                                 if module.module_id == "inv_profit" else None),
                ratio_label=(RATIO_MODULE_LABELS[module.module_id][0]
                             if module.module_id in RATIO_MODULE_LABELS else None),
            )
            if excluded:
                st.caption(
                    ("Unavailable matching ratio inputs: " if module.module_id in RATIO_MODULE_LABELS
                     else "USD amounts with unavailable year-end rates: ") + ", ".join(excluded)
                )
            if chart is not None:
                if summary:
                    st.caption(summary)
                _show_chart(chart)
            else:
                st.caption("Missing inputs · No matching reviewed values are available for these indicators and periods.")
        elif module.module_id == "tax_profit":
            st.caption("Profit for the year = profit before tax + income tax expense (recorded as a negative amount). Effective tax rate = −income tax expense / profit before tax, where pre-tax profit is positive.")
            chart, excluded = tax_profit_bars(
                plot_data, companies=companies, periods=plot_periods,
                display_mode=display_mode, unit=unit,
                show_labels=show_labels, decimals=decimals, transparent=transparent,
            )
            if excluded:
                st.caption("USD amounts with unavailable year-end rates: " + ", ".join(excluded))
            if chart is not None:
                with st.container(horizontal_alignment="center", key="tax_profit_chart"):
                    _show_chart(chart, width="content")
            else:
                st.caption("Missing inputs · No matching reviewed pre-tax profit or profit values are available.")
        else:
            stacked = module.module_id in STACKED_AMOUNT_MODULE_IDS
            if module.module_id == "exp_1":
                st.caption("Selected items from insurance expense notes, shown as amounts: positive values increase expense; negative values reduce it. Disclosures differ by insurer and are not a complete breakdown, so percentages and totals are omitted. Hover for the PDF page, source line and, for converted FWD values, original USD amount.")
            chart, excluded = peer_group_panels(
                plot_data, list(stacked_component_metrics(module) if stacked else module.metrics),
                companies=companies, periods=plot_periods,
                display_mode=display_mode, unit=unit,
                show_labels=(show_labels and module.module_id not in MOVEMENT_MODULE_IDS
                             and module.module_id not in HOVER_ONLY_LABEL_MODULE_IDS),
                decimals=decimals, transparent=transparent,
                color_by_period=module.module_id in YEAR_COLORED_MODULE_IDS,
                stacked=stacked,
                expense_mode="contribution" if module.module_id == "exp_1" else None,
                reported_labels=(NET_RESULT_REPORTED_LABELS
                                 if module.module_id == "inv_profit" else None),
                display_label=("Investment return" if module.module_id == "inv_return" else
                               "Net investment financial result" if module.module_id == "inv_profit" else None),
                alternative_metric_labels=module.module_id == "inv_return",
            )
            if excluded:
                st.caption("USD amount panels with unavailable year-end rates: " + ", ".join(excluded))
            if chart is not None:
                _show_chart(chart)
                if module.module_id in LATEST_YEAR_CHART_IDS:
                    st.caption(f"Latest available year shown: {max(plot_data['Period end'].astype(str))[:4]}YE.")
                if stacked:
                    st.caption("Stacks contain disclosed component lines only; missing components are not inferred.")
                if module.module_id in STACKED_AMOUNT_TOTAL_CODES:
                    st.caption("Reported totals are omitted from the stack to avoid double counting; they remain in Underlying cells.")
            else:
                st.caption("Missing inputs · No matching reviewed values are available for these indicators and periods.")
        if module.module_id not in {"csm_maturity_table", "six_dimensional_charts"}:
            missing = missing_metrics(plot_data, module)
            if missing and len(missing) < len(module.metrics):
                st.caption(f"Partially disclosed · {len(missing)} of {len(module.metrics)} indicators have no reviewed cells in this selection.")
            if module.note:
                st.caption(module.note)
    if module.module_id == "inv_profit":
        bridge = investment_result_reconciliation(rows)
        if not bridge.empty:
            with st.container(key="report_table_inv_profit"):
                st.markdown("**Profit-or-loss reconciliation**")
                render_report_table(bridge, tracked_company=tracked_company)
                st.caption("Original statement currencies, millions. The investment-contract liability movement "
                           "is calculated from the reported lines; it matches the separately disclosed FWD and YF line. "
                           "Sun Life has no such movement in this subtotal.")


for section, section_items in groupby(visible_modules, key=lambda item: item.section):
    with st.container(key=f"report_section_heading_{slug(section)}"):
        st.header(section, anchor=slug(section))
    for subsection, subsection_items in groupby(section_items, key=lambda item: item.subsection):
        if subsection != "All":
            with st.container(key=f"report_subsection_heading_{slug(section + ' ' + subsection)}"):
                st.subheader(subsection, anchor=slug(section + " " + subsection))
        for module in subsection_items:
            with st.container(key=f"report_chart_{module.module_id}"):
                _render_module(module)

with st.container(key="source_trace"):
    st.subheader("Underlying cells", anchor="underlying-cells")
    st.dataframe(
        rows[["Company", "Scope", "Currency", "Metric", "Period end", "Original value", "Source unit",
              "Value (millions)", "PDF page", "Audit status", "Review status"]],
        hide_index=True,
        column_config={"Value (millions)": st.column_config.NumberColumn(format="%.2f")},
    )
    if not preview:
        st.download_button(
            "Download reviewed peer cells", rows.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"HK_IFRS17_peer_{periods[-1]}.csv", mime="text/csv", icon=":material/download:",
        )
if full_report:
    back_cover()
