"""Investment stacks need a source total that reconciles to every component."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.external import load_analysis_records, validate_external_workbook
from hkifrs17.financial_investments import (
    COMPONENTS, financial_investment_chart, financial_investment_rows,
)


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
PERIODS = ["2024-12-31", "2025-12-31"]


def _complete_synthetic_filing() -> pd.DataFrame:
    """Supply a complete artificial filing to test chart math and layout."""
    source = load_analysis_records()
    filing = source.loc[source["Document ID"].eq("FWD_2025")
                        & source["Period end"].eq("2025-12-31")].copy()
    parts = filing.loc[filing["Metric code"].isin(COMPONENTS)
                       & filing["Value status"].eq("Reported")]
    total = float(parts["Value (millions)"].sum()) + 50.0
    template = parts.iloc[0].copy()
    ac = template.copy()
    ac["Metric code"] = "FIN_ASSET_AC"
    ac["Value (millions)"] = 50.0
    ac["Original value"] = 50_000.0
    aggregate = template.copy()
    aggregate["Metric code"] = "FIN_ASSET_TOTAL"
    aggregate["Value (millions)"] = total
    aggregate["Original value"] = total * 1_000
    return pd.concat([filing, pd.DataFrame([ac, aggregate])], ignore_index=True)


def test_incomplete_reference_never_creates_an_investment_stack() -> None:
    rows, issues = financial_investment_rows(load_analysis_records(), COMPANIES, PERIODS)
    assert rows.empty
    assert any("reported financial-investment total is unavailable" in issue for issue in issues)


def test_complete_synthetic_stack_reconciles_to_its_total() -> None:
    rows, issues = financial_investment_rows(_complete_synthetic_filing(),
                                             ["FWD Life Bermuda"], ["2025-12-31"])
    assert not issues
    assert set(rows["Category"]) == {"AC", "FVOCI", "FVTPL"}
    assert rows["Amount"].sum() == pytest.approx(rows["Reported total"].iloc[0])


def test_chart_is_stacked_and_uses_common_hkd_scale() -> None:
    rows, _ = financial_investment_rows(_complete_synthetic_filing(),
                                        ["FWD Life Bermuda"], ["2025-12-31"])
    chart, excluded = financial_investment_chart(rows, ["FWD Life Bermuda"],
                                                 display_mode="HKD converted")
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
    plotted = chart.data.loc[chart.data["Company"].eq("FWD Life Bermuda")]
    assert len(plotted) == 3
    assert plotted["Amount"].sum() == pytest.approx(rows["Reported total"].iloc[0] * 7.7833)
    assert plotted.loc[plotted["Category"].eq("AC"), "Percent label"].iloc[0] == ""


def test_missing_component_omits_incomplete_stack() -> None:
    source = _complete_synthetic_filing()
    source = source.loc[~(source["Metric code"].eq("FIN_ASSET_AC")
                          & source["Value status"].eq("Reported"))]
    rows, issues = financial_investment_rows(source, ["FWD Life Bermuda"], ["2025-12-31"])
    assert rows.empty
    assert any("FWD Life Bermuda 2025" in issue and "do not reconcile" in issue
               for issue in issues)


def test_downloadable_workbook_preserves_missing_classification() -> None:
    workbook = Path(__file__).resolve().parents[1] / "outputs" / "HKFRS17_Step5_6_current_data_upload.xlsx"
    records, _, _ = validate_external_workbook(workbook.read_bytes())
    rows, issues = financial_investment_rows(records, COMPANIES, PERIODS)
    assert rows.empty
    assert issues
    assert not records["Metric code"].eq("FIN_ASSET_TOTAL").any()


@pytest.mark.parametrize("page,key", [("05_insurer.py", "insurer"), ("06_peers.py", "peers")])
def test_page_keeps_incomplete_financial_investment_stack_unplotted(page: str, key: str) -> None:
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    records = load_analysis_records()
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button if button.label == "Use saved verified data").click().run()
        app.radio(key=f"{key}_secondary").set_value("Assets").run()
        app.radio(key=f"{key}_chart").set_value("asset_struct").run()
        assert not app.exception
        assert len(app.get("vega_lite_chart")) == 0
