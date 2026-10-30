"""Investment charts use verified P&L values and reconciled components."""

import json
import math
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.charts import investment_note_period_bars, peer_investment_note_panels
from hkifrs17.external import load_analysis_records
from hkifrs17.investment_note import investment_note_rows
from hkifrs17.report_modules import report_modules_for_rows


def _amount(rows, company, year):
    selected = rows.loc[
        rows["Company"].eq(company) & rows["Period"].eq(f"{year}-12-31"), "Amount"
    ]
    assert len(selected) == 1
    return float(selected.iloc[0])


def test_net_investment_chart_uses_note_totals_and_reconciles_components():
    records = load_analysis_records()
    totals = investment_note_rows(records, "result_total")
    components = investment_note_rows(records, "result_components")
    represented = investment_note_rows(records, "result_representation")

    assert math.isclose(_amount(totals, "FWD Life Bermuda", 2025), 113.534, abs_tol=1e-6)
    assert math.isclose(_amount(totals, "FWD Life Bermuda", 2024), -10.735, abs_tol=1e-6)
    assert math.isclose(_amount(totals, "Sun Life Hong Kong", 2025), 521, abs_tol=1e-6)
    assert math.isclose(_amount(totals, "Sun Life Hong Kong", 2024), 261, abs_tol=1e-6)
    assert math.isclose(_amount(totals, "YF Life", 2025), 1339.296754, abs_tol=1e-6)
    assert math.isclose(_amount(totals, "YF Life", 2024), -451.593053, abs_tol=1e-6)
    for (company, period), group in components.groupby(["Company", "Period"]):
        expected = _amount(totals, company, int(period[:4]))
        assert math.isclose(group["Amount"].sum(), expected, abs_tol=1e-6)
    for (company, period), group in represented.groupby(["Company", "Period"]):
        expected = _amount(totals, company, int(period[:4]))
        assert math.isclose(group["Amount"].sum(), expected, abs_tol=1e-6)
    assert set(represented["Company"]) == {"FWD Life Bermuda", "YF Life"}
    fwd_split = represented[
        represented["Company"].eq("FWD Life Bermuda")
        & represented["Period"].eq("2025-12-31")
    ]
    assert fwd_split["Amount"].tolist() == [17.861, 95.673]


def test_return_components_match_note_totals_and_sun_life_basis():
    records = load_analysis_records()
    totals = investment_note_rows(records, "return_total")
    components = investment_note_rows(records, "return_components")
    for (company, period), group in components.groupby(["Company", "Period"]):
        assert math.isclose(
            group["Amount"].sum(), _amount(totals, company, int(period[:4])), abs_tol=1e-6
        )
    sun = components[
        components["Company"].eq("Sun Life Hong Kong")
        & components["Period"].eq("2025-12-31")
    ]
    assert sun["Amount"].tolist() == [4248, 8688, -285]
    assert set(sun["Presentation basis"]) == {"Profit or loss only"}
    assert math.isclose(_amount(totals, "FWD Life Bermuda", 2025), 1250.304, abs_tol=1e-6)


def test_pl_investment_views_exclude_oci_and_reconcile():
    records = load_analysis_records()
    expected_returns = {
        ("FWD Life Bermuda", 2025): 816.753,
        ("FWD Life Bermuda", 2024): 362.412,
        ("Sun Life Hong Kong", 2025): 12651,
        ("Sun Life Hong Kong", 2024): 3886,
        ("YF Life", 2025): 6122.878110,
        ("YF Life", 2024): 3706.398145,
    }
    expected_results = {
        ("FWD Life Bermuda", 2025): 17.861,
        ("FWD Life Bermuda", 2024): 17.268,
        ("Sun Life Hong Kong", 2025): 521,
        ("Sun Life Hong Kong", 2024): 261,
        ("YF Life", 2025): 907.742385,
        ("YF Life", 2024): 652.817506,
    }
    for total_view, component_view, expected in (
        ("return_pl_total", "return_pl_components", expected_returns),
        ("result_pl_total", "result_pl_components", expected_results),
    ):
        totals = investment_note_rows(records, total_view)
        components = investment_note_rows(records, component_view)
        assert set(totals["Presentation basis"]) == {"Profit or loss only"}
        assert set(components["Presentation basis"]) == {"Profit or loss only"}
        for (company, year), amount in expected.items():
            assert math.isclose(_amount(totals, company, year), amount, abs_tol=1e-6)
            component_amount = components.loc[
                components["Company"].eq(company)
                & components["Period"].eq(f"{year}-12-31"), "Amount"
            ].sum()
            assert math.isclose(component_amount, amount, abs_tol=1e-6)
    fwd = investment_note_rows(records, "result_pl_components")
    fwd = fwd.loc[fwd["Company"].eq("FWD Life Bermuda")
                  & fwd["Period"].eq("2025-12-31")]
    assert fwd["Amount"].tolist() == pytest.approx([816.753, -824.179, 27.984, -2.697])


def test_finance_pl_chart_reconciles_and_has_clean_tooltip():
    records = load_analysis_records()
    finance = investment_note_rows(records, "finance_pl_total")
    expected_finance = {
        ("FWD Life Bermuda", 2024): -344.170,
        ("FWD Life Bermuda", 2025): -796.195,
        ("Sun Life Hong Kong", 2024): -3625,
        ("Sun Life Hong Kong", 2025): -12130,
        ("YF Life", 2024): -2850.435354,
        ("YF Life", 2025): -4983.664418,
    }
    assert set(finance["Presentation basis"]) == {"Profit or loss only"}
    for (company, year), value in expected_finance.items():
        assert math.isclose(_amount(finance, company, year), value, abs_tol=1e-6)
    fwd = investment_note_rows(
        records[records["Company"].eq("FWD Life Bermuda")], "result_pl_total"
    )
    chart = investment_note_period_bars(fwd)
    spec = chart.to_dict()
    spec_text = json.dumps(spec)
    assert "17.861" in spec_text
    tooltips = spec["layer"][0]["encoding"]["tooltip"]
    assert all(item.get("field") not in {"Source", "Metric"} for item in tooltips)
    peer, excluded = peer_investment_note_panels(
        investment_note_rows(records, "result_pl_total"),
        companies=["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"],
        periods=["2024-12-31", "2025-12-31"],
    )
    assert peer is not None and not excluded
    assert "uw_profit" in {module.module_id for module in report_modules_for_rows(records)}
    assert "uw_profit" in {module.module_id for module in report_modules_for_rows(records.iloc[:0])}


def test_investment_note_rejects_mismatched_statement_value():
    records = load_analysis_records()
    bad = records.copy()
    mask = (
        bad["Document ID"].eq("FWD_2025")
        & bad["Period end"].eq("2025-12-31")
        & bad["Metric code"].eq("NET_INV_RESULT")
    )
    assert mask.sum() == 1
    bad.loc[mask, "Value (millions)"] = 0
    rows = investment_note_rows(bad, "result_pl_total")
    assert not ((rows["Company"].eq("FWD Life Bermuda"))
                & (rows["Period"].eq("2025-12-31"))).any()


@pytest.mark.parametrize("page,key", [
    ("05_insurer.py", "insurer"),
    ("06_peers.py", "peers"),
])
def test_secondary_investment_renders_note_charts(page, key):
    records = load_analysis_records()
    records = records.loc[records["Company"].eq("FWD Life Bermuda")]
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button
             if button.label == "Use saved verified data").click().run()
        assert not app.exception
        app.radio(key=f"{key}_secondary").set_value("Investment").run()
        assert not app.exception
        headings = [item.value for item in app.markdown]
        assert "#### Investment return" in headings
        assert "#### Investment return components" in headings
        assert "#### Net insurance and reinsurance finance result" in headings
        assert "#### Net investment result" in headings
        assert "#### Investment result components" in headings
        assert headings.index("#### Net insurance and reinsurance finance result") < headings.index("#### Net investment result")
        assert not any("Represented by profit or loss and OCI" in item for item in headings)
        assert not any("per note" in item for item in headings)
        assert not any("Profit-or-loss reconciliation" in item for item in headings)
        assert not any("Note references:" in item.value for item in app.caption)
        assert sum("Profit or loss (P&L) only; amounts recognised in OCI are excluded."
                   in item.value for item in app.caption) == (4 if key == "peers" else 5)
        assert any("Formula: Net insurance and reinsurance finance result" in item.value
                   for item in app.caption)
        assert any("Formula: Reported net investment result" in item.value
                   for item in app.caption)
        assert any("FWD Life Bermuda: the three-line subtotal" in item.value
                   for item in app.caption)
        assert not any("Sun Life" in item.value or "YF" in item.value
                       for item in app.caption)
        assert len(app.get("vega_lite_chart")) == 5
        app.radio(key=f"{key}_chart").set_value("uw_profit").run()
        assert not app.exception
        assert "#### Net insurance and reinsurance finance result" in [item.value for item in app.markdown]
        assert len(app.get("vega_lite_chart")) == 1
        app.radio(key=f"{key}_chart").set_value("inv_return_components").run()
        assert not app.exception
        assert "#### Investment return components" in [item.value for item in app.markdown]
        assert len(app.get("vega_lite_chart")) == 1
        app.radio(key=f"{key}_chart").set_value("inv_profit_components").run()
        assert not app.exception
        assert "#### Investment result components" in [item.value for item in app.markdown]
        assert len(app.get("vega_lite_chart")) == 1
