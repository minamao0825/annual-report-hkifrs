"""The five plotted components must reconcile to each filing's reported result."""

from pathlib import Path

import pandas as pd
import pytest

from hkifrs17.charts import _stack_percent_label, peer_service_result_panels, service_result_period_bars
from hkifrs17.report_modules import REPORT_MODULES, module_rows
from hkifrs17.service_result import (
    SERVICE_RESULT_COMPONENTS, service_result_component_rows, service_result_notes,
)


@pytest.fixture(scope="module")
def records():
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_latest.xlsx")
    return pd.read_excel(workbook, sheet_name="Records")


def test_each_company_and_year_has_five_reconciled_components(records):
    components = service_result_component_rows(records)
    assert len(components) == 3 * 2 * 5
    assert set(components["Metric"]) == set(SERVICE_RESULT_COMPONENTS)
    for _, group in components.groupby(["Company", "Period"]):
        assert group["Stack order"].tolist() == list(range(5))
        assert group["Amount"].sum() == pytest.approx(group["Reported total"].iloc[0], abs=0.001)

    combined = components.loc[components["Metric"].eq(SERVICE_RESULT_COMPONENTS[1])]
    expected = {
        ("FWD Life Bermuda", "2024-12-31"): 21.519,
        ("FWD Life Bermuda", "2025-12-31"): 17.527,
        ("Sun Life Hong Kong", "2024-12-31"): 58.0,
        ("Sun Life Hong Kong", "2025-12-31"): 91.0,
        ("YF Life", "2024-12-31"): 46.679907,
        ("YF Life", "2025-12-31"): -86.349204,
    }
    for _, row in combined.iterrows():
        assert row["Amount"] == pytest.approx(expected[(row["Company"], row["Period"])])

    fwd = combined.loc[
        combined["Company"].eq("FWD Life Bermuda")
        & combined["Period"].eq("2025-12-31")
    ].iloc[0]
    assert "PAA net 1.016" in fwd["Calculation detail"]
    assert "other effects 16.511" in fwd["Calculation detail"]
    assert fwd["Bridge basis"] == "disclosed method subtotals"
    sun = combined.loc[
        combined["Company"].eq("Sun Life Hong Kong")
        & combined["Period"].eq("2025-12-31")
    ].iloc[0]
    assert "PAA net −42.000" in sun["Calculation detail"]
    assert "other effects 133.000" in sun["Calculation detail"]

    yf = combined.loc[combined["Company"].eq("YF Life")]
    assert yf["Bridge basis"].eq("derived combined residual").all()
    assert all("does not separately disclose PAA net result" in detail
               for detail in yf["Calculation detail"])
    assert any("−86.349" in note for note in service_result_notes(components))
    yf_loss = components.loc[
        components["Company"].eq("YF Life")
        & components["Metric"].eq(SERVICE_RESULT_COMPONENTS[4])
    ].set_index("Period")["Amount"]
    assert yf_loss["2025-12-31"] == pytest.approx(43.746077)
    assert yf_loss["2024-12-31"] == pytest.approx(-14.044676)


@pytest.mark.parametrize("module_id,period", [
    ("prof_2025", "2025-12-31"),
    ("prof_2024", "2024-12-31"),
])
def test_both_year_charts_stack_five_items_and_explain_yf(records, module_id, period):
    module = next(item for item in REPORT_MODULES if item.module_id == module_id)
    components = service_result_component_rows(module_rows(records, module))
    assert set(components["Period"]) == {period}
    yf = components.loc[components["Company"].eq("YF Life")]
    insurer = service_result_period_bars(yf)
    insurer_spec = insurer.to_dict(validate=True)
    bars = insurer_spec["layer"][0]["encoding"]
    assert bars["y"]["stack"] == "zero"
    assert bars["color"]["scale"]["domain"] == list(SERVICE_RESULT_COMPONENTS)
    color_range = bars["color"]["scale"]["range"]
    assert color_range[3] == "#1E49E2"
    assert color_range[4] == "#D9DEE7"
    label_color = insurer_spec["layer"][1]["encoding"]["color"]
    assert label_color["condition"]["value"] == "#FFFFFF"
    assert SERVICE_RESULT_COMPONENTS[3] in label_color["condition"]["test"]
    assert label_color["value"] != "#FFFFFF"
    chart_rows = [point for dataset in insurer_spec["datasets"].values()
                  for point in dataset if "Share (%)" in point]
    assert chart_rows
    assert all(not point["Percent label"] for point in chart_rows
               if abs(point["Share (%)"]) < 5)
    hover_fields = {entry["field"] for entry in bars["tooltip"] if isinstance(entry, dict)}
    assert {"Amount", "Calculation detail", "Reported total"} <= hover_fields
    assert not {"Metric", "Source"} & hover_fields

    peer, excluded = peer_service_result_panels(
        components, companies=sorted(components["Company"].unique()),
        periods=[period], display_mode="HKD converted",
    )
    assert excluded == []
    peer_spec = peer.to_dict(validate=True)
    peer_bars = peer_spec["spec"]["layer"][0]["encoding"]
    assert peer_bars["y"]["stack"] == "zero"
    assert peer_bars["color"]["scale"]["range"][3:] == ["#1E49E2", "#D9DEE7"]
    peer_label_color = peer_spec["spec"]["layer"][1]["encoding"]["color"]
    assert peer_label_color["condition"]["value"] == "#FFFFFF"
    assert SERVICE_RESULT_COMPONENTS[3] in peer_label_color["condition"]["test"]
    assert peer_label_color["value"] != "#FFFFFF"
    assert peer_spec["resolve"]["scale"]["y"] == "shared"


def test_service_result_percentage_label_cutoff_is_five_percent():
    assert _stack_percent_label(4.999, 5) == ""
    assert _stack_percent_label(-4.999, 5) == ""
    assert _stack_percent_label(5, 5) == "5%"
    assert _stack_percent_label(-5, 5) == "-5%"


def test_incomplete_or_nonreconciling_filing_is_not_plotted(records):
    damaged = records.copy()
    mask = damaged["Company"].eq("FWD Life Bermuda") & damaged["Period end"].eq("2025-12-31")
    damaged = damaged.loc[~(mask & damaged["Metric code"].eq("INS_EXP_PAA"))]
    components = service_result_component_rows(damaged)
    assert components.loc[components["Company"].eq("FWD Life Bermuda")
                          & components["Period"].eq("2025-12-31")].empty

    damaged = records.copy()
    mask = (damaged["Company"].eq("YF Life")
            & damaged["Period end"].eq("2025-12-31")
            & damaged["Metric code"].eq("INS_SERVICE_RESULT"))
    damaged.loc[mask, "Value (millions)"] += 1
    components = service_result_component_rows(damaged)
    assert components.loc[components["Company"].eq("YF Life")
                          & components["Period"].eq("2025-12-31")].empty
