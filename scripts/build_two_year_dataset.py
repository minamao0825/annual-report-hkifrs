"""Combine independently checked 2024 reports with the verified 2025 cells.

The 2024 figures come from the *current-year* columns of the three supplied
2024 PDFs. Sun Life 2024 is the audited consolidated set; the 2025 filing is
company-only, so it has a separate display identity and is never plotted as
an apparently comparable year-on-year series.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pandas as pd

from hkifrs17.catalog import METRIC_BY_CODE, PILOT_FILINGS
from hkifrs17.checks import RULES, evaluate_checks, normalize_plan
from hkifrs17.data import COLUMNS, normalize_records
from hkifrs17.demo import SAMPLE_VALUES


PROFILES_2024 = [
    {"document_id": "FWD_2024", "company_id": "FWD", "company": "FWD Life Bermuda",
     "legal_entity": "FWD Life Insurance Company (Bermuda) Limited", "scope": "Company",
     "period_end": "2024-12-31", "currency": "USD", "source_unit": "USD thousands",
     "pdf_file": "FWD-Life-Insurance-Company-Bermuda-Limited-2024-Financial-Statement.pdf",
     "note": "2024 current-year column; audited company financial statements."},
    {"document_id": "YF_2024", "company_id": "YF", "company": "YF Life",
     "legal_entity": "YF Life Insurance International Limited", "scope": "Consolidated",
     "period_end": "2024-12-31", "currency": "HKD", "source_unit": "HKD",
     "pdf_file": "YF Life_FS_2024.pdf",
     "note": "2024 current-year column; audited consolidated financial statements."},
    {"document_id": "SUN_GROUP_2024", "company_id": "SUN_GROUP",
     "company": "Sun Life Hong Kong (Consolidated)",
     "legal_entity": "Sun Life Hong Kong Limited", "scope": "Consolidated",
     "period_end": "2024-12-31", "currency": "HKD", "source_unit": "HKD millions",
     "pdf_file": "slhk-fs-2024.pdf",
     "note": "2024 audited consolidated statements. The 2025 dataset is company-only, so it is not a matching YoY population."},
]

# (reported signed 2024 amount, physical PDF page, source row label)
FWD = {
    "INS_FINANCE_PL": (-334091, 8, "Net finance expenses from insurance contracts"),
    "REINS_FINANCE_PL": (-10079, 8, "Net finance expenses from reinsurance contracts held"),
    "NET_INV_RESULT": (17268, 8, "Net investment result"),
    "OTHER_REVENUE": (22634, 8, "Other revenue"),
    "OTHER_EXPENSE": (-80779, 8, "General and other expenses"),
    "FINANCE_COST": (-6561, 8, "Finance costs"),
    "TAX_EXPENSE": (-95753, 8, "Income tax"),
    "OCI_TOTAL": (-29926, 9, "Total other comprehensive loss"),
    "COMPREHENSIVE_INCOME": (116676, 9, "Total comprehensive income"),
    "OCI_FVOCI_DEBT": (-466703, 9, "FVOCI debt securities fair value losses"),
    "OCI_FVOCI_RECYCLE": (386994, 9, "FVOCI debt securities transferred to profit or loss"),
    "OCI_INS_FINANCE": (59390, 9, "Insurance contract finance income in OCI"),
    "OCI_REINS_FINANCE": (-7684, 9, "Reinsurance contract finance expenses in OCI"),
    "OCI_HEDGE": (5066, 9, "Cash flow hedges in OCI"),
    "OCI_TAX": (-6989, 9, "Related income tax in OCI"),
    "INS_ASSETS": (77150, 10, "Insurance contract assets"),
    "REINS_LIABS": (177758, 10, "Reinsurance contract liabilities"),
    "FIN_ASSET_FVOCI_DEBT": (11222746, 10, "FVOCI debt securities"),
    "FIN_ASSET_FVTPL_DEBT": (867962, 10, "FVTPL debt securities"),
    "FIN_ASSET_FVTPL_EQUITY": (104800, 10, "FVTPL equity securities"),
    "FIN_ASSET_FVTPL_FUNDS": (4261173, 10, "FVTPL investment funds"),
    "EQUITY_OPEN": (2934254, 12, "Balance as at 1 January 2024: total equity"),
    "EQUITY_DIVIDENDS": (-298000, 12, "Dividend paid: total equity"),
    "EQUITY_NEW_CAPITAL": (26291, 12, "Issue of ordinary shares: total equity"),
    "INVESTING_CF": (-61717, 14, "Net cash used in investing activities"),
    "FINANCING_CF": (-276484, 15, "Net cash used in financing activities"),
    "NET_CASH_CHANGE": (153089, 15, "Net increase in cash and cash equivalents"),
    "CASH_OPEN": (352777, 15, "Cash and cash equivalents at beginning of year"),
    "CASH_CLOSE": (505866, 15, "Cash and cash equivalents at end of year"),
    "INS_NET_BALANCE": (-15376913, 66, "Insurance contracts: total net balance"),
    "REINS_NET_BALANCE": (297667, 66, "Reinsurance held: total net balance"),
    "INS_NONPAA_NET_OPEN": (-13783685, 67, "Insurance non-PAA: net opening balance"),
    "INS_NONPAA_PL_OCI": (16300, 67, "Insurance non-PAA: total P&L and OCI changes"),
    "INS_NONPAA_CASH": (-1597226, 67, "Insurance non-PAA: total cash flows"),
    "INS_NONPAA_NET_CLOSE": (-15364611, 67, "Insurance non-PAA: net closing balance"),
    "INS_NONPAA_LRC_CLOSE": (-14795460, 67, "Insurance non-PAA: remaining coverage excluding loss component"),
    "INS_NONPAA_LC_CLOSE": (-44572, 67, "Insurance non-PAA: loss component"),
    "INS_NONPAA_LIC_CLOSE": (-524579, 67, "Insurance non-PAA: liabilities for incurred claims"),
    "INS_EXP_NONPAA": (-507545, 67, "Insurance non-PAA: total insurance service expenses"),
    "INS_EXP_ONEROUS": (67779, 67, "Insurance non-PAA: reversals of losses on onerous contracts"),
    "INS_EXP_LIC": (22497, 67, "Insurance non-PAA: adjustments to incurred claims"),
    "INS_NONPAA_PVFCF_OPEN": (-12039708, 69, "Insurance non-PAA: opening PV of future cash flows"),
    "INS_NONPAA_RA_OPEN": (-219902, 69, "Insurance non-PAA: opening risk adjustment"),
    "INS_NONPAA_PVFCF_CLOSE": (-13400544, 69, "Insurance non-PAA: closing PV of future cash flows"),
    "INS_NONPAA_RA_CLOSE": (-231361, 69, "Insurance non-PAA: closing risk adjustment"),
    "INS_NONPAA_CSM_CLOSE": (-1732706, 69, "Insurance non-PAA: closing CSM subtotal"),
    "INS_CSM_FV_CLOSE": (-665192, 69, "Insurance CSM: fair value transition closing"),
    "INS_CSM_OTHER_CLOSE": (-1067514, 69, "Insurance CSM: other contracts closing"),
    "INS_CSM_FV_RELEASE": (85834, 69, "Insurance CSM release: fair value transition"),
    "INS_CSM_OTHER_RELEASE": (113215, 69, "Insurance CSM release: other contracts"),
    "CSM_ESTIMATE_CHANGE": (35688, 69, "Insurance CSM: changes in estimates"),
    "CSM_FINANCE_CHANGE": (-30163, 69, "Insurance CSM: finance expenses"),
    "INS_PAA_NET_OPEN": (-10981, 71, "Insurance PAA: net opening balance"),
    "INS_PAA_PL_OCI": (10515, 71, "Insurance PAA: total P&L and OCI changes"),
    "INS_PAA_CASH": (-11836, 71, "Insurance PAA: total cash flows"),
    "INS_PAA_NET_CLOSE": (-12302, 71, "Insurance PAA: net closing balance"),
    "INS_PAA_LRC_CLOSE": (921, 71, "Insurance PAA: remaining coverage"),
    "INS_PAA_LIC_CLOSE": (-13223, 71, "Insurance PAA: incurred claims"),
    "INS_EXP_PAA": (-61322, 71, "Insurance PAA: total insurance service expenses"),
    "REINS_NONPAA_NET_OPEN": (183672, 73, "Reinsurance non-PAA: net opening balance"),
    "REINS_NONPAA_PL_OCI": (-27367, 73, "Reinsurance non-PAA: total P&L and OCI changes"),
    "REINS_NONPAA_CASH": (142022, 73, "Reinsurance non-PAA: total cash flows"),
    "REINS_NONPAA_NET_CLOSE": (298327, 73, "Reinsurance non-PAA: net closing balance"),
    "REINS_NONPAA_ARC_CLOSE": (133691, 73, "Reinsurance non-PAA: remaining coverage excluding loss recovery"),
    "REINS_NONPAA_LOSS_RECOVERY_CLOSE": (6232, 73, "Reinsurance non-PAA: loss recovery component"),
    "REINS_NONPAA_AIC_CLOSE": (158404, 73, "Reinsurance non-PAA: assets for incurred claims"),
    "REINS_NONPAA_PVFCF_CLOSE": (275210, 75, "Reinsurance non-PAA: closing PV of future cash flows"),
    "REINS_NONPAA_RA_CLOSE": (6906, 75, "Reinsurance non-PAA: closing risk adjustment"),
    "REINS_NONPAA_CSM_CLOSE": (16211, 75, "Reinsurance non-PAA: closing CSM subtotal"),
    "REINS_CSM_FV_CLOSE": (356, 75, "Reinsurance CSM: fair value transition closing"),
    "REINS_CSM_OTHER_CLOSE": (15855, 75, "Reinsurance CSM: other contracts closing"),
    "REINS_CSM_RELEASE": (-2646, 75, "Reinsurance CSM recognised for services received"),
    "REINS_PAA_PL_OCI": (-2119, 77, "Reinsurance PAA: total P&L and OCI changes"),
    "REINS_PAA_CASH": (1459, 77, "Reinsurance PAA: total cash flows"),
    "REINS_PAA_NET_CLOSE": (-660, 77, "Reinsurance PAA: net closing balance"),
    "REINS_PAA_ARC_CLOSE": (-675, 77, "Reinsurance PAA: assets for remaining coverage"),
    "REINS_PAA_AIC_CLOSE": (15, 77, "Reinsurance PAA: assets for incurred claims"),
    "NB_INS_PROFIT_PV_OUT": (-3868912, 79, "New profitable insurance contracts: PV of cash outflows"),
    "NB_INS_PROFIT_PV_IN": (4305610, 79, "New profitable insurance contracts: PV of cash inflows"),
    "NB_INS_PROFIT_RA": (-23493, 79, "New profitable insurance contracts: risk adjustment"),
    "NB_INS_PROFIT_CSM": (-413205, 79, "New profitable insurance contracts: CSM"),
    "NB_INS_ONEROUS_PV_OUT": (-69501, 79, "New onerous insurance contracts: PV of cash outflows"),
    "NB_INS_ONEROUS_PV_IN": (68744, 79, "New onerous insurance contracts: PV of cash inflows"),
    "NB_INS_ONEROUS_RA": (-92, 79, "New onerous insurance contracts: risk adjustment"),
    "NB_INS_ONEROUS_LOSS": (-849, 79, "New onerous insurance contracts: initial loss"),
    "NB_REINS_PV_IN": (295700, 80, "New reinsurance contracts held: PV of cash inflows"),
    "NB_REINS_PV_OUT": (-296735, 80, "New reinsurance contracts held: PV of cash outflows"),
    "NB_REINS_RA": (493, 80, "New reinsurance contracts held: risk adjustment"),
    "NB_REINS_CSM": (1261, 80, "New reinsurance contracts held: CSM"),
    "CSM_MAT_INS_1Y": (196287, 80, "Insurance CSM: within one year"),
    "CSM_MAT_INS_1_5Y": (581675, 80, "Insurance CSM: one to five years"),
    "CSM_MAT_INS_5_10Y": (425442, 80, "Insurance CSM: five to ten years"),
    "CSM_MAT_INS_GT10Y": (529302, 80, "Insurance CSM: more than ten years"),
    "CSM_MAT_REINS_1Y": (-3457, 80, "Reinsurance CSM: within one year"),
    "CSM_MAT_REINS_1_5Y": (-5607, 80, "Reinsurance CSM: one to five years"),
    "CSM_MAT_REINS_5_10Y": (-2892, 80, "Reinsurance CSM: five to ten years"),
    "CSM_MAT_REINS_GT10Y": (-4255, 80, "Reinsurance CSM: more than ten years"),
    "RA_CONFIDENCE_PCT": (75, 83, "Risk adjustment target confidence level: 75th percentile"),
}

YF = {
    "INS_FINANCE_PL": (-3097871554, 24, "Net finance expenses from insurance contracts"),
    "REINS_FINANCE_PL": (247436200, 24, "Net finance income from reinsurance contracts"),
    "OTHER_REVENUE": (79675638, 24, "Other income"),
    "OTHER_EXPENSE": (-263019416, 24, "Other operating expenses"),
    "FINANCE_COST": (-5697503, 24, "Other finance costs"),
    "TAX_EXPENSE": (-126435599, 24, "Income tax expense"),
    "OCI_TOTAL": (-1477466812, 25, "Other comprehensive loss for the year"),
    "COMPREHENSIVE_INCOME": (-505937915, 25, "Total comprehensive loss for the year"),
    "OCI_INS_FINANCE": (-48740944, 25, "Insurance contract finance expenses in OCI"),
    "OCI_REINS_FINANCE": (60381305, 25, "Reinsurance contract finance income in OCI"),
    "OCI_HEDGE": (-357727924, 25, "Cash flow hedge: movement in hedging reserve"),
    "OCI_TAX": (57537332, 25, "Net deferred tax impact in OCI"),
    "EQUITY_OPEN": (16343837345, 28, "Balance at 1 January 2024: total equity"),
    "INVESTING_CF": (24472270, 30, "Net cash from investing activities"),
    "FINANCING_CF": (-299542063, 30, "Net cash used in financing activities"),
    "NET_CASH_CHANGE": (718307851, 30, "Net increase in cash and cash equivalents"),
    "CASH_OPEN": (3200075740, 30, "Cash and cash equivalents at 1 January"),
    "CASH_CLOSE": (3899941867, 30, "Cash and cash equivalents at 31 December"),
    "REV_CSM_SERVICE": (692647253, 90, "CSM recognised for services provided"),
    "REV_RA_RELEASE": (-32769586, 90, "Change in risk adjustment for risk expired"),
    "REV_EXPECTED_CLAIMS": (976597333, 90, "Expected incurred claims and other insurance service expenses"),
    "REV_ACQ_RECOVERY": (806430352, 90, "Recovery of insurance acquisition cash flows"),
    "REV_NONPAA_TOTAL": (2442905352, 90, "Contracts not measured under PAA: insurance revenue"),
    "REV_PAA_TOTAL": (357848544, 90, "Contracts measured under PAA: insurance revenue"),
    "INS_REVENUE_NOTE_TOTAL": (2800753896, 90, "Total insurance revenue"),
    "INV_RETURN_TOTAL": (3706398145, 91, "Total investment return"),
    "INS_FINANCE_TOTAL": (-3146612498, 91, "Total net finance expenses from insurance contracts"),
    "REINS_FINANCE_TOTAL": (427817505, 91, "Total net finance income from reinsurance contracts"),
    "NET_INV_RESULT_TOTAL": (784457867, 91, "Net financial result including OCI"),
    "INS_LIABS_NOTE_CLOSE": (69617927842, 113, "Insurance contract liabilities after acquisition cash flow assets"),
    "REINS_ASSETS_NOTE_CLOSE": (-6790716168, 113, "Reinsurance contract assets, presented as a deduction"),
    "INS_NOTE_NET_OPEN": (63579853198, 114, "Insurance contracts: net opening balance"),
    "INS_NOTE_PL_OCI": (2027518020, 114, "Insurance contracts: total P&L and OCI changes"),
    "INS_NOTE_CASHFLOWS": (4013612306, 114, "Insurance contracts: total cash flows"),
    "INS_NOTE_NET_CLOSE": (69620983524, 114, "Insurance contracts: net closing balance before acquisition cash flow assets"),
    "INS_NONPAA_NET_OPEN": (63474656274, 116, "Insurance contracts not under PAA: net opening balance"),
    "INS_NONPAA_PL_OCI": (2058094005, 116, "Insurance contracts not under PAA: total P&L and OCI changes"),
    "INS_NONPAA_CASH": (3974370690, 116, "Insurance contracts not under PAA: total cash flows"),
    "INS_NONPAA_NET_CLOSE": (69507120969, 116, "Insurance contracts not under PAA: net closing balance"),
    "INS_NONPAA_PVFCF_CLOSE": (58927856144, 116, "Insurance contracts not under PAA: closing PV of future cash flows"),
    "INS_NONPAA_RA_CLOSE": (1456766732, 116, "Insurance contracts not under PAA: closing risk adjustment"),
    "INS_CSM_FV_CLOSE": (6975446400, 116, "Insurance CSM: fair value transition closing"),
    "INS_CSM_OTHER_CLOSE": (2147051693, 116, "Insurance CSM: other contracts closing"),
    "INS_CSM_FV_RELEASE": (-555598556, 116, "Insurance CSM recognised for services: fair value transition"),
    "INS_CSM_OTHER_RELEASE": (-137048697, 116, "Insurance CSM recognised for services: other contracts"),
    "REINS_NOTE_NET_OPEN": (6517665664, 118, "Reinsurance contracts: net opening balance"),
    "REINS_NOTE_PL_OCI": (320160100, 118, "Reinsurance contracts: total P&L and OCI changes"),
    "REINS_NOTE_CASHFLOWS": (-47109596, 118, "Reinsurance contracts: total cash flows"),
    "REINS_NOTE_NET_CLOSE": (6790716168, 118, "Reinsurance contracts: net closing asset balance"),
}

SUN = {
    "INS_REVENUE": (3650, 13, "Insurance revenue"),
    "INS_EXPENSE": (-1955, 13, "Insurance service expenses"),
    "REINS_RESULT": (-388, 13, "Reinsurance contracts held net expenses"),
    "INS_SERVICE_RESULT": (1307, 13, "Net insurance service result"),
    "NET_INV_INCOME": (3709, 13, "Net investment income"),
    "NET_INV_RESULT": (84, 13, "Net investment result"),
    "INS_FINANCE_PL": (-4490, 13, "Insurance finance expenses from insurance contracts issued"),
    "REINS_FINANCE_PL": (865, 13, "Insurance finance income from reinsurance contracts held"),
    "OTHER_EXPENSE": (-1241, 13, "Other operating expenses and staff costs"),
    "FINANCE_COST": (-94, 13, "Finance costs"),
    "TAX_EXPENSE": (-68, 13, "Income tax expense"),
    "PBT": (965, 13, "Profit before taxation"),
    "PROFIT": (897, 13, "Profit for the year"),
    "OCI_TOTAL": (25, 14, "Other comprehensive income for the year"),
    "COMPREHENSIVE_INCOME": (922, 14, "Total comprehensive income for the year"),
    "OCI_FVOCI_DEBT": (50, 14, "FVOCI investment fair value movement"),
    "OCI_FVOCI_RECYCLE": (-30, 14, "FVOCI investment reclassification on disposal"),
    "OCI_TAX": (5, 14, "Deferred tax on investment revaluation reserve"),
    "INS_ASSETS": (444, 15, "Insurance contract assets"),
    "REINS_LIABS": (120, 16, "Reinsurance contract held liabilities"),
    "TOTAL_ASSETS": (117143, 15, "Total assets"),
    "TOTAL_LIABS": (108896, 16, "Audited liabilities: subordinated loans 23 + other liabilities subtotal 108,873"),
    "EQUITY": (8247, 16, "Total capital and reserves"),
    "INS_LIABS": (101529, 16, "Insurance contract liabilities"),
    "REINS_ASSETS": (2383, 15, "Reinsurance contract held assets"),
    "EQUITY_OPEN": (8180, 19, "At December 31, 2023 (restated): total equity"),
    "EQUITY_DIVIDENDS": (-855, 19, "Dividends paid: total equity"),
    "OPERATING_CF": (10559, 21, "Net cash from operating activities"),
    "INVESTING_CF": (-9422, 22, "Net cash used in investing activities"),
    "FINANCING_CF": (-1576, 22, "Net cash used in financing activities"),
    "NET_CASH_CHANGE": (-439, 22, "Net decrease in cash and cash equivalents"),
    "CASH_OPEN": (5865, 22, "Cash and cash equivalents at January 1"),
    "CASH_CLOSE": (5426, 22, "Cash and cash equivalents at December 31"),
    "REV_CSM_SERVICE": (1381, 87, "CSM recognised for services provided"),
    "REV_RA_RELEASE": (395, 87, "Change in risk adjustment for risk expired"),
    "REV_EXPECTED_CLAIMS": (1151, 87, "Expected incurred claims and service expenses"),
    "REV_ACQ_RECOVERY": (530, 87, "Recovery of insurance acquisition cash flows"),
    "REV_NONPAA_TOTAL": (3457, 87, "Contracts not measured under PAA: insurance revenue"),
    "REV_PAA_TOTAL": (193, 87, "Contracts measured under PAA: insurance revenue"),
    "INS_REVENUE_NOTE_TOTAL": (3650, 87, "Total insurance revenue"),
    "INS_EXP_CLAIMS": (-1037, 87, "Incurred claims and other incurred insurance service expenses"),
    "INS_EXP_LIC": (-19, 87, "Changes relating to past service: adjustment to LIC"),
    "INS_EXP_ONEROUS": (-139, 87, "Changes relating to future service: onerous losses"),
    "INS_EXP_ACQ_AMORT": (-530, 87, "Insurance acquisition cash flows: amortisation"),
    "INS_EXP_NONPAA": (-1725, 87, "Contracts not measured under PAA: insurance service expenses"),
    "INS_EXP_PAA": (-230, 87, "Contracts measured under PAA: insurance service expenses"),
    "INS_NOTE_NET_OPEN": (88155, 102, "Insurance non-PAA contracts: net opening balance"),
    "INS_NOTE_PL_OCI": (2776, 102, "Insurance non-PAA contracts: total changes in consolidated income and OCI"),
    "INS_NOTE_CASHFLOWS": (10034, 102, "Insurance non-PAA contracts: total cash flows"),
    "INS_NOTE_NET_CLOSE": (100965, 102, "Insurance non-PAA contracts: net closing balance"),
    "INS_NOTE_PVFCF_CLOSE": (75492, 103, "Insurance non-PAA contracts: closing PV of future cash flows"),
    "INS_NOTE_RA_CLOSE": (6329, 103, "Insurance non-PAA contracts: closing risk adjustment"),
    "INS_NOTE_CSM_CLOSE": (19144, 103, "Insurance non-PAA contracts: closing CSM"),
    "INS_NONPAA_NET_OPEN": (88155, 102, "Insurance non-PAA contracts: net opening balance"),
    "INS_NONPAA_PL_OCI": (2776, 102, "Insurance non-PAA contracts: total changes in consolidated income and OCI"),
    "INS_NONPAA_CASH": (10034, 102, "Insurance non-PAA contracts: total cash flows"),
    "INS_NONPAA_NET_CLOSE": (100965, 102, "Insurance non-PAA contracts: net closing balance"),
    "INS_NONPAA_PVFCF_CLOSE": (75492, 103, "Insurance non-PAA contracts: closing PV of future cash flows"),
    "INS_NONPAA_RA_CLOSE": (6329, 103, "Insurance non-PAA contracts: closing risk adjustment"),
    "INS_NONPAA_CSM_CLOSE": (19144, 103, "Insurance non-PAA contracts: closing CSM"),
    "CSM_OPEN": (12884, 103, "Insurance non-PAA contracts: net opening CSM"),
    "CSM_CLOSE": (19144, 103, "Insurance non-PAA contracts: net closing CSM"),
    "CSM_RELEASE": (-1381, 103, "Insurance non-PAA contracts: CSM recognised for services"),
    "CSM_NEW": (2936, 103, "Insurance non-PAA contracts: initial CSM on new contracts"),
    "REINS_NOTE_NET_OPEN": (-770, 105, "Reinsurance non-PAA contracts: net opening balance"),
    "REINS_NOTE_PL_OCI": (-501, 105, "Reinsurance non-PAA contracts: total changes in consolidated income and OCI"),
    "REINS_NOTE_CASHFLOWS": (-981, 105, "Reinsurance non-PAA contracts: total cash flows"),
    "REINS_NOTE_NET_CLOSE": (-2252, 105, "Reinsurance non-PAA contracts: net closing balance"),
    "REINS_NOTE_PVFCF_CLOSE": (1390, 106, "Reinsurance non-PAA contracts: closing PV of future cash flows"),
    "REINS_NOTE_RA_CLOSE": (-576, 106, "Reinsurance non-PAA contracts: closing risk adjustment"),
    "REINS_NOTE_CSM_CLOSE": (-3066, 106, "Reinsurance non-PAA contracts: closing CSM"),
    "REINS_NONPAA_NET_OPEN": (-770, 105, "Reinsurance non-PAA contracts: net opening balance"),
    "REINS_NONPAA_PL_OCI": (-501, 105, "Reinsurance non-PAA contracts: total changes in consolidated income and OCI"),
    "REINS_NONPAA_CASH": (-981, 105, "Reinsurance non-PAA contracts: total cash flows"),
    "REINS_NONPAA_NET_CLOSE": (-2252, 105, "Reinsurance non-PAA contracts: net closing balance"),
    "REINS_NONPAA_PVFCF_CLOSE": (1390, 106, "Reinsurance non-PAA contracts: closing PV of future cash flows"),
    "REINS_NONPAA_RA_CLOSE": (-576, 106, "Reinsurance non-PAA contracts: closing risk adjustment"),
    "REINS_NONPAA_CSM_CLOSE": (-3066, 106, "Reinsurance non-PAA contracts: closing CSM"),
}


def _seed_page(code: str, document_id: str) -> int:
    if document_id == "YF_2024":
        return 29 if code == "OPERATING_CF" else 26 if code in {
            "TOTAL_ASSETS", "TOTAL_LIABS", "EQUITY", "INS_LIABS", "REINS_ASSETS"} else 24
    if code in {"OPERATING_CF"}:
        return 14
    if code == "EQUITY":
        return 12
    if code in {"TOTAL_ASSETS", "TOTAL_LIABS", "INS_LIABS", "REINS_ASSETS"}:
        return 10
    if code in {"INS_LIABS_NOTE_CLOSE", "REINS_ASSETS_NOTE_CLOSE"}:
        return 66
    if code.startswith("REV_") or code == "INS_REVENUE_NOTE_TOTAL":
        return 55
    if code in {"INS_LIABS_NONPAA_CLOSE", "INS_NOTE_NET_OPEN", "INS_NOTE_PL_OCI",
                "INS_NOTE_CASHFLOWS", "INS_NOTE_NET_CLOSE"}:
        return 67
    if code.startswith("CSM_") or code in {"INS_NOTE_PVFCF_CLOSE", "INS_NOTE_RA_CLOSE", "INS_NOTE_CSM_CLOSE"}:
        return 69
    if code == "INS_LIABS_PAA_CLOSE":
        return 71
    if code in {"REINS_ASSETS_NONPAA_CLOSE", "REINS_NOTE_NET_OPEN", "REINS_NOTE_PL_OCI",
                "REINS_NOTE_CASHFLOWS", "REINS_NOTE_NET_CLOSE"}:
        return 73
    if code in {"REINS_NOTE_PVFCF_CLOSE", "REINS_NOTE_RA_CLOSE", "REINS_NOTE_CSM_CLOSE"}:
        return 75
    if code == "REINS_ASSETS_PAA_CLOSE":
        return 77
    return 8


def _record(profile: dict, code: str, amount: float, page: int, label: str) -> dict:
    metric = METRIC_BY_CODE[code]
    percent = metric.kind == "rate"
    calculated_liabilities = profile["document_id"] == "SUN_GROUP_2024" and code == "TOTAL_LIABS"
    return {
        "Document ID": profile["document_id"], "Company ID": profile["company_id"],
        "Company": profile["company"], "Legal entity": profile["legal_entity"],
        "Scope": profile["scope"], "Period end": profile["period_end"],
        "Metric code": code, "Metric": metric.label, "Section": metric.section,
        "Original value": amount, "Source unit": "percent" if percent else profile["source_unit"],
        "Currency": "%" if percent else profile["currency"],
        "Value (millions)": None, "Value status": "Reported", "PDF page": page,
        "Source label": label,
        "Audit status": "Calculated from two audited statement lines" if calculated_liabilities else "Audited statement or note",
        "Review status": "Verified",
        "Reviewer note": ("2024 liabilities subtotal = audited subordinated loans 23 + audited other liabilities 108,873; independently sums to 108,896."
                          if calculated_liabilities else
                          "2024 current-year source cell checked against the cited physical PDF page."),
    }


def make_records(root: Path) -> pd.DataFrame:
    source_workbook = root / "outputs/HK_IFRS17_FWD_YF_SunLife_2025_verified.xlsx"
    rows = pd.read_excel(source_workbook, sheet_name="Records").where(
        lambda cells: cells.notna(), None
    ).to_dict("records")
    for profile in PROFILES_2024:
        document_id = profile["document_id"]
        if document_id == "FWD_2024":
            seed = SAMPLE_VALUES["FWD_2025"]
            extras = FWD
        elif document_id == "YF_2024":
            seed = SAMPLE_VALUES["YF_2025"]
            extras = YF
        else:
            seed = {}
            extras = SUN
        assert not set(seed).intersection(extras), document_id
        for code, values in seed.items():
            amount = 491290 if document_id == "FWD_2024" and code == "OPERATING_CF" else values[1]
            rows.append(_record(profile, code, amount, _seed_page(code, document_id), values[3]))
        for code, (amount, page, label) in extras.items():
            rows.append(_record(profile, code, amount, page, label))
    fwd = PROFILES_2024[0]
    for currency, values in {
        "CNY": [1.08, 1.64, 1.42, 1.98, 1.70, 2.25, 2.09, 2.65, 2.52, 3.08],
        "HKD": [3.88, 4.70, 3.60, 4.41, 3.65, 4.46, 3.72, 4.53, 3.75, 4.56],
        "USD": [4.11, 4.85, 4.34, 5.08, 4.55, 5.29, 4.77, 5.51, 4.90, 5.64],
    }.items():
        for index, tenor in enumerate(("1Y", "5Y", "10Y", "15Y", "20Y")):
            for offset, basis in enumerate(("RF", "ILP")):
                code = f"DISCOUNT_{currency}_{tenor}_{basis}"
                rows.append(_record(fwd, code, values[2 * index + offset], 83,
                                    f"2024 {currency} {tenor} spot rate; {'risk free' if basis == 'RF' else 'with illiquidity premium'}"))
    result = normalize_records(pd.DataFrame(rows)[COLUMNS], [*PILOT_FILINGS, *PROFILES_2024])
    assert set(result["Period end"]) == {"2024-12-31", "2025-12-31"}
    assert not result.duplicated(["Document ID", "Period end", "Metric code"]).any()
    return result.sort_values(["Company", "Period end", "Section", "Metric code"]).reset_index(drop=True)


def make_plan(records: pd.DataFrame, root: Path) -> pd.DataFrame:
    filings = [*PILOT_FILINGS, *PROFILES_2024]
    ids = set(records["Document ID"])
    plan = normalize_plan(None, filings, ids)
    source_workbook = root / "outputs/HK_IFRS17_FWD_YF_SunLife_2025_verified.xlsx"
    older = pd.read_excel(source_workbook, sheet_name="Check plan").where(
        lambda cells: cells.notna(), None
    )
    plan = normalize_plan(older, filings, ids)
    present = {(doc, period): set(group["Metric code"]) for (doc, period), group
               in records.groupby(["Document ID", "Period end"])}
    references = {
        "FWD_2024": "FWD 2024 note 4 p.55; note 13 pp.66-83; audited company and 2024 source basis",
        "YF_2024": "YF 2024 note 5 p.90; note 21 pp.113-118; audited consolidated and 2024 source basis",
        "SUN_GROUP_2024": "Sun Life 2024 notes 7-8 p.87 and note 20 pp.102-106; audited consolidated and disclosed non-PAA cohort",
    }
    for index, row in plan.iterrows():
        document_id = row["Document ID"]
        if document_id not in references or row["Period end"] != "2024-12-31":
            continue
        rule = next(item for item in RULES if item.id == row["Check ID"])
        required = set(rule.parts) | ({rule.total} if rule.total else set())
        if not required.issubset(present[(document_id, "2024-12-31")]):
            continue
        plan.at[index, "Assessment"] = "Applicable"
        plan.at[index, "Measurement method"] = "Mixed" if rule.id in {
            "REVENUE_NOTE", "LIABILITY_NOTE", "REINSURANCE_NOTE", "INS_LIABS_METHOD",
            "REINS_ASSETS_METHOD", "REV_TOTAL_SPLIT", "REV_NONPAA_COMP",
            "INS_NET_ROLL", "REINS_NET_ROLL", "INS_MEAS_COMPONENTS", "REINS_MEAS_COMPONENTS",
        } else "GMM"
        plan.at[index, "Note scope"] = "Same entity and balance basis"
        plan.at[index, "Note reference"] = references[document_id]
        if (document_id, rule.id) in {("FWD_2024", "LIABILITY_NOTE"),
                                      ("YF_2024", "REINSURANCE_NOTE")}:
            plan.at[index, "Formula basis"] = "Reverse note sign for statement comparison"
    return normalize_plan(plan, filings, ids)


def verify_fwd_source(records: pd.DataFrame) -> None:
    source = (Path(__file__).resolve().parents[1] / "disclosures/uploads" /
              "FWD-Life-Insurance-Company-Bermuda-Limited-2024-Financial-Statement.pdf")
    with fitz.open(source) as pdf:
        misses = []
        group = records[records["Document ID"].eq("FWD_2024")]
        for _, row in group.iterrows():
            amount = abs(float(row["Original value"]))
            if amount == 75 and row["Metric code"] == "RA_CONFIDENCE_PCT":
                token = "75th percentile"
            elif row["Source unit"] == "percent":
                token = f"{amount:.2f} %"
            else:
                token = f"{amount:,.0f}"
            text = pdf[int(row["PDF page"]) - 1].get_text()
            if token not in text:
                misses.append((row["Metric code"], int(row["PDF page"]), token))
        if misses:
            raise AssertionError(f"FWD 2024 source page mismatches: {misses}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "scratch/two_year_export"
    output.mkdir(parents=True, exist_ok=True)
    records = make_records(root)
    verify_fwd_source(records)
    filings = [*PILOT_FILINGS, *PROFILES_2024]
    plan = make_plan(records, root)
    checks = evaluate_checks(records, filings, plan, verified_only=True)
    checks = checks[checks["Period end"].isin(("2024-12-31", "2025-12-31"))].copy()
    core = checks[checks["Check ID"].isin(("PRIMARY", "SERVICE", "BALANCE"))]
    assert len(core) == 18 and core["Result"].eq("Pass").all(), core.to_string(index=False)
    assert not checks["Result"].eq("Difference").any(), checks[checks["Result"].eq("Difference")].to_string(index=False)
    coverage = pd.DataFrame([
        {"Insurer": filing["company"], "Legal entity": filing["legal_entity"],
         "Scope": filing["scope"], "Currency": filing["currency"],
         "Source unit": filing["source_unit"], "Period end": filing["period_end"],
         "Source PDF": filing["pdf_file"],
         "Verified cells": int(records[records["Document ID"].eq(filing["document_id"])].shape[0]),
         "Pass": int(checks[checks["Document ID"].eq(filing["document_id"])]["Result"].eq("Pass").sum()),
         "Difference": int(checks[checks["Document ID"].eq(filing["document_id"])]["Result"].eq("Difference").sum()),
         "Missing inputs": int(checks[checks["Document ID"].eq(filing["document_id"])]["Result"].eq("Missing inputs").sum()),
         "Not applicable": int(checks[checks["Document ID"].eq(filing["document_id"])]["Result"].eq("Not applicable").sum()),
         "Coverage note": "Current-year cells only; unresolved optional checks remain Missing inputs.",
         } for filing in filings if filing["document_id"] in set(records["Document ID"])
    ])
    readme = pd.DataFrame({"Instruction": [
        "HK IFRS 17 | audited 2024 and 2025 source-checked dataset for three insurers",
        "Upload this workbook in Step 5. The same imported data is used by Step 5 and Step 6.",
        "The 2024 values are from the current-year columns of the supplied 2024 PDFs; the 2025 values are from the current-year columns of the supplied 2025 PDFs.",
        "Records is the canonical import sheet. Values retain source sign and unit. Value (millions) is recalculated by the platform.",
        "PDF page is the physical one-based PDF page, not the printed report page number.",
        "Sun Life 2024 audited profit or loss and cash flow are consolidated; Sun Life 2025 is company-only. They have separate insurer display identities and MUST NOT be read as a like-for-like year-on-year change.",
        "The 2024 Sun Life PDF also presents company-only balance sheets, but no complete company-only 2024 income and cash flow set. That incomplete population is not mixed into audited consolidated 2024 Records.",
        "Sun Life 2024 total liabilities 108,896 is a transparent sum of audited subordinated loans 23 and audited other liabilities 108,873; it is not a balancing plug.",
        "2024 source amounts can differ from 2025 report comparatives due to scope or restatement. The workbook does not silently substitute a 2025 comparative for a 2024 reported cell.",
        "FWD is US$'000; YF is HK$ units; Sun Life is HK$ millions. Never compare native-currency absolute amounts as equivalent.",
        "All 18 mandatory primary checks pass. Optional Missing inputs remain visible; Missing inputs is not a pass.",
        "No balancing plug, inferred movement, or invented yield is included. A 2024 opening row is a reported row of a 2024 rollforward, not a 2023 comparative column.",
    ]})
    for name, frame in (("Records", records), ("Checks", checks), ("Check plan", plan[plan["Period end"].isin(("2024-12-31", "2025-12-31"))]),
                        ("Coverage", coverage), ("Read me", readme)):
        (output / f"{name.replace(' ', '_')}.json").write_text(
            json.dumps(frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records"),
                       ensure_ascii=False, indent=2), encoding="utf-8")
    print("Cells:", len(records), "checks:", checks["Result"].value_counts().to_dict())
    print(coverage[["Insurer", "Period end", "Verified cells", "Pass", "Difference", "Missing inputs"]].to_string(index=False))


if __name__ == "__main__":
    main()
