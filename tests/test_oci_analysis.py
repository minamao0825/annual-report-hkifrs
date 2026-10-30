"""Source-scope and missing-data checks for the OCI comparison view."""

import math
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.external import load_analysis_records
from hkifrs17.investment_note import investment_note_rows
from hkifrs17.charts import frame_peer_company_panels, peer_investment_note_panels
from hkifrs17.oci_analysis import (
    oci_comparison_chart, oci_comparison_notes, oci_comparison_rows,
    oci_comparison_table, oci_comparison_wide_table,
)


PERIODS = ["2024-12-31", "2025-12-31"]
COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]


def _cell(rows: pd.DataFrame, company: str, year: str) -> pd.Series:
    return rows.loc[rows["Company"].eq(company) & rows["Year"].eq(year)].iloc[0]


def test_oci_amounts_conversion_and_scope() -> None:
    rows = oci_comparison_rows(load_analysis_records())
    fwd = _cell(rows, "FWD Life Bermuda", "2025")
    assert math.isclose(fwd["Asset-side OCI"], (139.201 + 294.350) * 7.7833)
    assert math.isclose(fwd["Insurance-finance OCI"], (-349.229 + 11.351) * 7.7833)
    assert math.isclose(fwd["FVOCI share (%)"], 14176.608 / 24196.184 * 100)
    assert math.isclose(_cell(rows, "YF Life", "2024")["Asset-side OCI"], -1236.050920)
    assert math.isclose(_cell(rows, "YF Life", "2024")["Insurance-finance OCI"],
                        -48.740944 + 180.381305)
    assert math.isclose(_cell(rows, "YF Life", "2025")["Insurance-finance OCI"],
                        -517.423381 + 163.197726)
    assert pd.isna(_cell(rows, "Sun Life Hong Kong", "2024")["Insurance-finance OCI"])
    table = oci_comparison_table(rows, COMPANIES, PERIODS)
    assert len(table) == 6
    assert table.loc[table["Company"].str.contains("Sun Life"),
                     "Insurance-finance OCI (HKD m)"].eq("Not available").all()
    notes = oci_comparison_notes(rows, COMPANIES, PERIODS)
    assert any("share one vertical amount scale" in note for note in notes)
    assert all("FWD USD amounts are converted" not in note for note in notes)


def test_peer_oci_table_places_each_year_and_measure_across_company_columns() -> None:
    rows = oci_comparison_rows(load_analysis_records())
    table = oci_comparison_wide_table(rows, COMPANIES, PERIODS)
    assert list(table.columns) == [
        "Item", "FWD Life Bermuda (Company)", "Sun Life Hong Kong (Company)",
        "YF Life (Consolidated)",
    ]
    assert len(table) == 10
    by_item = table.set_index("Item")
    assert by_item.at["FVOCI debt / total assets (2024YE)",
                      "FWD Life Bermuda (Company)"] == "57.93%"
    assert by_item.at["FVOCI debt / total assets (2025YE)",
                      "FWD Life Bermuda (Company)"] == "58.59%"
    assert by_item.at["Asset-side OCI (2025, HKD m)",
                      "FWD Life Bermuda (Company)"] == "+3,374.457"
    assert by_item.at["Insurance-finance OCI (2025, HKD m)",
                      "Sun Life Hong Kong (Company)"] == "Not available"


def test_missing_asset_component_is_not_treated_as_zero() -> None:
    source = load_analysis_records()
    source = source.loc[~(
        source["Company"].eq("FWD Life Bermuda")
        & source["Period end"].eq("2025-12-31")
        & source["Metric code"].eq("OCI_FVOCI_RECYCLE")
    )]
    rows = oci_comparison_rows(source)
    assert pd.isna(_cell(rows, "FWD Life Bermuda", "2025")["Asset-side OCI"])
    notes = oci_comparison_notes(rows, COMPANIES, PERIODS)
    assert any("FWD Life Bermuda: asset-side OCI is unavailable for 2025" in note
               for note in notes)


def test_oci_chart_shows_available_bars_only() -> None:
    rows = oci_comparison_rows(load_analysis_records())
    chart = oci_comparison_chart(rows, COMPANIES, PERIODS)
    spec = chart.to_dict()
    points = spec["datasets"][next(iter(spec["datasets"]))]
    assert spec["resolve"]["scale"]["y"] == "shared"
    assert len(points) == 10  # FWD 4, Sun Life 2, YF 4; no synthetic zero bars.
    assert all(point["HKD millions"] != 0 for point in points)
    assert any(point["Value label"] == "3,374.5" for point in points)
    assert all(not point["Value label"].startswith("+") for point in points)
    assert "Source" not in chart.to_json() and "Metric" not in chart.to_json()
    bars = spec["spec"]["layer"][0]
    labels = spec["spec"]["layer"][1]
    reference_rows = investment_note_rows(load_analysis_records(), "result_pl_components")
    reference, _ = peer_investment_note_panels(
        reference_rows, companies=COMPANIES, periods=PERIODS,
        display_mode="HKD converted",
    )
    reference_spec = reference.to_dict()
    reference_bars = reference_spec["spec"]["layer"][0]
    reference_labels = reference_spec["spec"]["layer"][1]
    assert bars["encoding"]["color"]["legend"] == reference_bars["encoding"]["color"]["legend"]
    assert bars["mark"]["opacity"] == reference_bars["mark"]["opacity"]
    assert labels["mark"]["fontSize"] == reference_labels["mark"]["fontSize"]
    assert labels["mark"]["fontWeight"] == reference_labels["mark"]["fontWeight"]
    assert bars["encoding"]["xOffset"]["scale"] == {"paddingInner": 0, "paddingOuter": 0}
    assert bars["mark"]["width"] == {"band": 1.0}


def test_oci_chart_supports_tracked_company_panel() -> None:
    rows = oci_comparison_rows(load_analysis_records())
    chart = oci_comparison_chart(rows, COMPANIES, PERIODS)
    framed = frame_peer_company_panels(
        chart, tracked_company="FWD Life Bermuda", tracked_scopes=("Company",),
    )
    assert framed.spec.layer[0].mark.type == "rect"
    assert framed.spec.layer[0].mark.strokeWidth == 1.8
    assert framed.to_dict()["resolve"]["scale"]["y"] == "shared"


@pytest.mark.parametrize("page,key", [
    ("05_insurer.py", "insurer"), ("06_peers.py", "peers"),
])
def test_oci_chart_and_table_render_together(page: str, key: str) -> None:
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    records = load_analysis_records()
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button
             if button.label == "Use saved verified data").click().run()
        app.radio(key=f"{key}_secondary").set_value("Comprehensive income").run()
        app.radio(key=f"{key}_chart").set_value("oci_deep").run()
        assert not app.exception
        assert "#### Asset and insurance-finance OCI comparison" in [
            item.value for item in app.markdown
        ]
        assert "**Year-end FVOCI balance and annual OCI amounts**" in [
            item.value for item in app.markdown
        ]
        assert len(app.get("vega_lite_chart")) == 1
        if key == "peers":
            assert any("Sun Life Hong Kong: insurance and reinsurance finance OCI is unavailable"
                       in item.value for item in app.caption)
