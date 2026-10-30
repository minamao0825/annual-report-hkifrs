"""Matching fulfilment-cash-flow ratio and annual peer mean lines."""

import math
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.charts import analytical_ratio_rows, company_year_comparison_bars
from hkifrs17.external import load_analysis_records


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
LABEL = "Insurance CSM / matching fulfilment cash flows"
PERIODS = ["2024-12-31", "2025-12-31"]


def test_ratio_keeps_pvfcf_plus_risk_adjustment_denominator() -> None:
    records = load_analysis_records()
    for company in COMPANIES:
        source = records.loc[
            records["Company"].eq(company)
            & records["Metric code"].isin((
                "INS_NONPAA_CSM_CLOSE", "INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE",
            ))
        ]
        values, gaps = analytical_ratio_rows(source)
        assert not gaps.loc[gaps["Ratio"].eq(LABEL)].shape[0]
        for period in PERIODS:
            actual = values.loc[values["Period"].eq(period) & values["Metric"].eq(LABEL),
                                "Amount"].iloc[0]
            lookup = source.loc[source["Period end"].eq(period)].set_index("Metric code")[
                "Value (millions)"
            ]
            expected = 100 * abs(lookup["INS_NONPAA_CSM_CLOSE"]) / abs(
                lookup["INS_NONPAA_PVFCF_CLOSE"] + lookup["INS_NONPAA_RA_CLOSE"]
            )
            assert math.isclose(actual, expected, abs_tol=1e-10)


def test_ratio_does_not_mix_filing_inputs_with_the_same_note_page() -> None:
    records = load_analysis_records()
    source = records.loc[
        records["Company"].eq("FWD Life Bermuda")
        & records["Period end"].eq("2025-12-31")
        & records["Metric code"].isin((
            "INS_NONPAA_CSM_CLOSE", "INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE",
        ))
    ].copy()
    source.loc[source["Metric code"].eq("INS_NONPAA_RA_CLOSE"), "Document ID"] = "OTHER_FILING"
    values, gaps = analytical_ratio_rows(source)
    assert values.empty
    assert not gaps.loc[gaps["Ratio"].eq(LABEL)].empty


def test_each_mean_line_uses_three_available_company_ratios() -> None:
    chart, excluded, summary = company_year_comparison_bars(
        load_analysis_records(),
        ["INS_NONPAA_CSM_CLOSE", "INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE"],
        companies=COMPANIES, periods=PERIODS, ratio_label=LABEL,
        yearly_mean_lines=True, decimals=0,
    )
    assert not excluded
    assert "2024YE: 17.07% (n=3)" in summary
    assert "2025YE: 17.08% (n=3)" in summary
    spec = chart.to_dict(validate=True)
    rules = [layer for layer in spec["layer"] if layer["mark"]["type"] == "rule"]
    assert len(rules) == 2
    assert [rule["mark"]["strokeDash"] for rule in rules] == [[3, 5], [9, 6]]
    assert all(rule["encoding"]["color"]["scale"]["range"] ==
               ["#7213EA", "#00338D"] for rule in rules)
    means = [spec["datasets"][rule["data"]["name"]][0] for rule in rules]
    assert [(row["Period label"], row["Insurers"]) for row in means] == [
        ("2024YE", 3), ("2025YE", 3),
    ]
    assert [row["Mean"] for row in means] == pytest.approx([17.0718009169, 17.0844383865])
    assert [row["Mean label"] for row in means] == [
        "2024YE mean: 17.07%", "2025YE mean: 17.08%",
    ]


def test_mean_count_tracks_visible_insurers() -> None:
    chart, excluded, summary = company_year_comparison_bars(
        load_analysis_records(),
        ["INS_NONPAA_CSM_CLOSE", "INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE"],
        companies=COMPANIES[:2], periods=PERIODS, ratio_label=LABEL,
        yearly_mean_lines=True,
    )
    assert not excluded
    assert "(n=2)" in summary
    spec = chart.to_dict()
    rules = [layer for layer in spec["layer"] if layer["mark"]["type"] == "rule"]
    assert len(rules) == 2
    assert all(spec["datasets"][rule["data"]["name"]][0]["Insurers"] == 2
               for rule in rules)


@pytest.mark.parametrize("page,key", [
    ("05_insurer.py", "insurer"), ("06_peers.py", "peers"),
])
def test_csm_ratio_page_explains_formula(page: str, key: str) -> None:
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    records = load_analysis_records()
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button
             if button.label == "Use saved verified data").click().run()
        app.radio(key=f"{key}_secondary").set_value("CSM").run()
        app.radio(key=f"{key}_chart").set_value("csm_ratio").run()
        assert not app.exception
        assert len(app.get("vega_lite_chart")) == 1
        assert any("PVFCF) + closing non-PAA risk adjustment (RA)|" in item.value
                   for item in app.caption)
        if key == "peers":
            assert not any("Equal-weight mean" in item.value for item in app.caption)
            assert not any("Only calculate from an explicitly matching" in item.value
                           for item in app.caption)
