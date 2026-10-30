"""Checks for the selected financial performance ratios used by Steps 5 and 6."""

from pathlib import Path

import pandas as pd

from hkifrs17.charts import financial_performance_peer_dots, financial_performance_trends
from hkifrs17.report_modules import RATIO_MODULE_LABELS, financial_performance_ratio_table
from hkifrs17 import report_ui


RECORDS = Path(__file__).resolve().parents[1] / "outputs" / "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx"
LABELS = list(RATIO_MODULE_LABELS["six_dimensional_charts"])


def test_step5_facets_ratios_with_independent_scales_and_exact_values():
    records = pd.read_excel(RECORDS, sheet_name="Records")
    chart, gaps, values = financial_performance_trends(
        records[records["Company"].eq("FWD Life Bermuda")], LABELS,
    )
    spec = chart.to_dict(validate=True)
    assert spec["facet"]["field"] == "Metric"
    assert spec["resolve"]["scale"]["y"] == "independent"
    assert [layer["mark"]["type"] for layer in spec["spec"]["layer"]] == [
        "rule", "line", "circle", "text",
    ]
    assert set(values["Metric"]).issubset(LABELS)
    assert "Investment yield" not in LABELS


def test_step6_dots_share_a_scale_within_each_ratio_and_connect_two_years():
    records = pd.read_excel(RECORDS, sheet_name="Records")
    chart, _, values = financial_performance_peer_dots(
        records, LABELS,
        companies=["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"],
        periods=["2024-12-31", "2025-12-31"],
    )
    spec = chart.to_dict(validate=True)
    assert spec["facet"]["field"] == "Metric"
    assert spec["resolve"]["scale"]["x"] == "independent"
    assert [layer["mark"]["type"] for layer in spec["spec"]["layer"]] == [
        "rule", "circle",
    ]
    assert spec["spec"]["layer"][1]["encoding"]["y"]["field"] == "Company label"
    assert set(values["Company"]) == {"FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"}


def test_financial_performance_table_shows_four_ratios_without_yield():
    records = pd.read_excel(RECORDS, sheet_name="Records")
    table = financial_performance_ratio_table(
        records, ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"],
        ["2025-12-31", "2024-12-31"],
    )
    assert table.columns.tolist() == ["Company", "Indicator", "2024YE", "2025YE"]
    assert len(table) == 3 * len(LABELS)
    assert table.groupby("Company")["Indicator"].apply(list).apply(lambda values: values == LABELS).all()
    assert "Investment yield" not in set(table["Indicator"])
    fwd_growth = table.loc[
        table["Company"].eq("FWD Life Bermuda (Company)")
        & table["Indicator"].eq("Insurance CSM year-on-year growth"), "2025YE",
    ].item()
    assert fwd_growth == "41.44%"


def test_peer_ratios_render_one_small_company_comparison_table_per_indicator(monkeypatch):
    records = pd.read_excel(RECORDS, sheet_name="Records")
    table = financial_performance_ratio_table(
        records, ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"],
        ["2024-12-31", "2025-12-31"],
    )
    markup = []
    monkeypatch.setattr(report_ui.st, "html", markup.append)
    report_ui.render_financial_performance_peer_tables(table)
    assert len(markup) == 1
    assert markup[0].count('class="financial-performance-card"') == len(LABELS)
    assert markup[0].count('class="report-table financial-performance-table"') == len(LABELS)
    assert markup[0].count('<th>Company</th><th>2024YE</th><th>2025YE</th>') == len(LABELS)
    assert markup[0].count('FWD Life Bermuda (Company)') == len(LABELS)
    assert markup[0].count('Sun Life Hong Kong (Company)') == len(LABELS)
    assert markup[0].count('YF Life (Consolidated)') == len(LABELS)
    assert markup[0].count('class="unavailable"') >= 4
    assert "Investment yield" not in markup[0]


def test_financial_performance_pages_render_tables_instead_of_ratio_charts():
    pages = Path(__file__).resolve().parents[1] / "app_pages"
    for name, renderer in (("05_insurer.py", "render_financial_performance_table"),
                           ("06_peers.py", "render_financial_performance_peer_tables")):
        text = (pages / name).read_text(encoding="utf-8")
        assert f"{renderer}(" in text
        assert "financial_performance_trends(" not in text
        assert "financial_performance_peer_dots(" not in text
