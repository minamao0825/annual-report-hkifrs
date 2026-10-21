"""The combined workbook retains scope, units and the import review gate."""

from pathlib import Path

import hkifrs17.external as external
import pandas as pd
from hkifrs17.catalog import PILOT_FILINGS


WORKBOOK = Path(__file__).resolve().parents[1] / "outputs" / "HK_IFRS17_FWD_YF_SunLife_2024_2025_verified.xlsx"
RESOLVED = Path(__file__).resolve().parents[1] / "outputs" / "HK_IFRS17_FWD_YF_SunLife_2024_2025_highlights_updated.xlsx"


def test_combined_2024_2025_workbook_imports_with_recomputed_checks(monkeypatch):
    # Simulate importing into an installation that knows only the pilot 2025
    # profiles. FWD's percentage rows use "%" rather than its USD currency.
    monkeypatch.setattr(external, "all_filings", lambda: list(PILOT_FILINGS))
    records, profiles, checks = external.validate_external_workbook(WORKBOOK.read_bytes())
    assert len(records) == 627
    assert {profile["document_id"] for profile in profiles} == {
        "FWD_2024", "YF_2024", "SUN_GROUP_2024"
    }
    assert checks["Result"].value_counts().to_dict() == {"Pass": 71, "Missing inputs": 31}
    mandatory = checks[checks["Check ID"].isin(["PRIMARY", "SERVICE", "BALANCE"])]
    assert len(mandatory) == 18 and mandatory["Result"].eq("Pass").all()
    assert set(records["Period end"]) == {"2024-12-31", "2025-12-31"}
    sun = records[records["Company"].str.startswith("Sun Life Hong Kong")]
    assert set(sun["Company"]) == {
        "Sun Life Hong Kong (Consolidated)", "Sun Life Hong Kong"
    }
    assert sun.groupby("Company")["Scope"].nunique().eq(1).all()


def test_followup_review_has_source_fields_and_preserves_unresolved_status(monkeypatch):
    monkeypatch.setattr(external, "all_filings", lambda: list(PILOT_FILINGS))
    records, profiles, checks = external.validate_external_workbook(RESOLVED.read_bytes())
    assert len(records) == 662
    assert len(profiles) == 3
    assert checks["Result"].value_counts().to_dict() == {
        "Pass": 86, "Not applicable": 12, "Missing inputs": 4,
    }
    review = pd.read_excel(RESOLVED, sheet_name="Missing review")
    assert len(review) == 31
    assert review["Result"].value_counts().to_dict() == {
        "Pass": 15, "Not applicable": 12, "Missing inputs": 4,
    }
    assert set(review.loc[review["Result"].eq("Missing inputs"), "Document ID"]) == {
        "YF_2024", "YF_2025",
    }
    csm = records[records["Metric code"].isin(["CSM_OPEN", "CSM_NET_MOVEMENT", "CSM_CLOSE"])]
    assert {"YF_2024", "YF_2025", "SUN_GROUP_2024"}.issubset(set(csm["Document ID"]))
    yf_highlights = records[
        records["Document ID"].isin(["YF_2024", "YF_2025"])
        & records["Metric code"].isin(["CSM_NEW", "CSM_RELEASE", "INS_ASSETS"])
    ]
    assert len(yf_highlights) == 6
    assert yf_highlights.groupby("Document ID")["Metric code"].nunique().to_dict() == {
        "YF_2024": 3, "YF_2025": 3,
    }
    highlights = pd.read_excel(RESOLVED, sheet_name="Financial Highlights", header=4, nrows=3)
    assert highlights["Company"].tolist() == [
        "FWD Life Bermuda", "Sun Life Hong Kong", "YF Life",
    ]
    assert highlights["New business CSM growth"].tolist() == [0.65, 0.75, 1.39]

