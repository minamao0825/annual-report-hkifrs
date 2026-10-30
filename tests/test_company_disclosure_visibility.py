"""Company-specific explanations follow the insurer shown in the report."""

import pytest

from hkifrs17.external import load_analysis_records
from hkifrs17.investment_note import (
    investment_note_captions, investment_note_rows, net_investment_explanations,
)
from hkifrs17.oci_analysis import oci_comparison_notes, oci_comparison_rows
from hkifrs17.oci_waterfall import oci_waterfall_notes, oci_waterfall_rows
from hkifrs17.report_modules import module_company_disclosure_notes
from hkifrs17.service_result import service_result_component_rows, service_result_notes


COMPANIES = ("FWD Life Bermuda", "Sun Life Hong Kong", "YF Life")
PERIODS = ["2024-12-31", "2025-12-31"]
OTHER_NAMES = {
    "FWD Life Bermuda": ("Sun Life", "YF"),
    "Sun Life Hong Kong": ("FWD", "YF"),
    "YF Life": ("FWD", "Sun Life"),
}


@pytest.mark.parametrize("selected_company", COMPANIES)
def test_disclosures_do_not_name_unselected_insurers(selected_company):
    records = load_analysis_records()
    selected = records.loc[records["Company"].eq(selected_company)]
    investment = investment_note_rows(selected, "result_pl_components")
    service = service_result_component_rows(selected)
    oci = oci_comparison_rows(selected)
    waterfall, _ = oci_waterfall_rows(selected, [selected_company], PERIODS)

    notes = (
        net_investment_explanations([selected_company])
        + investment_note_captions(investment)
        + service_result_notes(service)
        + oci_comparison_notes(oci, [selected_company], PERIODS)
        + oci_waterfall_notes(waterfall)
        + module_company_disclosure_notes("inv_return", [selected_company])
        + module_company_disclosure_notes("csm_maturity_table", [selected_company])
    )
    assert notes
    for other_name in OTHER_NAMES[selected_company]:
        assert all(other_name not in note for note in notes)
