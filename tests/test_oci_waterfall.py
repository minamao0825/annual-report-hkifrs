"""Reconciliation and source-scope checks for the current-year OCI waterfall."""

import math
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.charts import frame_peer_company_panels
from hkifrs17.external import load_analysis_records
from hkifrs17.oci_waterfall import (
    oci_waterfall_chart, oci_waterfall_key, oci_waterfall_notes, oci_waterfall_rows,
)


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]


def test_2025_waterfalls_reconcile_to_reported_totals() -> None:
    rows, issues = oci_waterfall_rows(load_analysis_records(), COMPANIES, ["2025-12-31"])
    assert not issues
    assert len(rows) == 3
    for _, row in rows.iterrows():
        assert math.isclose(
            row["Net Profit"] + sum(item["Amount"] for item in row["Components"]),
            row["Total Comprehensive Income"], abs_tol=0.000001,
        )
        assert math.isclose(
            sum(item["Amount"] for item in row["Components"]),
            row["OCI total"], abs_tol=0.000001,
        )
    values = rows.set_index("Company")
    assert [item["Amount"] for item in values.loc["FWD Life Bermuda", "Components"]] == pytest.approx(
        [139.201, 294.350, -349.229, 11.351, 5.686, -5.956]
    )
    assert [item["Amount"] for item in values.loc["Sun Life Hong Kong", "Components"]] == pytest.approx(
        [146, 85, -38, -1]
    )
    assert [item["Amount"] for item in values.loc["YF Life", "Components"]] == pytest.approx(
        [785.780024, -89.904333, 2.574158, -517.423381, 163.197726, 31.505952]
    )


def test_waterfall_uses_common_hkd_scale_and_tracked_panel() -> None:
    rows, _ = oci_waterfall_rows(load_analysis_records(), COMPANIES, ["2025-12-31"])
    chart, excluded = oci_waterfall_chart(
        rows, COMPANIES, display_mode="HKD converted", decimals=0,
    )
    assert not excluded
    spec = chart.to_dict()
    assert spec["resolve"]["scale"] == {"x": "independent", "y": "shared"}
    bars = spec["spec"]["layer"][1]
    assert bars["encoding"]["x"]["field"] == "Step number"
    assert bars["encoding"]["color"]["field"] == "Bar type"
    assert bars["encoding"]["color"]["scale"] == {
        "domain": ["Start", "Increase", "Decrease", "End"],
        "range": ["#00338D", "#FF3290", "#1E49E2", "#7213EA"],
    }
    points = chart.data.to_dict("records")
    assert len(points) == 22  # FWD 8, Sun Life 6, YF 8 statement steps.
    fwd_total = next(point for point in points if point["Company"].startswith("FWD")
                     and point["Step"] == "Total Comprehensive Income")
    assert math.isclose(fwd_total["Amount"], 312.408 * 7.7833)
    assert all(point["Bar type"] == ("Increase" if point["Amount"] > 0 else "Decrease")
               for point in points if point["Step"] not in {"Net Profit", "Total Comprehensive Income"}
               and point["Amount"])
    assert {point["Bar type"] for point in points if point["Step"] == "Net Profit"} == {"Start"}
    assert {point["Bar type"] for point in points
            if point["Step"] == "Total Comprehensive Income"} == {"End"}
    assert set(point["Step number"] for point in points if point["Company"].startswith("FWD")) == {
        str(number) for number in range(1, 9)
    }
    notes = oci_waterfall_notes(rows)
    assert any("1 Net Profit; 2 Fair value gains/(losses) on debt securities at FVOCI" in note
               for note in notes)
    assert any("Sun Life Hong Kong (Company) 2025YE" in note for note in notes)
    keys = oci_waterfall_key(rows, COMPANIES)
    assert [key["Company"] for key in keys] == COMPANIES
    assert [key["End number"] for key in keys] == [8, 6, 8]
    assert keys[0]["Items"][0] == (2, "FVOCI fair value change")
    assert keys[2]["Items"][3] == (5, "Insurance finance OCI")
    assert not any(point["Step"] in {"Others", "Non-reclassifiable OCI"} for point in points)
    assert "Source" not in chart.to_json() and "Metric" not in chart.to_json()
    framed = frame_peer_company_panels(
        chart, tracked_company="FWD Life Bermuda", tracked_scopes=("Company",),
    )
    assert framed.spec.layer[0].mark.type == "rect"


def test_yf_2024_statement_items_reconcile_and_are_plotted() -> None:
    rows, issues = oci_waterfall_rows(load_analysis_records(), COMPANIES, ["2024-12-31"])
    assert not issues
    assert set(rows["Company"]) == set(COMPANIES)
    yf = rows.loc[rows["Company"].eq("YF Life")].iloc[0]
    assert yf["Net Profit"] == pytest.approx(971.528897)
    assert [item["Amount"] for item in yf["Components"]] == pytest.approx([
        -1236.050920, -357.727924, -72.865661,
        -48.740944, 180.381305, 57.537332,
    ])
    assert yf["OCI total"] == pytest.approx(-1477.466812)
    assert yf["Total Comprehensive Income"] == pytest.approx(-505.937915)


def test_missing_statement_item_does_not_become_a_residual() -> None:
    source = load_analysis_records()
    source = source.loc[~(
        source["Company"].eq("FWD Life Bermuda")
        & source["Period end"].eq("2025-12-31")
        & source["Metric code"].eq("OCI_HEDGE")
    )]
    rows, issues = oci_waterfall_rows(source, COMPANIES, ["2025-12-31"])
    assert "FWD Life Bermuda" not in set(rows["Company"])
    assert any("Cash flow hedges" in issue for issue in issues)


@pytest.mark.parametrize("page,key", [
    ("05_insurer.py", "insurer"), ("06_peers.py", "peers"),
])
def test_current_year_oci_page_renders_waterfall(page: str, key: str) -> None:
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    records = load_analysis_records()
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button
             if button.label == "Use saved verified data").click().run()
        app.radio(key=f"{key}_secondary").set_value("Comprehensive income").run()
        app.radio(key=f"{key}_chart").set_value("oci_year_lat").run()
        assert not app.exception
        assert len(app.get("vega_lite_chart")) == 1
        if key == "peers":
            html = [item.proto.body for item in app.get("html")]
            assert any("oci-waterfall-key" in body for body in html)
            assert any("FWD Life Bermuda (Company)" in body for body in html)
            assert any("Net profit + signed OCI movements" in body for body in html)
            assert not any("Latest selected year shown" in item.value for item in app.caption)
        else:
            assert any("Net Profit + the OCI items disclosed" in item.value
                       for item in app.caption)
