import math
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.charts import company_year_comparison_bars
from hkifrs17.equity_waterfall import (
    equity_movement_table, equity_waterfall_chart, equity_waterfall_notes,
    equity_waterfall_rows,
)
from hkifrs17.external import load_analysis_records
from hkifrs17.fx import year_end_usd_hkd
from hkifrs17.report_modules import REPORT_MODULES


def test_reported_equity_bridges_reconcile_without_assuming_missing_items_are_zero():
    records = load_analysis_records()
    companies = sorted(records["Company"].unique())
    periods = sorted(records["Period end"].unique())
    rows, issues = equity_waterfall_rows(records, companies, periods)

    assert not issues
    assert len(rows) == 6
    for _, row in rows.iterrows():
        total = row["Opening"] + sum(item["Amount"] for item in row["Movements"])
        assert math.isclose(total, row["Closing"], abs_tol=1e-6)

    fwd_2025 = rows.loc[rows["Company"].eq("FWD Life Bermuda")
                        & rows["Year"].eq("2025")].iloc[0]
    assert math.isclose(fwd_2025["Remainder"], .030, abs_tol=1e-6)
    assert "Share capital issued" in fwd_2025["Missing items"]
    assert any(item["Calculated"] for item in fwd_2025["Movements"])
    assert any("not separately disclosed" in note for note in equity_waterfall_notes(rows))


def test_missing_profit_omits_bridge_and_chart_uses_selected_currency():
    records = load_analysis_records()
    selected = records.loc[records["Company"].eq("FWD Life Bermuda")
                           & records["Period end"].eq("2025-12-31")].copy()
    missing_profit = selected.loc[~selected["Metric code"].eq("PROFIT")]
    rows, issues = equity_waterfall_rows(missing_profit, ["FWD Life Bermuda"], ["2025-12-31"])
    assert rows.empty
    assert any("missing Profit for the year" in issue for issue in issues)

    rows, _ = equity_waterfall_rows(selected, ["FWD Life Bermuda"], ["2025-12-31"])
    chart, excluded = equity_waterfall_chart(rows, ["FWD Life Bermuda"],
                                              display_mode="HKD converted")
    assert not excluded
    spec = chart.to_dict()
    assert spec["resolve"]["scale"]["y"] == "shared"
    assert spec["spec"]["height"] == 330
    assert "Source" not in str(spec)
    assert "Metric" not in str(spec)


def test_net_assets_modules_follow_chart_table_order_and_growth_uses_matching_scopes():
    equity_ids = [module.module_id for module in REPORT_MODULES
                  if module.subsection == "Equity"]
    assert equity_ids[:3] == ["equity_balance_comparison", "equity_movement_table",
                              "equity_trend"]
    records = load_analysis_records()
    companies = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
    chart, gaps, summary = company_year_comparison_bars(
        records, ["EQUITY"], companies=companies,
        periods=["2024-12-31", "2025-12-31"], display_mode="HKD converted",
    )
    assert chart is not None and not gaps
    assert "3 increased, 0 decreased" in summary
    changes = {value["Company label"]: value["Change pct"]
               for dataset in chart.to_dict()["datasets"].values()
               for value in dataset if "Change pct" in value}
    assert changes["Sun Life Hong Kong (Company)"] == pytest.approx(
        100 * (8121 - 7922) / 7922)
    fwd_rate_2024 = year_end_usd_hkd(2024)[0]
    fwd_rate_2025 = year_end_usd_hkd(2025)[0]
    assert changes["FWD Life Bermuda (Company)"] == pytest.approx(
        100 * (3001.941 * fwd_rate_2025 - 2779.503 * fwd_rate_2024)
        / (2779.503 * fwd_rate_2024))


def test_movement_table_marks_missing_lines_and_reconciles_to_closing_equity():
    records = load_analysis_records()
    companies = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
    table, issues = equity_movement_table(records, companies, ["2025-12-31"],
                                          display_mode="Native currencies", decimals=3)
    assert not issues
    assert table["Item"].tolist() == [
        "Profit for the year", "Other comprehensive income", "Dividends paid",
        "Share capital issued", "Other disclosed equity movements",
        "Unallocated reconciliation remainder*", "Net assets movement",
    ]
    fwd = "FWD Life Bermuda (Company) · USD"
    assert table.loc[table["Item"].eq("Share capital issued"), fwd].iloc[0] == "Not disclosed"
    assert table.loc[table["Item"].eq("Unallocated reconciliation remainder*"), fwd].iloc[0] == "0.030"
    assert table.loc[table["Item"].eq("Net assets movement"), fwd].iloc[0] == "222.438"


@pytest.mark.parametrize("page,key", [("05_insurer.py", "insurer"),
                                       ("06_peers.py", "peers")])
def test_equity_navigation_renders_comparison_waterfall_and_detail_table(page, key):
    records = load_analysis_records()
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=60)
        app.session_state["analysis_data_active"] = True
        app.session_state[f"{key}_primary"] = "Key financial statement analysis"
        app.session_state[f"{key}_secondary"] = "Equity"
        app.session_state[f"{key}_chart"] = "__all_in_selection__"
        app.run()
    assert not app.exception
    assert len(app.get("vega_lite_chart")) >= 2
    assert any("Net assets movement = closing equity" in item.value
               for item in app.caption)
    if key == "peers":
        html = [item.proto.body for item in app.get("html")]
        assert any('equity-movement-meta">2025YE · Amounts in millions' in body
                   for body in html)
        assert not any("Latest selected year shown" in item.value
                       or "Partially disclosed" in item.value for item in app.caption)
        equity_notes = [item.value for item in app.caption
                        if "Opening equity + profit + OCI" in item.value]
        assert len(equity_notes) == 1
        assert "omitted undisclosed lines" in equity_notes[0]
        assert "underlying components are unidentified" in equity_notes[0]
