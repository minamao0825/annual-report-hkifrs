"""Source reconciliation and display rules for financial-investment stacks."""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.external import load_analysis_records, validate_external_workbook
from hkifrs17.financial_investments import (
    financial_investment_chart, financial_investment_notes, financial_investment_rows,
)


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
PERIODS = ["2024-12-31", "2025-12-31"]


def test_every_year_end_stack_reconciles_to_reported_investment_total() -> None:
    rows, issues = financial_investment_rows(load_analysis_records(), COMPANIES, PERIODS)
    assert not issues
    totals = {
        ("FWD Life Bermuda", "2024-12-31"): 16_512.701,
        ("FWD Life Bermuda", "2025-12-31"): 20_809.488,
        ("Sun Life Hong Kong", "2024-12-31"): 103_043,
        ("Sun Life Hong Kong", "2025-12-31"): 137_330,
        ("YF Life", "2024-12-31"): 77_563.271772,
        ("YF Life", "2025-12-31"): 91_018.460644,
    }
    assert set(rows.groupby(["Company", "Period"]).groups) == set(totals)
    for key, group in rows.groupby(["Company", "Period"]):
        assert group["Amount"].sum() == pytest.approx(totals[key])
        assert group["Reported total"].iloc[0] == pytest.approx(totals[key])
    yf = rows.loc[rows["Company"].eq("YF Life") & rows["Period"].eq("2025-12-31")]
    assert yf.loc[yf["Category"].eq("AC"), "Amount"].sum() == pytest.approx(37_523.745888)
    sun = rows.loc[rows["Company"].eq("Sun Life Hong Kong") & rows["Period"].eq("2025-12-31")]
    interest = sun.loc[sun["Metric code"].eq("FIN_ASSET_FVTPL_INTEREST")].iloc[0]
    assert interest["Amount"] == 93_661
    assert interest["Derivation"] == "Sum of disclosed line items"
    assert set(sun["Category"]) == {"FVOCI", "FVTPL"}
    assert any("rather than a separately reported subtotal" in note for note in financial_investment_notes(sun))
    notes = financial_investment_notes(rows)
    assert len(notes) == 1
    assert "70,331 HKD millions (2024YE)" in notes[0]
    assert "93,661 HKD millions (2025YE)" in notes[0]
    assert "Each stack reconciles" not in notes[0]


def test_chart_is_stacked_and_uses_common_hkd_scale() -> None:
    rows, _ = financial_investment_rows(load_analysis_records(), COMPANIES, PERIODS)
    chart, excluded = financial_investment_chart(rows, COMPANIES, display_mode="HKD converted")
    assert not excluded
    spec = chart.to_dict()
    bars, labels = spec["spec"]["layer"]
    assert bars["encoding"]["y"]["stack"] == "zero"
    color = bars["encoding"]["color"]
    assert color["field"] == "Category"
    assert color["scale"]["domain"] == ["AC", "FVOCI", "FVTPL"]
    assert color["scale"]["range"] == ["#1E49E2", "#00B8F5", "#B497FF"]
    assert color["legend"]["direction"] == "vertical"
    assert color["legend"]["columns"] == 1
    assert bars["mark"]["width"]["band"] == 0.9
    assert bars["encoding"]["x"]["scale"] == {"paddingInner": 0.5, "paddingOuter": 0.45}
    assert "stroke" not in bars["mark"]
    assert "strokeWidth" not in bars["mark"]
    assert labels["mark"]["fontWeight"] == "bold"
    assert labels["encoding"]["text"]["field"] == "Percent label"
    assert labels["encoding"]["color"]["condition"]["value"] == "#FFFFFF"
    assert "AC" in labels["encoding"]["color"]["condition"]["test"]
    assert spec["resolve"]["scale"]["y"] == "shared"
    assert "Source label" not in str(bars["encoding"]["tooltip"])
    assert "Metric" not in str(bars["encoding"]["tooltip"])
    assert "Asset class" not in str(bars["encoding"]["tooltip"])
    assert "Derivation" not in str(bars["encoding"]["tooltip"])
    fwd = chart.data.loc[chart.data["Company"].eq("FWD Life Bermuda") &
                         chart.data["Period"].eq("2025-12-31")]
    assert len(fwd) == 3
    assert fwd["Amount"].sum() == pytest.approx(20_809.488 * 7.7833)
    assert fwd.loc[fwd["Category"].eq("AC"), "Percent label"].iloc[0] == ""
    assert fwd.loc[fwd["Category"].eq("FVOCI"), "Percent label"].iloc[0] == "68%"
    sun = chart.data.loc[chart.data["Company"].eq("Sun Life Hong Kong") &
                         chart.data["Period"].eq("2025-12-31")]
    assert set(sun["Category"]) == {"FVOCI", "FVTPL"}
    assert sun.loc[sun["Category"].eq("FVTPL"), "Amount"].iloc[0] == 134_900


def test_missing_component_omits_incomplete_stack() -> None:
    source = load_analysis_records()
    source = source.loc[~(source["Company"].eq("YF Life") &
                          source["Period end"].eq("2025-12-31") &
                          source["Metric code"].eq("FIN_ASSET_AC_DEBT"))]
    rows, issues = financial_investment_rows(source, COMPANIES, PERIODS)
    assert not ((rows["Company"].eq("YF Life") & rows["Period"].eq("2025-12-31")).any())
    assert any("YF Life 2025" in issue for issue in issues)


def test_downloadable_workbook_contains_the_completed_classification() -> None:
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_investment_updated.xlsx")
    records, _, _ = validate_external_workbook(workbook.read_bytes())
    rows, issues = financial_investment_rows(records, COMPANIES, PERIODS)
    assert not issues
    assert len(rows.groupby(["Company", "Period"])) == 6
    sun = records.loc[records["Company"].eq("Sun Life Hong Kong") &
                      records["Period end"].eq("2025-12-31") &
                      records["Metric code"].eq("FIN_ASSET_FVTPL_INTEREST")].iloc[0]
    assert sun["Value status"] == "Derived from disclosed items"


@pytest.mark.parametrize("page,key", [("05_insurer.py", "insurer"), ("06_peers.py", "peers")])
def test_page_renders_financial_investment_stack(page: str, key: str) -> None:
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    records = load_analysis_records()
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button if button.label == "Use saved verified data").click().run()
        app.radio(key=f"{key}_secondary").set_value("Assets").run()
        app.radio(key=f"{key}_chart").set_value("asset_struct").run()
        assert not app.exception
        assert len(app.get("vega_lite_chart")) == 1
