"""The two report pages share the source Step 7 inventory and HK exclusions."""

import json
import pandas as pd

from hkifrs17.catalog import METRIC_BY_CODE
from hkifrs17.charts import analytical_ratio_rows, peer_group_panels, period_bars
from hkifrs17.metric_blueprint import CHART_REQUIREMENTS
from hkifrs17.demo import demo_records
from hkifrs17.report_modules import (
    COMPARATIVE_MOVEMENT_IDS, EXCLUDED_CHART_METRIC_CODES, EXCLUDED_SOURCE_IDS,
    MOVEMENT_MODULE_IDS,
    NET_RESULT_REPORTED_LABELS,
    RATIO_MODULE_LABELS, REPORT_MODULES, SOURCE_REPORT_MODULES,
    investment_result_reconciliation, module_rows, movement_chart_rows,
    report_modules_for_rows,
)


def test_all_applicable_step7_modules_and_hk_metrics_are_displayed():
    expected_ids = [item.source_id for item in CHART_REQUIREMENTS
                    if item.source_id not in EXCLUDED_SOURCE_IDS]
    assert [item.module_id for item in SOURCE_REPORT_MODULES] == expected_ids
    assert len(SOURCE_REPORT_MODULES) == 40
    assert [item.section for item in SOURCE_REPORT_MODULES[:3]] == [
        "Key financial statement analysis"] * 3
    assert {code for module in REPORT_MODULES for code in module.metrics} >= {
        code for code, metric in METRIC_BY_CODE.items()
        if metric.kind != "rate" and code not in EXCLUDED_CHART_METRIC_CODES
    }
    investment_return = next(item for item in REPORT_MODULES
                             if item.module_id == "inv_return")
    assert investment_return.metrics == ("INV_RETURN", "NET_INV_INCOME")
    assert investment_return.title == "Investment return"
    net_result = next(item for item in REPORT_MODULES if item.module_id == "inv_profit")
    assert net_result.metrics == ("NET_INV_RESULT",)
    assert net_result.title == "Net investment result as reported"
    assert not any({"INV_RETURN_TOTAL", "NET_INV_RESULT_TOTAL"} & set(item.metrics)
                   for item in REPORT_MODULES)
    assert "comprehensive solvency" not in " ".join(
        item.title.lower() for item in REPORT_MODULES
    )
    assert RATIO_MODULE_LABELS["six_dimensional_charts"] == (
        "Return on average equity", "Insurance CSM year-on-year growth",
        "Equity / total assets", "Investment yield", "Equity year-on-year growth",
    )


def test_investment_bridge_and_reported_company_chart_labels():
    values = {
        "FWD Life Bermuda": {"INV_RETURN": 816.753, "INS_FINANCE_PL": -824.179,
                              "REINS_FINANCE_PL": 27.984, "NET_INV_RESULT": 17.861},
        "Sun Life Hong Kong": {"NET_INV_INCOME": 12651, "INS_FINANCE_PL": -11929,
                               "REINS_FINANCE_PL": -201, "NET_INV_RESULT": 521},
        "YF Life": {"INV_RETURN": 6122.878110, "INS_FINANCE_PL": -5280.042009,
                    "REINS_FINANCE_PL": 296.377591, "NET_INV_RESULT": 907.742385},
    }
    rows = pd.DataFrame([
        {"Company": company, "Scope": "Consolidated" if company == "YF Life" else "Company",
         "Period end": "2025-12-31", "Currency": "USD" if company == "FWD Life Bermuda" else "HKD",
         "Metric code": code, "Metric": METRIC_BY_CODE[code].label,
         "Value (millions)": value, "PDF page": 8, "Source label": code}
        for company, company_values in values.items() for code, value in company_values.items()
    ])
    bridge = investment_result_reconciliation(rows).set_index("Company")
    assert bridge.loc["FWD Life Bermuda (Company)",
                      "Investment-contract liability movement"] == "-2.697"
    assert bridge.loc["Sun Life Hong Kong (Company)",
                      "Investment-contract liability movement"] == "0"
    assert bridge.loc["YF Life (Consolidated)",
                      "Investment-contract liability movement"] == "-231.471307"
    result = rows[rows["Metric code"].eq("NET_INV_RESULT")]
    yf_prior = result[result["Company"].eq("YF Life")].copy()
    yf_prior["Period end"] = "2024-12-31"
    yf_prior["Value (millions)"] = 652.817506
    result = pd.concat([result, yf_prior], ignore_index=True)
    single = period_bars(result[result["Company"].eq("YF Life")], ["NET_INV_RESULT"],
                         reported_labels=NET_RESULT_REPORTED_LABELS,
                         display_label="Net investment financial result",
                         color_by_period=True)
    peer, excluded = peer_group_panels(result, ["NET_INV_RESULT"],
                                        companies=list(values), periods=["2024-12-31", "2025-12-31"],
                                        reported_labels=NET_RESULT_REPORTED_LABELS,
                                        display_label="Net investment financial result",
                                        color_by_period=True)
    assert not excluded
    for chart in (single, peer):
        chart_spec = chart.to_dict()
        chart_text = json.dumps(chart_spec)
        assert "Net financial result" in chart_text
        assert "Net investment result in profit or loss" not in chart_text
        assert {row["Metric"] for dataset in chart_spec["datasets"].values()
                for row in dataset} == {"Net investment financial result"}
        bar_color = (chart_spec["spec"] if "spec" in chart_spec else chart_spec)["layer"][0]["encoding"]["color"]
        assert bar_color["field"] == "Period label"
        assert bar_color["scale"] == {
            "domain": ["2024YE", "2025YE"], "range": ["#76D2FF", "#1E49E2"],
        }
    start, excluded = peer_group_panels(
        rows[rows["Metric code"].isin({"INV_RETURN", "NET_INV_INCOME"})],
        ["INV_RETURN", "NET_INV_INCOME"], companies=list(values),
        periods=["2025-12-31"], color_by_period=True,
        display_label="Investment return",
        alternative_metric_labels=True,
    )
    assert not excluded
    assert start.to_dict()["spec"]["layer"][0]["encoding"]["color"]["field"] == "Period label"
    assert {row["Metric"] for dataset in start.to_dict()["datasets"].values()
            for row in dataset} == {"Investment return"}


def test_comparative_modules_never_reuse_current_year_values():
    rows = pd.DataFrame({"Period end": ["2024-12-31", "2025-12-31"],
                         "Metric code": ["OCI_TOTAL", "OCI_TOTAL"]})
    previous = next(item for item in REPORT_MODULES if item.module_id == "oci_year_pre")
    current = next(item for item in REPORT_MODULES if item.module_id == "oci_year_lat")
    assert module_rows(rows, previous)["Period end"].tolist() == ["2024-12-31"]
    assert module_rows(rows, current)["Period end"].tolist() == ["2025-12-31"]
    assert module_rows(rows.iloc[1:], previous).empty


def test_movement_charts_show_only_latest_selected_year():
    records = demo_records()
    shown = report_modules_for_rows(records)
    shown_ids = {module.module_id for module in shown}
    assert COMPARATIVE_MOVEMENT_IDS == {"oci_year_pre", "csm_comp_pre"}
    assert not shown_ids.intersection(COMPARATIVE_MOVEMENT_IDS)
    assert {module.module_id for module in shown if "movement" in module.title.lower()} == (
        shown_ids.intersection(MOVEMENT_MODULE_IDS)
    )
    for module in shown:
        if module.module_id not in MOVEMENT_MODULE_IDS:
            continue
        plotted = movement_chart_rows(module_rows(records, module), module)
        if not plotted.empty:
            assert set(plotted["Period end"].astype(str).str[:4]) == {"2025"}
    csm_module = next(module for module in shown if module.module_id == "csm_table")
    source_rows = module_rows(records, csm_module)
    assert set(source_rows["Period end"].astype(str).str[:4]) == {"2024", "2025"}
    assert set(movement_chart_rows(source_rows, csm_module)["Period end"].astype(str).str[:4]) == {"2025"}


def test_movement_charts_follow_single_selected_year_without_affecting_other_charts():
    selected = demo_records()
    selected = selected[selected["Period end"].astype(str).eq("2024-12-31")]
    movement = next(module for module in REPORT_MODULES if module.module_id == "csm_table")
    regular = next(module for module in REPORT_MODULES if module.module_id == "csm_bal")
    assert set(movement_chart_rows(module_rows(selected, movement), movement)["Period end"]) == {"2024-12-31"}
    assert movement_chart_rows(selected, regular).equals(selected)


def test_investment_yield_is_a_disclosed_rate_and_equity_growth_is_derived():
    assert METRIC_BY_CODE["INV_YIELD"].kind == "rate"
    rows = pd.DataFrame({
        "Period end": ["2025-12-31"] * 3,
        "Metric code": ["INV_YIELD", "EQUITY_OPEN", "EQUITY"],
        "Value (millions)": [3.25, 100.0, 110.0],
        "PDF page": [50, 12, 12],
    })
    values, _ = analytical_ratio_rows(rows)
    found = dict(zip(values["Metric"], values["Amount"]))
    assert found["Investment yield"] == 3.25
    assert found["Equity year-on-year growth"] == 10.0


def test_csm_source_ratios_require_matching_note_page():
    assert RATIO_MODULE_LABELS["csm_ratio_trend"] == (
        "CSM release / opening CSM", "New business CSM / opening CSM",
    )
    rows = pd.DataFrame({
        "Period end": ["2025-12-31"] * 3,
        "Metric code": ["CSM_OPEN", "CSM_RELEASE", "CSM_NEW"],
        "Value (millions)": [100.0, -15.0, 25.0],
        "PDF page": [62, 62, 62],
    })
    values, _ = analytical_ratio_rows(rows)
    found = dict(zip(values["Metric"], values["Amount"]))
    assert found["CSM release / opening CSM"] == 15.0
    assert found["New business CSM / opening CSM"] == 25.0
    rows.loc[2, "PDF page"] = 63
    values, gaps = analytical_ratio_rows(rows)
    assert "New business CSM / opening CSM" not in set(values["Metric"])
    assert "New business CSM / opening CSM" in set(gaps["Ratio"])


def test_redundant_revenue_note_chart_and_partial_profit_mix_are_hidden():
    from pathlib import Path

    workbook = (Path(__file__).resolve().parents[1] / "outputs" /
                "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx")
    records = pd.read_excel(workbook, sheet_name="Records")
    for selected in (records, *(group for _, group in records.groupby("Company"))):
        ids = {module.module_id for module in report_modules_for_rows(selected)}
        assert "hk_insurance_revenue_detail" not in ids
        assert "inc_total" in ids
    yf = records[records["Company"].eq("YF Life")]
    assert "prof_mix" not in {module.module_id for module in report_modules_for_rows(yf)}
    assert "perf_total" in {module.module_id for module in report_modules_for_rows(yf)}
    assert "prof_mix" in {module.module_id for module in report_modules_for_rows(records)}


def test_revenue_note_chart_returns_when_its_value_is_distinct():
    rows = pd.DataFrame({
        "Document ID": ["X_2025", "X_2025"],
        "Period end": ["2025-12-31", "2025-12-31"],
        "Metric code": ["INS_REVENUE", "INS_REVENUE_NOTE_TOTAL"],
        "Value (millions)": [100.0, 99.0],
    })
    ids = {module.module_id for module in report_modules_for_rows(rows)}
    assert "hk_insurance_revenue_detail" in ids
