"""Assemble source-checked 2025 cells from three supplied HK insurer filings.

Every extra tuple is (reported signed amount, physical PDF page, line label).
The pilot seed cells are used only after the cited source pages were checked.
No missing note movement is inferred from a closing balance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from hkifrs17.catalog import METRIC_BY_CODE, PILOT_FILINGS
from hkifrs17.checks import RULES, evaluate_checks, normalize_plan
from hkifrs17.data import COLUMNS, normalize_records
from hkifrs17.demo import demo_records


FWD = {
    # Primary statements (physical pages 8-15), US$'000.
    "INS_FINANCE_PL": (-824179, 8, "Net finance expenses from insurance contracts"),
    "REINS_FINANCE_PL": (27984, 8, "Net finance income from reinsurance contracts held"),
    "NET_INV_RESULT": (17861, 8, "Net investment result"),
    "OTHER_REVENUE": (17268, 8, "Other revenue"),
    "OTHER_EXPENSE": (-63578, 8, "General and other expenses"),
    "FINANCE_COST": (-6663, 8, "Finance costs"),
    "TAX_EXPENSE": (-41461, 8, "Income tax"),
    "OCI_TOTAL": (95403, 9, "Total other comprehensive income"),
    "COMPREHENSIVE_INCOME": (312408, 9, "Total comprehensive income"),
    "OCI_FVOCI_DEBT": (139201, 9, "FVOCI debt securities fair value gains"),
    "OCI_FVOCI_RECYCLE": (294350, 9, "FVOCI debt securities transferred to profit or loss"),
    "OCI_INS_FINANCE": (-349229, 9, "Insurance contract finance expenses in OCI"),
    "OCI_REINS_FINANCE": (11351, 9, "Reinsurance contract finance income in OCI"),
    "OCI_HEDGE": (5686, 9, "Cash flow hedges in OCI"),
    "OCI_TAX": (-5956, 9, "Related income tax in OCI"),
    "INS_ASSETS": (112195, 10, "Insurance contract assets"),
    "REINS_LIABS": (119427, 10, "Reinsurance contract liabilities"),
    "FIN_ASSET_FVOCI_DEBT": (14176608, 10, "FVOCI debt securities"),
    "FIN_ASSET_FVTPL_DEBT": (1828947, 10, "FVTPL debt securities"),
    "FIN_ASSET_FVTPL_EQUITY": (138111, 10, "FVTPL equity securities"),
    "FIN_ASSET_FVTPL_FUNDS": (4616979, 10, "FVTPL investment funds"),
    "EQUITY_OPEN": (2779503, 12, "Balance as at 1 January 2025: total equity"),
    "EQUITY_DIVIDENDS": (-90000, 12, "Dividend paid: total equity"),
    "INVESTING_CF": (-6650, 14, "Net cash used in investing activities"),
    "FINANCING_CF": (-103883, 15, "Net cash used in financing activities"),
    "NET_CASH_CHANGE": (62853, 15, "Net increase in cash and cash equivalents"),
    "CASH_OPEN": (505866, 15, "Cash and cash equivalents at beginning of year"),
    "CASH_CLOSE": (568719, 15, "Cash and cash equivalents at end of year"),
    # Note 13: keep net asset/liability signs exactly as printed.
    "INS_NET_BALANCE": (-19881599, 62, "Insurance contracts: total net balance"),
    "REINS_NET_BALANCE": (677826, 62, "Reinsurance contracts held: total net balance"),
    "INS_NONPAA_NET_OPEN": (-15364611, 63, "Insurance non-PAA: net opening balance"),
    "INS_NONPAA_PL_OCI": (-875948, 63, "Insurance non-PAA: total P&L and OCI changes"),
    "INS_NONPAA_CASH": (-3621056, 63, "Insurance non-PAA: total cash flows"),
    "INS_NONPAA_NET_CLOSE": (-19861615, 63, "Insurance non-PAA: net closing balance"),
    "INS_NONPAA_LRC_CLOSE": (-19620936, 63, "Insurance non-PAA: remaining coverage excluding loss component"),
    "INS_NONPAA_LC_CLOSE": (-41778, 63, "Insurance non-PAA: loss component"),
    "INS_NONPAA_LIC_CLOSE": (-198901, 63, "Insurance non-PAA: liabilities for incurred claims"),
    "INS_EXP_NONPAA": (-503116, 63, "Insurance non-PAA: total insurance service expenses"),
    "INS_EXP_ONEROUS": (-2080, 63, "Insurance non-PAA: losses on onerous contracts"),
    "INS_EXP_LIC": (-6931, 63, "Insurance non-PAA: adjustments to incurred claims"),
    "INS_NONPAA_PVFCF_OPEN": (-13400544, 65, "Insurance non-PAA: opening PV of future cash flows"),
    "INS_NONPAA_RA_OPEN": (-231361, 65, "Insurance non-PAA: opening risk adjustment"),
    "INS_NONPAA_PVFCF_CLOSE": (-17162870, 65, "Insurance non-PAA: closing PV of future cash flows"),
    "INS_NONPAA_RA_CLOSE": (-248056, 65, "Insurance non-PAA: closing risk adjustment"),
    "INS_NONPAA_CSM_CLOSE": (-2450689, 65, "Insurance non-PAA: closing CSM subtotal"),
    "INS_CSM_FV_CLOSE": (-771527, 65, "Insurance CSM: fair value transition closing"),
    "INS_CSM_OTHER_CLOSE": (-1679162, 65, "Insurance CSM: other contracts closing"),
    "INS_CSM_FV_RELEASE": (98226, 65, "Insurance CSM release: fair value transition"),
    "INS_CSM_OTHER_RELEASE": (168992, 65, "Insurance CSM release: other contracts"),
    "CSM_ESTIMATE_CHANGE": (-269112, 65, "Insurance CSM: changes in estimates"),
    "CSM_FINANCE_CHANGE": (-35192, 65, "Insurance CSM: finance expenses"),
    "INS_PAA_NET_OPEN": (-12302, 67, "Insurance PAA: net opening balance"),
    "INS_PAA_PL_OCI": (1023, 67, "Insurance PAA: total P&L and OCI changes"),
    "INS_PAA_CASH": (-8705, 67, "Insurance PAA: total cash flows"),
    "INS_PAA_NET_CLOSE": (-19984, 67, "Insurance PAA: net closing balance"),
    "INS_PAA_LRC_CLOSE": (-5931, 67, "Insurance PAA: remaining coverage"),
    "INS_PAA_LIC_CLOSE": (-14053, 67, "Insurance PAA: incurred claims"),
    "INS_EXP_PAA": (-73477, 67, "Insurance PAA: total insurance service expenses"),
    "REINS_NONPAA_NET_OPEN": (298327, 69, "Reinsurance non-PAA: net opening balance"),
    "REINS_NONPAA_PL_OCI": (35481, 69, "Reinsurance non-PAA: total P&L and OCI changes"),
    "REINS_NONPAA_CASH": (344353, 69, "Reinsurance non-PAA: total cash flows"),
    "REINS_NONPAA_NET_CLOSE": (678161, 69, "Reinsurance non-PAA: net closing balance"),
    "REINS_NONPAA_ARC_CLOSE": (518929, 69, "Reinsurance non-PAA: remaining coverage excluding loss recovery"),
    "REINS_NONPAA_LOSS_RECOVERY_CLOSE": (10707, 69, "Reinsurance non-PAA: loss recovery component"),
    "REINS_NONPAA_AIC_CLOSE": (148525, 69, "Reinsurance non-PAA: assets for incurred claims"),
    "REINS_NONPAA_PVFCF_CLOSE": (650787, 71, "Reinsurance non-PAA: closing PV of future cash flows"),
    "REINS_NONPAA_RA_CLOSE": (6907, 71, "Reinsurance non-PAA: closing risk adjustment"),
    "REINS_NONPAA_CSM_CLOSE": (20467, 71, "Reinsurance non-PAA: closing CSM subtotal"),
    "REINS_CSM_FV_CLOSE": (-3505, 71, "Reinsurance CSM: fair value transition closing"),
    "REINS_CSM_OTHER_CLOSE": (23972, 71, "Reinsurance CSM: other contracts closing"),
    "REINS_CSM_RELEASE": (-3314, 71, "Reinsurance CSM recognised for services received"),
    "REINS_PAA_NET_OPEN": (-660, 73, "Reinsurance PAA: net opening balance"),
    "REINS_PAA_PL_OCI": (-1051, 73, "Reinsurance PAA: total P&L and OCI changes"),
    "REINS_PAA_CASH": (1376, 73, "Reinsurance PAA: total cash flows"),
    "REINS_PAA_NET_CLOSE": (-335, 73, "Reinsurance PAA: net closing balance"),
    "REINS_PAA_ARC_CLOSE": (-412, 73, "Reinsurance PAA: assets for remaining coverage"),
    "REINS_PAA_AIC_CLOSE": (77, 73, "Reinsurance PAA: assets for incurred claims"),
    "NB_INS_PROFIT_PV_OUT": (-5623365, 75, "New profitable insurance contracts: PV of cash outflows"),
    "NB_INS_PROFIT_PV_IN": (6334521, 75, "New profitable insurance contracts: PV of cash inflows"),
    "NB_INS_PROFIT_RA": (-30259, 75, "New profitable insurance contracts: risk adjustment"),
    "NB_INS_PROFIT_CSM": (-680897, 75, "New profitable insurance contracts: CSM"),
    "NB_INS_ONEROUS_PV_OUT": (-183460, 75, "New onerous insurance contracts: PV of cash outflows"),
    "NB_INS_ONEROUS_PV_IN": (179917, 75, "New onerous insurance contracts: PV of cash inflows"),
    "NB_INS_ONEROUS_RA": (-51, 75, "New onerous insurance contracts: risk adjustment"),
    "NB_INS_ONEROUS_LOSS": (-3594, 75, "New onerous insurance contracts: initial loss"),
    "NB_REINS_PV_IN": (433716, 76, "New reinsurance contracts held: PV of cash inflows"),
    "NB_REINS_PV_OUT": (-439341, 76, "New reinsurance contracts held: PV of cash outflows"),
    "NB_REINS_RA": (606, 76, "New reinsurance contracts held: risk adjustment"),
    "NB_REINS_CSM": (8101, 76, "New reinsurance contracts held: CSM"),
    "CSM_MAT_INS_1Y": (275073, 76, "Insurance CSM: within one year"),
    "CSM_MAT_INS_1_5Y": (843531, 76, "Insurance CSM: one to five years"),
    "CSM_MAT_INS_5_10Y": (637120, 76, "Insurance CSM: five to ten years"),
    "CSM_MAT_INS_GT10Y": (694965, 76, "Insurance CSM: more than ten years"),
    "CSM_MAT_REINS_1Y": (-2386, 76, "Reinsurance CSM: within one year"),
    "CSM_MAT_REINS_1_5Y": (-4246, 76, "Reinsurance CSM: one to five years"),
    "CSM_MAT_REINS_5_10Y": (-4859, 76, "Reinsurance CSM: five to ten years"),
    "CSM_MAT_REINS_GT10Y": (-8976, 76, "Reinsurance CSM: more than ten years"),
    "RA_CONFIDENCE_PCT": (75, 79, "Risk adjustment target confidence level: 75th percentile"),
}

YF = {
    # Notes 5, 6 and 22. Values below are the 2025 column in HKD units.
    "REV_CSM_SERVICE": (781157687, 97, "CSM recognised for services provided"),
    "REV_RA_RELEASE": (-9529521, 97, "Change in risk adjustment for non-financial risk for risk expired"),
    "REV_EXPECTED_CLAIMS": (1102418489, 97, "Expected incurred claims and other insurance service expenses"),
    "REV_ACQ_RECOVERY": (877988780, 97, "Recovery of insurance acquisition cash flows"),
    "REV_NONPAA_TOTAL": (2752035435, 97, "Contracts not measured under PAA: insurance revenue"),
    "REV_PAA_TOTAL": (324415426, 97, "Contracts measured under PAA: insurance revenue"),
    "INS_REVENUE_NOTE_TOTAL": (3076450861, 97, "Total insurance revenue"),
    "INV_RETURN_TOTAL": (6908658134, 98, "Total investment return including OCI"),
    "INS_FINANCE_TOTAL": (-5797465390, 98, "Total net finance expenses from insurance contracts"),
    "REINS_FINANCE_TOTAL": (459575317, 98, "Total net finance income from reinsurance contracts"),
    "NET_INV_RESULT_TOTAL": (1339296754, 98, "Net financial result including OCI"),
    "INS_LIABS_NOTE_CLOSE": (82629053348, 119, "Insurance contract liabilities after acquisition cash flow assets"),
    "REINS_ASSETS_NOTE_CLOSE": (-7482492186, 119, "Reinsurance contract assets, presented as a deduction"),
    "INS_NOTE_NET_OPEN": (69620983524, 120, "Insurance contracts: net opening balance"),
    "INS_NOTE_PL_OCI": (5213148598, 120, "Insurance contracts: total changes in profit or loss and OCI"),
    "INS_NOTE_CASHFLOWS": (7798347323, 120, "Insurance contracts: total cash flows"),
    "INS_NOTE_NET_CLOSE": (82632479445, 120, "Insurance contracts: net closing balance before acquisition cash flow assets"),
    "INS_NONPAA_NET_OPEN": (69507120869, 122, "Insurance contracts not under PAA: net opening balance"),
    "INS_NONPAA_PL_OCI": (5252995111, 122, "Insurance contracts not under PAA: total changes in profit or loss and OCI"),
    "INS_NONPAA_CASH": (7771449460, 122, "Insurance contracts not under PAA: total cash flows"),
    "INS_NONPAA_NET_CLOSE": (82531565540, 122, "Insurance contracts not under PAA: net closing balance"),
    "INS_NONPAA_PVFCF_CLOSE": (70044772796, 122, "Insurance contracts not under PAA: closing PV of future cash flows"),
    "INS_NONPAA_RA_CLOSE": (1725027810, 122, "Insurance contracts not under PAA: closing risk adjustment"),
    "INS_CSM_FV_CLOSE": (6544346635, 122, "Insurance CSM: fair value transition closing"),
    "INS_CSM_OTHER_CLOSE": (4217418299, 122, "Insurance CSM: other contracts closing"),
    "INS_CSM_FV_RELEASE": (-559724381, 122, "Insurance CSM recognised for services: fair value transition"),
    "INS_CSM_OTHER_RELEASE": (-221433306, 122, "Insurance CSM recognised for services: other contracts"),
    "REINS_NOTE_NET_OPEN": (6790716168, 124, "Reinsurance contracts: net opening balance"),
    "REINS_NOTE_PL_OCI": (555482860, 124, "Reinsurance contracts: total changes in profit or loss and OCI"),
    "REINS_NOTE_CASHFLOWS": (136293158, 124, "Reinsurance contracts: total cash flows"),
    "REINS_NOTE_NET_CLOSE": (7482492186, 124, "Reinsurance contracts: net closing asset balance"),
    "INS_FINANCE_PL": (-5280042009, 27, "Net finance expenses from insurance contracts"),
    "REINS_FINANCE_PL": (296377591, 27, "Net finance income from reinsurance contracts"),
    "OTHER_REVENUE": (46138565, 27, "Other income"),
    "OTHER_EXPENSE": (-233802024, 27, "Other operating expenses"),
    "FINANCE_COST": (-7285000, 27, "Other finance costs"),
    "TAX_EXPENSE": (-167398667, 27, "Income tax expense"),
    "OCI_TOTAL": (375730146, 28, "Other comprehensive income for the year"),
    "COMPREHENSIVE_INCOME": (1751291829, 28, "Total comprehensive income for the year"),
    "OCI_INS_FINANCE": (-517423381, 28, "Insurance contract finance expenses in OCI"),
    "OCI_REINS_FINANCE": (163197726, 28, "Reinsurance contract finance income in OCI"),
    "OCI_HEDGE": (-89904333, 28, "Cash flow hedge: net movement in hedging reserve"),
    "OCI_TAX": (31505952, 28, "Net deferred tax impact in OCI"),
    "EQUITY_OPEN": (15837899430, 31, "Balance at 1 January 2025: total equity"),
    "EQUITY_DIVIDENDS": (-300000000, 31, "Dividends paid: total equity"),
    "INVESTING_CF": (-176227398, 33, "Net cash used in investing activities"),
    "FINANCING_CF": (-482779514, 33, "Net cash used in financing activities"),
    "NET_CASH_CHANGE": (681860420, 33, "Net increase in cash and cash equivalents"),
    "CASH_OPEN": (3899941867, 33, "Cash and cash equivalents at 1 January"),
    "CASH_CLOSE": (4587613441, 33, "Cash and cash equivalents at 31 December"),
}

SUN = {
    # Notes 7 and 8; HK$ millions. Policyholder tax is a separate disclosed line.
    "REV_CSM_SERVICE": (1877, 81, "CSM recognised for services provided"),
    "REV_RA_RELEASE": (394, 81, "Change in risk adjustment for non-financial risk for risk expired"),
    "REV_EXPECTED_CLAIMS": (1130, 81, "Expected incurred claims and other insurance service expenses"),
    "REV_ACQ_RECOVERY": (1284, 81, "Recovery of insurance acquisition cash flows"),
    "REV_POLICYHOLDER_TAX": (276, 81, "Income taxes specifically chargeable to the policyholder"),
    "REV_NONPAA_TOTAL": (4961, 81, "Contracts not measured under PAA: insurance revenue"),
    "REV_PAA_TOTAL": (258, 81, "Contracts measured under PAA: insurance revenue"),
    "INS_REVENUE_NOTE_TOTAL": (5219, 81, "Total insurance revenue"),
    "INS_EXP_CLAIMS": (-1248, 81, "Incurred claims and other incurred insurance service expenses"),
    "INS_EXP_LIC": (-25, 81, "Changes relating to past service: adjustment to LIC"),
    "INS_EXP_ONEROUS": (-98, 81, "Changes relating to future service: losses on onerous contracts"),
    "INS_EXP_ACQ_AMORT": (-1284, 81, "Insurance acquisition cash flows: amortisation"),
    "INS_EXP_NONPAA": (-2655, 81, "Contracts not measured under PAA: insurance service expenses"),
    "INS_EXP_PAA": (-300, 81, "Contracts measured under PAA: insurance service expenses"),
    # Note 20 uses a non-PAA contract population for these reconciliations.
    "INS_NOTE_NET_OPEN": (100965, 94, "Insurance non-PAA contracts: net opening balance"),
    "INS_NOTE_PL_OCI": (9623, 94, "Insurance non-PAA contracts: total changes in profit or loss and OCI"),
    "INS_NOTE_CASHFLOWS": (25773, 94, "Insurance non-PAA contracts: total cash flows"),
    "INS_NOTE_NET_CLOSE": (136361, 94, "Insurance non-PAA contracts: net closing balance"),
    "INS_NOTE_PVFCF_CLOSE": (104290, 95, "Insurance non-PAA contracts: closing PV of future cash flows"),
    "INS_NOTE_RA_CLOSE": (7314, 95, "Insurance non-PAA contracts: closing risk adjustment"),
    "INS_NOTE_CSM_CLOSE": (24757, 95, "Insurance non-PAA contracts: closing CSM"),
    "INS_NONPAA_NET_OPEN": (100965, 94, "Insurance non-PAA contracts: net opening balance"),
    "INS_NONPAA_PL_OCI": (9623, 94, "Insurance non-PAA contracts: total changes in profit or loss and OCI"),
    "INS_NONPAA_CASH": (25773, 94, "Insurance non-PAA contracts: total cash flows"),
    "INS_NONPAA_NET_CLOSE": (136361, 94, "Insurance non-PAA contracts: net closing balance"),
    "INS_NONPAA_PVFCF_CLOSE": (104290, 95, "Insurance non-PAA contracts: closing PV of future cash flows"),
    "INS_NONPAA_RA_CLOSE": (7314, 95, "Insurance non-PAA contracts: closing risk adjustment"),
    "INS_NONPAA_CSM_CLOSE": (24757, 95, "Insurance non-PAA contracts: closing CSM"),
    "CSM_OPEN": (19144, 95, "Insurance non-PAA contracts: net opening CSM"),
    "CSM_NET_MOVEMENT": (5613, 95, "Insurance non-PAA contracts: total P&L and OCI movement in CSM"),
    "CSM_CLOSE": (24757, 95, "Insurance non-PAA contracts: net closing CSM"),
    "CSM_RELEASE": (-1877, 95, "Insurance non-PAA contracts: CSM recognised for services"),
    "CSM_NEW": (5151, 95, "Insurance non-PAA contracts: initial CSM on new contracts"),
    "REINS_NOTE_NET_OPEN": (-2252, 96, "Reinsurance non-PAA contracts: net opening balance"),
    "REINS_NOTE_PL_OCI": (491, 96, "Reinsurance non-PAA contracts: total changes in profit or loss and OCI"),
    "REINS_NOTE_CASHFLOWS": (442, 96, "Reinsurance non-PAA contracts: total cash flows"),
    "REINS_NOTE_NET_CLOSE": (-1319, 96, "Reinsurance non-PAA contracts: net closing balance"),
    "REINS_NOTE_PVFCF_CLOSE": (2073, 97, "Reinsurance non-PAA contracts: closing PV of future cash flows"),
    "REINS_NOTE_RA_CLOSE": (-610, 97, "Reinsurance non-PAA contracts: closing risk adjustment"),
    "REINS_NOTE_CSM_CLOSE": (-2782, 97, "Reinsurance non-PAA contracts: closing CSM"),
    "REINS_NONPAA_NET_OPEN": (-2252, 96, "Reinsurance non-PAA contracts: net opening balance"),
    "REINS_NONPAA_PL_OCI": (491, 96, "Reinsurance non-PAA contracts: total changes in profit or loss and OCI"),
    "REINS_NONPAA_CASH": (442, 96, "Reinsurance non-PAA contracts: total cash flows"),
    "REINS_NONPAA_NET_CLOSE": (-1319, 96, "Reinsurance non-PAA contracts: net closing balance"),
    "REINS_NONPAA_PVFCF_CLOSE": (2073, 97, "Reinsurance non-PAA contracts: closing PV of future cash flows"),
    "REINS_NONPAA_RA_CLOSE": (-610, 97, "Reinsurance non-PAA contracts: closing risk adjustment"),
    "REINS_NONPAA_CSM_CLOSE": (-2782, 97, "Reinsurance non-PAA contracts: closing CSM"),
    "INS_FINANCE_PL": (-11929, 13, "Insurance finance expenses from insurance contracts issued"),
    "REINS_FINANCE_PL": (-201, 13, "Insurance finance expenses from reinsurance contracts held"),
    "NET_INV_RESULT": (521, 13, "Net investment result"),
    "OTHER_EXPENSE": (-1138, 13, "Other operating expenses and staff costs"),
    "FINANCE_COST": (-17, 13, "Finance costs"),
    "TAX_EXPENSE": (-145, 13, "Income tax expense"),
    "OCI_TOTAL": (192, 14, "Other comprehensive income for the year"),
    "COMPREHENSIVE_INCOME": (1624, 14, "Total comprehensive income for the year"),
    "OCI_TAX": (-38, 14, "Deferred tax on investment revaluation reserve"),
    "INS_ASSETS": (574, 15, "Insurance contract assets"),
    "REINS_LIABS": (483, 15, "Reinsurance contract held liabilities"),
    "EQUITY_OPEN": (7922, 17, "At December 31, 2024: total equity"),
    "EQUITY_DIVIDENDS": (-1425, 17, "Dividends paid: total equity"),
    "INVESTING_CF": (-21788, 19, "Net cash used in investing activities"),
    "FINANCING_CF": (-1558, 19, "Net cash used in financing activities"),
    "NET_CASH_CHANGE": (1079, 19, "Net increase in cash and cash equivalents"),
    "CASH_OPEN": (3030, 19, "Cash and cash equivalents at January 1"),
    "CASH_CLOSE": (4109, 19, "Cash and cash equivalents at December 31"),
}


def _make_records() -> pd.DataFrame:
    source = demo_records()
    source = source[source["Period end"].eq("2025-12-31") &
                    source["Document ID"].isin(["FWD_2025", "YF_2025", "SUN_2025"])].copy().reset_index(drop=True)
    source["Original value"] = source["Original value"].astype(float)
    source["Review status"] = "Verified"
    source["Reviewer note"] = "2025 source cell checked against the cited physical PDF page."
    for document_id, extras in (("FWD_2025", FWD), ("YF_2025", YF), ("SUN_2025", SUN)):
        filing = next(item for item in PILOT_FILINGS if item["document_id"] == document_id)
        assert not set(extras).intersection(source[source["Document ID"].eq(document_id)]["Metric code"])
        for code, (value, page, label) in extras.items():
            metric = METRIC_BY_CODE[code]
            unit = "percent" if metric.kind == "rate" else filing["source_unit"]
            source.loc[len(source)] = {
                "Document ID": document_id, "Company ID": filing["company_id"],
                "Company": filing["company"], "Legal entity": filing["legal_entity"],
                "Scope": filing["scope"], "Period end": filing["period_end"],
                "Metric code": code, "Metric": metric.label, "Section": metric.section,
                "Original value": value, "Source unit": unit, "Currency": filing["currency"],
                "Value (millions)": None, "Value status": "Reported", "PDF page": page,
                "Source label": label, "Audit status": "Audited statement or note",
                "Review status": "Verified", "Reviewer note": "2025 source cell checked against the cited physical PDF page.",
            }
    for currency, values in {
        "CNY": [1.34, 1.75, 1.64, 2.05, 1.87, 2.28, 2.27, 2.68, 2.68, 3.09],
        "HKD": [2.63, 3.44, 2.72, 3.54, 3.10, 3.92, 3.33, 4.15, 3.45, 4.27],
        "USD": [3.45, 4.25, 3.70, 4.50, 4.20, 5.00, 4.67, 5.47, 4.97, 5.76],
    }.items():
        for index, tenor in enumerate(("1Y", "5Y", "10Y", "15Y", "20Y")):
            for offset, basis in enumerate(("RF", "ILP")):
                code = f"DISCOUNT_{currency}_{tenor}_{basis}"
                source.loc[len(source)] = {
                    "Document ID": "FWD_2025", "Company ID": "FWD", "Company": "FWD Life Bermuda",
                    "Legal entity": "FWD Life Insurance Company (Bermuda) Limited", "Scope": "Company",
                    "Period end": "2025-12-31", "Metric code": code, "Metric": METRIC_BY_CODE[code].label,
                    "Section": METRIC_BY_CODE[code].section, "Original value": values[2 * index + offset],
                    "Source unit": "percent", "Currency": "%", "Value (millions)": None,
                    "Value status": "Reported", "PDF page": 79,
                    "Source label": f"2025 {currency} {tenor} spot rate; {'risk free' if basis == 'RF' else 'with illiquidity premium'}",
                    "Audit status": "Audited note", "Review status": "Verified",
                    "Reviewer note": "2025 discount rate checked against note 13, physical page 79.",
                }
    result = normalize_records(source[COLUMNS], list(PILOT_FILINGS))
    assert set(result["Period end"]) == {"2025-12-31"}
    return result.sort_values(["Company", "Section", "Metric code"]).reset_index(drop=True)


def _make_plan(records: pd.DataFrame) -> pd.DataFrame:
    ids = set(records["Document ID"])
    plan = normalize_plan(None, list(PILOT_FILINGS), ids)
    present = {doc: set(group["Metric code"]) for doc, group in records.groupby("Document ID")}
    references = {
        "FWD_2025": "FWD 2025 note 4 p.51; note 13 pp.62-79; same company and 2025 signed source basis",
        "YF_2025": "YF 2025 note 5 p.97 and note 22 pp.119-124; consolidated and 2025 source basis",
        "SUN_2025": "Sun Life 2025 notes 7-8 p.81; note 20 pp.94-97; company, 2025 and disclosed non-PAA cohort basis",
    }
    for index, row in plan.iterrows():
        if row["Period end"] != "2025-12-31":
            continue
        document_id = row["Document ID"]
        rule = next(item for item in RULES if item.id == row["Check ID"])
        required = set(rule.parts) | ({rule.total} if rule.total else set())
        if not required.issubset(present[document_id]):
            continue
        plan.at[index, "Assessment"] = "Applicable"
        plan.at[index, "Measurement method"] = "Mixed" if rule.id in {
            "REVENUE_NOTE", "LIABILITY_NOTE", "REINSURANCE_NOTE", "INS_LIABS_METHOD",
            "REINS_ASSETS_METHOD", "REV_TOTAL_SPLIT", "REV_NONPAA_COMP",
            "INS_NET_ROLL", "REINS_NET_ROLL",
        } else "GMM"
        plan.at[index, "Note scope"] = "Same entity and balance basis"
        plan.at[index, "Note reference"] = references[document_id]
        if (document_id, rule.id) in {("FWD_2025", "LIABILITY_NOTE"),
                                      ("YF_2025", "REINSURANCE_NOTE")}:
            plan.at[index, "Formula basis"] = "Reverse note sign for statement comparison"
    return normalize_plan(plan, list(PILOT_FILINGS), ids)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "scratch" / "three_filing_export"
    output.mkdir(parents=True, exist_ok=True)
    records = _make_records()
    ids = set(records["Document ID"])
    plan = _make_plan(records)
    checks = evaluate_checks(records, list(PILOT_FILINGS), plan, verified_only=True)
    core = checks[checks["Check ID"].isin(["PRIMARY", "SERVICE", "BALANCE"]) &
                  checks["Period end"].eq("2025-12-31")]
    assert len(core) == 9 and core["Result"].eq("Pass").all(), core.to_string(index=False)
    assert not checks["Result"].eq("Difference").any(), checks[checks["Result"].eq("Difference")].to_string(index=False)
    checks = checks[checks["Period end"].eq("2025-12-31")].copy()
    coverage = pd.DataFrame([
        {"Insurer": filing["company"], "Legal entity": filing["legal_entity"],
         "Scope": filing["scope"], "Currency": filing["currency"],
         "Source unit": filing["source_unit"], "Period end": "2025-12-31",
         "Source PDF": filing["pdf_file"],
         "Verified cells": int(records["Document ID"].eq(filing["document_id"]).sum()),
         "Pass": int(checks[checks["Document ID"].eq(filing["document_id"])]["Result"].eq("Pass").sum()),
         "Difference": int(checks[checks["Document ID"].eq(filing["document_id"])]["Result"].eq("Difference").sum()),
         "Missing inputs": int(checks[checks["Document ID"].eq(filing["document_id"])]["Result"].eq("Missing inputs").sum()),
         "Not applicable": int(checks[checks["Document ID"].eq(filing["document_id"])]["Result"].eq("Not applicable").sum()),
         "Coverage note": "2025 primary statements and selected notes; unresolved note checks remain Missing inputs.",
         } for filing in PILOT_FILINGS if filing["document_id"] in ids
    ])
    readme = pd.DataFrame({"Instruction": [
        "HK IFRS 17 | three-insurer 2025 source-checked dataset",
        "Upload this workbook in Step 5. The same imported data is used by Step 5 and Step 6.",
        "Only the 2025 reporting column was transcribed; the 2024 comparative column is excluded.",
        "Records is the canonical import sheet. Values retain the source sign and unit. Value (millions) is recalculated by the platform.",
        "PDF page is the physical one-based PDF page, not the printed annual-report page number.",
        "YF Life is consolidated; FWD and Sun Life are company statements. Peer comparison should filter by reporting scope.",
        "FWD is US$'000; YF is HK$ units; Sun Life is HK$ millions. Never compare native-currency absolute amounts as equivalent.",
        "Checks shows Pass / Difference / Missing inputs / Not applicable. Missing inputs is not a pass.",
        "All nine mandatory primary checks pass. Some optional note checks remain Missing inputs; they are never presented as Pass.",
        "Sun Life note 7 has a separate policyholder-tax revenue line. It is included in its non-PAA revenue composition check.",
        "Sun Life note 20 movement and measurement checks refer to disclosed non-PAA cohorts, not the whole statement balance.",
        "YF note 22 contract balance movement uses a full insurance/reinsurance cohort; acquisition cash flow assets explain the difference between gross note movement and statement liabilities.",
        "Sun Life 2024 comparative in the PDF is unaudited; it was not imported.",
        "The data is limited to the cited reported cells; no balancing plug, inferred movement, or invented investment yield is included.",
    ]})
    for name, frame in (("Records", records), ("Checks", checks), ("Check plan", plan[plan["Period end"].eq("2025-12-31")]),
                        ("Coverage", coverage), ("Read me", readme)):
        (output / f"{name.replace(' ', '_')}.json").write_text(
            json.dumps(frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records"),
                       ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    print(f"Cells: {len(records)}; checks: {checks['Result'].value_counts().to_dict()}")
    print(coverage[["Insurer", "Verified cells", "Pass", "Difference", "Missing inputs"]].to_string(index=False))


if __name__ == "__main__":
    main()
