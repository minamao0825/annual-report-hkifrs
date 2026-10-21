"""The report charts retain the requested period and insurer layout."""

from pathlib import Path

import pandas as pd
import pytest

from hkifrs17.catalog import INSURER_CHART_GROUPS, PEER_METRIC_GROUPS
from hkifrs17.charts import (
    KPMG_BRIGHT_CHART_COLORS, _revenue_stack_rows, company_year_comparison_bars,
    peer_group_panels,
    peer_rate_panels, peer_ratio_module_panels, peer_ratio_panels,
    peer_revenue_stack_panels, period_bars, ratio_module_period_bars,
    revenue_stack_bars, tax_profit_bars,
)
from hkifrs17.demo import demo_records
from hkifrs17.data import standardize_hkd
from hkifrs17.metric_blueprint import CHART_REQUIREMENTS
from hkifrs17.report_modules import (
    COMPANY_YEAR_COMPARISON_IDS, HOVER_ONLY_LABEL_MODULE_IDS, REPORT_MODULES,
    RATIO_MODULE_LABELS,
    STACKED_AMOUNT_MODULE_IDS, TABLE_MODULE_IDS, YEAR_COLORED_MODULE_IDS,
    module_rows, stacked_component_metrics,
)


def test_insurer_bars_group_indicators_within_each_period():
    records = demo_records("YF_2025")
    chart = period_bars(records, list(INSURER_CHART_GROUPS[0][1]))
    spec = chart.to_dict(validate=True)
    encoding = spec["layer"][0]["encoding"]
    assert encoding["x"]["field"] == "Period label"
    assert encoding["xOffset"]["field"] == "Metric"
    assert encoding["color"]["field"] == "Metric"
    assert encoding["color"]["scale"]["range"][0] == KPMG_BRIGHT_CHART_COLORS[0]
    assert encoding["x"]["sort"] == ["2024YE", "2025YE"]


def test_tax_profit_chart_shows_two_bars_and_source_based_tax_rate():
    assert next(module.title for module in REPORT_MODULES
                if module.module_id == "tax_profit") == (
                    "Pre-tax profit, net profit and effective tax rate"
                )
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    fwd = records[records["Company"].eq("FWD Life Bermuda")]
    chart, excluded = tax_profit_bars(fwd)
    spec = chart.to_dict(validate=True)
    points = next(iter(spec["datasets"].values()))
    bars = [point for point in points if point.get("Row kind") == "bar"]
    rates = [point for point in points if point.get("Row kind") == "rate"]
    assert excluded == []
    assert {point["Metric"] for point in bars} == {"Profit before tax", "Profit"}
    assert len(bars) == 4
    assert {point["Period"]: point["Rate label"] for point in rates} == {
        "2024-12-31": "39.5%", "2025-12-31": "16.0%",
    }
    labels = spec["layer"][1]["encoding"]
    assert labels["y"]["field"] == "Label midpoint"
    assert labels["color"]["condition"]["value"] == "#FFFFFF"
    assert labels["color"]["value"] == "#0C233C"
    assert "xOffset" not in spec["layer"][2]["encoding"]

    without_tax = fwd[~(fwd["Metric code"].eq("TAX_EXPENSE")
                        & fwd["Period end"].eq("2024-12-31"))]
    missing_spec = tax_profit_bars(without_tax)[0].to_dict(validate=True)
    missing_points = next(iter(missing_spec["datasets"].values()))
    assert {point["Period"] for point in missing_points
            if point.get("Row kind") == "rate"} == {"2025-12-31"}

    no_positive_pbt = fwd.copy()
    no_positive_pbt.loc[
        no_positive_pbt["Metric code"].eq("PBT")
        & no_positive_pbt["Period end"].eq("2024-12-31"),
        "Value (millions)",
    ] = 0
    zero_spec = tax_profit_bars(no_positive_pbt)[0].to_dict(validate=True)
    zero_points = next(iter(zero_spec["datasets"].values()))
    assert {point["Period"] for point in zero_points
            if point.get("Row kind") == "rate"} == {"2025-12-31"}


def test_peer_bars_use_one_responsive_panel_per_insurer():
    records = demo_records()
    companies = ["YF Life", "FWD Life Bermuda", "Sun Life Hong Kong"]
    periods = ["2024-12-31", "2025-12-31"]
    chart, excluded = peer_group_panels(
        records, list(PEER_METRIC_GROUPS[0][1]),
        companies=companies, periods=periods,
    )
    spec = chart.to_dict(validate=True)
    assert excluded == []
    assert spec["facet"]["field"] == "Company"
    assert spec["columns"] == 3
    assert spec["spec"]["layer"][0]["encoding"]["x"]["field"] == "Period label"
    assert spec["spec"]["layer"][0]["encoding"]["xOffset"]["field"] == "Metric"
    assert spec["resolve"]["scale"]["y"] == "independent"
    assert spec["spec"]["width"] < 760


def test_hkd_conversion_does_not_silently_mix_usd():
    records = demo_records()
    companies = ["YF Life", "FWD Life Bermuda"]
    periods = ["2024-12-31", "2025-12-31"]
    chart, excluded = peer_group_panels(
        records, list(PEER_METRIC_GROUPS[0][1]),
        companies=companies, periods=periods, display_mode="HKD converted",
    )
    assert excluded == []
    converted_spec = chart.to_dict(validate=True)
    assert converted_spec["columns"] == 2
    assert converted_spec["resolve"]["scale"]["y"] == "shared"
    assert converted_spec["spec"]["layer"][0]["encoding"]["y"]["title"] == "HKD millions"
    assert converted_spec["spec"]["layer"][0]["encoding"]["y"]["axis"]["format"] == ",.2~f"
    fwd = standardize_hkd(records[records["Company"].eq("FWD Life Bermuda") & records["Currency"].eq("USD")])
    assert set(fwd["USD/HKD rate"].dropna()) == {7.7677, 7.7833}
    assert (fwd["HKD value (millions)"].round(8) ==
            (pd.to_numeric(fwd["Value (millions)"]) * fwd["USD/HKD rate"]).round(8)).all()
    ratios = peer_ratio_panels(records, companies=companies, periods=periods)
    assert ratios.to_dict(validate=True)["facet"]["field"] == "Company"


def test_revenue_method_split_is_stacked_with_full_legend_and_percentage_labels():
    records = demo_records("FWD_2025")
    codes = ["REV_NONPAA_TOTAL", "REV_PAA_TOTAL"]
    chart = revenue_stack_bars(records, codes, require_all=True)
    spec = chart.to_dict(validate=True)
    bars = spec["layer"][0]["encoding"]
    labels = spec["layer"][1]["encoding"]
    assert bars["y"]["stack"] == "zero"
    assert "xOffset" not in bars
    assert bars["color"]["legend"]["labelLimit"] == 1000
    assert bars["color"]["legend"]["columns"] == 1
    assert labels["text"]["field"] == "Percent label"
    shares = _revenue_stack_rows(records, codes, denominator_code=None, require_all=True)
    assert shares.groupby("Period")["Share (%)"].sum().round(8).eq(100).all()


def test_non_paa_components_keep_signed_amounts_and_use_reported_total():
    records = demo_records("FWD_2025")
    codes = [item.metrics for item in CHART_REQUIREMENTS if item.source_id == "comp_2"][0]
    assert "REV_POLICYHOLDER_TAX" in codes
    rows = _revenue_stack_rows(records, list(codes), denominator_code="REV_NONPAA_TOTAL",
                               require_all=False)
    assert not rows.empty
    assert rows.groupby("Period")["Share (%)"].sum().round(8).eq(100).all()
    chart, excluded = peer_revenue_stack_panels(
        records, list(codes), companies=["FWD Life Bermuda"],
        periods=["2024-12-31", "2025-12-31"], denominator_code="REV_NONPAA_TOTAL",
    )
    assert excluded == []
    spec = chart.to_dict(validate=True)
    assert spec["spec"]["layer"][0]["encoding"]["y"]["stack"] == "zero"
    assert spec["spec"]["layer"][1]["encoding"]["text"]["field"] == "Percent label"


def test_hkd_revenue_stacks_share_y_scale_across_companies():
    records = demo_records()
    chart, excluded = peer_revenue_stack_panels(
        records, ["REV_NONPAA_TOTAL", "REV_PAA_TOTAL"],
        companies=["FWD Life Bermuda", "YF Life"],
        periods=["2024-12-31", "2025-12-31"],
        require_all=True, display_mode="HKD converted", unit="billions",
    )
    assert excluded == []
    spec = chart.to_dict(validate=True)
    assert spec["resolve"]["scale"]["y"] == "shared"
    assert spec["spec"]["layer"][0]["encoding"]["y"]["title"] == "HKD billions"


@pytest.mark.parametrize("module_id", [
    "prof_2025", "prof_2024", "uw_profit", "oci_deep",
])
def test_requested_component_charts_stack_signed_details_in_both_steps(module_id):
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    module = next(item for item in REPORT_MODULES if item.module_id == module_id)
    assert module_id in STACKED_AMOUNT_MODULE_IDS
    data = module_rows(records, module)
    codes = list(stacked_component_metrics(module))
    assert not data[data["Metric code"].isin(codes)].empty
    assert "INS_SERVICE_RESULT" not in codes
    assert "INS_FINANCE_TOTAL" not in codes
    assert "REINS_FINANCE_TOTAL" not in codes

    insurer_chart = period_bars(data, codes, stacked=True)
    insurer_bars = insurer_chart.to_dict(validate=True)["layer"][0]["encoding"]
    assert insurer_bars["y"]["stack"] == "zero"
    assert "xOffset" not in insurer_bars
    assert insurer_bars["color"]["field"] == "Metric"

    peer_chart, excluded = peer_group_panels(
        data, codes, companies=sorted(data["Company"].unique()),
        periods=sorted(data["Period end"].unique()),
        display_mode="HKD converted", stacked=True,
    )
    assert excluded == []
    peer_spec = peer_chart.to_dict(validate=True)
    assert peer_spec["resolve"]["scale"]["y"] == "shared"
    assert peer_spec["spec"]["layer"][0]["encoding"]["y"]["stack"] == "zero"
    assert "xOffset" not in peer_spec["spec"]["layer"][0]["encoding"]


def test_negative_risk_adjustment_is_not_normalized_to_positive():
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    yf = records[records["Company"].eq("YF Life")]
    codes = [item.metrics for item in CHART_REQUIREMENTS if item.source_id == "comp_2"][0]
    rows = _revenue_stack_rows(yf, list(codes), denominator_code="REV_NONPAA_TOTAL",
                               require_all=False)
    risk = rows[rows["Metric code"].eq("REV_RA_RELEASE")]
    assert risk["Amount"].lt(0).all()
    assert risk["Share (%)"].lt(0).all()
    assert risk["Label midpoint"].lt(0).all()


def test_requested_charts_use_blue_year_colors_without_changing_other_legends():
    expected_titles = {
        "Profit for the year", "Insurance revenue", "Insurance service expenses",
        "Insurance service result",
        "Other comprehensive income", "Total comprehensive income", "Total assets",
        "Insurance CSM closing balance", "CSM to matching fulfilment cash flows",
        "New profitable insurance contract CSM", "Initial onerous-contract loss",
        "New profitable contract CSM to PV inflows", "Risk adjustment confidence level",
        "Insurance revenue detail", "Investment return", "Net investment result as reported",
        "Financial position", "CSM",
        "Reinsurance CSM release",
    }
    assert {m.title for m in REPORT_MODULES if m.module_id in YEAR_COLORED_MODULE_IDS} == expected_titles
    records = demo_records("FWD_2025")
    colored = period_bars(records, ["INS_EXPENSE"], color_by_period=True).to_dict(validate=True)
    color = colored["layer"][0]["encoding"]["color"]
    assert color["field"] == "Period label"
    assert color["scale"] == {
        "domain": ["2024YE", "2025YE"], "range": ["#76D2FF", "#1E49E2"],
    }
    assert "xOffset" not in colored["layer"][0]["encoding"]
    labels = colored["layer"][1]["encoding"]
    assert labels["y"]["field"] == "Label midpoint"
    assert labels["color"]["condition"]["test"] == "(datum['Period label'] === '2025YE')"
    assert labels["color"]["condition"]["value"] == "#FFFFFF"
    assert labels["color"]["value"] == "#0C233C"
    ordinary = period_bars(records, ["INS_EXPENSE"]).to_dict(validate=True)
    assert ordinary["layer"][0]["encoding"]["color"]["field"] == "Metric"


def test_peer_amount_ratio_and_rate_panels_share_the_year_palette():
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    company = ["FWD Life Bermuda"]
    periods = ["2024-12-31", "2025-12-31"]
    amount, excluded = peer_group_panels(
        records, ["TOTAL_ASSETS"], companies=company, periods=periods,
        color_by_period=True,
    )
    assert excluded == []
    ratio, gaps = peer_ratio_module_panels(
        records, ["Insurance CSM / matching fulfilment cash flows"],
        companies=company, periods=periods, color_by_period=True,
    )
    assert gaps.empty
    rate = peer_rate_panels(
        records, ["RA_CONFIDENCE_PCT"], companies=company, periods=periods,
        color_by_period=True,
    )
    insurer_ratio, _ = ratio_module_period_bars(
        records[records["Company"].eq(company[0])],
        ["Insurance CSM / matching fulfilment cash flows"], color_by_period=True,
    )
    for chart in (amount, ratio, rate):
        color = chart.to_dict(validate=True)["spec"]["layer"][0]["encoding"]["color"]
        assert color["field"] == "Period label"
        assert color["scale"]["range"] == ["#76D2FF", "#1E49E2"]
    assert insurer_ratio.to_dict(validate=True)["layer"][0]["encoding"]["color"]["field"] == "Period label"


def test_financial_performance_ratios_keep_values_in_hover_only():
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    labels = list(RATIO_MODULE_LABELS["six_dimensional_charts"])
    insurer, _ = ratio_module_period_bars(
        records[records["Company"].eq("FWD Life Bermuda")], labels,
        show_labels=False,
    )
    peer, _ = peer_ratio_module_panels(
        records, labels, companies=["FWD Life Bermuda"],
        periods=["2024-12-31", "2025-12-31"], show_labels=False,
    )
    assert len(insurer.to_dict(validate=True)["layer"]) == 1
    assert len(peer.to_dict(validate=True)["spec"]["layer"]) == 1


def test_expense_chart_company_names_have_extra_axis_clearance():
    records = demo_records("YF_2025")
    chart, _, _ = company_year_comparison_bars(
        records, ["INS_EXPENSE"], companies=["YF Life"],
        periods=["2024-12-31", "2025-12-31"], axis_label_padding=30,
    )
    assert chart.to_dict(validate=True)["layer"][0]["encoding"]["x"]["axis"]["labelPadding"] == 30


def test_expense_total_displays_magnitude_and_growth_without_changing_source():
    records = demo_records("FWD_2025")
    source = records.loc[records["Metric code"].eq("INS_EXPENSE"), "Value (millions)"].copy()
    chart, _, summary = company_year_comparison_bars(
        records, ["INS_EXPENSE"], companies=["FWD Life Bermuda"],
        periods=["2024-12-31", "2025-12-31"], expense_mode="magnitude",
    )
    spec = chart.to_dict(validate=True)
    amounts = [row for dataset in spec["datasets"].values() for row in dataset
               if row.get("Metric code") == "INS_EXPENSE"]
    assert len(amounts) == 2
    assert all(row["Amount"] == abs(row["Accounting signed amount"]) for row in amounts)
    assert all(row["Accounting signed amount"] < 0 for row in amounts)
    assert "1 increased" in summary
    assert records.loc[source.index, "Value (millions)"].equals(source)


def test_expense_components_show_costs_above_zero_and_reversals_below():
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    records = records[records["Company"].eq("FWD Life Bermuda")]
    chart = period_bars(
        records, ["INS_EXP_ONEROUS", "INS_EXP_LIC"],
        expense_mode="contribution",
    )
    spec = chart.to_dict(validate=True)
    components = [row for dataset in spec["datasets"].values() for row in dataset
                  if row.get("Metric code") in {"INS_EXP_ONEROUS", "INS_EXP_LIC"}]
    assert components
    assert all(row["Amount"] == -row["Accounting signed amount"] for row in components)
    assert any(row["Accounting signed amount"] > 0 and row["Amount"] < 0
               for row in components)
    assert any(row["Accounting signed amount"] < 0 and row["Amount"] > 0
               for row in components)
    bars = spec["layer"][0]["encoding"]
    assert bars["y"]["stack"] is None
    assert bars["xOffset"]["field"] == "Metric"
    assert not any("Share (%)" in row or "Percent label" in row for row in components)


def test_yf_expense_detail_uses_liability_movement_sign():
    records = demo_records("YF_2025")
    records = records.loc[records["Metric code"].eq("INS_EXPENSE")].copy()
    records["Metric code"] = "INS_EXP_ONEROUS"
    records["Metric"] = "Onerous contract losses and reversals"
    records["Value (millions)"] = 14.0
    chart = period_bars(records, ["INS_EXP_ONEROUS"],
                        expense_mode="contribution")
    spec = chart.to_dict(validate=True)
    components = [row for dataset in spec["datasets"].values() for row in dataset
                  if row.get("Metric code") in {"INS_EXP_ONEROUS", "INS_EXP_LIC"}]
    assert components
    assert all(row["Amount"] == row["Accounting signed amount"] for row in components)


def test_converted_fwd_hover_shows_original_usd_amount():
    records = demo_records("FWD_2025")
    chart, excluded = peer_group_panels(
        records, ["INS_REVENUE"], companies=["FWD Life Bermuda"],
        periods=["2024-12-31", "2025-12-31"], display_mode="HKD converted",
        unit="billions",
    )
    assert excluded == []
    spec = chart.to_dict(validate=True)
    tooltip = spec["spec"]["layer"][0]["encoding"]["tooltip"]
    assert {item.get("field") for item in tooltip if isinstance(item, dict)} >= {
        "Amount", "Original source amount (millions)", "Original source currency"
    }
    converted = [row for dataset in spec["datasets"].values() for row in dataset
                 if row.get("Company", "").startswith("FWD Life Bermuda")]
    assert converted
    assert all(row["Original source currency"] == "USD" for row in converted)
    assert all(abs(row["Amount"] * 1000 -
                   row["Original source amount (millions)"] * row["USD/HKD rate"]) < 1e-6
               for row in converted)


@pytest.mark.parametrize("module_id", sorted(COMPANY_YEAR_COMPARISON_IDS))
def test_selected_financial_charts_group_years_by_company_without_changing_colors(module_id):
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    module = next(item for item in REPORT_MODULES if item.module_id == module_id)
    is_ratio = module_id in RATIO_MODULE_LABELS
    ratio_label = RATIO_MODULE_LABELS[module_id][0] if is_ratio else None
    companies = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
    periods = ["2024-12-31", "2025-12-31"]
    chart, excluded, summary = company_year_comparison_bars(
        records, list(module.metrics), companies=companies, periods=periods,
        display_mode="HKD converted", unit="billions", ratio_label=ratio_label,
    )
    if not is_ratio:
        assert excluded == []
    spec = chart.to_dict(validate=True)
    bars = spec["layer"][0]["encoding"]
    assert bars["x"]["field"] == "Company label"
    assert bars["x"]["axis"]["labelAngle"] == 0
    assert bars["x"]["axis"]["labelOverlap"] is False
    assert bars["xOffset"]["field"] == "Period label"
    assert bars["xOffset"]["scale"] == {"paddingInner": 0, "paddingOuter": 0}
    assert spec["layer"][0]["mark"]["width"] == {"band": 1}
    assert bars["color"]["scale"] == {
        "domain": ["2024YE", "2025YE"], "range": ["#76D2FF", "#1E49E2"],
    }
    assert bars["y"]["title"] == ("Ratio (%)" if is_ratio else "HKD billions")
    assert "2025YE vs 2024YE" in summary
    assert any("Change label" in row for dataset in spec["datasets"].values()
               for row in dataset)
    native, _, _ = company_year_comparison_bars(
        records, list(module.metrics), companies=companies, periods=periods,
        display_mode="Native currencies", ratio_label=ratio_label,
    )
    native_spec = native.to_dict(validate=True)
    if is_ratio:
        assert native_spec["layer"][0]["encoding"]["y"]["title"] == "Ratio (%)"
        assert any(row.get("Value label", "").endswith("%")
                   for dataset in native_spec["datasets"].values() for row in dataset)
    else:
        source_currencies = set(records.loc[
            records["Metric code"].isin(module.metrics)
            & records["Company"].isin(companies), "Currency"
        ])
        if len(source_currencies) > 1:
            assert len(native_spec["hconcat"]) == len(source_currencies)
            assert {item["title"] for item in native_spec["hconcat"]} == source_currencies
            assert native_spec["resolve"]["scale"]["y"] == "independent"
        else:
            assert native_spec["layer"][0]["encoding"]["y"]["title"] == (
                f"{next(iter(source_currencies))} millions"
            )


@pytest.mark.parametrize("module_id", [
    "csm_trans", "nb_struct", "asset_struct", "report_detail", "nbv_table",
])
def test_selected_charts_keep_amounts_in_hover_only(module_id):
    assert module_id in HOVER_ONLY_LABEL_MODULE_IDS
    if module_id in {"report_detail", "nbv_table"}:
        assert module_id not in TABLE_MODULE_IDS
    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    module = next(item for item in REPORT_MODULES if item.module_id == module_id)
    insurer = period_bars(records, list(module.metrics), show_labels=False)
    peer, _ = peer_group_panels(
        records, list(module.metrics), companies=["FWD Life Bermuda", "YF Life"],
        periods=["2024-12-31", "2025-12-31"], show_labels=False,
    )
    for chart in (insurer, peer):
        spec = chart.to_dict(validate=True)
        layers = (spec["spec"]["layer"] if "spec" in spec else spec["layer"])
        assert len(layers) == 1
        assert any(item.get("field") == "Amount" for item in layers[0]["encoding"]["tooltip"]
                   if isinstance(item, dict))


@pytest.mark.parametrize("current, expected", [(-2.5, "↗ 50.0%"), (-7.5, "↘ 50.0%")])
def test_company_comparison_uses_diagonal_arrows_for_negative_yoy(current, expected):
    records = pd.DataFrame({
        "Company": ["YF Life", "YF Life"], "Scope": ["Consolidated"] * 2,
        "Period end": ["2024-12-31", "2025-12-31"],
        "Currency": ["HKD"] * 2, "Metric code": ["OCI_TOTAL"] * 2,
        "Metric": ["Other comprehensive income"] * 2,
        "Value (millions)": [-5.0, current], "PDF page": [9] * 2,
        "Source label": ["Other comprehensive income"] * 2,
    })
    chart, _, _ = company_year_comparison_bars(
        records, ["OCI_TOTAL"], companies=["YF Life"],
        periods=["2024-12-31", "2025-12-31"],
    )
    spec = chart.to_dict(validate=True)
    assert any(row.get("Change label") == expected
               for dataset in spec["datasets"].values() for row in dataset)
