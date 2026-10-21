"""The delivered workbook can be imported without weakening the review gate."""

from pathlib import Path

import hkifrs17.external as external
from hkifrs17.demo import demo_records


WORKBOOK = Path(__file__).resolve().parents[1] / "outputs" / "HK_IFRS17_FWD_YF_SunLife_2025_verified.xlsx"
LATEST = Path(__file__).resolve().parents[1] / "outputs" / "HK_IFRS17_FWD_YF_SunLife_2024_2025_latest.xlsx"


def test_three_filing_workbook_recomputes_checks_and_is_idempotent(tmp_path, monkeypatch):
    source = WORKBOOK.read_bytes()
    records, profiles, checks = external.validate_external_workbook(source)
    assert len(records) == 314
    assert profiles == []
    assert set(records["Period end"]) == {"2025-12-31"}
    assert checks["Result"].value_counts().to_dict() == {"Missing inputs": 15, "Pass": 36}
    indexed = checks.set_index(["Document ID", "Check ID"])
    assert indexed.loc[("SUN_2025", "REV_NONPAA_COMP"), "Result"] == "Pass"
    assert indexed.loc[("SUN_2025", "CSM_ROLL"), "Result"] == "Pass"
    assert indexed.loc[("YF_2025", "INS_NET_ROLL"), "Result"] == "Pass"
    assert indexed.loc[("YF_2025", "REINS_NET_ROLL"), "Result"] == "Pass"
    monkeypatch.setattr(external, "EXTERNAL_RECORDS_FILE", tmp_path / "external_records.json")
    first_count, _ = external.save_external_workbook(source)
    second_count, _ = external.save_external_workbook(source)
    assert first_count == second_count == 314
    assert len(external.load_external()) == 314
    monkeypatch.setattr(external, "load_integrated", lambda: demo_records("YF_2025"))
    combined = external.load_analysis_records()
    assert len(combined) == 314
    assert set(combined["Period end"]) == {"2025-12-31"}


def test_aligned_workbook_imports_reported_values_only():
    records, profiles, checks = external.validate_external_workbook(LATEST.read_bytes())
    assert profiles == []
    assert len(records) == 861
    assert set(records["Value status"]) == {"Reported"}
    assert set(records["Review status"]) == {"Verified"}
    assert len(checks) == 102
    assert not checks["Result"].eq("Difference").any()
