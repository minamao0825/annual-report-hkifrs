"""The restored appendix follows the verified filing scope and reconciliations."""

from hkifrs17.appendix_tables import (
    insurance_service_appendix_tables, new_business_appendix_tables,
)
from hkifrs17.external import load_analysis_records
from hkifrs17.report_ui import render_appendix_year_tables
from hkifrs17 import report_ui


COMPANIES = ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]
PERIODS = ["2024-12-31", "2025-12-31"]


def _cell(frame, item, company):
    column = next(column for column in frame.columns if column.startswith(company + " ("))
    return frame.loc[frame["Item"].eq(item), column].iloc[0]


def test_insurance_service_appendix_keeps_method_gaps_and_yf_signs():
    tables = insurance_service_appendix_tables(
        load_analysis_records(), COMPANIES, PERIODS,
        display_mode="HKD converted", decimals=1,
    )
    assert list(tables) == PERIODS
    prior, current = tables.values()
    assert _cell(current, "Net insurance service result", "FWD Life Bermuda") == "2,285.0"
    assert _cell(current, "Net insurance service result", "Sun Life Hong Kong") == "1,974.0"
    assert _cell(current, "Net insurance service result", "YF Life") == "809.8"
    assert _cell(current, "Non-PAA insurance service expenses", "YF Life") == "Not disclosed"
    assert _cell(current, "PAA insurance service expenses", "YF Life") == "Not disclosed"
    assert _cell(current, "Policyholder taxes charged", "FWD Life Bermuda") == "Not disclosed"
    assert _cell(current, "Policyholder taxes charged", "Sun Life Hong Kong") == "276.0"
    yf_column = next(column for column in current.columns
                     if column.startswith("YF Life ("))
    yf_loss_rows = current.loc[current["Item"].eq("Onerous contract losses and reversals"),
                               yf_column].tolist()
    assert yf_loss_rows == ["Not disclosed", "43.7‡"]
    assert _cell(prior, "Net insurance service result", "YF Life") == "633.1"


def test_new_business_appendix_uses_matching_initial_recognition_and_prior_year():
    tables = new_business_appendix_tables(
        load_analysis_records(), COMPANIES, PERIODS,
        display_mode="HKD converted", decimals=1,
    )
    prior, current = tables.values()
    assert _cell(current, "New profitable insurance contracts: CSM", "FWD Life Bermuda") == "5,299.6"
    assert _cell(current, "Initial loss component from new onerous business", "FWD Life Bermuda").startswith("(")
    assert _cell(current, "Total PV of future cash inflows from new business", "YF Life") == "20,678.6†"
    assert _cell(current, "New business IFRS profit margin", "YF Life") == "8.8%†"
    assert _cell(current, "New-business CSM year-on-year growth", "YF Life") == "139.4%†"
    assert _cell(prior, "New-business CSM year-on-year growth", "YF Life") == "Not available"


def test_appendix_renderer_marks_missing_and_keeps_year_order(monkeypatch):
    markup = []
    monkeypatch.setattr(report_ui.st, "html", markup.append)
    tables = new_business_appendix_tables(
        load_analysis_records(), COMPANIES, PERIODS,
    )
    render_appendix_year_tables(tables, tracked_company="YF Life",
                                unit_label="HKD millions")
    assert len(markup) == 2
    assert "2024YE" in markup[0] and "2025YE" in markup[1]
    assert "Unit: HKD millions" in markup[0]
    assert 'class="unavailable"' in markup[0]
    assert "tracked-column" in markup[1]
