"""Insurance-only transition-category shares and report navigation."""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from hkifrs17.csm_transition import csm_transition_chart, csm_transition_rows
from hkifrs17.external import load_analysis_records
from hkifrs17.report_modules import REPORT_MODULES
from hkifrs17.report_notes import combine_year_notes


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
PERIODS = ["2024-12-31", "2025-12-31"]


def test_insurance_shares_reconcile_and_sun_life_is_unavailable() -> None:
    rows, issues = csm_transition_rows(
        load_analysis_records(), COMPANIES, PERIODS, display_mode="HKD converted",
    )
    assert len(issues) == 2
    assert all("Sun Life Hong Kong" in issue for issue in issues)
    combined = combine_year_notes(issues, COMPANIES)
    assert len(combined) == 1
    assert combined[0].startswith("Sun Life Hong Kong 2024YE and 2025YE:")
    for company in ("FWD Life Bermuda", "YF Life"):
        for period in PERIODS:
            split = rows.loc[rows["Company"].eq(company) & rows["Period end"].eq(period)]
            assert split["Share"].sum() == pytest.approx(100)
            assert set(split["Category"]) == {
                "Fair value approach at transition", "Other insurance contracts",
            }
            assert split["Currency"].eq("HKD").all()
    sun = rows.loc[rows["Company"].eq("Sun Life Hong Kong")]
    assert sun["Status"].eq("Not disclosed").all()
    assert sun["Share"].isna().all()
    assert set(sun["Plot share"]) == {100.0}  # Grey placeholder, not data.
    assert not rows["Category"].str.contains("Reinsurance").any()


def test_modified_retrospective_category_appears_when_disclosed() -> None:
    records = load_analysis_records()
    base = records.loc[
        records["Company"].eq("YF Life")
        & records["Period end"].eq("2025-12-31")
        & records["Metric code"].eq("INS_CSM_OTHER_CLOSE")
    ].iloc[0].copy()
    modified = base.copy()
    modified["Metric code"] = "INS_CSM_MOD_CLOSE"
    modified["Value (millions)"] = 100.0
    records = records.copy()
    records.loc[base.name, "Value (millions)"] -= 100.0
    records.loc[len(records)] = modified
    rows, issues = csm_transition_rows(records, ["YF Life"], ["2025-12-31"])
    assert not issues
    assert "Modified retrospective approach at transition" in set(rows["Category"])
    assert rows["Share"].sum() == pytest.approx(100)


def test_a_selected_year_without_company_data_is_not_plotted_as_zero() -> None:
    rows, issues = csm_transition_rows(
        load_analysis_records(), ["FWD Life Bermuda"], ["2023-12-31"],
    )
    assert len(rows) == 1
    assert rows.iloc[0]["Status"] == "Not disclosed"
    assert rows["Share"].isna().all()
    assert any("2023YE" in issue for issue in issues)


def test_chart_has_three_category_legend_and_no_source_tooltip() -> None:
    rows, _ = csm_transition_rows(load_analysis_records(), COMPANIES, PERIODS)
    chart = csm_transition_chart(rows, COMPANIES)
    assert chart is not None
    spec = chart.to_dict()
    assert spec["facet"]["sort"] == [
        "FWD Life Bermuda (Company) · USD",
        "Sun Life Hong Kong (Company) · HKD",
        "YF Life (Consolidated) · HKD",
    ]
    bars = spec["spec"]["layer"][1]
    assert bars["encoding"]["x"]["scale"]["domain"] == [0, 100]
    assert bars["encoding"]["color"]["scale"]["domain"] == [
        "Fair value approach at transition",
        "Modified retrospective approach at transition",
        "Other insurance contracts",
    ]
    assert "Source" not in chart.to_json() and "Metric" not in chart.to_json()
    module = next(item for item in REPORT_MODULES if item.module_id == "csm_trans")
    assert "Reinsurance" not in module.title
    assert not any(code.startswith("REINS_") for code in module.metrics)


@pytest.mark.parametrize("page,key", [
    ("05_insurer.py", "insurer"), ("06_peers.py", "peers"),
])
def test_report_pages_render_transition_chart(page: str, key: str) -> None:
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    records = load_analysis_records()
    with patch("hkifrs17.external.load_analysis_records", return_value=records):
        app = AppTest.from_file(str(path), default_timeout=45).run()
        assert not app.exception
        next(button for button in app.button
             if button.label == "Use saved verified data").click().run()
        app.radio(key=f"{key}_secondary").set_value("CSM").run()
        app.radio(key=f"{key}_chart").set_value("csm_trans").run()
        assert not app.exception
        assert len(app.get("vega_lite_chart")) == 1
        assert any("Other insurance contracts are not a transition method" in item.value
                   for item in app.caption)
        if key == "peers":
            assert sum("complete insurance CSM category split" in item.value
                       for item in app.caption) == 1
