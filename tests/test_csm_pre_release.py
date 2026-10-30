"""Pre-release CSM composition uses three disclosed signed movements."""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.charts import peer_group_panels
from hkifrs17.csm_waterfall import (
    PRE_RELEASE_CSM_CODES, PRE_RELEASE_CSM_COLORS, PRE_RELEASE_CSM_LABELS,
    csm_pre_release_combined_chart, csm_pre_release_rows,
)
from hkifrs17.external import load_analysis_records
from hkifrs17.report_modules import REPORT_MODULES


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]


def test_only_complete_pre_release_movements_are_used() -> None:
    source = load_analysis_records()
    rows, issues = csm_pre_release_rows(source, COMPANIES, ["2025-12-31"])
    assert not issues
    assert set(rows["Metric code"]) == set(PRE_RELEASE_CSM_CODES)
    assert rows.groupby("Company")["Metric code"].nunique().to_dict() == {
        company: 3 for company in COMPANIES
    }
    for module_id in ("csm_comp_lat", "csm_comp_pre"):
        module = next(item for item in REPORT_MODULES if item.module_id == module_id)
        assert module.metrics == PRE_RELEASE_CSM_CODES
        assert "CSM_RELEASE" not in module.metrics

    missing = source.loc[~(
        source["Company"].eq("YF Life")
        & source["Period end"].eq("2025-12-31")
        & source["Metric code"].eq("CSM_FINANCE_CHANGE")
    )]
    partial, issues = csm_pre_release_rows(missing, COMPANIES, ["2025-12-31"])
    assert "YF Life" not in set(partial["Company"])
    assert any("YF Life" in issue for issue in issues)


def test_peer_stack_uses_amounts_and_absolute_movement_shares() -> None:
    source = load_analysis_records()
    rows, _ = csm_pre_release_rows(source, COMPANIES, ["2025-12-31"])
    chart, excluded = peer_group_panels(
        rows, list(PRE_RELEASE_CSM_CODES), companies=COMPANIES,
        periods=["2025-12-31"], display_mode="HKD converted",
        stacked=True, metric_labels=PRE_RELEASE_CSM_LABELS,
        metric_colors=PRE_RELEASE_CSM_COLORS,
        white_label_metric="New business CSM",
        absolute_share_labels=True, minimum_percent_label=5,
    )
    assert not excluded
    assert chart is not None
    values = chart.data
    for _, group in values.groupby("Company"):
        assert group["Share (%)"].sum() == pytest.approx(100)
    fwd = values.loc[values["Company"].str.startswith("FWD Life Bermuda")]
    assert fwd.loc[fwd["Metric"].eq("New business CSM"), "Amount"].iloc[0] == pytest.approx(
        680.897 * 7.7833
    )
    assert fwd.loc[fwd["Metric"].eq("New business CSM"), "Share (%)"].iloc[0] == pytest.approx(
        69.112496, abs=0.00001
    )
    spec = chart.to_dict()
    bars = spec["spec"]["layer"][0]
    assert bars["encoding"]["y"]["stack"] == "zero"
    assert not any(item.get("field") in {"Source", "Metric code"}
                   for item in bars["encoding"]["tooltip"])

    prior, _ = csm_pre_release_rows(source, ["FWD Life Bermuda"], ["2024-12-31"])
    negative, _ = peer_group_panels(
        prior, list(PRE_RELEASE_CSM_CODES), companies=["FWD Life Bermuda"],
        periods=["2024-12-31"], stacked=True,
        metric_labels=PRE_RELEASE_CSM_LABELS,
        absolute_share_labels=True,
    )
    estimate = negative.data.loc[negative.data["Metric"].eq("Changes in estimates")].iloc[0]
    assert estimate["Amount"] < 0
    assert estimate["Share (%)"] > 0


def test_one_shared_amount_chart_per_year_converts_mixed_currencies() -> None:
    source = load_analysis_records()
    for period in ("2025-12-31", "2024-12-31"):
        rows, issues = csm_pre_release_rows(source, COMPANIES, [period])
        assert not issues
        chart, excluded, currency = csm_pre_release_combined_chart(
            rows, COMPANIES, display_mode="Native currencies",
            tracked_company="YF Life",
        )
        assert chart is not None and not excluded and currency == "HKD"
        spec = chart.to_dict()
        bars = spec["layer"][0]["encoding"]
        assert bars["x"]["field"] == "Insurer"
        assert bars["y"]["stack"] == "zero"
        assert bars["opacity"]["condition"]["test"]
        assert bars["color"]["scale"]["domain"] == list(PRE_RELEASE_CSM_COLORS)
        assert set(chart.data["Company"]) == set(COMPANIES)
        assert chart.data["Currency"].eq("HKD").all()
        for _, group in chart.data.groupby("Company"):
            assert group["Share (%)"].sum() == pytest.approx(100)
        assert not any(item.get("field") in {"Source", "Metric code"}
                       for item in bars["tooltip"])
        assert any(item.get("field") == "Share (%)" for item in bars["tooltip"])
        fwd = chart.data.loc[chart.data["Company"].eq("FWD Life Bermuda")]
        assert fwd.loc[fwd["Component"].eq("New business CSM"), "Amount"].iloc[0] == pytest.approx(
            (680.897 if period.startswith("2025") else 413.205)
            * (7.7833 if period.startswith("2025") else 7.7677)
        )
        if period.startswith("2024"):
            estimate = fwd.loc[fwd["Component"].eq("Changes in estimates")].iloc[0]
            assert estimate["Amount"] < 0 < estimate["Share (%)"]
            assert estimate["Percent label"] == ""
            assert fwd.loc[fwd["Component"].eq("Finance change on CSM"),
                           "Percent label"].iloc[0] == ""
            yf = chart.data.loc[chart.data["Company"].eq("YF Life")]
            assert yf.loc[yf["Component"].eq("Finance change on CSM"),
                          "Percent label"].iloc[0] == ""
            assert yf.loc[yf["Component"].eq("New business CSM"),
                          "Percent label"].iloc[0] == "43%"


@pytest.mark.parametrize("page,key", [
    ("05_insurer.py", "insurer"), ("06_peers.py", "peers"),
])
def test_report_pages_render_current_year_stack(page: str, key: str) -> None:
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    records = load_analysis_records()
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button
             if button.label == "Use saved verified data").click().run()
        app.radio(key=f"{key}_secondary").set_value("CSM").run()
        app.radio(key=f"{key}_chart").set_value("csm_comp_lat").run()
        assert not app.exception
        assert len(app.get("vega_lite_chart")) == 2
        assert any("2024YE · Comparative year" in item.value for item in app.markdown)
        assert any("not shares of closing CSM" in item.value for item in app.caption)
