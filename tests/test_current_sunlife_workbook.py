"""Current reviewed workbook uses Sun Life's same-scope 2025 filing columns."""

from pathlib import Path

from hkifrs17.external import validate_external_workbook


WORKBOOK = (
    Path(__file__).resolve().parents[1]
    / "outputs/HK_IFRS17_FWD_YF_SunLife_2024_2025_latest.xlsx"
)


def test_current_sunlife_workbook_uses_company_comparatives():
    records, profiles, checks = validate_external_workbook(WORKBOOK.read_bytes())
    assert len(records) == 861
    assert profiles == []
    assert "SUN_GROUP_2024" not in set(records["Document ID"])
    sun = records[records["Company"].eq("Sun Life Hong Kong")]
    assert sun.groupby("Period end").size().to_dict() == {
        "2024-12-31": 140,
        "2025-12-31": 140,
    }
    assert set(sun["Document ID"]) == {"SUN_2025"}
    assert set(sun["Scope"]) == {"Company"}
    prior = sun[sun["Period end"].eq("2024-12-31")].set_index("Metric code")
    assert prior.loc["PROFIT", "Value (millions)"] == 774
    assert prior.loc["TOTAL_ASSETS", "Value (millions)"] == 116664
    assert prior.loc["NET_INV_INCOME", "Value (millions)"] == 3886
    assert prior.loc["REV_POLICYHOLDER_TAX", "Value (millions)"] == 141
    assert prior["Audit status"].eq("Unaudited 2024 comparative").all()
    assert not checks["Result"].eq("Difference").any()
    required = checks[checks["Check ID"].isin({"PRIMARY", "SERVICE", "BALANCE"})]
    assert len(required) == 18 and required["Result"].eq("Pass").all()
