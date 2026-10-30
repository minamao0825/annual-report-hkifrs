"""Present CSM balances consistently while retaining the filing's signed source.

Some insurers present the insurance CSM as a negative contract liability in
their measurement reconciliations. Detect that convention per filing and year
from the disclosed opening/closing CSM, rather than from the insurer name.
Initial-recognition cash flows, risk adjustments and losses use consistent
component signs. Original source values remain untouched.
"""

from __future__ import annotations

import pandas as pd


INSURANCE_BALANCE_ANCHORS = frozenset({
    "CSM_OPEN", "CSM_CLOSE", "INS_NONPAA_CSM_CLOSE", "INS_NOTE_CSM_CLOSE",
})
INSURANCE_SIGNED_CODES = frozenset({
    *INSURANCE_BALANCE_ANCHORS,
    "CSM_NEW", "CSM_RELEASE", "CSM_NET_MOVEMENT",
    "CSM_ESTIMATE_CHANGE", "CSM_FINANCE_CHANGE",
    "INS_CSM_FV_CLOSE", "INS_CSM_MOD_CLOSE", "INS_CSM_OTHER_CLOSE",
    "INS_CSM_FV_RELEASE", "INS_CSM_OTHER_RELEASE",
})
REINSURANCE_BALANCE_ANCHORS = frozenset({
    "REINS_NONPAA_CSM_CLOSE", "REINS_NOTE_CSM_CLOSE",
})
REINSURANCE_SIGNED_CODES = frozenset({
    *REINSURANCE_BALANCE_ANCHORS,
    "REINS_CSM_MOD_CLOSE", "REINS_CSM_FV_CLOSE", "REINS_CSM_OTHER_CLOSE",
    "REINS_CSM_RELEASE", "NB_REINS_CSM",
})
CSM_MAGNITUDE_CODES = frozenset({
    *(f"CSM_MAT_{kind}_{bucket}"
      for kind in ("INS", "REINS")
      for bucket in ("1Y", "1_5Y", "5_10Y", "GT10Y")),
})

# Initial-recognition note columns can be presented on either side of the
# insurance-contract-liability reconciliation. These labels have fixed cash
# flow meanings, so orient each component by its meaning, not by insurer name.
# The original statement sign is retained in Original value.
NEW_BUSINESS_PRESENTATION_SIGNS = {
    "NB_INS_PROFIT_CSM": 1,
    "NB_INS_PROFIT_PV_IN": -1,
    "NB_INS_PROFIT_PV_OUT": 1,
    "NB_INS_PROFIT_RA": 1,
    "NB_INS_ONEROUS_PV_IN": -1,
    "NB_INS_ONEROUS_PV_OUT": 1,
    "NB_INS_ONEROUS_RA": 1,
    "NB_INS_ONEROUS_LOSS": 1,
}


def _orientation(group: pd.DataFrame, anchors: frozenset[str]) -> int | None:
    balances = pd.to_numeric(
        group.loc[group["Metric code"].isin(anchors), "Value (millions)"],
        errors="coerce",
    ).dropna()
    balances = balances.loc[balances.ne(0)]
    if balances.empty:
        return None
    if balances.lt(0).all():
        return -1
    if balances.gt(0).all():
        return 1
    # A mixed-sign net balance might represent a real change in position;
    # the filing needs review before its signed movements can be reoriented.
    return None


def orient_csm_values(frame: pd.DataFrame) -> pd.DataFrame:
    """Orient CSM to a positive balance, preserving genuine signed offsets.

    CSM rollforward movements are multiplied by the same sign as their balance,
    so opening + movement = closing remains true. Maturity buckets are future
    recognition *amounts* and are displayed as positive magnitudes even when a
    source note uses the opposite profit-or-loss sign. Initial-recognition
    components use their labelled cash-flow direction. The raw Original value
    column remains as printed in the filing for source-level reconciliations.
    """
    if frame.empty:
        return frame
    result = frame.copy()
    for _, group in result.groupby(["Document ID", "Period end"], sort=False):
        codes = group["Metric code"]
        insurance_sign = _orientation(group, INSURANCE_BALANCE_ANCHORS)
        reinsurance_sign = _orientation(group, REINSURANCE_BALANCE_ANCHORS)
        if insurance_sign is not None:
            selected = group.index[codes.isin(INSURANCE_SIGNED_CODES)]
            result.loc[selected, "Value (millions)"] = (
                pd.to_numeric(result.loc[selected, "Value (millions)"], errors="coerce")
                * insurance_sign
            )
        if reinsurance_sign is not None:
            selected = group.index[codes.isin(REINSURANCE_SIGNED_CODES)]
            result.loc[selected, "Value (millions)"] = (
                pd.to_numeric(result.loc[selected, "Value (millions)"], errors="coerce")
                * reinsurance_sign
            )
        # These are defined as magnitudes even if the balance anchor is absent.
        selected = group.index[codes.isin(CSM_MAGNITUDE_CODES | {"CSM_NEW"})]
        result.loc[selected, "Value (millions)"] = pd.to_numeric(
            result.loc[selected, "Value (millions)"], errors="coerce",
        ).abs()
        for code, sign in NEW_BUSINESS_PRESENTATION_SIGNS.items():
            selected = group.index[codes.eq(code)]
            if len(selected):
                result.loc[selected, "Value (millions)"] = (
                    pd.to_numeric(result.loc[selected, "Value (millions)"], errors="coerce")
                    .abs() * sign
                )
    return result
