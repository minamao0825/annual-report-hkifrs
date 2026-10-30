"""Editable physical-page and table selections for Step 1 batch extraction."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import pandas as pd

from .data import COLUMNS

PAGE_DISCOVERY_VERSION = 10
EXTRACTION_PLAN_VERSION = 1


TABLE_METRICS = {
    "Profit or loss": (
        "INS_REVENUE", "INS_EXPENSE", "REINS_RESULT", "INS_SERVICE_RESULT",
        "INS_GROSS_RESULT", "INV_RETURN", "NET_INV_INCOME", "INS_FINANCE_PL",
        "REINS_FINANCE_PL", "NET_INV_RESULT", "OTHER_REVENUE", "OTHER_EXPENSE",
        "FINANCE_COST", "PBT", "TAX_EXPENSE", "PROFIT",
    ),
    "Financial position": (
        "TOTAL_ASSETS", "TOTAL_LIABS", "EQUITY", "INS_ASSETS", "INS_LIABS",
        "REINS_ASSETS", "REINS_LIABS", "FIN_ASSET_FVOCI_DEBT", "FIN_ASSET_FVTPL_DEBT",
        "FIN_ASSET_FVTPL_EQUITY", "FIN_ASSET_FVTPL_FUNDS",
    ),
    "Cash flows": (
        "OPERATING_CF", "INVESTING_CF", "FINANCING_CF", "NET_CASH_CHANGE", "CASH_OPEN", "CASH_CLOSE",
    ),
    "CSM / contract note": ("CSM_OPEN", "CSM_NEW", "CSM_RELEASE", "CSM_NET_MOVEMENT", "CSM_CLOSE"),
    "Insurance revenue note": (
        "INS_REVENUE_NOTE_TOTAL", "REV_CSM_SERVICE", "REV_RA_RELEASE",
        "REV_EXPECTED_CLAIMS", "REV_ACQ_RECOVERY", "REV_POLICYHOLDER_TAX",
        "REV_NONPAA_TOTAL", "REV_PAA_TOTAL",
    ),
    "Insurance balances note": ("INS_LIABS_NOTE_OPEN", "INS_LIABS_NOTE_MOVEMENT", "INS_LIABS_NOTE_CLOSE"),
    "Reinsurance balances note": ("REINS_ASSETS_NOTE_OPEN", "REINS_ASSETS_NOTE_MOVEMENT", "REINS_ASSETS_NOTE_CLOSE"),
    "Insurance contract balances": (
        "INS_LIABS_NOTE_OPEN", "INS_LIABS_NOTE_CLOSE", "INS_LIABS_NONPAA_CLOSE", "INS_LIABS_PAA_CLOSE",
        "INS_ACQ_ASSET_CLOSE",
    ),
    "Insurance net movement": (
        "INS_NOTE_NET_OPEN", "INS_NOTE_PL_OCI", "INS_NOTE_CASHFLOWS", "INS_NOTE_NET_CLOSE",
    ),
    "Insurance measurement components": (
        "INS_NOTE_PVFCF_CLOSE", "INS_NOTE_RA_CLOSE", "INS_NOTE_CSM_CLOSE", "INS_NOTE_NET_CLOSE",
    ),
    "Reinsurance contract balances": (
        "REINS_ASSETS_NOTE_OPEN", "REINS_ASSETS_NOTE_CLOSE", "REINS_ASSETS_NONPAA_CLOSE", "REINS_ASSETS_PAA_CLOSE",
    ),
    "Reinsurance net movement": (
        "REINS_NOTE_NET_OPEN", "REINS_NOTE_PL_OCI", "REINS_NOTE_CASHFLOWS", "REINS_NOTE_NET_CLOSE",
    ),
    "Reinsurance measurement components": (
        "REINS_NOTE_PVFCF_CLOSE", "REINS_NOTE_RA_CLOSE", "REINS_NOTE_CSM_CLOSE", "REINS_NOTE_NET_CLOSE",
    ),
    "Comprehensive income": (
        "OCI_TOTAL", "COMPREHENSIVE_INCOME", "OCI_FVOCI_DEBT", "OCI_FVOCI_RECYCLE",
        "OCI_INS_FINANCE", "OCI_REINS_FINANCE", "OCI_HEDGE", "OCI_TAX",
        "OCI_FAIR_VALUE_RESERVE", "OCI_FX_TRANSLATION", "OCI_ECL_ADJUSTMENT",
    ),
    "Other comprehensive income analysis": (
        "OCI_TOTAL", "OCI_FVOCI_DEBT", "OCI_FVOCI_RECYCLE", "OCI_INS_FINANCE",
        "OCI_REINS_FINANCE", "OCI_HEDGE", "OCI_TAX", "OCI_FAIR_VALUE_RESERVE",
        "OCI_FX_TRANSLATION", "OCI_ECL_ADJUSTMENT",
    ),
    "Equity movement": ("EQUITY_OPEN", "EQUITY", "EQUITY_DIVIDENDS", "EQUITY_NEW_CAPITAL", "EQUITY_OTHER"),
    "Investment result analysis": (
        "INV_RETURN_TOTAL", "NET_INV_RESULT_TOTAL", "INS_FINANCE_TOTAL", "REINS_FINANCE_TOTAL",
        "INV_YIELD", "INV_INTEREST_EIR",
        "INV_OTHER_REV_UNDERLYING_DESIGNATED", "INV_OTHER_REV_UNDERLYING_MANDATORY",
        "INV_OTHER_REV_UNDERLYING_INCOME", "INV_OTHER_REV_NONUNDERLYING_AC_FVOCI",
        "INV_OTHER_REV_NONUNDERLYING_FVPL", "INV_OTHER_REV_NONUNDERLYING_INCOME",
        "INV_OTHER_REV_TOTAL", "INV_IMPAIRMENT_AC", "INV_IMPAIRMENT_FVOCI",
        "INV_IMPAIRMENT_TOTAL",
    ),
    "Financial investment classification": (
        "FIN_ASSET_TOTAL", "FIN_ASSET_AC", "FIN_ASSET_AC_DEBT", "FIN_ASSET_AC_LOANS",
        "FIN_ASSET_FVOCI_DEBT", "FIN_ASSET_FVOCI_EQUITY", "FIN_ASSET_FVTPL_DEBT",
        "FIN_ASSET_FVTPL_EQUITY", "FIN_ASSET_FVTPL_FUNDS", "FIN_ASSET_FVTPL_INTEREST",
        "FIN_ASSET_FVTPL_TRUST_EQUITY", "FIN_ASSET_FVTPL_PARTNERSHIPS",
        "FIN_ASSET_FVTPL_MORTGAGES", "FIN_ASSET_FVTPL_LOANS",
        "FIN_ASSET_FVTPL_UNLISTED_EQ_OTHER", "FIN_ASSET_FVTPL_DERIVATIVES",
    ),
    "Insurance service expense analysis": (
        "INS_EXP_CLAIMS", "INS_EXP_ACQ_AMORT", "INS_EXP_ONEROUS", "INS_EXP_LIC",
        "INS_EXP_NONPAA", "INS_EXP_PAA",
    ),
    "Expenses note": (
        "EXP_NOTE_CLAIMS", "EXP_NOTE_COMMISSIONS", "EXP_NOTE_STAFF", "EXP_NOTE_DEPRECIATION",
        "EXP_NOTE_AMORTISATION", "EXP_NOTE_MARKETING", "EXP_NOTE_PROFESSIONAL", "EXP_NOTE_IT",
        "EXP_NOTE_INV_MGMT", "EXP_NOTE_OTHER", "EXP_NOTE_TOTAL", "OTHER_EXPENSE",
    ),
    "Investment assets note": (
        "INV_NOTE_DEBT", "INV_NOTE_EQUITY", "INV_NOTE_FUNDS", "INV_NOTE_GOV_BONDS",
        "INV_NOTE_CORP_BONDS", "INV_NOTE_STRUCTURED",
    ),
    "Contract asset and liability summary": (
        "INS_NET_BALANCE", "REINS_NET_BALANCE",
    ),
    "Insurance non-PAA remaining/incurred movement": (
        "INS_NONPAA_NET_OPEN", "INS_NONPAA_PL_OCI", "INS_NONPAA_CASH", "INS_NONPAA_NET_CLOSE",
        "INS_GROSS_OPEN", "INS_GROSS_PL_OCI", "INS_GROSS_CASH", "INS_GROSS_CLOSE",
        "INS_NONPAA_LRC_CLOSE", "INS_NONPAA_LC_CLOSE", "INS_NONPAA_LIC_CLOSE",
        "INS_LIABS_NONPAA_CLOSE", "INS_EXP_NONPAA", "INS_EXP_CLAIMS", "INS_EXP_ACQ_AMORT",
        "INS_EXP_ONEROUS", "INS_EXP_LIC",
    ),
    "Insurance non-PAA measurement reconciliation": (
        "INS_NONPAA_PVFCF_OPEN", "INS_NONPAA_RA_OPEN", "CSM_OPEN",
        "INS_CSM_FV_OPEN", "INS_CSM_OTHER_OPEN",
        "INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE", "INS_NONPAA_CSM_CLOSE",
        "INS_CSM_FV_CLOSE", "INS_CSM_MOD_CLOSE", "INS_CSM_OTHER_CLOSE",
        "INS_CSM_FV_PL_OCI", "INS_CSM_OTHER_PL_OCI",
        "INS_CSM_FV_RELEASE", "INS_CSM_OTHER_RELEASE",
        "CSM_NEW", "CSM_RELEASE", "CSM_CLOSE", "CSM_ESTIMATE_CHANGE", "CSM_FINANCE_CHANGE",
    ),
    "Insurance PAA remaining/incurred movement": (
        "INS_PAA_NET_OPEN", "INS_PAA_PL_OCI", "INS_PAA_CASH", "INS_PAA_NET_CLOSE",
        "INS_PAA_LRC_CLOSE", "INS_PAA_LC_CLOSE", "INS_PAA_LIC_CLOSE",
        "INS_LIABS_PAA_CLOSE", "INS_EXP_PAA",
    ),
    "Reinsurance non-PAA remaining/incurred movement": (
        "REINS_NONPAA_NET_OPEN", "REINS_NONPAA_PL_OCI", "REINS_NONPAA_CASH", "REINS_NONPAA_NET_CLOSE",
        "REINS_NONPAA_ARC_CLOSE", "REINS_NONPAA_LOSS_RECOVERY_CLOSE", "REINS_NONPAA_AIC_CLOSE",
        "REINS_ASSETS_NONPAA_CLOSE",
    ),
    "Reinsurance non-PAA measurement reconciliation": (
        "REINS_CSM_FV_OPEN", "REINS_CSM_OTHER_OPEN",
        "REINS_NONPAA_PVFCF_CLOSE", "REINS_NONPAA_RA_CLOSE", "REINS_NONPAA_CSM_CLOSE",
        "REINS_CSM_FV_CLOSE", "REINS_CSM_MOD_CLOSE", "REINS_CSM_OTHER_CLOSE", "REINS_CSM_RELEASE",
    ),
    "Reinsurance PAA remaining/incurred movement": (
        "REINS_PAA_NET_OPEN", "REINS_PAA_PL_OCI", "REINS_PAA_CASH", "REINS_PAA_NET_CLOSE",
        "REINS_PAA_ARC_CLOSE", "REINS_PAA_LOSS_RECOVERY_CLOSE", "REINS_PAA_AIC_CLOSE",
        "REINS_ASSETS_PAA_CLOSE",
    ),
    "Initially recognised insurance contracts": (
        "NB_INS_PROFIT_CSM", "NB_INS_PROFIT_PV_IN", "NB_INS_PROFIT_PV_OUT", "NB_INS_PROFIT_RA",
        "NB_INS_ONEROUS_PV_IN", "NB_INS_ONEROUS_PV_OUT", "NB_INS_ONEROUS_RA", "NB_INS_ONEROUS_LOSS",
    ),
    "Initially recognised reinsurance contracts": (
        "NB_REINS_CSM", "NB_REINS_PV_IN", "NB_REINS_PV_OUT", "NB_REINS_RA",
    ),
    "Expected CSM recognition": (
        "CSM_MAT_INS_1Y", "CSM_MAT_INS_1_5Y", "CSM_MAT_INS_5_10Y", "CSM_MAT_INS_GT10Y",
        "CSM_MAT_REINS_1Y", "CSM_MAT_REINS_1_5Y", "CSM_MAT_REINS_5_10Y", "CSM_MAT_REINS_GT10Y",
    ),
    "Risk adjustment confidence level": ("RA_CONFIDENCE_PCT",),
}
for _currency in ("CNY", "HKD", "USD"):
    TABLE_METRICS[f"Discount rates · {_currency}"] = tuple(
        f"DISCOUNT_{_currency}_{tenor}_{basis}"
        for tenor in ("1Y", "5Y", "10Y", "15Y", "20Y") for basis in ("RF", "ILP")
    ) + tuple(
        f"DISCOUNT_{_currency}_{tenor}_SPOT_{bound}"
        for tenor in ("1Y", "5Y", "10Y", "15Y", "20Y")
        for bound in ("LOW", "HIGH")
    )
TABLE_METRICS["Discount rates · Sun Life disclosed portfolio groups"] = tuple(
    f"DISCOUNT_CNY_{tenor}_PREMIUM"
    for tenor in ("1Y", "5Y", "10Y", "15Y", "20Y")
) + tuple(
    f"DISCOUNT_OTHER_PORTFOLIOS_{tenor}_{basis}"
    for tenor in ("1Y", "5Y", "10Y", "15Y", "20Y")
    for basis in ("RF", "PREMIUM_UP_TO")
)

# Page discovery targets are physical report tables, not individual currencies,
# contract columns or reconciliation line items. Keep the older names above for
# saved pilot hints and existing reviewed extraction plans.
DISCOVERY_TARGETS = {
    "Profit or loss": ("Profit or loss",),
    "Comprehensive income": ("Comprehensive income",),
    "Financial position": ("Financial position",),
    "Equity movement": ("Equity movement",),
    "Cash flows": ("Cash flows",),
    "Investment result analysis": ("Investment result analysis",),
    "Financial investment classification": ("Financial investment classification",),
    "Insurance and reinsurance contracts": (
        "Insurance revenue note", "Insurance service expense analysis",
        "Contract asset and liability summary", "Insurance balances note",
        "Reinsurance balances note", "Insurance contract balances",
        "Reinsurance contract balances", "CSM / contract note",
        "Insurance net movement", "Insurance measurement components",
        "Insurance non-PAA remaining/incurred movement",
        "Insurance non-PAA measurement reconciliation",
        "Insurance PAA remaining/incurred movement",
        "Reinsurance net movement", "Reinsurance measurement components",
        "Reinsurance non-PAA remaining/incurred movement",
        "Reinsurance non-PAA measurement reconciliation",
        "Reinsurance PAA remaining/incurred movement",
        "Initially recognised insurance contracts",
        "Initially recognised reinsurance contracts", "Expected CSM recognition",
        "Risk adjustment confidence level",
    ),
    "Discount rates and illiquidity premiums": (
        "Discount rates · CNY", "Discount rates · HKD", "Discount rates · USD",
        "Discount rates · Sun Life disclosed portfolio groups",
    ),
}
for _target, _members in DISCOVERY_TARGETS.items():
    TABLE_METRICS[_target] = tuple(dict.fromkeys(
        code for member in _members for code in TABLE_METRICS[member]
    ))


def discovery_target_for(table: str) -> str:
    """Map older detailed page selections to their report-level table."""
    if table in {
        "Insurance service expenses", "Insurance and reinsurance contract balances",
        "Insurance contract movement and measurement",
        "Reinsurance contract movement and measurement",
    }:
        return "Insurance and reinsurance contracts"
    for target, members in DISCOVERY_TARGETS.items():
        if table == target or table in members:
            return target
    return table

TABLE_FAMILIES = {
    "Primary statements": ("Profit or loss", "Comprehensive income", "Financial position", "Equity movement", "Cash flows"),
    "Revenue, expense and investments": (
        "Insurance revenue note", "Insurance service expense analysis", "Expenses note",
        "Other comprehensive income analysis", "Investment result analysis",
        "Financial investment classification", "Investment assets note",
    ),
    "Insurance contract movements": (
        "Contract asset and liability summary", "Insurance non-PAA remaining/incurred movement",
        "Insurance non-PAA measurement reconciliation", "Insurance PAA remaining/incurred movement",
        "Insurance contract balances", "Insurance net movement", "Insurance measurement components",
        "CSM / contract note",
    ),
    "Reinsurance contract movements": (
        "Reinsurance non-PAA remaining/incurred movement", "Reinsurance non-PAA measurement reconciliation",
        "Reinsurance PAA remaining/incurred movement",
        "Reinsurance contract balances", "Reinsurance net movement", "Reinsurance measurement components",
    ),
    "New business and assumptions": (
        "Initially recognised insurance contracts", "Initially recognised reinsurance contracts",
        "Expected CSM recognition", "Discount rates · CNY", "Discount rates · HKD",
        "Discount rates · USD", "Discount rates · Sun Life disclosed portfolio groups",
        "Risk adjustment confidence level",
    ),
}
PLAN_COLUMNS = ["Extract", "Physical PDF page", "Table"]
RECORD_KEYS = ["Document ID", "Period end", "Metric code"]


def suggested_plan(filing: dict, total_pages: int) -> pd.DataFrame:
    """Seed editable rows from manually checked pilot hints; CSM remains opt-in."""
    keys = (
        ("page_profit", "Profit or loss"),
        ("page_balance", "Financial position"),
        ("page_cashflow", "Cash flows"),
        ("page_csm", "CSM / contract note"),
    )
    rows = []
    for key, table in keys:
        page = int(filing.get(key) or 0)
        if 1 <= page <= total_pages:
            rows.append({"Extract": key != "page_csm", "Physical PDF page": page, "Table": table})
    for page, table in filing.get("note_page_hints", ()):
        if 1 <= int(page) <= total_pages and table in TABLE_METRICS:
            row = {"Extract": False, "Physical PDF page": int(page), "Table": table}
            if row not in rows:
                rows.append(row)
    return pd.DataFrame(rows, columns=PLAN_COLUMNS)


def validate_plan(frame: pd.DataFrame, total_pages: int) -> list[tuple[int, str]]:
    if not set(PLAN_COLUMNS).issubset(frame.columns):
        raise ValueError("The extraction plan needs Extract, Physical PDF page and Table columns.")
    selected = []
    for index, row in frame.iterrows():
        if pd.isna(row["Extract"]) or not bool(row["Extract"]):
            continue
        raw_page = row["Physical PDF page"]
        try:
            page = int(raw_page)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Plan row {index + 1}: enter a physical PDF page number.") from exc
        if pd.isna(raw_page) or float(raw_page) != page or not 1 <= page <= total_pages:
            raise ValueError(f"Plan row {index + 1}: page must be an integer from 1 to {total_pages}.")
        table = str(row["Table"]).strip()
        if table not in TABLE_METRICS:
            raise ValueError(f"Plan row {index + 1}: choose a supported table.")
        pair = (page, table)
        if pair not in selected:
            selected.append(pair)
    if len({page for page, _ in selected}) > 12:
        raise ValueError("Select at most 12 physical pages per run; run another batch for additional pages.")
    return selected


def group_pages(selections: list[tuple[int, str]]) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = OrderedDict()
    for page, table in selections:
        grouped.setdefault(page, []).append(table)
    return grouped


def metric_codes_for(tables: list[str]) -> set[str]:
    return {code for table in tables for code in TABLE_METRICS[table]}


def merge_extracted(current: pd.DataFrame, incoming: pd.DataFrame,
                    earlier_batch_keys: set[tuple] | None = None,
                    source_task: tuple[int, str] | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Replace one table-page's Pending set, preserving reviewed and failed pages."""
    if incoming.empty:
        return current.copy(), {"added": 0, "replaced_pending": 0,
                                "removed_pending": 0, "preserved": 0}
    if not set(COLUMNS).issubset(incoming.columns):
        raise ValueError("Extracted records are missing required columns.")
    incoming = incoming.drop_duplicates(RECORD_KEYS, keep="first").copy()
    old_keys = set(map(tuple, current[RECORD_KEYS].itertuples(index=False, name=None)))
    locked = current[current["Review status"].ne("Pending")]
    protected = set(map(tuple, locked[RECORD_KEYS].itertuples(index=False, name=None)))
    protected.update(earlier_batch_keys or set())
    stale_pending_keys: set[tuple] = set()
    if source_task is not None:
        page, table = source_task
        task_mask = (current["Review status"].eq("Pending")
                     & current["PDF page"].eq(page)
                     & current["Metric code"].isin(TABLE_METRICS[table]))
        task_keys = list(map(tuple, current[RECORD_KEYS].itertuples(index=False, name=None)))
        stale_mask = task_mask & pd.Series(
            [key not in protected for key in task_keys], index=current.index)
        stale_pending_keys = {key for key, remove in zip(task_keys, stale_mask) if remove}
        current = current.loc[~stale_mask].copy()
    source_keys = list(map(tuple, incoming[RECORD_KEYS].itertuples(index=False, name=None)))
    permitted = incoming[[key not in protected for key in source_keys]].copy()
    permitted_keys = set(map(tuple, permitted[RECORD_KEYS].itertuples(index=False, name=None)))
    remaining = current[[key not in permitted_keys for key in map(tuple, current[RECORD_KEYS].itertuples(index=False, name=None))]]
    merged = pd.concat([remaining, permitted], ignore_index=True)[COLUMNS]
    return merged, {
        "added": len(permitted_keys - old_keys),
        "replaced_pending": len(permitted_keys & old_keys),
        "removed_pending": len(stale_pending_keys - permitted_keys),
        "preserved": len(source_keys) - len(permitted_keys),
    }


def extract_confirmed_batch(
    tasks: list[tuple[int, str]], *,
    extractor: Callable[[int, str], pd.DataFrame],
    load_current: Callable[[], pd.DataFrame],
    save_current: Callable[[pd.DataFrame], None],
    progress: Callable[[int, int, int, str], None] | None = None,
    max_workers: int = 1,
) -> pd.DataFrame:
    """Extract independently; merge and save in the original reviewed order."""
    if not 1 <= max_workers <= 4:
        raise ValueError("Choose 1 to 4 parallel extraction requests.")
    unique_tasks = list(dict.fromkeys(tasks))
    rows: list[dict] = []
    earlier_keys: set[tuple] = set()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(extractor, page, table) for page, table in unique_tasks]
        for index, ((physical_page, table), future) in enumerate(zip(unique_tasks, futures), start=1):
            outcome = {
                "Physical PDF page": physical_page, "Table": table,
                "Status": "Failed", "Detail": "",
                "Added": 0, "Refreshed Pending": 0,
                "Removed stale Pending": 0, "Preserved": 0,
            }
            try:
                incoming = future.result()
                if incoming.empty:
                    outcome["Detail"] = ("No unambiguous mapped cells found; inspect this PDF page "
                                         "and retry this table alone.")
                else:
                    merged, counts = merge_extracted(load_current(), incoming, earlier_keys,
                                                      source_task=(physical_page, table))
                    if counts["added"] or counts["replaced_pending"] or counts["removed_pending"]:
                        save_current(merged)
                    earlier_keys.update(map(tuple, incoming[RECORD_KEYS].itertuples(index=False, name=None)))
                    outcome.update({
                        "Status": "Saved as Pending", "Detail": "",
                        "Added": counts["added"],
                        "Refreshed Pending": counts["replaced_pending"],
                        "Removed stale Pending": counts["removed_pending"],
                        "Preserved": counts["preserved"],
                    })
            except Exception as exc:
                outcome["Detail"] = str(exc)
            rows.append(outcome)
            if progress is not None:
                progress(index, len(unique_tasks), physical_page, table)
    return pd.DataFrame(rows, columns=[
        "Physical PDF page", "Table", "Status", "Detail",
        "Added", "Refreshed Pending", "Removed stale Pending", "Preserved",
    ])


