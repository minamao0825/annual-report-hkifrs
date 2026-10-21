"""Source-page transcriptions for an explicitly unpublished demo preview.

These cells have been visually transcribed from the four user-provided PDFs.
They intentionally start Pending; publication requires a reviewer to check them.
"""

from __future__ import annotations

import pandas as pd

from .catalog import PILOT_FILINGS
from .data import COLUMNS, normalize_records


# metric: (2025 amount, 2024 amount, 2025 PDF page, source row label[, 2024 PDF page])
SAMPLE_VALUES = {
    "YF_2025": {
        "INS_REVENUE": (3076450861, 2800753896, 27, "Insurance revenue"),
        "INS_EXPENSE": (-2347425822, -2108240998, 27, "Insurance service expenses"),
        "REINS_RESULT": (80777402, -59368539, 27, "Net income/(expenses) from reinsurance contracts"),
        "INS_SERVICE_RESULT": (809802441, 633144359, 27, "Insurance service result"),
        "INV_RETURN": (6122878110, 3706398145, 27, "Investment return"),
        "PBT": (1542960350, 1097964496, 27, "Profit before tax"),
        "PROFIT": (1375561683, 971528897, 27, "Profit for the year"),
        "TOTAL_ASSETS": (107155953242, 92063965488, 29, "Total assets"),
        "TOTAL_LIABS": (89866761983, 76226066058, 29, "Total liabilities"),
        "EQUITY": (17289191259, 15837899430, 29, "Net assets"),
        "INS_LIABS": (82629053348, 69617927842, 29, "Insurance contract liabilities"),
        "REINS_ASSETS": (7482492186, 6790716168, 29, "Reinsurance contract assets"),
        "OPERATING_CF": (1340867332, 993377644, 32, "Net cash from operating activities"),
    },
    "FWD_2025": {
        "INS_REVENUE": (875076, 870383, 8, "Insurance revenue"),
        "INS_EXPENSE": (-576593, -568867, 8, "Insurance service expenses"),
        "REINS_RESULT": (-4905, -11723, 8, "Net expenses from reinsurance contracts held"),
        "INS_SERVICE_RESULT": (293578, 289793, 8, "Insurance service result"),
        "INV_RETURN": (816753, 362412, 8, "Investment return"),
        "PBT": (258466, 242355, 8, "Profit before tax"),
        "PROFIT": (217005, 146602, 8, "Profit for the year"),
        "TOTAL_ASSETS": (24196184, 19372489, 10, "Total assets"),
        "TOTAL_LIABS": (21194243, 16592986, 10, "Total liabilities"),
        "EQUITY": (3001941, 2779503, 12, "Total equity"),
        "INS_LIABS": (19993794, 15454063, 10, "Insurance contract liabilities"),
        "REINS_ASSETS": (797253, 475425, 10, "Reinsurance contract assets"),
        "OPERATING_CF": (173386, 494001, 14, "Net cash generated from operating activities"),
        "REV_CSM_SERVICE": (267218, 199049, 51, "Note 4 · CSM recognised for services provided"),
        "REV_RA_RELEASE": (15818, 13169, 51, "Note 4 · Change in risk adjustment for risk expired"),
        "REV_EXPECTED_CLAIMS": (256926, 208268, 51, "Note 4 · Expected incurred claims and service expenses"),
        "REV_ACQ_RECOVERY": (260621, 378085, 51, "Note 4 · Recovery of insurance acquisition cash flows"),
        "REV_NONPAA_TOTAL": (800583, 798571, 51, "Note 4 · Non-PAA insurance revenue subtotal"),
        "REV_PAA_TOTAL": (74493, 71812, 51, "Note 4 · Contracts measured under the PAA"),
        "INS_REVENUE_NOTE_TOTAL": (875076, 870383, 51, "Note 4 · Total insurance revenue"),
        "INS_LIABS_NOTE_CLOSE": (-19993794, -15454063, 62, "Note 13 · Insurance contract liabilities, statement sign"),
        "REINS_ASSETS_NOTE_CLOSE": (797253, 475425, 62, "Note 13 · Reinsurance contract assets"),
        "INS_LIABS_NONPAA_CLOSE": (-19973810, -15441761, 63, "Note 13 · Non-PAA closing insurance liabilities", 64),
        "INS_LIABS_PAA_CLOSE": (-19984, -12302, 67, "Note 13 · PAA closing insurance liabilities", 68),
        "REINS_ASSETS_NONPAA_CLOSE": (797204, 475410, 69, "Note 13 · Non-PAA closing reinsurance assets", 70),
        "REINS_ASSETS_PAA_CLOSE": (49, 15, 73, "Note 13 · PAA closing reinsurance assets", 74),
        "INS_NOTE_NET_OPEN": (-15364611, -13783685, 63, "Note 13 · Non-PAA net opening insurance balance", 64),
        "INS_NOTE_PL_OCI": (-875948, 16300, 63, "Note 13 · Non-PAA total changes in profit or loss and OCI", 64),
        "INS_NOTE_CASHFLOWS": (-3621056, -1597226, 63, "Note 13 · Non-PAA total cash flows", 64),
        "INS_NOTE_NET_CLOSE": (-19861615, -15364611, 63, "Note 13 · Non-PAA net closing insurance balance", 64),
        "INS_NOTE_PVFCF_CLOSE": (-17162870, -13400544, 65, "Note 13 · Non-PAA net closing PVFCF component", 66),
        "INS_NOTE_RA_CLOSE": (-248056, -231361, 65, "Note 13 · Non-PAA net closing RA component", 66),
        "INS_NOTE_CSM_CLOSE": (-2450689, -1732706, 65, "Note 13 · Non-PAA net closing CSM subtotal", 66),
        "CSM_OPEN": (-1732706, -1524075, 65, "Note 13 · Non-PAA net opening CSM subtotal", 66),
        "CSM_NEW": (-680897, -413205, 65, "Note 13 · CSM on contracts initially recognised", 66),
        "CSM_RELEASE": (267218, 199049, 65, "Note 13 · CSM recognised for services provided", 66),
        "CSM_NET_MOVEMENT": (-717983, -208631, 65, "Note 13 · CSM subtotal, total changes in profit or loss and OCI", 66),
        "CSM_CLOSE": (-2450689, -1732706, 65, "Note 13 · Non-PAA net closing CSM subtotal", 66),
        "REINS_NOTE_NET_OPEN": (298327, 183672, 69, "Note 13 · Non-PAA net opening reinsurance balance", 70),
        "REINS_NOTE_PL_OCI": (35481, -27367, 69, "Note 13 · Non-PAA total changes in profit or loss and OCI", 70),
        "REINS_NOTE_CASHFLOWS": (344353, 142022, 69, "Note 13 · Non-PAA total cash flows", 70),
        "REINS_NOTE_NET_CLOSE": (678161, 298327, 69, "Note 13 · Non-PAA net closing reinsurance balance", 70),
        "REINS_NOTE_PVFCF_CLOSE": (650787, 275210, 71, "Note 13 · Non-PAA net closing PVFCF component", 72),
        "REINS_NOTE_RA_CLOSE": (6907, 6906, 71, "Note 13 · Non-PAA net closing RA component", 72),
        "REINS_NOTE_CSM_CLOSE": (20467, 16211, 71, "Note 13 · Non-PAA net closing CSM subtotal", 72),
    },
    "CTF_2025": {
        "INS_REVENUE": (3890982, 3246501, 10, "Insurance revenue"),
        "INS_EXPENSE": (-2765611, -2508033, 10, "Insurance service expenses"),
        "REINS_RESULT": (-68249, 79940, 10, "Net (expenses)/income from reinsurance contracts held"),
        "INS_SERVICE_RESULT": (1057122, 818408, 10, "Insurance service result"),
        "INV_RETURN": (6035612, 2143062, 10, "Investment return"),
        "PBT": (1412737, 1180158, 10, "Profit before income tax"),
        "PROFIT": (1293571, 1071264, 11, "Profit for the year"),
        "TOTAL_ASSETS": (104529013, 87630411, 12, "Total assets"),
        "TOTAL_LIABS": (85056026, 69565699, 12, "Total liabilities"),
        "EQUITY": (19472987, 18064712, 13, "Total equity"),
        "INS_LIABS": (77481798, 64618152, 12, "Insurance contract liabilities"),
        "REINS_ASSETS": (97485, 254430, 12, "Reinsurance contract assets"),
        "OPERATING_CF": (3261911, 352640, 16, "Net cash inflow from operating activities"),
    },
    "SUN_2025": {
        "INS_REVENUE": (5219, 3650, 13, "Insurance revenue"),
        "INS_EXPENSE": (-2955, -1955, 13, "Insurance service expenses"),
        "REINS_RESULT": (-290, -388, 13, "Reinsurance contracts held net expenses"),
        "INS_SERVICE_RESULT": (1974, 1307, 13, "Net insurance service result"),
        "NET_INV_INCOME": (12651, 3886, 13, "Net investment income"),
        "PBT": (1577, 779, 13, "Profit before taxation"),
        "PROFIT": (1432, 774, 13, "Profit for the year"),
        "TOTAL_ASSETS": (152738, 116664, 15, "Total assets"),
        "TOTAL_LIABS": (144617, 108742, 15, "Total liabilities"),
        "EQUITY": (8121, 7922, 15, "Net assets"),
        "INS_LIABS": (137110, 101529, 15, "Insurance contract liabilities"),
        "REINS_ASSETS": (1813, 2383, 15, "Reinsurance contract held assets"),
        "OPERATING_CF": (24425, 10778, 18, "Net cash from operating activities"),
    },
}


def demo_records(document_id: str | None = None) -> pd.DataFrame:
    rows = []
    for filing in PILOT_FILINGS:
        if document_id is not None and document_id != filing["document_id"]:
            continue
        for code, amounts in SAMPLE_VALUES[filing["document_id"]].items():
            current, comparative, page, label = amounts[:4]
            comparative_page = amounts[4] if len(amounts) > 4 else page
            for year, amount, source_page in ((2025, current, page), (2024, comparative, comparative_page)):
                rows.append({
                    "Document ID": filing["document_id"],
                    "Company ID": filing["company_id"],
                    "Company": filing["company"],
                    "Legal entity": filing["legal_entity"],
                    "Scope": filing["scope"],
                    "Period end": filing["period_end"].replace("2025", str(year)),
                    "Metric code": code,
                    "Metric": "",
                    "Section": "",
                    "Original value": amount,
                    "Source unit": filing["source_unit"],
                    "Currency": filing["currency"],
                    "Value (millions)": None,
                    "Value status": "Reported",
                    "PDF page": source_page,
                    "Source label": label,
                    "Audit status": "Unaudited comparative" if filing["company_id"] == "SUN" and year == 2024 else ("Audited statement" if year == 2025 else "Comparative in 2025 statement"),
                    "Review status": "Pending",
                    "Reviewer note": "Demo transcription; check against the cited PDF page before verification.",
                })
    return normalize_records(pd.DataFrame(rows, columns=COLUMNS), list(PILOT_FILINGS))
