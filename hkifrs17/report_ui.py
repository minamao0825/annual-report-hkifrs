"""Shared platform screen styling and printable report layout."""

from __future__ import annotations

from base64 import b64encode
from functools import lru_cache
from html import escape
from pathlib import Path
import re

import pandas as pd
import streamlit as st

from .report_modules import ReportModule
from .highlights import HIGHLIGHT_COLUMNS


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def inject_styles() -> None:
    st.markdown("""
<style>
:root { --screen-red:#FF4B4B; --screen-ink:#30333D; --screen-muted:#858994; --report-blue:#00338D; }
.stApp { background:#F4F6FB; color:var(--screen-ink); }
.block-container { max-width:none; padding:1.2rem 3.2rem 3rem; }
h1,h2,h3 { color:var(--screen-ink); }
h1 { font-weight:750; letter-spacing:-.025em; }
h2 { border:0; padding:0; margin-top:1.7rem; }
h3 { border:0; padding:0; margin-top:1.2rem; }
.st-key-app_header h1 { font-size:clamp(2.3rem,3.5vw,4.5rem); line-height:1.14; margin-bottom:1.3rem; }
.st-key-app_header [data-testid="stCaptionContainer"] { color:var(--screen-muted); font-size:1.12rem; }
.st-key-step_tabs { display:flex; flex-wrap:nowrap!important; gap:1.6rem!important; overflow-x:auto!important; overflow-y:hidden!important; white-space:nowrap; scrollbar-width:thin; border-bottom:1px solid #D8DCE5; margin-top:1.1rem; margin-bottom:1.3rem; }
.st-key-step_tabs > [data-testid="stElementContainer"] { flex:0 0 auto; margin:0!important; }
.st-key-step_tabs a[data-testid="stPageLink-NavLink"] { display:block; padding:10px 0 12px!important; margin:0!important; border:0!important; border-bottom:3px solid transparent!important; border-radius:0!important; background:transparent!important; box-shadow:none!important; color:var(--screen-ink)!important; font-size:1rem!important; font-weight:400!important; text-decoration:none!important; line-height:1.5rem!important; }
.st-key-step_tabs a[data-testid="stPageLink-NavLink"] > span:first-child { display:none!important; }
.st-key-step_tabs a[data-testid="stPageLink-NavLink"] > span:last-child { display:block!important; line-height:1.5rem!important; }
.st-key-step_tabs a[data-testid="stPageLink-NavLink"] span,
.st-key-step_tabs a[data-testid="stPageLink-NavLink"] p { color:inherit!important; font-size:1rem!important; font-weight:400!important; margin:0!important; }
.st-key-step_tabs a[data-testid="stPageLink-NavLink"]:hover { color:var(--screen-red)!important; border-bottom-color:var(--screen-red)!important; }
[data-testid="stSidebar"] { background:#F4F6FB; border-right:1px solid #D8DCE5; }
.kpmg-side-label { color:var(--screen-ink); font-weight:750; font-size:15px; margin:13px 0 6px; border-bottom:1px solid #D8DCE5; padding-bottom:5px; }
.kpmg-side-sub a { display:block; color:#4F5564; text-decoration:none; font-size:13px; padding:3px 0 3px 12px; }
.kpmg-side-sub a:hover { color:var(--screen-red); text-decoration:underline; }
.kpmg-jump { display:block; text-align:center; background:#FF4B4B; color:white!important; padding:9px 10px; border-radius:6px; text-decoration:none!important; font-weight:700; margin:12px 0; }
.report-table { width:100%; border-collapse:collapse; font:12px Arial,sans-serif; margin:9px 0 22px; }
.report-table th { background:#00338D; color:white; text-align:left; padding:7px 9px; border:1px solid #D8DCE5; }
.report-table td { background:white; color:#30333D; padding:6px 9px; border:1px solid #D8DCE5; }
.report-table tr:nth-child(even) td { background:#F4F6FB; }
.discount-rate-table { table-layout:fixed; font-size:clamp(10px,.9vw,13px); }
.discount-rate-table th { text-align:center; }
.discount-rate-table th:first-child { width:23%; text-align:left; }
.discount-rate-table td { vertical-align:top; line-height:1.55; overflow-wrap:anywhere; }
.discount-rate-table td:first-child { font-weight:700; }
.discount-rate-table td.unavailable { background:#CECECE!important; color:white; font-weight:700; }
.highlights-wrap { width:100%; max-width:100%; margin:12px 0 24px; }
.highlights-table { width:100%; border-collapse:collapse; font:clamp(7px,.82vw,12px) Arial,sans-serif; table-layout:fixed; }
.highlights-table th { background:#00338D; color:white; text-align:center; padding:clamp(3px,.6vw,10px) clamp(2px,.45vw,7px); border:1px solid white; line-height:1.3; font-weight:700; overflow-wrap:anywhere; }
.highlights-table th:first-child { width:17%; text-align:left; }
.highlights-table td { padding:clamp(2px,.45vw,7px) clamp(2px,.5vw,8px); text-align:center; border:1px solid #E4E7EB; color:#30333D; overflow-wrap:anywhere; }
.highlights-table td:first-child { text-align:left; }
.highlights-table tbody tr:nth-child(even) td { background:#F5F6F8; }
.highlights-table td.unavailable { background:#CECECE!important; color:white; font-weight:700; }
[data-testid="stMetric"] { background:white; border:1px solid #E1E4EA; border-radius:8px; padding:12px; }
@media (max-width: 800px) { .block-container { padding:1rem 1rem 2rem; } }
.report-cover { position:relative; aspect-ratio:16/9; width:100%; background:#062A68; margin:14px 0 30px; overflow:hidden; }
.report-cover-image { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; display:block; }
.report-cover-title { position:absolute; left:7%; bottom:15%; width:80%; color:white; text-shadow:0 2px 12px rgba(0,12,50,.6); }
.report-cover-title h1 { color:white!important; font-size:clamp(33px,4vw,60px); border:0; margin:0 0 12px; }
.report-cover-title p { color:white!important; font-size:clamp(14px,1.6vw,24px); margin:4px 0; }
.report-back { min-height:500px; aspect-ratio:16/9; width:100%; background:#FFFFFF; border-left:7vw solid #00338D; padding:8% 7%; break-before:page; position:relative; }
.report-back .back-kpmg { color:#00338D; font-size:32px; font-weight:900; letter-spacing:-.07em; }
.report-back h1 { color:#00338D; font-size:clamp(44px,6vw,84px); margin-top:35px; }
.report-back p { max-width:600px; color:#344869; }
.report-back small { position:absolute; bottom:7%; color:#56657e; }
.report-page-break { break-before:page; height:0; }
@media print {
  @page { size:338.67mm 190.5mm; margin:10mm; }
  :root { --report-content-height:150mm; }
  html[data-report-print-format="a4"] { --report-content-height:205mm; }
  html,body,.stApp { background:white!important; -webkit-print-color-adjust:exact!important; print-color-adjust:exact!important; }
  .block-container { max-width:none!important; padding:0!important; }
  [data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stToolbar"],
  .st-key-step_tabs, .st-key-app_header, .st-key-peer_core_config, .st-key-source_trace,
  .st-key-report_screen_controls, [class*="st-key-report_screen_summary"],
  [class*="st-key-report_section_heading_"],
  [class*="st-key-report_subsection_heading_"], .print-hide, [data-testid="stStatusWidget"],
  button, input, [data-testid="stSelectbox"], [data-testid="stToggle"],
  [data-testid="stDataFrame"], [data-testid="stAlert"] { display:none!important; }
  .report-cover, .report-back { width:318mm!important; height:140mm!important; aspect-ratio:auto;
    margin:0!important; break-inside:avoid-page!important; }
  .report-back { min-height:0; }
  html[data-report-print-format="a4"] .report-cover,
  html[data-report-print-format="a4"] .report-back { width:190mm!important; height:140mm!important; }
  html[data-report-print-format="a4"] .report-cover {
    height:107mm!important; aspect-ratio:2134/1202!important;
    background-size:contain!important; background-position:center!important;
    margin:75mm auto 0!important;
  }
  h1,h2,h3,h4 { break-after:avoid-page!important; page-break-after:avoid!important; }
  [class*="st-key-report_chart_"] { display:block!important; break-before:page!important; page-break-before:always!important; }
  html[data-report-print-format="a4"] .st-key-report_chart_prof_mix,
  html[data-report-print-format="a4"] .st-key-report_chart_tax_profit,
  html[data-report-print-format="a4"] .st-key-report_chart_oci_profit {
    break-before:auto!important; page-break-before:auto!important;
  }
  html[data-report-print-format="a4"] .st-key-report_chart_prof_mix {
    height:auto!important; min-height:0!important; overflow:visible!important;
  }
  html:not([data-report-print-format="a4"]) .st-key-report_chart_tax_profit {
    height:160mm!important; min-height:160mm!important; overflow:hidden!important;
  }
  html:not([data-report-print-format="a4"]) .st-key-report_chart_net_profit {
    break-before:auto!important; page-break-before:auto!important;
  }
  [class*="st-key-report_visual_"] { display:block!important; overflow:hidden!important; }
  [class*="st-key-report_visual_"]:not([class*="st-key-report_visual_summary_table"]):not([class*="st-key-report_visual_csm_maturity_table"]),
  [class*="st-key-report_figure_"], [class*="st-key-report_table_"] {
    display:grid!important; align-content:center!important;
    min-height:var(--report-content-height)!important; width:100%!important;
    break-inside:avoid-page!important; page-break-inside:avoid!important;
    overflow:hidden!important;
  }
  html[data-report-print-format="a4"] [class*="st-key-report_visual_"]:not([class*="st-key-report_visual_summary_table"]):not([class*="st-key-report_visual_csm_maturity_table"]),
  html[data-report-print-format="a4"] [class*="st-key-report_figure_"],
  html[data-report-print-format="a4"] [class*="st-key-report_table_"] {
    min-height:235mm!important; height:auto!important; padding:8mm 0!important;
    box-sizing:border-box!important; overflow:visible!important;
  }
  html[data-report-print-format="a4"] [class*="st-key-report_table_"] {
    padding-top:8mm!important;
  }
  html:not([data-report-print-format="a4"]) [class*="st-key-report_visual_"]:not([class*="st-key-report_visual_summary_table"]):not([class*="st-key-report_visual_csm_maturity_table"]),
  html:not([data-report-print-format="a4"]) [class*="st-key-report_figure_"],
  html:not([data-report-print-format="a4"]) [class*="st-key-report_table_"] {
    position:relative!important; top:8mm!important;
  }
  html[data-report-print-format="a4"] .st-key-report_visual_prof_mix,
  html[data-report-print-format="a4"] .st-key-report_visual_oci_profit {
    break-before:page!important; page-break-before:always!important;
  }
  html body .st-key-report_chart_six_dimensional_charts .st-key-report_visual_six_dimensional_charts {
    display:block!important; height:auto!important; min-height:0!important;
    padding:0!important; top:auto!important; overflow:visible!important;
    break-inside:auto!important; page-break-inside:auto!important;
  }
  html[data-report-print-format="a4"] .st-key-report_chart_six_dimensional_charts {
    break-inside:auto!important; page-break-inside:auto!important;
  }
  .st-key-report_figure_six_dimensional_charts_group_2,
  .st-key-report_figure_six_dimensional_charts_yield {
    break-before:page!important; page-break-before:always!important;
  }
  [class*="st-key-report_figure_"] > *, [class*="st-key-report_table_"] > *,
  [class*="st-key-report_visual_"] > * { width:100%!important; }
  [class*="st-key-report_table_"],
  [class*="st-key-report_figure_csm_maturity_table_reinsurance_following"] {
    break-before:page!important; page-break-before:always!important;
  }
  [class*="st-key-report_table_"] .report-table,
  [class*="st-key-report_table_"] .highlights-wrap { margin-left:auto!important; margin-right:auto!important; }
  [data-testid="stVegaLiteChart"], [data-testid="stMetric"] {
    break-inside:avoid-page!important; page-break-inside:avoid!important;
    max-width:100%!important; overflow:visible!important; margin-left:auto!important; margin-right:auto!important;
  }
  [data-testid="stVegaLiteChart"] canvas,
  [data-testid="stVegaLiteChart"] svg { max-width:100%!important; }
  .report-table, .highlights-wrap { break-inside:avoid-page!important; page-break-inside:avoid!important; }
  .report-table { font-size:10px; }
  .report-table tr { break-inside:avoid-page!important; page-break-inside:avoid!important; }
  .report-page-break { break-before:page; }
}
</style>
""", unsafe_allow_html=True)


def sidebar_outline(modules: list[tuple[str, list[str]]]) -> None:
    st.sidebar.markdown("## Report contents")
    st.sidebar.caption("All charts are shown on the page. Use these links to jump to a section.")
    for group, children in modules:
        html = f'<div class="kpmg-side-label">{escape(group)}</div>'
        html += '<div class="kpmg-side-sub">' + ''.join(
            f'<a href="#{slug(item)}">{escape(item)}</a>' for item in children
        ) + '</div>'
        st.sidebar.markdown(html, unsafe_allow_html=True)


ALL_CHARTS = "All charts"
ALL_IN_SELECTION = "__all_in_selection__"


def selected_report_modules(modules: tuple[ReportModule, ...], primary: str,
                            secondary: str = ALL_IN_SELECTION,
                            chart_id: str = ALL_IN_SELECTION) -> tuple[ReportModule, ...]:
    """Keep the chart list aligned with the sidebar's three navigation levels."""
    if primary == ALL_CHARTS:
        return modules
    return tuple(item for item in modules
                 if item.section == primary
                 and (secondary == ALL_IN_SELECTION or item.subsection == secondary)
                 and (chart_id == ALL_IN_SELECTION or item.module_id == chart_id))


def _reset_subnavigation(key: str) -> None:
    st.session_state[f"{key}_secondary"] = ALL_IN_SELECTION
    st.session_state[f"{key}_chart"] = ALL_IN_SELECTION


def _reset_chart_navigation(key: str) -> None:
    st.session_state[f"{key}_chart"] = ALL_IN_SELECTION


def sidebar_report_navigation(modules: tuple[ReportModule, ...], *, key: str,
                              heading: str) -> tuple[bool, tuple[ReportModule, ...]]:
    """Select exactly the report modules displayed by Steps 5 and 6."""
    st.sidebar.markdown(f"### {escape(heading)}")
    sections = list(dict.fromkeys(item.section for item in modules))
    primary_options = [*sections, ALL_CHARTS]
    primary_key = f"{key}_primary"
    if primary_key in st.session_state and st.session_state[primary_key] not in primary_options:
        st.session_state[primary_key] = ALL_CHARTS
    main = st.sidebar.radio("Primary module", primary_options,
                            key=primary_key, on_change=_reset_subnavigation,
                            args=(key,))
    if main == ALL_CHARTS:
        st.sidebar.caption("All charts, report cover and back cover are ready for printing.")
        return True, modules

    primary_modules = selected_report_modules(modules, main)
    subsections = list(dict.fromkeys(item.subsection for item in primary_modules))
    secondary_options = [ALL_IN_SELECTION, *[s for s in subsections if s != "All"]]
    secondary_key = f"{key}_secondary"
    if st.session_state.get(secondary_key) not in secondary_options:
        st.session_state[secondary_key] = ALL_IN_SELECTION
    secondary = st.sidebar.radio(
        "Secondary module", secondary_options,
        format_func=lambda value: "All in selected module" if value == ALL_IN_SELECTION else value,
        key=secondary_key, on_change=_reset_chart_navigation, args=(key,),
    )
    choices = selected_report_modules(modules, main, secondary)
    chart_options = [ALL_IN_SELECTION, *[item.module_id for item in choices]]
    chart_key = f"{key}_chart"
    if st.session_state.get(chart_key) not in chart_options:
        st.session_state[chart_key] = ALL_IN_SELECTION
    selected_id = st.sidebar.radio(
        "Chart", chart_options,
        format_func=lambda value: (
            "All in selected section" if value == ALL_IN_SELECTION else
            next(item.title for item in choices if item.module_id == value)
        ),
        key=chart_key,
    )
    visible = selected_report_modules(modules, main, secondary, selected_id)
    st.sidebar.caption(f"Showing {len(visible)} chart{'s' if len(visible) != 1 else ''} in this selection.")
    return False, visible


def render_report_table(frame: pd.DataFrame) -> None:
    """Full HTML table stays visible in both screen and all-chart print views."""
    if frame.empty:
        return
    st.html(frame.to_html(index=False, escape=True, border=0, classes="report-table"))


def render_discount_rate_table(frame: pd.DataFrame) -> None:
    """English year columns with readable multiline currency and basis ranges."""
    if frame.empty:
        return
    headers = "".join(f"<th>{escape(str(column))}</th>" for column in frame.columns)
    body = []
    for _, row in frame.iterrows():
        cells = []
        for column in frame.columns:
            value = str(row[column])
            css = ' class="unavailable"' if value == "Not disclosed" else ""
            cells.append(f"<td{css}>{escape(value).replace(chr(10), '<br>')}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    st.html('<table class="report-table discount-rate-table"><thead><tr>'
            + headers + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")


def render_financial_highlights_table(frame: pd.DataFrame, period: str) -> None:
    """Compact eight-ratio comparison with explicit unavailable cells."""
    if frame.empty:
        return
    prior = str(int(period[:4]) - 1)
    current = period[:4]
    headers = ["<th>Company</th>"]
    for index, (label, formula) in enumerate(HIGHLIGHT_COLUMNS):
        year_line = (f"{current}YE/{current} opening−1" if index == 0 else
                     f"{current}YE/{prior}YE−1" if index in (1, 2, 3, 6, 7) else "")
        headers.append(f"<th>{escape(label)}<br>{escape(formula)}"
                       + (f"<br>{year_line}" if year_line else "") + "</th>")
    body = []
    for _, row in frame.iterrows():
        cells = [f"<td>{escape(str(row['Company']))}</td>"]
        for label, _ in HIGHLIGHT_COLUMNS:
            value = row[label]
            cells.append('<td class="unavailable">Unavailable</td>' if pd.isna(value)
                         else f"<td>{float(value):.0f}%</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    st.html('<div class="highlights-wrap"><table class="highlights-table"><thead><tr>'
            + "".join(headers) + "</tr></thead><tbody>" + "".join(body)
            + "</tbody></table></div>")


def print_controls(key: str, *, all_mode: bool = False) -> bool:
    report_layout = all_mode or st.sidebar.toggle(
        "Full report layout", value="print=1" in str(st.context.url or ""), key=f"{key}_report_layout",
        help="Adds the annual-report cover and English back cover to the all-chart print view.",
    )
    if report_layout:
        with st.sidebar:
            st.html("""
<div class="report-export-buttons">
  <button type="button" data-format="a4">Export portrait A4 PDF</button>
  <button type="button" data-format="wide">Export landscape 16:9 PDF</button>
</div>
<style>
.report-export-buttons { display:grid; gap:8px; }
.report-export-buttons button { width:100%; padding:11px; border:0; border-radius:6px;
  color:#fff; font-weight:700; cursor:pointer; background:#00338D; }
.report-export-buttons button + button { background:#008C83; }
</style>
<script>
function exportReportPdf(format) {
  const size = format === 'a4' ? 'A4 portrait' : '338.67mm 190.5mm';
  document.documentElement.dataset.reportPrintFormat = format;
  let pageStyle = document.getElementById('report-print-page-size');
  if (!pageStyle) {
    pageStyle = document.createElement('style');
    pageStyle.id = 'report-print-page-size';
    document.body.appendChild(pageStyle);
  }
  pageStyle.textContent = '@page { size: ' + size + '; margin: 10mm; }';
  requestAnimationFrame(() => window.print());
}
document.querySelectorAll('.report-export-buttons button').forEach(button => {
  button.addEventListener('click', () => exportReportPdf(button.dataset.format));
  button.dataset.ready = 'true';
});
window.addEventListener('afterprint', () => {
  document.documentElement.removeAttribute('data-report-print-format');
  document.getElementById('report-print-page-size')?.remove();
});
</script>
""", unsafe_allow_javascript=True)
        st.sidebar.caption("In the print dialog, choose Save as PDF and enable background graphics.")
    return report_layout


def cover(title: str, subtitle: str, note: str) -> None:
    st.html(f'<div class="report-cover"><img class="report-cover-image" src="{_cover_image_uri()}" alt="">'
            f'<div class="report-cover-title"><h1>{escape(title)}</h1>'
            f'<p>{escape(subtitle)}</p><p>{escape(note)}</p></div></div>')


@lru_cache(maxsize=1)
def _cover_image_uri() -> str:
    image_path = Path(__file__).resolve().parents[1] / "static" / "annual_cover.png"
    return "data:image/png;base64," + b64encode(image_path.read_bytes()).decode("ascii")


def back_cover() -> None:
    st.html('<div class="report-back"><div class="back-kpmg">KPMG</div><h1>Thank you</h1>'
            '<p>HK IFRS 17 financial statements explorer</p>'
            '<small>Source figures remain traceable to the reviewed filing and original PDF page.</small></div>')
