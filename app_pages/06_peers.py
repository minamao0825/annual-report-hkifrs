"""Responsive, source-aware small multiples for peer comparison."""

from __future__ import annotations

from itertools import groupby

import pandas as pd
import streamlit as st

from hkifrs17.charts import (company_year_comparison_bars, csm_maturity_lines, csm_ratio_trend_chart, frame_peer_company_panels, peer_group_panels, peer_investment_note_panels,
                            peer_ratio_module_panels, peer_revenue_stack_panels, peer_service_result_panels, tax_profit_bars)
from hkifrs17.appendix_tables import (
    insurance_service_appendix_tables, new_business_appendix_tables,
)
from hkifrs17.csm_waterfall import (
    csm_pre_release_combined_chart, csm_pre_release_rows, csm_rollforward_table,
    csm_waterfall_chart, csm_waterfall_notes, csm_waterfall_rows,
)
from hkifrs17.csm_transition import csm_transition_chart, csm_transition_rows
from hkifrs17.data import standardize_hkd
from hkifrs17.demo import demo_records
from hkifrs17.external import load_analysis_records
from hkifrs17.equity_waterfall import (
    equity_movement_table, equity_waterfall_chart, equity_waterfall_notes,
    equity_waterfall_rows,
)
from hkifrs17.financial_investments import (
    financial_investment_chart, financial_investment_notes, financial_investment_rows,
)
from hkifrs17.fx import year_end_usd_hkd
from hkifrs17.highlights import financial_highlights_table
from hkifrs17.investment_note import (
    NET_FINANCE_FORMULA, NET_INVESTMENT_FORMULA,
    investment_note_captions, investment_note_rows, net_investment_explanations,
)
from hkifrs17.new_business_ratios import (
    IFRS_MARGIN_EXPLANATION, RATIO_EXPLANATION, RATIO_TITLES,
    new_business_ifrs_margin_chart, new_business_ifrs_margin_rows,
    new_business_ratio_chart, new_business_ratio_rows,
)
from hkifrs17.oci_analysis import (
    oci_comparison_chart, oci_comparison_notes, oci_comparison_rows,
    oci_comparison_wide_table,
)
from hkifrs17.oci_waterfall import (
    oci_waterfall_chart, oci_waterfall_key, oci_waterfall_rows,
)
from hkifrs17.report_modules import (
    COMPANY_YEAR_COMPARISON_IDS, HOVER_ONLY_LABEL_MODULE_IDS,
    LATEST_YEAR_CHART_IDS,
    MOVEMENT_MODULE_IDS, RATIO_MODULE_LABELS, REPORT_MODULES,
    NET_RESULT_REPORTED_LABELS,
    STACKED_AMOUNT_MODULE_IDS, STACKED_AMOUNT_TOTAL_CODES,
    YEAR_COLORED_MODULE_IDS, discount_rate_summary,
    confidence_level_summary,
    financial_performance_ratio_table,
    stacked_component_metrics,
    missing_metrics, module_company_disclosure_notes, module_rows, movement_chart_rows, report_modules_for_rows,
)
from hkifrs17.report_notes import combine_company_notes, combine_year_notes
from hkifrs17.report_ui import (
    ALL_IN_SELECTION, back_cover, cover, print_controls, render_financial_highlights_table,
    render_csm_rollforward_table, render_discount_rate_table, render_confidence_level_table,
    render_financial_performance_peer_tables,
    render_equity_movement_table, render_report_table, render_oci_comparison_table,
    render_oci_waterfall_key,
    render_appendix_year_tables, sidebar_report_navigation, slug,
)
from hkifrs17.service_result import service_result_component_rows, service_result_notes


with st.container(key="report_screen_controls"):
    st.title("Peer comparison")
    st.caption("Step 6 · Compare reviewed insurer disclosures across selected periods and chart modules.")
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
        period_options = sorted(cohort_rows["Period end"].astype(str).unique())
        second = st.columns([2, 2, 2])
        with second[0]:
            companies = st.multiselect("Displayed insurers", company_options, default=company_options)
        with second[1]:
            periods = st.multiselect("Comparison periods", period_options, default=period_options)
        with second[2]:
            tracking_options = [None, *companies]
            if ("step6_tracked_company" not in st.session_state or
                    st.session_state["step6_tracked_company"] not in tracking_options):
                st.session_state["step6_tracked_company"] = None
            tracked_company = st.selectbox(
                "Tracked insurer", tracking_options,
                format_func=lambda value: "None" if value is None else value,
                key="step6_tracked_company",
            )
        if {"Sun Life Hong Kong", "Sun Life Hong Kong (Consolidated)"}.issubset(companies):
            st.caption("Sun Life 2024 consolidated and 2025 company figures are separate chart identities because their reporting scopes differ.")

        third = st.columns([1, 1, 1])
        with third[0]:
            display_mode = st.selectbox("Amount currency", ["HKD converted", "Native currencies"])
        with third[1]:
            unit = st.selectbox("Display unit", ["millions", "billions"])
        with third[2]:
            decimals = st.selectbox("Value label decimal places", [0, 1, 2], index=0)
        show_labels = True
        transparent = st.toggle("Transparent chart background", value=True)
        st.caption("Chart type, series colors and layout follow the selected chart module.")

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
    if display_mode == "Native currencies" and coverage["Currency"].nunique() > 1:
        st.caption("Amount panels show each insurer's original currency with independent scales. Select HKD converted for absolute peer comparisons.")
    if cohort == "06-30":
        st.caption("June and December financial years stay in separate cohorts.")


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
        if module.module_id not in {"csm_maturity_table", "summary_table", "six_dimensional_charts", "oci_deep", "csm_comp_lat"}:
            appendix_prefix = ('<span class="appendix-print-prefix">Appendix-</span>'
                               if module.module_id in {"report_detail", "nbv_table"} else "")
            st.markdown(f"#### {appendix_prefix}{module.title}",
                        unsafe_allow_html=bool(appendix_prefix))
            if module.module_id == "csm_ratio":
                st.caption("Formula: |closing non-PAA insurance CSM| / |closing non-PAA present value of future cash flows (PVFCF) + closing non-PAA risk adjustment (RA)| × 100%. All three inputs use the same filing and note page. The denominator is matching fulfilment cash flows, not BEL. Each annual mean is the unweighted average of the displayed insurers with available ratios; check the reporting scope before comparing companies.")
            if module.module_id == "csm_ratio_trend":
                st.caption("CSM amortization ratio = |CSM released for services| / "
                           "(|closing CSM| + |CSM released for services|) × 100%. "
                           "CSM replenishment ratio = |new-business CSM| / |CSM released for services| × 100%. "
                           "The dashed 100% line equals 1×: above it, new business exceeds the year's release. "
                           "The two panels have separate percentage axes, and point labels use two decimal places. "
                           "Other movements also affect closing CSM.")
            if module.module_id == "inv_return":
                if "Sun Life Hong Kong" in companies:
                    st.caption("P&L investment return excludes OCI; Sun Life Hong Kong uses net investment income, including investment-contract liability movements.")
                else:
                    st.caption("P&L investment return excludes OCI.")
            elif module.module_id in {"inv_return_components", "uw_profit", "inv_profit", "inv_profit_components"}:
                st.caption("Profit or loss (P&L) only; amounts recognised in OCI are excluded.")
            if module.module_id == "uw_profit":
                st.caption(NET_FINANCE_FORMULA)
            elif module.module_id == "inv_profit":
                st.caption(NET_INVESTMENT_FORMULA)
                for note in combine_company_notes(net_investment_explanations(companies), companies):
                    st.caption(note)
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
                    financial_highlights_table(cohort_rows, companies, max(periods),
                                               include_source_comparatives=not preview), max(periods),
                    tracked_company=tracked_company,
                )
                if not preview and "Sun Life Hong Kong" in companies and periods[-1].startswith("2025"):
                    st.caption("Sun Life Hong Kong year-on-year figures use unaudited 2024 company comparatives in its 2025 filing; 2024 consolidated figures are excluded from this calculation.")
                if not preview and "YF Life" in companies:
                    st.caption("YF Life CSM amortization combines the fair-value-transition and other-contract CSM release lines in the insurance note.")
        elif module.module_id == "report_detail":
            tables = insurance_service_appendix_tables(
                rows, companies, periods, display_mode=display_mode,
                unit=unit, decimals=decimals,
            )
            render_appendix_year_tables(
                tables, tracked_company=tracked_company,
                unit_label=(f"HKD {unit}" if display_mode == "HKD converted"
                            else f"native currencies · {unit}"),
            )
            st.caption("Amounts follow the selected currency and unit. † Calculated from "
                       "matching reported lines. Not disclosed means no reviewed line at "
                       "that method scope.")
            if "YF Life" in companies:
                st.caption("‡ All-method expense items from the liability carrying-amount "
                           "movement are sign-adjusted to the profit-or-loss expense basis. "
                           "Separate non-PAA and PAA expense totals are not disclosed.")
        elif module.module_id == "nbv_table":
            tables = new_business_appendix_tables(
                cohort_rows, companies, periods, display_mode=display_mode,
                unit=unit, decimals=decimals,
            )
            render_appendix_year_tables(
                tables, tracked_company=tracked_company,
                unit_label=(f"HKD {unit}" if display_mode == "HKD converted"
                            else f"native currencies · {unit}"),
            )
            st.caption("† Analytical measure. New business IFRS profit margin = "
                       "(new profitable contract CSM − initial loss component) / total PV of "
                       "new-business cash inflows. CSM replenishment = |new-business CSM| / "
                       "|CSM released|. The initial loss is shown as a deduction; reinsurance "
                       "is excluded. Ratios use source-currency values, so FX conversion "
                       "does not affect them. Growth needs a matching prior-year filing.")
        elif module.module_id == "oci_deep":
            analysis = oci_comparison_rows(data)
            chart = oci_comparison_chart(
                analysis, companies, periods, transparent=transparent,
            )
            with st.container(key="report_figure_oci_deep_chart"):
                st.markdown(f"#### {module.title}")
                if chart is not None:
                    _show_chart(chart)
                else:
                    st.caption("No reviewed asset-side or insurance-finance OCI amount is available for this selection.")
            with st.container(key="report_table_oci_deep"):
                st.markdown("**Year-end FVOCI balance and annual OCI amounts**")
                render_oci_comparison_table(
                    oci_comparison_wide_table(analysis, companies, periods),
                    tracked_company=tracked_company,
                )
                for note in combine_company_notes(
                    oci_comparison_notes(analysis, companies, periods, include_scale_note=False),
                    companies,
                ):
                    st.caption(note)
        elif module.module_id == "six_dimensional_charts":
            with st.container(key="report_table_six_dimensional_charts"):
                st.markdown(f"#### {module.title}")
                render_financial_performance_peer_tables(
                    financial_performance_ratio_table(data, companies, periods),
                    tracked_company=tracked_company,
                )
                st.caption("Percentages are shown to two decimal places. "
                           "Grey cells mean matching inputs are unavailable.")
                if module.note:
                    st.caption(module.note)
        elif module.module_id == "oci_year_lat":
            bridge, issues = oci_waterfall_rows(plot_data, companies, plot_periods)
            chart, excluded = oci_waterfall_chart(
                bridge, companies, display_mode=display_mode, unit=unit,
                decimals=decimals, transparent=transparent, height=265,
            )
            if chart is not None:
                _show_chart(chart)
                render_oci_waterfall_key(oci_waterfall_key(bridge, companies))
            else:
                st.caption("Missing inputs · A reconciled OCI bridge is unavailable for this selection.")
            for issue in [*issues, *excluded]:
                st.caption(issue)
        elif module.module_id == "csm_table":
            bridge, issues = csm_waterfall_rows(plot_data, companies, plot_periods)
            chart, excluded = csm_waterfall_chart(
                bridge, companies, display_mode=display_mode, unit=unit,
                decimals=decimals, transparent=transparent, show_labels=show_labels,
            )
            if chart is not None:
                _show_chart(chart)
                for note in combine_company_notes(csm_waterfall_notes(bridge), companies):
                    st.caption(note)
            else:
                st.caption("Missing inputs · A reconciled insurance CSM bridge is unavailable for this selection.")
            for issue in [*issues, *excluded]:
                st.caption(issue)
        elif module.module_id == "equity_balance_comparison":
            chart, excluded, summary = company_year_comparison_bars(
                data, ["EQUITY"], companies=companies, periods=periods,
                display_mode=display_mode, unit=unit,
                tracked_company=tracked_company, show_labels=show_labels,
                decimals=decimals, transparent=transparent,
            )
            if chart is not None:
                _show_chart(chart)
                if summary:
                    st.caption(summary)
                st.caption("Net assets = reported closing equity. Growth (%) = "
                           "(current year-end net assets − prior year-end net assets) "
                           "/ |prior year-end net assets| × 100%, using the same reporting scope. "
                           "In HKD converted mode, growth includes the USD/HKD conversion effect.")
            else:
                st.caption("Missing inputs · A matching two-year net assets comparison is unavailable.")
            if excluded:
                st.caption("USD amount panels with unavailable year-end rates: " + ", ".join(excluded))
        elif module.module_id == "equity_trend":
            bridge, issues = equity_waterfall_rows(plot_data, companies, plot_periods)
            chart, excluded = equity_waterfall_chart(
                bridge, companies, display_mode=display_mode, unit=unit,
                decimals=decimals, transparent=transparent, show_labels=show_labels,
                height=295,
            )
            if chart is not None:
                _show_chart(chart)
                notes = combine_company_notes(equity_waterfall_notes(bridge), companies)
                if notes:
                    st.caption(" ".join(notes))
            else:
                st.caption("Missing inputs · A reconciled equity bridge is unavailable for this selection.")
            for issue in [*issues, *excluded]:
                st.caption(issue)
        elif module.module_id == "equity_movement_table":
            table, issues = equity_movement_table(
                plot_data, companies, plot_periods,
                display_mode=display_mode, unit=unit, decimals=decimals,
            )
            if not table.empty:
                render_equity_movement_table(
                    table, tracked_company=tracked_company,
                    period_label=f"{max(plot_periods)[:4]}YE", unit=unit,
                )
                st.caption("Net assets movement = closing equity − opening equity. "
                           "Remainder* = net assets movement − the sum of displayed profit, OCI and "
                           "disclosed equity movements; it is calculated, not separately disclosed. "
                           "Not disclosed means a reviewed line is unavailable, not zero. "
                           "Bond issuance and subsidiary consolidation are not separately extracted equity lines.")
            else:
                st.caption("Missing inputs · No equity movement detail is available for this selection.")
            for issue in issues:
                st.caption(issue)
        elif module.module_id == "csm_rollforward_table":
            table, issues = csm_rollforward_table(
                plot_data, companies, plot_periods, display_mode=display_mode, unit=unit,
            )
            if not table.empty:
                render_csm_rollforward_table(table, tracked_company=tracked_company)
                st.caption("Other movements* = closing CSM − opening CSM − new business CSM "
                           "− CSM finance change − CSM estimate change − CSM release. "
                           "This is a calculated reconciliation remainder, not a separately disclosed item. "
                           "Missing inputs are shown as Not disclosed; no remainder is calculated for an incomplete bridge.")
            else:
                st.caption("Missing inputs · No insurance CSM roll-forward data are available for this selection.")
            for issue in issues:
                st.caption(issue)
        elif module.module_id == "csm_trans":
            transition, issues = csm_transition_rows(
                data, companies, periods, display_mode=display_mode, unit=unit,
            )
            chart = csm_transition_chart(
                transition, companies, transparent=transparent, show_labels=show_labels,
            )
            if chart is not None:
                _show_chart(chart)
            else:
                st.caption("Missing inputs · No insurance CSM transition-category data are available.")
            for issue in combine_year_notes(issues, companies):
                st.caption(issue)
        elif module.module_id == "csm_comp_lat":
            current_year = max(plot_data["Period end"].astype(str).str[:4])
            comparative_year = str(int(current_year) - 1)
            composition_note = (
                "Percentage labels = |item| / (|new business| + |estimate change| + |finance change|) × 100%. "
                "Negative items extend below zero. Opening CSM, CSM release and other movements are excluded; "
                "these percentages are not shares of closing CSM."
            )
            for year, label in ((current_year, "Current year"),
                                (comparative_year, "Comparative year")):
                container_key = ("csm_comp_lat_current" if year == current_year
                                 else "csm_comp_lat_comparative")
                with st.container(key=container_key):
                    if year == current_year:
                        st.markdown(f"#### {module.title}")
                    st.markdown(f"**{year}YE · {label}**")
                    year_rows = rows.loc[rows["Period end"].astype(str).str.startswith(year)]
                    if year_rows.empty:
                        st.caption(f"{year}YE · No selected source data are available.")
                        if year == comparative_year:
                            st.caption(composition_note)
                        continue
                    year_periods = sorted(year_rows["Period end"].astype(str).unique())
                    movements, issues = csm_pre_release_rows(year_rows, companies, year_periods)
                    chart, excluded, shown_currency = csm_pre_release_combined_chart(
                        movements, companies, display_mode=display_mode, unit=unit,
                        tracked_company=tracked_company, transparent=transparent,
                        show_labels=show_labels,
                    )
                    if chart is not None:
                        st.altair_chart(chart, width="stretch")
                        if (display_mode == "Native currencies" and shown_currency == "HKD"
                                and "USD" in set(movements["Currency"])):
                            st.caption("Mixed source currencies are converted to HKD for this shared amount axis; "
                                       "original amounts and currencies remain in the hover details.")
                    else:
                        st.caption(f"{year}YE · A complete three-item pre-release CSM mix is unavailable.")
                    for issue in [*issues, *excluded]:
                        st.caption(issue)
                    if year == comparative_year:
                        st.caption(composition_note)
        elif module.module_id == "csm_ratio_trend":
            chart, gaps, _ = csm_ratio_trend_chart(
                data, companies, periods, tracked_company=tracked_company,
                decimals=2, transparent=transparent, show_labels=show_labels,
            )
            if chart is not None:
                st.altair_chart(chart, width="stretch")
            else:
                st.caption("Missing inputs · Matching reviewed CSM ratios are unavailable for these insurers and periods.")
            for _, gap in gaps.iterrows():
                st.caption(f"{gap['Company']} {gap['Period'][:4]}YE · {gap['Ratio']}: matching inputs unavailable.")
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
            summary = discount_rate_summary(data, companies, periods)
            render_discount_rate_table(summary, tracked_company=tracked_company)
            displayed = summary["Company"].astype(str).tolist() if not summary.empty else []
            for insurer in companies:
                if not any(label == insurer or label.startswith(f"{insurer} (")
                           for label in displayed):
                    st.caption(f"{insurer}: no reviewed discount-rate tenor disclosure is available.")
        elif module.module_id == "confidence_level":
            render_confidence_level_table(
                confidence_level_summary(data, companies, periods),
                tracked_company=tracked_company,
            )
        elif module.module_id == "csm_maturity_table":
            chart, missing = csm_maturity_lines(
                plot_data, kind="Insurance", companies=companies,
                transparent=transparent, tracked_company=tracked_company,
            )
            with st.container(key=f"report_figure_{module.module_id}_insurance"):
                st.markdown(f"#### {module.title}")
                if chart is not None:
                    _show_chart(chart)
                    st.caption(f"Latest available year shown: {max(plot_data['Period end'].astype(str))[:4]}YE. "
                               "Lines show cumulative share through 1, 5 and 10 years where disclosed. "
                               "A missing first-five-years split is derived from closing CSM and later buckets; "
                               "the over-10-year bucket remains in the denominator and hover details.")
                if module.note:
                    st.caption(module.note)
                for note in combine_company_notes(
                    module_company_disclosure_notes(module.module_id, companies), companies,
                ):
                    st.caption(note)
                if missing:
                    st.caption("Insurance CSM · Matching maturity buckets and closing CSM unavailable for: "
                               + ", ".join(missing) + ". Their disclosed cells remain in the table.")
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
            else:
                st.caption("Missing inputs · Matching revenue components and totals are unavailable.")
        elif module.module_id == "nb_value_ratios":
            st.caption(RATIO_EXPLANATION)
            ratio_rows, gaps = new_business_ratio_rows(data, companies, periods)
            for ratio in RATIO_TITLES:
                chart, _mean = new_business_ratio_chart(
                    ratio_rows, ratio, companies=companies, periods=periods,
                    tracked_company=tracked_company, decimals=decimals,
                    show_labels=show_labels, transparent=transparent,
                    height=115,
                )
                if chart is not None:
                    with st.container(key=f"nb_value_ratio_{slug(ratio)}"):
                        st.markdown(f"**{ratio}**")
                        st.altair_chart(chart, width="stretch")
            if ratio_rows.empty:
                st.caption("Missing inputs · Matching new-business ratios are unavailable.")
            for gap in gaps:
                st.caption(gap)
        elif module.module_id in COMPANY_YEAR_COMPARISON_IDS - {"inv_return", "inv_profit"}:
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
                display_mode=display_mode, unit=unit,
                tracked_company=tracked_company, show_labels=comparison_labels,
                decimals=decimals, transparent=transparent,
                label_font_size=comparison_font_size, bar_width=comparison_bar_width,
                axis_label_padding=30 if module.module_id == "exp_total" else 10,
                expense_mode="magnitude" if module.module_id == "exp_total" else None,
                reported_labels=(NET_RESULT_REPORTED_LABELS
                                 if module.module_id == "inv_profit" else None),
                ratio_label=(RATIO_MODULE_LABELS[module.module_id][0]
                             if module.module_id in RATIO_MODULE_LABELS else None),
                yearly_mean_lines=module.module_id == "csm_ratio",
            )
            if excluded:
                st.caption(
                    ("Unavailable matching ratio inputs: " if module.module_id in RATIO_MODULE_LABELS
                     else "USD amounts with unavailable year-end rates: ") + ", ".join(excluded)
                )
            if chart is not None:
                if summary and module.module_id != "csm_ratio":
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
        elif module.module_id in {"prof_2025", "prof_2024"}:
            components = service_result_component_rows(plot_data)
            chart, excluded = peer_service_result_panels(
                components, companies=companies, periods=plot_periods,
                display_mode=display_mode, unit=unit, show_labels=show_labels,
                decimals=decimals, transparent=transparent,
            )
            if excluded:
                st.caption("USD amount panels with unavailable year-end rates: " + ", ".join(excluded))
            if chart is not None:
                _show_chart(chart)
                visible = components.loc[
                    components["Company"].isin(companies)
                    & components["Period"].isin(plot_periods)
                    & ~components["Company"].isin(excluded)
                ]
                for note in combine_company_notes(
                    service_result_notes(visible, include_overview=False), companies,
                ):
                    st.caption(note)
            else:
                st.caption("Missing inputs · A complete five-item bridge to the reported insurance service result is unavailable.")
        elif module.module_id in {"inv_return", "inv_return_components", "uw_profit", "inv_profit", "inv_profit_components"}:
            views = {
                "inv_return": (("return_pl_total", None),),
                "inv_return_components": (("return_pl_components", None),),
                "uw_profit": (("finance_pl_total", None),),
                "inv_profit": (("result_pl_total", None),),
                "inv_profit_components": (("result_pl_components", None),),
            }[module.module_id]
            first_rows = investment_note_rows(plot_data, views[0][0])
            for view, heading in views:
                note_rows = first_rows if view == views[0][0] else investment_note_rows(plot_data, view)
                chart, excluded = peer_investment_note_panels(
                    note_rows, companies=companies, periods=plot_periods,
                    display_mode=display_mode, unit=unit, show_labels=show_labels,
                    decimals=decimals, transparent=transparent,
                )
                if excluded:
                    st.caption("USD amount panels with unavailable year-end rates: " + ", ".join(excluded))
                if chart is not None:
                    if heading:
                        st.markdown(f"**{heading}**")
                    _show_chart(chart)
            visible = first_rows.loc[
                first_rows["Company"].isin(companies) & first_rows["Period"].isin(plot_periods)
            ]
            if visible.empty:
                st.caption("Missing inputs · A matching, reconciled P&L investment breakdown is unavailable.")
            else:
                if module.module_id != "inv_return":
                    for note in combine_company_notes(
                        investment_note_captions(visible), companies,
                    ):
                        st.caption(note)
        elif module.module_id == "asset_struct":
            components, issues = financial_investment_rows(plot_data, companies, plot_periods)
            chart, excluded = financial_investment_chart(
                components, companies, display_mode=display_mode, unit=unit,
                decimals=decimals, transparent=transparent,
            )
            if chart is not None:
                _show_chart(chart)
                for note in combine_company_notes(financial_investment_notes(components), companies):
                    st.caption(note)
            else:
                st.caption("Missing inputs · A complete, reconciled financial-investment breakdown is unavailable.")
            for issue in [*issues, *excluded]:
                st.caption(issue)
        elif module.module_id == "nb_struct":
            margin_rows, issues = new_business_ifrs_margin_rows(
                data, companies, plot_periods,
            )
            chart = new_business_ifrs_margin_chart(
                margin_rows, companies=companies, periods=plot_periods,
                tracked_company=tracked_company, decimals=2,
                show_labels=show_labels, transparent=transparent,
            )
            if chart is not None:
                with st.container(horizontal_alignment="center", key="nb_ifrs_margin_layout"):
                    with st.container(width=1050):
                        _show_chart(chart)
            else:
                st.caption("Missing inputs · A matched new-business IFRS profit margin is unavailable.")
            st.caption(IFRS_MARGIN_EXPLANATION)
            for issue in issues:
                st.caption(issue)
        else:
            stacked = module.module_id in STACKED_AMOUNT_MODULE_IDS
            if module.module_id == "nb_lost":
                st.caption("Initial-recognition presentation: CSM, risk adjustment, initial loss and PV of outflows are positive; PV of inflows is negative. Original filing signs remain in the source cells.")
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
                show_small_percent_labels=module.module_id == "exp_1",
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
                if stacked and module.module_id != "exp_1":
                    st.caption("Stacks contain disclosed component lines only; missing components are not inferred.")
                if module.module_id in STACKED_AMOUNT_TOTAL_CODES:
                    st.caption("Reported totals are omitted from the stack to avoid double counting; they remain in Underlying cells.")
            else:
                st.caption("Missing inputs · No matching reviewed values are available for these indicators and periods.")
        if module.module_id not in {"csm_maturity_table", "six_dimensional_charts"}:
            missing = missing_metrics(plot_data, module) if module.module_id not in {"oci_deep", "oci_year_lat", "asset_struct", "csm_trans"} else []
            if module.module_id not in {"discount_rate", "report_detail", "nbv_table", "equity_movement_table", "equity_trend"} and missing and len(missing) < len(module.metrics):
                st.caption(f"Partially disclosed · {len(missing)} of {len(module.metrics)} indicators have no reviewed cells in this selection.")
            if module.note and module.module_id not in {"oci_deep", "comp_2", "inv_return", "uw_profit", "inv_profit", "csm_ratio", "csm_ratio_trend", "asset_struct"}:
                st.caption(module.note)
            if module.module_id != "inv_return":
                for note in combine_company_notes(
                    module_company_disclosure_notes(module.module_id, companies), companies,
                ):
                    st.caption(note)
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
