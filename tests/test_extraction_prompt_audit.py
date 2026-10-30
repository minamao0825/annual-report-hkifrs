"""Regression checks for the source errors found in the YF review."""

from hkifrs17.catalog import METRICS, PILOT_FILINGS
from hkifrs17.pdf import extraction_prompt


YF = next(filing for filing in PILOT_FILINGS if filing["document_id"] == "YF_2025")


def _metrics(*codes):
    return [metric for metric in METRICS if metric.code in codes]


def test_comparative_only_page_and_printed_unit_take_priority():
    prompt = extraction_prompt(
        YF, _metrics("INS_NOTE_PL_OCI"),
        ["Insurance and reinsurance contracts"], ("2024",), physical_page=123,
    )
    assert "only year(s) 2024" in prompt
    assert "Treat this as a hard limit" in prompt
    assert "continuation page in a later-year filing" in prompt
    assert "unit printed on THIS table overrides the filing unit hint" in prompt
    assert "HK$ million means source_unit HKD millions, not HKD" in prompt
    assert "visible year heading and unit" in prompt
    assert "Business-review highlights" in prompt


def test_contract_prompt_excludes_wrong_population_component_and_partial_movement():
    prompt = extraction_prompt(
        YF, _metrics("CSM_NET_MOVEMENT", "INS_NONPAA_NET_CLOSE",
                     "INS_LIABS_PAA_CLOSE", "REINS_NONPAA_NET_CLOSE",
                     "INS_LIABS_NOTE_MOVEMENT"),
        ["Insurance and reinsurance contracts"], physical_page=122,
    )
    assert "unprefixed CSM_* codes refer to insurance contracts issued" in prompt
    assert "Never fill them from a reinsurance-held CSM table" in prompt
    assert "remaining-coverage column excluding loss components" in prompt
    assert "method-level total, not one measurement component" in prompt
    assert "loss and OCI excludes cash flows" in prompt
    assert "current-year opening row belongs to" in prompt
