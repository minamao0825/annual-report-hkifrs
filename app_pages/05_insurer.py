"""Single-insurer Step 7-aligned report with source-page drilldown."""

from __future__ import annotations

from itertools import groupby
from pathlib import Path

import pandas as pd
import streamlit as st

from hkifrs17.charts import (
    company_year_comparison_bars, csm_maturity_lines, csm_ratio_trend_chart,
    investment_note_period_bars, period_bars,
    ratio_module_period_bars, revenue_stack_bars, service_result_period_bars, tax_profit_bars,
)
from hkifrs17.appendix_tables import (
    insurance_service_appendix_tables, new_business_appendix_tables,
)
from hkifrs17.csm_waterfall import (
    csm_pre_release_combined_chart, csm_pre_release_rows, csm_rollforward_table,
    csm_waterfall_chart, csm_waterfall_notes, csm_waterfall_rows,
)
from hkifrs17.csm_transition import csm_transition_chart, csm_transition_rows
from hkifrs17.demo import demo_records
from hkifrs17.equity_waterfall import (
    equity_movement_table, equity_waterfall_chart, equity_waterfall_notes,
    equity_waterfall_rows,
)
from hkifrs17.external import load_analysis_records, save_external_workbook
from hkifrs17.financial_investments import (
    financial_investment_chart, financial_investment_notes, financial_investment_rows,
)
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
    oci_comparison_table,
)
from hkifrs17.oci_waterfall import (
    oci_waterfall_chart, oci_waterfall_notes, oci_waterfall_rows,
)
from hkifrs17.pdf import page_png
from hkifrs17.report import html_report
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
from hkifrs17.report_ui import (
    ALL_IN_SELECTION, back_cover, cover, print_controls, render_financial_highlights_table,
    render_csm_rollforward_table, render_discount_rate_table, render_confidence_level_table,
    render_financial_performance_table,
    render_equity_movement_table, render_report_table, render_appendix_year_tables,
    sidebar_report_navigation, slug,
)
from hkifrs17.service_result import service_result_component_rows, service_result_notes
from hkifrs17.storage import filing_by_id, pdf_path


with st.container(key="report_screen_controls"):
    st.title("Insurer explorer")
    st.caption("Step 5 · Source Step 7 indicators, adapted to Hong Kong disclosures. Chart colors and layout follow the selected module.")
    with st.expander("Upload reviewed Excel data for Steps 5 and 6", icon=":material/upload_file:"):
        st.caption("Use a standardized .xlsx workbook with a Records sheet and, where available, a Check plan sheet. The platform recalculates units and reconciliation results before adding the data to both report pages.")
        example_workbook = Path(__file__).resolve().parents[1] / "outputs" / "HKFRS17_Step5_6_current_data_upload.xlsx"
        if example_workbook.is_file():
            st.download_button("Download the current three-insurer 2024–2025 workbook", example_workbook.read_bytes(),
                               file_name=example_workbook.name,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               icon=":material/download:")
            st.caption("This saved workbook uses the earlier source-evidence layout. The six newer image-evidence fields remain blank on import; check the PDF page and source label before relying on a legacy cell.")
        external_file = st.file_uploader("Choose external workbook", type="xlsx", key="step5_external_workbook")
        if external_file is not None and st.button("Import verified data", type="primary", icon=":material/check:"):
            try:
                imported_count, import_checks = save_external_workbook(external_file.getvalue())
            except (ValueError, OSError) as exc:
                st.error(f"Import failed: {exc}")
            else:
                st.session_state["analysis_data_active"] = True
                st.session_state["insurer_primary"] = REPORT_MODULES[0].section
                st.session_state["insurer_secondary"] = "Profitability"
                st.session_state["insurer_chart"] = ALL_IN_SELECTION
                st.success(f"Imported {imported_count} verified source cells. They are now available in Steps 5 and 6.")
                st.dataframe(import_checks[["Company", "Period end", "Check", "Result", "Missing inputs", "Detail"]],
                             hide_index=True, width="stretch")

    saved_records = load_analysis_records()
    if not saved_records.empty and not st.session_state.get("analysis_data_active", False):
        st.caption(f"{len(saved_records)} saved verified source cells are available. Choose Use saved verified data to display them in this session.")
        if st.button("Use saved verified data", key="step5_use_saved_data"):
            st.session_state["analysis_data_active"] = True
            st.session_state["insurer_primary"] = REPORT_MODULES[0].section
            st.session_state["insurer_secondary"] = "Profitability"
            st.session_state["insurer_chart"] = ALL_IN_SELECTION
    active_records = (saved_records if st.session_state.get("analysis_data_active", False)
                      else saved_records.iloc[0:0].copy())
    preview = st.toggle(
        "Preview unpublished pilot transcriptions", value=False,
        help="Off by default. Enable only to inspect Pending sample values.",
    )
    records = demo_records() if preview else active_records
    if preview:
        st.warning("Demo preview · These page transcriptions are Pending and have not passed review or publication.")
    elif not active_records.empty:
        st.caption(f"Loaded {len(active_records)} verified source cells in this session.")
    if records.empty:
        st.info("No dataset is active in this session. Review and integrate a filing in Steps 1–4, import a verified workbook above, choose saved verified data, or explicitly enable the demo preview.")
        st.stop()

    companies = sorted(records["Company"].unique())
    with st.container(border=True):
        st.subheader("Choose insurer")
        selected_company = st.selectbox(
            "Insurer to display", companies,
            index=companies.index(st.session_state.get("step5_active_insurer"))
            if st.session_state.get("step5_active_insurer") in companies else 0,
        )
        if st.button("Display selected insurer", type="primary", icon=":material/monitoring:"):
            st.session_state["step5_active_insurer"] = selected_company
        company = st.session_state.get("step5_active_insurer", selected_company)
        if company not in companies:
            company = selected_company
            st.session_state["step5_active_insurer"] = company
        if company in {"Sun Life Hong Kong", "Sun Life Hong Kong (Consolidated)"} and {
            "Sun Life Hong Kong", "Sun Life Hong Kong (Consolidated)"
        }.issubset(companies):
            st.caption("Sun Life 2024 is consolidated; 2025 is company-only. Select them separately because the reporting scopes differ.")
        st.caption(f"Showing: {company}")
rows = records[records["Company"].eq(company)].copy()
period = max(rows["Period end"].astype(str))
filing = filing_by_id(str(rows.loc[rows["Period end"].astype(str).eq(period), "Document ID"].iloc[0]))
display_modules = tuple(
    module for module in report_modules_for_rows(rows)
    if module.section != "HKFRS 17 supplementary disclosures"
)
st.session_state.setdefault("insurer_secondary", "Profitability")
all_mode, visible_modules = sidebar_report_navigation(
    display_modules, key="insurer", heading="Insurer report navigation",
)
full_report = print_controls("insurer", all_mode=all_mode)
if full_report:
    cover("HK IFRS 17 · Insurer report", company, f"Financial year ended {period} · {filing['currency']}")
with st.container(key="report_screen_summary_top"):
    st.caption(f"{filing['legal_entity']} · {filing['scope']} · Year ended {period} · {filing['source_unit']}")
    st.caption("Charts follow the source annual-report Step 7 module order. Movement charts show the latest available year. Mainland-only measures are omitted.")


def _module_table(data: pd.DataFrame, codes: tuple[str, ...]) -> None:
    selected = data[data["Metric code"].isin(codes)].copy()
    if selected.empty:
        return
    table = selected[["Metric", "Period end", "Value (millions)", "Currency", "PDF page", "Source label"]]
    render_report_table(table.sort_values(["Metric", "Period end"]))


def _render_module(module) -> None:
    data = module_rows(rows, module)
    plot_data = movement_chart_rows(data, module)
    anchor = slug(module.module_id + " " + module.title)
    st.markdown(f'<div id="{anchor}"></div>', unsafe_allow_html=True)
    with st.container(key=f"report_visual_{module.module_id}"):
        if module.module_id not in {"csm_maturity_table", "summary_table", "six_dimensional_charts", "oci_deep"}:
            st.markdown(f"#### {module.title}")
            if module.module_id == "csm_ratio":
                st.caption("Formula: |closing non-PAA insurance CSM| / |closing non-PAA present value of future cash flows (PVFCF) + closing non-PAA risk adjustment (RA)| × 100%. All three inputs use the same filing and note page. The denominator is matching fulfilment cash flows, not BEL.")
            if module.module_id == "csm_ratio_trend":
                st.caption("CSM amortization ratio = |CSM released for services| / "
                           "(|closing CSM| + |CSM released for services|) × 100%. "
                           "CSM replenishment ratio = |new-business CSM| / |CSM released for services| × 100%. "
                           "The dashed 100% line equals 1×: above it, new business exceeds the year's release. "
                           "The two panels have separate percentage axes, and point labels use two decimal places. "
                           "Other movements also affect closing CSM.")
            if module.module_id in {"inv_return", "inv_return_components", "uw_profit", "inv_profit", "inv_profit_components"}:
                st.caption("Profit or loss (P&L) only; amounts recognised in OCI are excluded.")
            if module.module_id == "uw_profit":
                st.caption(NET_FINANCE_FORMULA)
            elif module.module_id == "inv_profit":
                st.caption(NET_INVESTMENT_FORMULA)
                for note in net_investment_explanations([company]):
                    st.caption(note)
        if module.module_id == "summary_table":
            chart = period_bars(data, ["TOTAL_LIABS", "EQUITY"], stacked=True)
            with st.container(key="report_figure_summary_table"):
                st.markdown(f"#### {module.title}")
                if chart is not None:
                    st.altair_chart(chart, width="stretch")
                st.caption("Balance-sheet composition · Total liabilities + equity = total assets. Hover for amounts.")
            with st.container(key="report_table_summary_table"):
                st.markdown("**Financial Highlights table**")
                render_financial_highlights_table(
                    financial_highlights_table(rows, [company], period,
                                               include_source_comparatives=not preview), period,
                )
                st.caption("Percentages are rounded to whole numbers. Grey cells mean a matching source input is unavailable.")
                if not preview and company == "Sun Life Hong Kong" and period.startswith("2025"):
                    st.caption("Year-on-year figures use unaudited 2024 company comparatives in the 2025 filing; 2024 consolidated figures are excluded from this calculation.")
                if not preview and company == "YF Life":
                    st.caption("YF Life CSM amortization combines the fair-value-transition and other-contract CSM release lines in the insurance note.")
        elif module.module_id == "report_detail":
            tables = insurance_service_appendix_tables(
                rows, [company], sorted(rows["Period end"].astype(str).unique()),
            )
            render_appendix_year_tables(tables, unit_label=f"{filing['currency']} millions")
            st.caption("Amounts use the filing currency in millions. † Calculated from matching "
                       "reported lines. Not disclosed means no reviewed line at that method scope.")
            if company == "YF Life":
                st.caption("‡ All-method expense items from the liability carrying-amount "
                           "movement are sign-adjusted to the profit-or-loss expense basis. "
                           "Separate non-PAA and PAA expense totals are not disclosed.")
        elif module.module_id == "nbv_table":
            tables = new_business_appendix_tables(
                rows, [company], sorted(rows["Period end"].astype(str).unique()),
            )
            render_appendix_year_tables(tables, unit_label=f"{filing['currency']} millions")
            st.caption("† Analytical measure. New business IFRS profit margin = "
                       "(new profitable contract CSM − initial loss component) / total PV of "
                       "new-business cash inflows. CSM replenishment = |new-business CSM| / "
                       "|CSM released|. The initial loss is shown as a deduction; reinsurance "
                       "is excluded. Growth needs a matching prior-year filing.")
        elif module.module_id == "oci_deep":
            analysis = oci_comparison_rows(data)
            selected_periods = sorted(rows["Period end"].astype(str).unique())
            chart = oci_comparison_chart(analysis, [company], selected_periods)
            with st.container(key="report_figure_oci_deep_chart"):
                st.markdown(f"#### {module.title}")
                if chart is not None:
                    st.altair_chart(chart, width="stretch")
                else:
                    st.caption("No reviewed asset-side or insurance-finance OCI amount is available for this selection.")
            with st.container(key="report_table_oci_deep"):
                st.markdown("**Year-end FVOCI balance and annual OCI amounts**")
                render_report_table(oci_comparison_table(analysis, [company], selected_periods))
                for note in oci_comparison_notes(analysis, [company], selected_periods):
                    st.caption(note)
        elif module.module_id == "six_dimensional_charts":
            with st.container(key="report_table_six_dimensional_charts"):
                st.markdown(f"#### {module.title}")
                render_financial_performance_table(financial_performance_ratio_table(
                    data, [company], sorted(data["Period end"].astype(str).unique()),
                ))
                st.caption("Percentages are shown to two decimal places. "
                           "Grey cells mean matching inputs are unavailable.")
                if module.note:
                    st.caption(module.note)
        elif module.module_id == "oci_year_lat":
            bridge, issues = oci_waterfall_rows(
                plot_data, [company], sorted(plot_data["Period end"].astype(str).unique()),
            )
            chart, excluded = oci_waterfall_chart(bridge, [company])
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                st.caption(f"Latest available year shown: {max(bridge['Year'])}YE.")
                for note in oci_waterfall_notes(bridge):
                    st.caption(note)
            else:
                st.caption("Missing inputs · A reconciled OCI bridge is unavailable for this selection.")
            for issue in [*issues, *excluded]:
                st.caption(issue)
        elif module.module_id == "csm_table":
            bridge, issues = csm_waterfall_rows(
                plot_data, [company], sorted(plot_data["Period end"].astype(str).unique()),
            )
            chart, excluded = csm_waterfall_chart(bridge, [company])
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                st.caption(f"Latest available year shown: {max(bridge['Year'])}YE.")
                for note in csm_waterfall_notes(bridge):
                    st.caption(note)
            else:
                st.caption("Missing inputs · A reconciled insurance CSM bridge is unavailable for this selection.")
            for issue in [*issues, *excluded]:
                st.caption(issue)
        elif module.module_id == "equity_balance_comparison":
            chart, excluded, summary = company_year_comparison_bars(
                data, ["EQUITY"], companies=[company],
                periods=sorted(data["Period end"].astype(str).unique()),
                display_mode="Native currencies", unit="millions",
            )
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                if summary:
                    st.caption(summary)
                st.caption("Net assets = reported closing equity. Growth (%) = "
                           "(current year-end net assets − prior year-end net assets) "
                           "/ |prior year-end net assets| × 100%, using the same reporting scope.")
            else:
                st.caption("Missing inputs · A matching two-year net assets comparison is unavailable.")
            for issue in excluded:
                st.caption(issue)
        elif module.module_id == "equity_trend":
            bridge, issues = equity_waterfall_rows(
                plot_data, [company], sorted(plot_data["Period end"].astype(str).unique()),
            )
            chart, excluded = equity_waterfall_chart(bridge, [company])
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                st.caption(f"Latest available year shown: {max(bridge['Year'])}YE.")
                for note in equity_waterfall_notes(bridge):
                    st.caption(note)
            else:
                st.caption("Missing inputs · A reconciled equity bridge is unavailable for this selection.")
            for issue in [*issues, *excluded]:
                st.caption(issue)
        elif module.module_id == "equity_movement_table":
            table, issues = equity_movement_table(data, [company], [period])
            if not table.empty:
                render_equity_movement_table(table)
                st.caption(f"{period[:4]}YE · Amounts in filing-currency millions. "
                           "Net assets movement = closing equity − opening equity. "
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
                plot_data, [company], sorted(plot_data["Period end"].astype(str).unique()),
            )
            if not table.empty:
                render_csm_rollforward_table(table)
                st.caption(f"Latest available year shown: {max(plot_data['Period end'].astype(str).str[:4])}YE · "
                           "amounts in millions, in the filing currency shown beside the insurer.")
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
                data, [company], sorted(data["Period end"].astype(str).unique()),
            )
            chart = csm_transition_chart(transition, [company])
            if chart is not None:
                st.altair_chart(chart, width="stretch")
            else:
                st.caption("Missing inputs · No insurance CSM transition-category data are available.")
            for issue in issues:
                st.caption(issue)
        elif module.module_id == "csm_comp_lat":
            current_year = max(plot_data["Period end"].astype(str).str[:4])
            comparative_year = str(int(current_year) - 1)
            for year, label in ((current_year, "Current year"),
                                (comparative_year, "Comparative year")):
                container_key = ("csm_comp_lat_current" if year == current_year
                                 else "csm_comp_lat_comparative")
                with st.container(key=container_key):
                    st.markdown(f"**{year}YE · {label}**")
                    year_rows = rows.loc[rows["Period end"].astype(str).str.startswith(year)]
                    if year_rows.empty:
                        st.caption(f"{year}YE · No source data are available for this insurer.")
                        continue
                    movements, issues = csm_pre_release_rows(
                        year_rows, [company], sorted(year_rows["Period end"].astype(str).unique()),
                    )
                    chart, excluded, shown_currency = csm_pre_release_combined_chart(
                        movements, [company],
                    )
                    if chart is not None:
                        st.altair_chart(chart, width="stretch")
                        st.caption(f"Shared amount axis: {shown_currency} millions.")
                    else:
                        st.caption(f"{year}YE · A complete three-item pre-release CSM mix is unavailable.")
                    for issue in [*issues, *excluded]:
                        st.caption(issue)
            st.caption("Column segments show signed new-business, estimate and finance CSM movements. "
                       "Percentage labels = |item| / (|new business| + |estimate change| + |finance change|) × 100%. "
                       "Negative items extend below zero. Opening CSM, CSM release and other movements are excluded; "
                       "these percentages are not shares of closing CSM.")
        elif module.module_id == "csm_ratio_trend":
            chart, gaps, _ = csm_ratio_trend_chart(
                data, [company], sorted(data["Period end"].astype(str).unique()),
            )
            if chart is not None:
                st.altair_chart(chart, width="stretch")
            else:
                st.caption("Missing inputs · Matching reviewed CSM ratios are unavailable for this filing.")
            for _, gap in gaps.iterrows():
                st.caption(f"{gap['Period'][:4]}YE · {gap['Ratio']}: matching inputs unavailable.")
        elif module.module_id in RATIO_MODULE_LABELS and module.module_id not in COMPANY_YEAR_COMPARISON_IDS:
            chart, _gaps = ratio_module_period_bars(
                data, list(RATIO_MODULE_LABELS[module.module_id]),
                color_by_period=module.module_id in YEAR_COLORED_MODULE_IDS,
                show_labels=module.module_id != "six_dimensional_charts",
            )
            if chart is not None:
                st.altair_chart(chart, width="stretch")
            else:
                st.caption("Missing inputs · Matching reviewed ratio components are unavailable for this filing and period.")
        elif module.module_id == "discount_rate":
            summary = discount_rate_summary(
                data, [company], sorted(rows["Period end"].astype(str).unique()),
            )
            if summary.empty:
                st.caption("No reviewed discount-rate tenor disclosure is available for this selection.")
            else:
                render_discount_rate_table(summary)
        elif module.module_id == "confidence_level":
            summary = confidence_level_summary(
                data, [company], sorted(data["Period end"].astype(str).unique()),
            )
            render_confidence_level_table(summary)
        elif module.module_id == "csm_maturity_table":
            chart, missing = csm_maturity_lines(
                plot_data, kind="Insurance", companies=[company],
            )
            with st.container(key=f"report_figure_{module.module_id}_insurance"):
                st.markdown(f"#### {module.title}")
                if chart is not None:
                    st.altair_chart(chart, width="stretch")
                    st.caption(f"Latest available year shown: {max(plot_data['Period end'].astype(str))[:4]}YE. "
                               "Lines show cumulative share through 1, 5 and 10 years where disclosed. "
                               "A missing first-five-years split is derived from closing CSM and later buckets; "
                               "the over-10-year bucket remains in the denominator and hover details.")
                if module.note:
                    st.caption(module.note)
                for note in module_company_disclosure_notes(module.module_id, [company]):
                    st.caption(note)
                if missing:
                    st.caption("Insurance CSM · Matching maturity buckets and closing CSM are unavailable for a percentage curve.")
        elif module.module_id in {"comp_1", "comp_2"}:
            is_method_split = module.module_id == "comp_1"
            chart = revenue_stack_bars(
                data, list(module.metrics),
                denominator_code=None if is_method_split else "REV_NONPAA_TOTAL",
                require_all=is_method_split,
            )
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                st.caption(
                    "Each bar is 100% of PAA + non-PAA revenue. Hover for both component amounts."
                    if is_method_split else
                    "Percentage labels use reported non-PAA revenue. Negative components extend below zero; hover for signed amounts."
                )
            else:
                st.caption("Missing inputs · A matching revenue split and total are unavailable.")
        elif module.module_id == "nb_value_ratios":
            st.caption(RATIO_EXPLANATION)
            ratio_rows, gaps = new_business_ratio_rows(
                data, [company], sorted(data["Period end"].astype(str).unique()),
            )
            for ratio in RATIO_TITLES:
                chart, _mean = new_business_ratio_chart(
                    ratio_rows, ratio, companies=[company],
                    periods=sorted(data["Period end"].astype(str).unique()),
                    show_mean=False,
                )
                if chart is not None:
                    st.markdown(f"**{ratio}**")
                    st.altair_chart(chart, width="stretch")
            if ratio_rows.empty:
                st.caption("Missing inputs · Matching new-business ratios are unavailable.")
            for gap in gaps:
                st.caption(gap)
        elif module.module_id in COMPANY_YEAR_COMPARISON_IDS - {"inv_return", "inv_profit"}:
            if module.module_id == "exp_total":
                st.caption("Expense magnitude is shown as a positive amount; the source statement reports it as a deduction. Hover for the signed amount.")
            comparison_labels, comparison_font_size, comparison_bar_width = True, 11, 36
            if not all_mode:
                label_column, size_column, width_column = st.columns(3)
                with label_column:
                    comparison_labels = st.toggle(
                        "Show labels", value=True, key=f"step5_{module.module_id}_comparison_labels",
                    )
                with size_column:
                    comparison_font_size = st.slider(
                        "Label size", 8, 16, 11, key=f"step5_{module.module_id}_comparison_font_size",
                    )
                with width_column:
                    comparison_bar_width = st.slider(
                        "Bar width", 18, 52, 36, key=f"step5_{module.module_id}_comparison_bar_width",
                    )
            chart, unavailable, summary = company_year_comparison_bars(
                data, list(module.metrics), companies=[company],
                periods=sorted(rows["Period end"].astype(str).unique()),
                show_labels=comparison_labels, label_font_size=comparison_font_size,
                bar_width=comparison_bar_width,
                axis_label_padding=30 if module.module_id == "exp_total" else 10,
                expense_mode="magnitude" if module.module_id == "exp_total" else None,
                reported_labels=(NET_RESULT_REPORTED_LABELS
                                 if module.module_id == "inv_profit" else None),
                ratio_label=(RATIO_MODULE_LABELS[module.module_id][0]
                             if module.module_id in RATIO_MODULE_LABELS else None),
            )
            if unavailable:
                st.caption("Unavailable matching ratio inputs: " + ", ".join(unavailable))
            if chart is not None:
                if summary:
                    st.caption(summary)
                st.altair_chart(chart, width="stretch")
            else:
                st.caption("Missing inputs · No reviewed values are available for these indicators and periods.")
        elif module.module_id == "tax_profit":
            st.caption("Profit for the year = profit before tax + income tax expense (recorded as a negative amount). Effective tax rate = −income tax expense / profit before tax, where pre-tax profit is positive.")
            chart, _excluded = tax_profit_bars(plot_data)
            if chart is not None:
                with st.container(horizontal_alignment="center", key="tax_profit_chart"):
                    st.altair_chart(chart, width="content")
            else:
                st.caption("Missing inputs · No reviewed pre-tax profit or profit values are available.")
        elif module.module_id in {"prof_2025", "prof_2024"}:
            components = service_result_component_rows(plot_data)
            chart = service_result_period_bars(components)
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                for note in service_result_notes(components):
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
                chart = investment_note_period_bars(note_rows)
                if chart is not None:
                    if heading:
                        st.markdown(f"**{heading}**")
                    st.altair_chart(chart, width="stretch")
            if first_rows.empty:
                st.caption("Missing inputs · A matching, reconciled P&L investment breakdown is unavailable.")
            else:
                for note in investment_note_captions(first_rows):
                    st.caption(note)
        elif module.module_id == "asset_struct":
            components, issues = financial_investment_rows(
                plot_data, [company], sorted(plot_data["Period end"].astype(str).unique()),
            )
            chart, excluded = financial_investment_chart(components, [company])
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                for note in financial_investment_notes(components):
                    st.caption(note)
            else:
                st.caption("Missing inputs · A complete, reconciled financial-investment breakdown is unavailable.")
            for issue in [*issues, *excluded]:
                st.caption(issue)
        elif module.module_id == "nb_struct":
            margin_rows, issues = new_business_ifrs_margin_rows(
                data, [company], sorted(data["Period end"].astype(str).unique()),
            )
            chart = new_business_ifrs_margin_chart(
                margin_rows, companies=[company],
                periods=sorted(data["Period end"].astype(str).unique()),
            )
            if chart is not None:
                with st.container(horizontal_alignment="center", key="nb_ifrs_margin_layout"):
                    with st.container(width=1050):
                        st.altair_chart(chart, width="stretch")
            else:
                st.caption("Missing inputs · A matched new-business IFRS profit margin is unavailable.")
            st.caption(IFRS_MARGIN_EXPLANATION)
            for issue in issues:
                st.caption(issue)
        else:
            stacked = module.module_id in STACKED_AMOUNT_MODULE_IDS
            if module.module_id == "nb_lost":
                st.caption("Initial-recognition presentation: CSM, risk adjustment, initial loss and PV of outflows are positive; PV of inflows is negative. Original filing signs remain in the source cells.")
            if module.module_id == "exp_1":
                st.caption("Stack height shows disclosed non-PAA expense amounts. Whole-number labels show each item's signed share of the absolute total of displayed items; negative items extend below zero. These items may not form a complete expense breakdown.")
            chart = period_bars(
                plot_data, list(stacked_component_metrics(module) if stacked else module.metrics),
                stacked=stacked,
                expense_mode="contribution" if module.module_id == "exp_1" else None,
                show_small_percent_labels=module.module_id == "exp_1",
                color_by_period=module.module_id in YEAR_COLORED_MODULE_IDS,
                show_labels=(module.module_id not in MOVEMENT_MODULE_IDS
                             and module.module_id not in HOVER_ONLY_LABEL_MODULE_IDS),
                reported_labels=(NET_RESULT_REPORTED_LABELS
                                 if module.module_id == "inv_profit" else None),
                display_label=("Investment return" if module.module_id == "inv_return" else
                               "Net investment financial result" if module.module_id == "inv_profit" else None),
                alternative_metric_labels=module.module_id == "inv_return",
            )
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                if module.module_id in LATEST_YEAR_CHART_IDS:
                    st.caption(f"Latest available year shown: {max(plot_data['Period end'].astype(str))[:4]}YE.")
                if stacked:
                    st.caption("Stacks contain disclosed component lines only; missing components are not inferred.")
                if module.module_id in STACKED_AMOUNT_TOTAL_CODES:
                    st.caption("Reported totals are omitted from the stack to avoid double counting; they remain in the source trace.")
            else:
                st.caption("Missing inputs · No reviewed values are available for these indicators and periods.")
        if module.module_id not in {"csm_maturity_table", "six_dimensional_charts"}:
            missing = missing_metrics(plot_data, module) if module.module_id not in {"oci_deep", "oci_year_lat", "asset_struct", "csm_trans"} else []
            if module.module_id not in {"discount_rate", "report_detail", "nbv_table"} and missing and len(missing) < len(module.metrics):
                st.caption(f"Partially disclosed · {len(missing)} of {len(module.metrics)} source indicators are unavailable.")
            if module.note and module.module_id != "oci_deep":
                st.caption(module.note)
            for note in module_company_disclosure_notes(module.module_id, [company]):
                st.caption(note)
with st.container(key="report_screen_summary_charts"):
    st.subheader("Year-on-year view")
    st.caption("The charts below follow the sidebar selection. Choose All charts in the sidebar for the complete report.")
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
    st.subheader("Source trace", anchor="source-trace")
    visible = rows[["Metric", "Period end", "Original value", "Source unit", "Value (millions)",
                    "PDF page", "Source label", "Audit status", "Review status"]].sort_values(["Metric", "Period end"])
    visible = visible.rename(columns={"Value (millions)": "Chart value (millions or %)"})
    st.dataframe(visible, hide_index=True,
                 column_config={"Chart value (millions or %)": st.column_config.NumberColumn(format="%.2f")})
    source_options = rows.sort_values(["Metric", "Period end"]).reset_index(drop=True)
    source_index = st.selectbox(
        "Open a source cell", list(source_options.index),
        format_func=lambda index: f"{source_options.loc[index, 'Metric']} · {source_options.loc[index, 'Period end']} · PDF p.{source_options.loc[index, 'PDF page']}",
    )
    selected = source_options.loc[source_index]
    selected_filing = filing_by_id(str(selected["Document ID"]))
    source_path = pdf_path(selected_filing)
    if source_path.is_file():
        with st.expander("View original PDF page", icon=":material/visibility:"):
            st.caption(f"Original row: {selected['Source label']} · {selected['Original value']:,.0f} {selected['Source unit']}")
            st.image(page_png(source_path, int(selected["PDF page"])), width="stretch")
    else:
        st.caption("The external workbook has a source-page reference, but its PDF is not stored in this platform.")
    if not preview:
        st.download_button(
            "Download reviewed HTML report", html_report(rows, company=company, period_end=period),
            file_name=f"{filing['document_id']}_reviewed_report.html", mime="text/html",
            icon=":material/download:",
        )
if full_report:
    back_cover()
