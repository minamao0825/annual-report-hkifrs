"""Checks for the five financial performance ratio views used by Steps 5 and 6."""

from pathlib import Path

import pandas as pd

from hkifrs17.charts import financial_performance_peer_dots, financial_performance_trends
from hkifrs17.report_modules import PERFORMANCE_RATIO_PAGE_GROUPS, RATIO_MODULE_LABELS


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
    assert not values[values["Metric"].eq("Investment yield")].empty or (
        not gaps[gaps["Ratio"].eq("Investment yield")].empty
    )


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


def test_print_groups_keep_two_ratios_on_each_page():
    assert PERFORMANCE_RATIO_PAGE_GROUPS == (
        ("Return and CSM growth", (
            "Return on average equity", "Insurance CSM year-on-year growth",
        )),
        ("Equity ratios", (
            "Equity / total assets", "Equity year-on-year growth",
        )),
    )
    records = pd.read_excel(RECORDS, sheet_name="Records")
    for _, labels in PERFORMANCE_RATIO_PAGE_GROUPS:
        insurer, _, _ = financial_performance_trends(
            records[records["Company"].eq("FWD Life Bermuda")], list(labels),
        )
        peer, _, _ = financial_performance_peer_dots(
            records, list(labels),
            companies=["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"],
            periods=["2024-12-31", "2025-12-31"],
        )
        assert insurer.to_dict(validate=True)["columns"] == 1
        assert peer.to_dict(validate=True)["columns"] == 1
