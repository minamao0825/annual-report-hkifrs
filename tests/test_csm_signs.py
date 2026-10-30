"""CSM presentation follows the disclosed sign convention, not insurer names."""

import pandas as pd
import pytest

from hkifrs17.checks import default_plan, evaluate_checks
from hkifrs17.csm_signs import orient_csm_values
from hkifrs17.data import normalize_records
from hkifrs17.external import load_external
from hkifrs17.storage import all_filings


def test_fwd_liability_sign_becomes_positive_balance_and_signed_bridge() -> None:
    rows = load_external()
    fwd = rows.loc[rows["Company"].eq("FWD Life Bermuda") &
                   rows["Period end"].eq("2025-12-31")].set_index("Metric code")
    assert fwd.at["CSM_CLOSE", "Original value"] == -2_450_689
    assert fwd.at["CSM_CLOSE", "Value (millions)"] == pytest.approx(2450.689)
    assert fwd.at["CSM_NEW", "Value (millions)"] == pytest.approx(680.897)
    assert fwd.at["INS_CSM_FV_CLOSE", "Value (millions)"] == pytest.approx(771.527)
    assert fwd.at["INS_CSM_OTHER_CLOSE", "Value (millions)"] == pytest.approx(1679.162)
    assert fwd.at["CSM_RELEASE", "Value (millions)"] == pytest.approx(-267.218)
    assert (fwd.at["CSM_OPEN", "Value (millions)"] +
            fwd.at["CSM_NET_MOVEMENT", "Value (millions)"] ==
            pytest.approx(fwd.at["CSM_CLOSE", "Value (millions)"]))
    assert fwd.at["CSM_MAT_REINS_1Y", "Value (millions)"] == pytest.approx(2.386)
    # A genuine offset within the reinsurance CSM remains negative.
    assert fwd.at["REINS_CSM_FV_CLOSE", "Value (millions)"] == pytest.approx(-3.505)
    assert (fwd.at["REINS_CSM_FV_CLOSE", "Value (millions)"] +
            fwd.at["REINS_CSM_OTHER_CLOSE", "Value (millions)"] ==
            pytest.approx(fwd.at["REINS_NONPAA_CSM_CLOSE", "Value (millions)"]))


def test_negative_convention_is_detected_for_an_unseen_filing_and_year() -> None:
    source = load_external()
    sample = source.loc[source["Company"].eq("FWD Life Bermuda") &
                        source["Period end"].eq("2025-12-31") &
                        source["Metric code"].isin((
                            "CSM_OPEN", "CSM_CLOSE", "CSM_NET_MOVEMENT", "CSM_NEW",
                            "CSM_RELEASE", "INS_CSM_FV_CLOSE", "INS_CSM_OTHER_CLOSE",
                        ))].copy()
    sample["Document ID"] = "UNSEEN_2027"
    sample["Company ID"] = "UNSEEN"
    sample["Company"] = "New Insurer"
    sample["Legal entity"] = "New Insurer Limited"
    sample["Period end"] = "2027-12-31"
    profile = next(item.copy() for item in all_filings() if item["document_id"] == "FWD_2025")
    profile.update(document_id="UNSEEN_2027", company_id="UNSEEN",
                   company="New Insurer", legal_entity="New Insurer Limited",
                   period_end="2027-12-31")
    corrected = normalize_records(sample, [profile]).set_index("Metric code")
    assert corrected.at["CSM_CLOSE", "Value (millions)"] == pytest.approx(2450.689)
    assert corrected.at["CSM_NET_MOVEMENT", "Value (millions)"] == pytest.approx(717.983)
    assert corrected.at["CSM_NEW", "Value (millions)"] == pytest.approx(680.897)
    assert corrected.at["CSM_RELEASE", "Value (millions)"] == pytest.approx(-267.218)
    assert corrected.at["CSM_CLOSE", "Original value"] == -2_450_689


def test_modified_transition_csm_uses_the_same_insurance_sign() -> None:
    source = load_external()
    sample = source.loc[source["Company"].eq("FWD Life Bermuda") &
                        source["Period end"].eq("2025-12-31") &
                        source["Metric code"].isin(("CSM_CLOSE", "INS_CSM_FV_CLOSE"))].copy()
    modified = sample.loc[sample["Metric code"].eq("INS_CSM_FV_CLOSE")].copy()
    modified["Metric code"] = "INS_CSM_MOD_CLOSE"
    sample = pd.concat([sample, modified], ignore_index=True)
    sample["Value (millions)"] *= -1
    corrected = orient_csm_values(sample).set_index("Metric code")
    assert corrected.at["INS_CSM_MOD_CLOSE", "Value (millions)"] == pytest.approx(771.527)


def test_positive_filing_and_source_component_checks_are_preserved() -> None:
    rows = load_external()
    sun = rows.loc[rows["Company"].eq("Sun Life Hong Kong") &
                   rows["Period end"].eq("2025-12-31")].set_index("Metric code")
    assert sun.at["CSM_CLOSE", "Value (millions)"] == 24_757
    assert sun.at["CSM_RELEASE", "Value (millions)"] == -1877
    assert sun.at["REINS_NONPAA_CSM_CLOSE", "Value (millions)"] == 2782

    fwd = rows.loc[rows["Document ID"].eq("FWD_2025") &
                   rows["Period end"].eq("2025-12-31")]
    filing = next(item for item in all_filings() if item["document_id"] == "FWD_2025")
    plan = default_plan([filing], {"FWD_2025"})
    for check_id in ("CSM_ROLL", "INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS"):
        selected = plan["Check ID"].eq(check_id) & plan["Period end"].eq("2025-12-31")
        plan.loc[selected, ["Assessment", "Measurement method", "Note scope", "Note reference"]] = [
            "Applicable", "Mixed", "Same entity and balance basis", "Note 13",
        ]
    checks = evaluate_checks(fwd, [filing], plan, verified_only=True)
    checked = checks.loc[checks["Check ID"].isin((
        "CSM_ROLL", "INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS",
    )) & checks["Period end"].eq("2025-12-31")]
    assert checked.set_index("Check ID")["Result"].to_dict() == {
        "CSM_ROLL": "Pass", "INS_MEAS_COMPONENTS": "Pass",
        "REINS_MEAS_COMPONENTS": "Pass",
    }


def test_ambiguous_balance_sign_does_not_flip_movements() -> None:
    values = pd.DataFrame({
        "Document ID": ["X_2027"] * 3,
        "Period end": ["2027-12-31"] * 3,
        "Metric code": ["CSM_OPEN", "CSM_CLOSE", "CSM_NET_MOVEMENT"],
        "Value (millions)": [-10.0, 5.0, 15.0],
    })
    result = orient_csm_values(values).set_index("Metric code")
    assert result.at["CSM_NET_MOVEMENT", "Value (millions)"] == 15.0


def test_initial_recognition_components_share_one_sign_convention_and_reconcile() -> None:
    rows = load_external()
    new_business = rows.loc[rows["Metric code"].str.startswith("NB_INS_")]
    for (_, _), group in new_business.groupby(["Company", "Period end"]):
        values = group.set_index("Metric code")["Value (millions)"]
        assert values["NB_INS_PROFIT_CSM"] >= 0
        assert values["NB_INS_PROFIT_RA"] >= 0
        assert values["NB_INS_PROFIT_PV_OUT"] >= 0
        assert values["NB_INS_PROFIT_PV_IN"] <= 0
        assert values["NB_INS_ONEROUS_LOSS"] >= 0
        assert values["NB_INS_ONEROUS_RA"] >= 0
        assert values["NB_INS_ONEROUS_PV_OUT"] >= 0
        assert values["NB_INS_ONEROUS_PV_IN"] <= 0
        assert sum(values[code] for code in (
            "NB_INS_PROFIT_CSM", "NB_INS_PROFIT_RA",
            "NB_INS_PROFIT_PV_OUT", "NB_INS_PROFIT_PV_IN",
        )) == pytest.approx(0, abs=1e-5)
        assert sum(values[code] for code in (
            "NB_INS_ONEROUS_RA", "NB_INS_ONEROUS_PV_OUT",
            "NB_INS_ONEROUS_PV_IN",
        )) == pytest.approx(values["NB_INS_ONEROUS_LOSS"], abs=1e-5)

    fwd = new_business.loc[new_business["Company"].eq("FWD Life Bermuda")
                           & new_business["Period end"].eq("2025-12-31")].set_index("Metric code")
    assert fwd.at["NB_INS_ONEROUS_LOSS", "Original value"] == -3594
    assert fwd.at["NB_INS_ONEROUS_LOSS", "Value (millions)"] == pytest.approx(3.594)
    assert fwd.at["NB_INS_PROFIT_RA", "Value (millions)"] == pytest.approx(30.259)
    assert fwd.at["NB_INS_PROFIT_PV_IN", "Value (millions)"] == pytest.approx(-6334.521)


def test_new_insurer_initial_recognition_signs_do_not_depend_on_name_or_csm_balance() -> None:
    source = load_external()
    sample = source.loc[source["Company"].eq("FWD Life Bermuda")
                        & source["Period end"].eq("2025-12-31")
                        & source["Metric code"].str.startswith("NB_INS_")].copy()
    sample["Document ID"] = "UNSEEN_NB_2027"
    sample["Company ID"] = "UNSEEN_NB"
    sample["Company"] = "New Insurer"
    sample["Legal entity"] = "New Insurer Limited"
    sample["Period end"] = "2027-12-31"
    profile = next(item.copy() for item in all_filings() if item["document_id"] == "FWD_2025")
    profile.update(document_id="UNSEEN_NB_2027", company_id="UNSEEN_NB",
                   company="New Insurer", legal_entity="New Insurer Limited",
                   period_end="2027-12-31")
    corrected = normalize_records(sample, [profile]).set_index("Metric code")
    assert corrected.at["NB_INS_ONEROUS_LOSS", "Value (millions)"] == pytest.approx(3.594)
    assert corrected.at["NB_INS_ONEROUS_RA", "Value (millions)"] == pytest.approx(.051)
    assert corrected.at["NB_INS_PROFIT_PV_IN", "Value (millions)"] == pytest.approx(-6334.521)
