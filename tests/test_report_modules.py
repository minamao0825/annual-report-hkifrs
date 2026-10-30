"""The two report pages share the source Step 7 inventory and HK exclusions."""

import json
import pandas as pd
import pytest

from hkifrs17.catalog import METRIC_BY_CODE
from hkifrs17.charts import analytical_ratio_rows, csm_ratio_trend_chart, peer_group_panels, period_bars
from hkifrs17.metric_blueprint import CHART_REQUIREMENTS
from hkifrs17.demo import demo_records
from hkifrs17.external import load_analysis_records
from hkifrs17 import report_ui
from hkifrs17.report_modules import (
    COMPARATIVE_MOVEMENT_IDS, EXCLUDED_CHART_METRIC_CODES, EXCLUDED_SOURCE_IDS,
    HIDDEN_REPORT_MODULE_IDS, MOVEMENT_MODULE_IDS,
    NET_RESULT_REPORTED_LABELS,
    RATIO_MODULE_LABELS, REPORT_MODULES, SOURCE_REPORT_MODULES,
    discount_rate_summary,
    confidence_level_summary,
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
    source_or_displayed = (*REPORT_MODULES, *(
        module for module in SOURCE_REPORT_MODULES
        if module.module_id in HIDDEN_REPORT_MODULE_IDS
    ))
    assert {code for module in source_or_displayed for code in module.metrics} >= {
        code for code, metric in METRIC_BY_CODE.items()
        if metric.kind != "rate" and code not in EXCLUDED_CHART_METRIC_CODES
    }
    assert HIDDEN_REPORT_MODULE_IDS == {"nb_margin_trend"}
    assert not HIDDEN_REPORT_MODULE_IDS.intersection(
        module.module_id for module in REPORT_MODULES
    )
    assert [(module.module_id, module.title) for module in REPORT_MODULES
            if module.section == "Appendix"] == [
        ("report_detail", "Insurance service result detail"),
        ("nbv_table", "New business information"),
    ]
    investment_return = next(item for item in REPORT_MODULES
                             if item.module_id == "inv_return")
    assert investment_return.metrics == ("INV_RETURN", "NET_INV_INCOME")
    assert investment_return.title == "Investment return"
    net_result = next(item for item in REPORT_MODULES if item.module_id == "inv_profit")
    assert net_result.metrics == ("NET_INV_RESULT",)
    assert net_result.title == "Net investment result"
    net_finance = next(item for item in REPORT_MODULES if item.module_id == "uw_profit")
    assert net_finance.metrics == ("INS_FINANCE_PL", "REINS_FINANCE_PL")
    assert net_finance.title == "Net insurance and reinsurance finance result"
    assert [item.module_id for item in REPORT_MODULES
            if item.section == "Key financial statement analysis"
            and item.subsection == "Investment"] == [
                "inv_return", "inv_return_components",
                "uw_profit",
                "inv_profit", "inv_profit_components",
            ]
    assert not any({"INV_RETURN_TOTAL", "NET_INV_RESULT_TOTAL"} & set(item.metrics)
                   for item in REPORT_MODULES)
    assert "comprehensive solvency" not in " ".join(
        item.title.lower() for item in REPORT_MODULES
    )
    assert RATIO_MODULE_LABELS["six_dimensional_charts"] == (
        "Return on average equity", "Insurance CSM year-on-year growth",
        "Equity / total assets", "Equity year-on-year growth",
    )


def test_yf_spot_ranges_are_not_invented_when_source_cells_are_absent():
    records = load_analysis_records()
    spots = records.loc[
        records["Company"].eq("YF Life")
        & records["Metric code"].str.contains("_SPOT_")
    ]
    assert spots.empty
    summary = discount_rate_summary(
        records, ["YF Life"], ["2025-12-31", "2024-12-31"],
    )
    assert summary.empty
    assert list(summary.columns) == [
        "Company", "Currency / portfolio", "Disclosed rate", "Value form", "Year",
    ]


def test_fwd_and_sun_life_discount_rates_keep_disclosed_tenor_and_basis():
    records = load_analysis_records()
    summary = discount_rate_summary(
        records, ["FWD Life Bermuda", "Sun Life Hong Kong"],
        ["2025-12-31", "2024-12-31"],
    )
    assert len(summary) == 16
    selected = summary.set_index(["Company", "Currency / portfolio", "Disclosed rate", "Year"])
    fwd = selected.loc[("FWD Life Bermuda (Company)", "HKD",
                        "Spot rate with illiquidity premium", "2025YE")]
    assert fwd["1Y"] == "3.44%"
    sun = selected.loc[("Sun Life Hong Kong (Company)", "RMB NP / RMB UL",
                        "Spot rate with illiquidity premium", "2025YE")]
    assert sun["1Y"] == "1.74%"
    other = selected.loc[("Sun Life Hong Kong (Company)",
                          "RMB NP / RMB UL", "Spot rate with illiquidity premium", "2024YE")]
    assert other["5Y"] == "1.84%"
    assert other["Value form"] == "Point"
    assert not summary.loc[summary["Company"].eq("Sun Life Hong Kong (Company)"),
                           "Disclosed rate"].eq("Illiquidity premium").any()
    derived = records.loc[
        records["Company"].eq("Sun Life Hong Kong")
        & records["Metric code"].eq("DISCOUNT_CNY_1Y_ILP")
    ]
    assert derived["Value status"].eq("Reported").all()
    source_cells = records.loc[
        records["Company"].eq("Sun Life Hong Kong")
        & (records["Metric code"].str.startswith("DISCOUNT_OTHER_PORTFOLIOS_")
           | records["Metric code"].str.endswith("_PREMIUM"))
    ]
    assert source_cells.empty


def test_discount_rate_table_adapts_to_new_company_tenor_and_scope(monkeypatch):
    rows = pd.DataFrame([
        ("Company", "2024-12-31", "DISCOUNT_EUR_3Y_RF", 2.50),
        ("Company", "2025-12-31", "DISCOUNT_EUR_3Y_RF", 2.60),
        ("Company", "2025-12-31", "DISCOUNT_EUR_30Y_RF", 3.10),
        ("Consolidated", "2025-12-31", "DISCOUNT_EUR_3Y_RF", 4.00),
    ], columns=["Scope", "Period end", "Metric code", "Value (millions)"])
    rows["Company"] = "Future Life"
    rows["Value status"] = "Reported"
    rows["Source label"] = "Disclosed EUR risk-free spot rate"
    summary = discount_rate_summary(rows, ["Future Life"],
                                    ["2024-12-31", "2025-12-31"])
    assert summary.columns.tolist()[-2:] == ["3Y", "30Y"]
    selected = summary.set_index(["Company", "Year"])
    assert selected.loc[("Future Life (Company)", "2024YE"), "3Y"] == "2.50%"
    assert selected.loc[("Future Life (Company)", "2025YE"), "30Y"] == "3.10%"
    assert selected.loc[("Future Life (Consolidated)", "2025YE"), "3Y"] == "4.00%"
    assert selected.loc[("Future Life (Consolidated)", "2024YE"), "3Y"] == "Not disclosed"

    markup = []
    monkeypatch.setattr(report_ui.st, "html", markup.append)
    report_ui.render_discount_rate_table(summary, tracked_company="Future Life")
    assert len(markup) == 2
    assert 'discount-rate-page-start' not in markup[0]
    assert 'discount-rate-page-start' not in markup[1]
    assert all('<th>Currency / portfolio</th>' in part and '<th>3Y</th>' in part
               for part in markup)
    assert all('<th>Company</th>' not in part for part in markup)
    assert all(part.index("2024YE") < part.index("2025YE") for part in markup)


def test_discount_rate_print_pages_pack_short_company_tables(monkeypatch):
    records = load_analysis_records()
    summary = discount_rate_summary(
        records, ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"],
        ["2024-12-31", "2025-12-31"],
    )
    assert summary.groupby("Company", sort=False).size().tolist() == [12, 4]

    markup = []
    monkeypatch.setattr(report_ui.st, "html", markup.append)
    report_ui.render_discount_rate_table(summary)
    assert len(markup) == 2
    assert ["discount-rate-page-start" in part for part in markup] == [
        False, True,
    ]


def test_discount_rate_print_pages_isolate_tables_over_twelve_rows(monkeypatch):
    company_sizes = [("Large", 13), ("Small A", 4), ("Small B", 8), ("Small C", 5)]
    frame = pd.DataFrame(
        [
            (company, f"Currency {index}", "Spot rate", "Point", "2025YE", "1.00%")
            for company, size in company_sizes for index in range(size)
        ],
        columns=["Company", "Currency / portfolio", "Disclosed rate",
                 "Value form", "Year", "1Y"],
    )
    markup = []
    monkeypatch.setattr(report_ui.st, "html", markup.append)
    report_ui.render_discount_rate_table(frame)
    assert ["discount-rate-page-start" in part for part in markup] == [
        False, True, False, True,
    ]


def test_company_confidence_levels_keep_sun_life_missing_visible():
    records = load_analysis_records()
    summary = confidence_level_summary(
        records, ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"],
        ["2025-12-31", "2024-12-31"],
    ).set_index("Company")
    assert list(summary.columns) == ["2024YE", "2025YE"]
    assert summary.loc["FWD Life Bermuda (Company)"].tolist() == ["75%", "75%"]
    assert summary.loc["YF Life (Consolidated)"].tolist() == ["75%", "75%"]
    assert summary.loc["Sun Life Hong Kong (Company)"].tolist() == [
        "Not disclosed", "Not disclosed",
    ]


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
        "CSM amortization ratio", "New business CSM / CSM release",
    )
    module = next(item for item in REPORT_MODULES if item.module_id == "csm_ratio_trend")
    assert module.title == "CSM amortization and replenishment trends"
    assert module.metrics == ("CSM_CLOSE", "CSM_NEW", "CSM_RELEASE")
    rows = pd.DataFrame({
        "Period end": ["2025-12-31"] * 3,
        "Metric code": ["CSM_CLOSE", "CSM_RELEASE", "CSM_NEW"],
        "Value (millions)": [85.0, -15.0, 25.0],
        "PDF page": [62, 62, 62],
        "Document ID": ["FILING_2025"] * 3,
        "Scope": ["Company"] * 3,
    })
    values, _ = analytical_ratio_rows(rows)
    amortization = values.loc[values["Metric"].eq("CSM amortization ratio")].iloc[0]
    assert amortization["Amount"] == 15.0
    ratio = values.loc[values["Metric"].eq("New business CSM / CSM release")].iloc[0]
    assert ratio["Amount"] == 25 / 15
    assert ratio["Compared with 1×"] == "Above 1×"
    rows.loc[2, "Value (millions)"] = 10.0
    values, _ = analytical_ratio_rows(rows)
    assert values.loc[values["Metric"].eq("New business CSM / CSM release"),
                      "Compared with 1×"].iloc[0] == "Below 1×"
    rows.loc[2, "PDF page"] = 63
    values, gaps = analytical_ratio_rows(rows)
    assert "CSM amortization ratio" in set(values["Metric"])
    assert "New business CSM / CSM release" not in set(values["Metric"])
    assert "New business CSM / CSM release" in set(gaps["Ratio"])
    rows.loc[2, "PDF page"] = 62
    rows.loc[1, "Value (millions)"] = 0.0
    values, gaps = analytical_ratio_rows(rows)
    assert values.loc[values["Metric"].eq("CSM amortization ratio"), "Amount"].iloc[0] == 0.0
    assert "New business CSM / CSM release" not in set(values["Metric"])
    assert "New business CSM / CSM release" in set(gaps["Ratio"])


def test_two_csm_trend_panels_use_disclosed_years_and_100_percent_reference():
    companies = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
    periods = ["2024-12-31", "2025-12-31"]
    chart, gaps, rows = csm_ratio_trend_chart(
        load_analysis_records(), companies, periods,
        tracked_company="FWD Life Bermuda",
    )
    assert chart is not None and gaps.empty
    spec = chart.to_dict()
    assert spec["facet"]["field"] == "Display metric"
    assert spec["columns"] == 2
    assert spec["resolve"]["scale"]["y"] == "independent"
    assert spec["spec"]["layer"][0]["mark"]["type"] == "rule"
    assert spec["spec"]["layer"][0]["mark"]["strokeDash"] == [5, 4]
    assert spec["spec"]["layer"][1]["mark"]["type"] == "line"
    assert spec["spec"]["layer"][1]["mark"]["strokeDash"] == [5, 4]
    assert spec["spec"]["layer"][1]["encoding"]["opacity"]["condition"]["test"]
    tooltip = spec["spec"]["layer"][1]["encoding"]["tooltip"]
    assert not any(item.get("field") in {"Source", "Metric"} for item in tooltip)
    assert len(rows) == 12
    replenishment = rows.loc[rows["Display metric"].eq("CSM replenishment ratio")]
    assert replenishment["Value (%)"].gt(100).all()
    assert replenishment["Comparison"].eq("Above 100%").all()
    fwd_2024_amortization = rows.loc[
        rows["Company"].eq("FWD Life Bermuda")
        & rows["Period"].eq("2024-12-31")
        & rows["Display metric"].eq("CSM amortization ratio")
    ].iloc[0]
    assert fwd_2024_amortization["Value label"] == "10.30%"
    yf_2025 = rows.loc[rows["Company"].eq("YF Life")
                       & rows["Period"].eq("2025-12-31")]
    assert yf_2025.loc[yf_2025["Display metric"].eq("CSM amortization ratio"),
                       "Value (%)"].iloc[0] == pytest.approx(
                           100 * 781.157687 / (10761.764934 + 781.157687))
    incomplete = load_analysis_records().loc[lambda data: ~(
        data["Company"].eq("YF Life")
        & data["Period end"].eq("2024-12-31")
        & data["Metric code"].eq("CSM_NEW")
    )]
    _, gaps, partial = csm_ratio_trend_chart(incomplete, companies, periods)
    yf_2024 = partial.loc[partial["Company"].eq("YF Life")
                          & partial["Period"].eq("2024-12-31")]
    assert set(yf_2024["Display metric"]) == {"CSM amortization ratio"}
    assert ((gaps["Company"].eq("YF Life"))
            & (gaps["Ratio"].eq("New business CSM / CSM release"))).any()


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
