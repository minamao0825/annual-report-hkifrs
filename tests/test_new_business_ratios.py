"""New-business ratios use matching initial-recognition note columns."""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.external import load_analysis_records
from hkifrs17.new_business_ratios import (
    RATIO_TITLES, new_business_ifrs_margin_chart, new_business_ifrs_margin_rows,
    new_business_ratio_chart, new_business_ratio_rows,
)
from hkifrs17.report_modules import REPORT_MODULES


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
PERIODS = ["2024-12-31", "2025-12-31"]


def test_ratios_reconcile_to_sun_life_2024_note_and_follow_loss_chart():
    modules = [module.module_id for module in REPORT_MODULES]
    loss_index = modules.index("nb_lost")
    assert modules[loss_index + 1] == "nb_value_ratios"

    rows, gaps = new_business_ratio_rows(load_analysis_records(), COMPANIES, PERIODS)
    assert len(rows) == 18
    assert not gaps
    sun_2024 = rows.loc[
        rows["Company"].eq("Sun Life Hong Kong")
        & rows["Period"].eq("2024-12-31")
    ].set_index("Ratio")
    assert sun_2024.at[RATIO_TITLES[1], "Ratio (%)"] == pytest.approx(-100 * 139 / 225)
    assert sun_2024.at[RATIO_TITLES[2], "Ratio (%)"] == pytest.approx(
        100 * (447 + 37) / (31418 + 225)
    )


def test_missing_inputs_are_omitted_and_peer_mean_uses_only_available_insurers():
    records = load_analysis_records()
    missing = records.loc[
        ~(
            records["Company"].eq("YF Life")
            & records["Period end"].eq("2025-12-31")
            & records["Metric code"].eq("NB_INS_ONEROUS_PV_IN")
        )
    ]
    rows, gaps = new_business_ratio_rows(missing, COMPANIES, PERIODS)
    assert len(rows) == 16
    assert len(gaps) == 2
    chart, mean = new_business_ratio_chart(
        rows, RATIO_TITLES[1], companies=COMPANIES, periods=PERIODS,
        tracked_company="Sun Life Hong Kong",
    )
    assert chart is not None
    assert mean == pytest.approx((-100 * 3.594 / 179.917 - 100 * 15 / 307) / 2)
    spec = chart.to_dict(validate=True)
    assert "Source" not in str(spec)
    assert "Metric" not in str(spec)
    assert any(layer.get("mark", {}).get("type") == "rect" for layer in spec["layer"])
    assert any(layer.get("encoding", {}).get("text", {}).get("field") == "Mean label"
               for layer in spec["layer"])
    assert any(layer.get("encoding", {}).get("y", {}).get("field") == "Label center"
               for layer in spec["layer"])
    bars = next(layer for layer in spec["layer"]
                if layer.get("mark", {}).get("type") == "bar")
    assert bars["encoding"]["color"]["legend"]["orient"] == "right"
    


def test_year_bars_touch_within_each_insurer():
    rows, _ = new_business_ratio_rows(load_analysis_records(), COMPANIES, PERIODS)
    chart, _ = new_business_ratio_chart(
        rows, RATIO_TITLES[0], companies=COMPANIES, periods=PERIODS,
    )
    spec = chart.to_dict(validate=True)
    bars = [layer for layer in spec["layer"]
            if layer.get("mark", {}).get("type") == "bar"]
    assert len(bars) == 1
    assert "size" not in bars[0]["mark"]
    assert bars[0]["encoding"]["xOffset"]["scale"] == {
        "paddingInner": 0, "paddingOuter": 0,
    }
    assert bars[0]["encoding"]["x"]["axis"]["labelAlign"] == "center"
    assert spec["width"] == "container"


def test_new_business_ifrs_margin_uses_both_inflow_columns_and_both_years():
    rows, gaps = new_business_ifrs_margin_rows(
        load_analysis_records(), COMPANIES, PERIODS,
    )
    assert len(rows) == 6
    assert not gaps
    fwd_2025 = rows.loc[
        rows["Company"].eq("FWD Life Bermuda")
        & rows["Period"].eq("2025-12-31")
    ].iloc[0]
    assert fwd_2025["Margin (%)"] == pytest.approx(
        100 * (680.897 - 3.594) / (6334.521 + 179.917)
    )
    chart = new_business_ifrs_margin_chart(
        rows, companies=COMPANIES, periods=PERIODS,
        tracked_company="YF Life",
    )
    spec = chart.to_dict(validate=True)
    assert spec["width"] == "container"
    assert any(layer.get("mark", {}).get("type") == "line" for layer in spec["layer"])
    legend = spec["layer"][0]["encoding"]["color"]["legend"]
    assert legend["orient"] == "top"
    assert legend["columns"] == 3
    assert "Source" not in str(spec)
    assert "Metric" not in str(spec)


def test_new_business_ifrs_margin_drops_incomplete_company_year():
    records = load_analysis_records()
    incomplete = records.loc[~(
        records["Company"].eq("YF Life")
        & records["Period end"].eq("2025-12-31")
        & records["Metric code"].eq("NB_INS_ONEROUS_PV_IN")
    )]
    rows, gaps = new_business_ifrs_margin_rows(incomplete, COMPANIES, PERIODS)
    assert len(rows) == 5
    assert len(gaps) == 1
    assert "NB_INS_ONEROUS_PV_IN" in gaps[0]


@pytest.mark.parametrize("page,key", [("05_insurer.py", "insurer"),
                                       ("06_peers.py", "peers")])
def test_new_business_ratio_charts_render_in_both_reports(page, key):
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    with patch("hkifrs17.external.load_analysis_records", return_value=load_analysis_records()):
        app = AppTest.from_file(str(path), default_timeout=60)
        app.session_state["analysis_data_active"] = True
        app.session_state[f"{key}_primary"] = "Key financial statement analysis"
        app.session_state[f"{key}_secondary"] = "New business"
        app.session_state[f"{key}_chart"] = "__all_in_selection__"
        app.run()
    assert not app.exception
    assert len(app.get("vega_lite_chart")) >= 3
    assert any("loss ratio =" in item.value for item in app.caption)
    assert any("New business IFRS profit margin =" in item.value for item in app.caption)
    assert not any("smaller inflow base" in item.value for item in app.caption)
    if key == "peers":
        assert not any("mean across displayed insurers with available inputs" in item.value
                       for item in app.caption)
