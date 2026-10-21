"""Single-insurer Step 7-aligned report with source-page drilldown."""

from __future__ import annotations

from itertools import groupby
from pathlib import Path

import pandas as pd
import streamlit as st

from hkifrs17.charts import (
    company_year_comparison_bars, csm_maturity_lines, financial_performance_trends, period_bars,
    ratio_module_period_bars, revenue_stack_bars, tax_profit_bars,
)
from hkifrs17.demo import demo_records
from hkifrs17.external import load_analysis_records, save_external_workbook
from hkifrs17.highlights import financial_highlights_table
from hkifrs17.pdf import page_png
from hkifrs17.report import html_report
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
from hkifrs17.storage import filing_by_id, pdf_path


with st.container(key="report_screen_controls"):
    st.title("Insurer explorer")
    st.caption("Step 5 · Source Step 7 indicators, adapted to Hong Kong disclosures. Period is the horizontal axis; colors identify indicators.")
    with st.expander("Upload reviewed Excel data for Steps 5 and 6", icon=":material/upload_file:"):
        st.caption("Use a standardized .xlsx workbook with a Records sheet and, where available, a Check plan sheet. The platform recalculates units and reconciliation results before adding the data to both report pages.")
        example_workbook = Path(__file__).resolve().parents[1] / "outputs" / "HK_IFRS17_FWD_YF_SunLife_2024_2025_latest.xlsx"
        if example_workbook.is_file():
            st.download_button("Download the latest three-insurer 2024–2025 workbook", example_workbook.read_bytes(),
                               file_name=example_workbook.name,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               icon=":material/download:")
            st.caption("Each insurer and year has the same 187 metrics. Rows marked Not disclosed have no numeric value and are excluded from charts and reconciliation checks.")
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
        if {"Sun Life Hong Kong", "Sun Life Hong Kong (Consolidated)"}.issubset(companies):
            st.caption("Sun Life 2024 is consolidated; 2025 is company-only. Select them separately because the reporting scopes differ.")
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
        st.caption(f"Showing: {company}")
rows = records[records["Company"].eq(company)].copy()
period = max(rows["Period end"].astype(str))
filing = filing_by_id(str(rows.loc[rows["Period end"].astype(str).eq(period), "Document ID"].iloc[0]))
display_modules = report_modules_for_rows(rows)
st.session_state.setdefault("insurer_secondary", "Profitability")
all_mode, visible_modules = sidebar_report_navigation(
    display_modules, key="insurer", heading="Insurer report navigation",
)
full_report = print_controls("insurer", all_mode=all_mode)
if full_report:
    cover("HK IFRS 17 · Insurer report", company, f"Financial year ended {period} · {filing['currency']}")
with st.container(key="report_screen_summary_top"):
    st.caption(f"{filing['legal_entity']} · {filing['scope']} · Year ended {period} · {filing['source_unit']}")
    st.caption("Charts follow the source annual-report Step 7 module order. Movement charts show the latest available year. Mainland-only measures are omitted; additional HKFRS 17 note fields follow in a separate section.")


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
        if module.module_id not in {"csm_maturity_table", "summary_table", "six_dimensional_charts"}:
            st.markdown(f"#### {module.title}")
        if module.module_id == "summary_table":
            chart = period_bars(data, ["TOTAL_LIABS", "EQUITY"], stacked=True)
            with st.container(key="report_figure_summary_table"):
                st.markdown(f"#### {module.title}")
                if chart is not None:
                    st.altair_chart(chart, width="stretch")
                st.caption("Balance-sheet composition · Total liabilities + equity = total assets. Hover for the original PDF page and source label.")
            with st.container(key="report_table_summary_table"):
                st.markdown("**Financial Highlights table**")
                render_financial_highlights_table(
                    financial_highlights_table(rows, [company], period,
                                               include_source_comparatives=not preview), period,
                )
                st.caption("Percentages are rounded to whole numbers. Grey cells mean a matching source input is unavailable.")
                if not preview and company == "Sun Life Hong Kong":
                    st.caption("Year-on-year figures use unaudited 2024 company comparatives in the 2025 filing; 2024 consolidated figures are excluded from this calculation.")
                if not preview and company == "YF Life":
                    st.caption("YF Life CSM amortization combines the fair-value-transition and other-contract CSM release lines in the insurance note.")
        elif module.module_id == "six_dimensional_charts":
            for group_number, (group_title, group_labels) in enumerate(PERFORMANCE_RATIO_PAGE_GROUPS, 1):
                with st.container(key=f"report_figure_six_dimensional_charts_group_{group_number}"):
                    st.markdown(f"#### {module.title}")
                    st.markdown(f"**{group_title}**")
                    chart, _gaps, _values = financial_performance_trends(data, list(group_labels))
                    if chart is not None:
                        with st.container(horizontal_alignment="center", key=f"performance_ratio_chart_group_{group_number}"):
                            st.altair_chart(chart, width="content")
                    else:
                        st.caption("Missing inputs · Matching reviewed ratio components are unavailable.")
                    if group_number == 2:
                        st.caption("Hover for exact values. Ratios with missing inputs are omitted.")
                        if module.note:
                            st.caption(module.note)
            yield_chart, _gaps, _values = financial_performance_trends(data, ["Investment yield"])
            if yield_chart is not None:
                with st.container(key="report_figure_six_dimensional_charts_yield"):
                    st.markdown(f"#### {module.title} · Investment yield")
                    with st.container(horizontal_alignment="center", key="performance_ratio_chart_yield"):
                        st.altair_chart(yield_chart, width="content")
                    st.caption("Investment yield uses the rate disclosed in the filing.")
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
            render_discount_rate_table(summary)
            st.caption("Each range spans the disclosed 1Y, 5Y, 10Y, 15Y and 20Y spot rates. "
                       "Currencies and risk-free versus illiquidity-premium assumptions are kept separate.")
        elif module.module_id == "confidence_level":
            _module_table(data, module.metrics)
        elif module.module_id == "csm_maturity_table":
            maturity = {
                kind: csm_maturity_lines(plot_data, kind=kind, companies=[company])
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
                        st.altair_chart(chart, width="stretch")
                        if kind == available[-1]:
                            st.caption(f"Latest available year shown: {max(plot_data['Period end'].astype(str))[:4]}YE. "
                                       "Lines show cumulative share through 1, 5 and 10 years where disclosed. "
                                       "A missing first-five-years split is derived from closing CSM and later buckets; "
                                       "the over-10-year bucket remains in the denominator and hover details.")
                            if module.note:
                                st.caption(module.note)
                elif missing:
                    st.caption(f"{kind} CSM · Matching maturity buckets and closing CSM are unavailable for a percentage curve.")
            if not available:
                st.markdown(f"#### {module.title}")
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
                    "Percentage labels use the PAA + non-PAA revenue total. Hover for amounts and source pages."
                    if is_method_split else
                    "Percentage labels use reported non-PAA revenue. Negative components extend below zero; hover for signed amounts and source pages."
                )
            else:
                st.caption("Missing inputs · A matching revenue split and total are unavailable.")
        elif module.module_id in COMPANY_YEAR_COMPARISON_IDS:
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
        else:
            stacked = module.module_id in STACKED_AMOUNT_MODULE_IDS
            if module.module_id == "exp_1":
                st.caption("Selected items from insurance expense notes, shown as amounts: positive values increase expense; negative values reduce it. Disclosures differ by insurer and are not a complete breakdown, so percentages and totals are omitted. Hover for the PDF page and source line.")
            chart = period_bars(
                plot_data, list(stacked_component_metrics(module) if stacked else module.metrics),
                stacked=stacked,
                expense_mode="contribution" if module.module_id == "exp_1" else None,
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
            missing = missing_metrics(plot_data, module)
            if missing and len(missing) < len(module.metrics):
                st.caption(f"Partially disclosed · {len(missing)} of {len(module.metrics)} source indicators are unavailable.")
            if module.note:
                st.caption(module.note)
    if module.module_id == "inv_profit":
        bridge = investment_result_reconciliation(rows)
        if not bridge.empty:
            with st.container(key="report_table_inv_profit"):
                st.markdown("**Profit-or-loss reconciliation**")
                render_report_table(bridge)
                st.caption("Original statement currencies, millions. The investment-contract liability movement "
                           "is calculated from the reported lines; it matches the separately disclosed FWD and YF line. "
                           "Sun Life has no such movement in this subtotal.")


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
