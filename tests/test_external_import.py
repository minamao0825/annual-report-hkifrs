"""The delivered workbook can be imported without weakening the review gate."""

from pathlib import Path
import json
import os

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
    monkeypatch.setattr(external, "EXTERNAL_IMPORTS_FILE", tmp_path / "external_imports.json")
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


def test_legacy_workbook_import_keeps_missing_image_evidence_blank():
    source = Path(__file__).resolve().parents[1] / "outputs" / "HKFRS17_Step5_6_current_data_upload.xlsx"
    records, _, checks = external.validate_external_workbook(source.read_bytes())
    assert len(records) == 656
    assert not checks["Result"].eq("Difference").any()
    evidence = ["Source table heading", "Source row", "Column heading",
                "Table year", "Unit evidence", "Evidence box"]
    assert records[evidence].fillna("").eq("").all().all()


def test_yf_2024_reinsurance_oci_matches_2025_report_comparative():
    """Physical PDF page 28 shows HKD 180,381,305 in its 2024 column."""
    records = external.load_external()
    cell = records.loc[(records["Document ID"] == "YF_2024")
                       & (records["Period end"] == "2024-12-31")
                       & (records["Metric code"] == "OCI_REINS_FINANCE")].iloc[0]
    assert cell["Original value"] == 180_381_305
    assert cell["Value (millions)"] == 180.381305


def test_legacy_integration_date_outweighs_copied_file_mtime(tmp_path, monkeypatch):
    source = external.load_external()
    imported = source.loc[source["Document ID"].eq("YF_2025")
                          & source["Metric code"].eq("INS_REVENUE")].head(1).copy()
    older = imported.copy()
    imported.loc[:, "Source label"] = "newer reviewed import"
    older.loc[:, "Source label"] = "older integrated snapshot"
    integrated_file = tmp_path / "integrated_records.xlsx"
    integrated_file.touch()
    os.utime(integrated_file, (2_000_000_000, 2_000_000_000))
    imports_file = tmp_path / "external_imports.json"
    imports_file.write_text(json.dumps({"YF_2025": 1_700_000_000}), encoding="utf-8")
    monkeypatch.setattr(external, "DATA", tmp_path)
    monkeypatch.setattr(external, "EXTERNAL_RECORDS_FILE", tmp_path / "external_records.json")
    monkeypatch.setattr(external, "EXTERNAL_IMPORTS_FILE", imports_file)
    monkeypatch.setattr(external, "load_integrated", lambda: older)
    monkeypatch.setattr(external, "load_external", lambda: imported)
    monkeypatch.setattr(external, "integration_status",
                        lambda: {"integrated_at_utc": "2022-01-01 00:00:00"})
    result = external.load_analysis_records()
    assert len(result) == 1
    assert result.iloc[0]["Source label"] == "newer reviewed import"
