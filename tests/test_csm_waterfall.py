"""CSM waterfall arithmetic, disclosure limits, and report wiring."""

import math
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.charts import frame_peer_company_panels
from hkifrs17.csm_waterfall import (
    csm_rollforward_table, csm_waterfall_chart, csm_waterfall_notes, csm_waterfall_rows,
)
from hkifrs17.external import load_analysis_records
from hkifrs17.report_modules import REPORT_MODULES


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]


@pytest.mark.parametrize("period", ["2024-12-31", "2025-12-31"])
def test_each_bridge_reconciles_to_reported_closing_csm(period: str) -> None:
    rows, issues = csm_waterfall_rows(load_analysis_records(), COMPANIES, [period])
    assert not issues
    assert set(rows["Company"]) == set(COMPANIES)
    for _, row in rows.iterrows():
        assert math.isclose(row["Opening"] + sum(item["Amount"] for item in row["Movements"]),
                            row["Closing"], abs_tol=0.000001)
    remainders = rows.set_index("Company")["Calculated remainder"]
    assert remainders["FWD Life Bermuda"] == 0
    assert remainders["Sun Life Hong Kong"] == pytest.approx(-15 if period.startswith("2024") else 0)
    assert remainders["YF Life"] == pytest.approx(
        -60.030564 if period.startswith("2024") else 4.626467, abs=0.000002,
    )


def test_csm_chart_shares_hkd_scale_and_tracks_selected_insurer() -> None:
    rows, _ = csm_waterfall_rows(load_analysis_records(), COMPANIES, ["2025-12-31"])
    chart, excluded = csm_waterfall_chart(
        rows, COMPANIES, display_mode="HKD converted", decimals=0,
    )
    assert not excluded
    spec = chart.to_dict()
    assert spec["resolve"]["scale"] == {"x": "independent", "y": "shared"}
    bars = spec["spec"]["layer"][1]
    assert bars["encoding"]["x"]["axis"]["labelOverlap"] is False
    assert bars["encoding"]["x"]["axis"]["labelLimit"] == 110
    assert bars["encoding"]["y2"]["field"] == "Lower"
    assert bars["encoding"]["color"]["scale"] == {
        "domain": ["Opening", "Increase", "Decrease", "Closing"],
        "range": ["#00338D", "#FF3290", "#1E49E2", "#7213EA"],
    }
    points = chart.data.to_dict("records")
    fwd = [point for point in points if point["Panel"].startswith("FWD")]
    assert next(point for point in fwd if point["Step"] == "Open")["Amount"] == pytest.approx(
        1732.706 * 7.7833
    )
    assert next(point for point in fwd if point["Step"] == "Close")["Amount"] == pytest.approx(
        2450.689 * 7.7833
    )
    yf_steps = [point["Step"] for point in points if point["Panel"].startswith("YF Life")]
    assert yf_steps == ["Open", "New business", "Estimates", "Finance", "Release", "Other*", "Close"]
    assert "Source" not in chart.to_json() and "Metric" not in chart.to_json()
    framed = frame_peer_company_panels(chart, tracked_company="FWD Life Bermuda",
                                       tracked_scopes=("Company",))
    assert framed.spec.layer[0].mark.type == "rect"
    assert any("not a separately disclosed CSM item" in note for note in csm_waterfall_notes(rows))


def test_missing_component_or_conflicting_net_movement_omits_bridge() -> None:
    source = load_analysis_records()
    missing = source.loc[~(
        source["Company"].eq("FWD Life Bermuda")
        & source["Period end"].eq("2025-12-31")
        & source["Metric code"].eq("CSM_RELEASE")
    )]
    rows, issues = csm_waterfall_rows(missing, COMPANIES, ["2025-12-31"])
    assert "FWD Life Bermuda" not in set(rows["Company"])
    assert any("Release" in issue for issue in issues)
    conflicting = source.copy()
    index = conflicting.index[
        conflicting["Company"].eq("YF Life")
        & conflicting["Period end"].eq("2025-12-31")
        & conflicting["Metric code"].eq("CSM_NET_MOVEMENT")
    ][0]
    conflicting.loc[index, "Value (millions)"] += 10
    rows, issues = csm_waterfall_rows(conflicting, COMPANIES, ["2025-12-31"])
    assert "YF Life" not in set(rows["Company"])
    assert any("does not reconcile" in issue for issue in issues)


def test_csm_rollforward_table_reconciles_and_marks_missing_components() -> None:
    source = load_analysis_records()
    table, issues = csm_rollforward_table(
        source, COMPANIES, ["2025-12-31"], display_mode="HKD converted",
    )
    assert not issues
    assert len(table) == 3
    assert [module.module_id for module in REPORT_MODULES][
        [module.module_id for module in REPORT_MODULES].index("csm_table") + 1
    ] == "csm_rollforward_table"
    assert "HKD" in table.iloc[0]["Company"]
    assert table.iloc[0]["Opening CSM"] == "13,486.2"
    assert table.iloc[0]["Closing CSM"] == "19,074.4"
    assert table.iloc[2]["Other movements*"] == "4.6"

    missing = source.loc[~(
        source["Company"].eq("YF Life")
        & source["Period end"].eq("2025-12-31")
        & source["Metric code"].eq("CSM_RELEASE")
    )]
    incomplete, issues = csm_rollforward_table(missing, COMPANIES, ["2025-12-31"])
    yf = incomplete.loc[incomplete["Company"].str.startswith("YF Life")].iloc[0]
    assert yf["CSM release"] == "Not disclosed"
    assert yf["Other movements*"] == "Not disclosed"
    assert any("Release" in issue for issue in issues)


@pytest.mark.parametrize("page,key", [
    ("05_insurer.py", "insurer"), ("06_peers.py", "peers"),
])
def test_report_page_renders_csm_waterfall(page: str, key: str) -> None:
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    records = load_analysis_records()
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button
             if button.label == "Use saved verified data").click().run()
        app.radio(key=f"{key}_secondary").set_value("CSM").run()
        app.radio(key=f"{key}_chart").set_value("csm_table").run()
        assert not app.exception
        assert len(app.get("vega_lite_chart")) == 1
        assert any("Opening CSM + signed movements" in item.value for item in app.caption)
        app.radio(key=f"{key}_chart").set_value("csm_rollforward_table").run()
        assert not app.exception
        assert any("Other movements*" in item.proto.body for item in app.get("html"))
