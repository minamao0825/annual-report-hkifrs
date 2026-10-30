"""Source Step 7 chart inventory adapted to HKFRS 17 filing disclosures.

The source module IDs are kept for traceability.  A conditional item is never
treated as a reported zero or as a comparable peer indicator without its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import METRIC_BY_CODE
from .extraction_plan import TABLE_METRICS


@dataclass(frozen=True)
class ChartRequirement:
    source_id: str
    section: str
    subsection: str
    hk_title: str
    decision: str  # Reuse, Adapt, Conditional, Exclude
    metrics: tuple[str, ...]
    note: str = ""


CHART_REQUIREMENTS = (
    ChartRequirement("summary_table", "Financial results", "Overview", "Financial highlights", "Adapt",
                     ("INS_REVENUE", "INS_SERVICE_RESULT", "PROFIT", "TOTAL_ASSETS", "EQUITY", "INS_LIABS", "CSM_CLOSE", "CSM_NEW")),
    ChartRequirement("prof_mix", "Financial results", "Profitability", "Insurance service and reported net investment results", "Adapt",
                     ("INS_SERVICE_RESULT", "NET_INV_RESULT"), "These are distinct reported results, not a complete decomposition of net profit."),
    ChartRequirement("tax_profit", "Financial results", "Profitability", "Pre-tax profit, net profit and effective tax rate", "Reuse",
                     ("PBT", "TAX_EXPENSE", "PROFIT")),
    ChartRequirement("net_profit", "Financial results", "Profitability", "Profit for the year", "Reuse", ("PROFIT",)),
    ChartRequirement("inc_total", "Financial results", "Insurance service", "Insurance revenue", "Reuse", ("INS_REVENUE",)),
    ChartRequirement("comp_1", "Financial results", "Insurance service", "Insurance revenue shares: PAA vs non-PAA", "Reuse",
                     ("REV_NONPAA_TOTAL", "REV_PAA_TOTAL")),
    ChartRequirement("comp_2", "Financial results", "Insurance service", "Non-PAA insurance revenue composition", "Adapt",
                     ("REV_CSM_SERVICE", "REV_RA_RELEASE", "REV_EXPECTED_CLAIMS", "REV_ACQ_RECOVERY", "REV_POLICYHOLDER_TAX"),
                     "Only separately disclosed components are plotted; no balancing residual is invented."),
    ChartRequirement("exp_total", "Financial results", "Insurance service", "Insurance service expenses", "Reuse", ("INS_EXPENSE",)),
    ChartRequirement("exp_1", "Financial results", "Insurance service", "Non-PAA insurance service expense composition", "Adapt",
                     ("INS_EXP_CLAIMS", "INS_EXP_ACQ_AMORT", "INS_EXP_ONEROUS", "INS_EXP_LIC")),
    ChartRequirement("exp_struct", "Financial results", "Insurance service", "Mainland expense classification", "Exclude", (),
                     "The source acquisition/maintenance/non-fulfilment classification is not assumed for HK filings."),
    ChartRequirement("perf_total", "Financial results", "Insurance service", "Insurance service result", "Reuse", ("INS_SERVICE_RESULT",)),
    ChartRequirement("prof_2025", "Financial results", "Insurance service", "Current-year insurance service result components", "Adapt",
                     ("INS_REVENUE", "INS_EXPENSE", "REINS_RESULT", "INS_SERVICE_RESULT")),
    ChartRequirement("prof_2024", "Financial results", "Insurance service", "Comparative insurance service result components", "Adapt",
                     ("INS_REVENUE", "INS_EXPENSE", "REINS_RESULT", "INS_SERVICE_RESULT")),
    ChartRequirement("inv_return", "Financial results", "Investment", "Investment return", "Adapt",
                     ("INV_RETURN", "NET_INV_INCOME"),
                     "P&L investment return is shown; investment OCI is excluded."),
    ChartRequirement("uw_profit", "Financial results", "Investment", "Net insurance and reinsurance finance result", "Adapt",
                     ("INS_FINANCE_PL", "REINS_FINANCE_PL"),
                     "Signed P&L total of insurance and reinsurance contract finance results; OCI is excluded."),
    ChartRequirement("inv_profit", "Financial results", "Investment", "Net investment result", "Adapt",
                     ("NET_INV_RESULT",),
                     "Use the reported profit-or-loss net investment / financial result; OCI is excluded."),
    ChartRequirement("oci_profit", "Financial results", "Comprehensive income", "Other comprehensive income", "Reuse", ("OCI_TOTAL",)),
    ChartRequirement("oci_deep", "Financial results", "Comprehensive income", "Asset and insurance-finance OCI comparison", "Adapt",
                     ("OCI_FVOCI_DEBT", "OCI_FVOCI_RECYCLE", "OCI_INS_FINANCE", "OCI_REINS_FINANCE"),
                     "Do not infer an asset-liability matching percentage from unlike scopes."),
    ChartRequirement("oci_year_lat", "Financial results", "Comprehensive income", "Current-year OCI movements", "Adapt",
                     ("PROFIT", "OCI_TOTAL", "COMPREHENSIVE_INCOME", "OCI_FVOCI_DEBT", "OCI_FVOCI_RECYCLE",
                      "OCI_INS_FINANCE", "OCI_REINS_FINANCE", "OCI_HEDGE", "OCI_TAX",
                      "OCI_FAIR_VALUE_RESERVE", "OCI_FX_TRANSLATION", "OCI_ECL_ADJUSTMENT")),
    ChartRequirement("oci_year_pre", "Financial results", "Comprehensive income", "Comparative OCI movements", "Reuse",
                     ("OCI_FVOCI_DEBT", "OCI_FVOCI_RECYCLE", "OCI_INS_FINANCE", "OCI_REINS_FINANCE", "OCI_HEDGE", "OCI_TAX",
                      "OCI_FAIR_VALUE_RESERVE", "OCI_FX_TRANSLATION", "OCI_ECL_ADJUSTMENT")),
    ChartRequirement("total_profit", "Financial results", "Comprehensive income", "Total comprehensive income", "Reuse", ("COMPREHENSIVE_INCOME",)),
    ChartRequirement("asset_trend", "Financial position", "Assets", "Total assets", "Reuse", ("TOTAL_ASSETS",)),
    ChartRequirement("asset_struct", "Financial position", "Assets", "Financial investments by measurement category", "Adapt",
                     ("FIN_ASSET_TOTAL", "FIN_ASSET_AC", "FIN_ASSET_AC_DEBT", "FIN_ASSET_AC_LOANS",
                      "FIN_ASSET_FVOCI_DEBT", "FIN_ASSET_FVOCI_EQUITY", "FIN_ASSET_FVTPL_DEBT",
                      "FIN_ASSET_FVTPL_EQUITY", "FIN_ASSET_FVTPL_FUNDS", "FIN_ASSET_FVTPL_INTEREST",
                      "FIN_ASSET_FVTPL_TRUST_EQUITY", "FIN_ASSET_FVTPL_PARTNERSHIPS",
                      "FIN_ASSET_FVTPL_MORTGAGES", "FIN_ASSET_FVTPL_LOANS",
                      "FIN_ASSET_FVTPL_UNLISTED_EQ_OTHER", "FIN_ASSET_FVTPL_DERIVATIVES"),
                     "Each year-end stack uses disclosed HKFRS 9 measurement categories and asset classes and reconciles to the reported investment total."),
    ChartRequirement("csm_bal", "Financial position", "CSM", "Insurance CSM closing balance", "Reuse", ("INS_NONPAA_CSM_CLOSE",)),
    ChartRequirement("csm_ratio", "Financial position", "CSM", "CSM to matching fulfilment cash flows", "Conditional",
                     ("INS_NONPAA_CSM_CLOSE", "INS_NONPAA_PVFCF_CLOSE", "INS_NONPAA_RA_CLOSE"),
                     "Only calculate from an explicitly matching method and contract population; do not label PVFCF as BEL."),
    ChartRequirement("csm_table", "Financial position", "CSM", "Insurance CSM movement", "Reuse",
                     ("CSM_OPEN", "CSM_NEW", "CSM_ESTIMATE_CHANGE", "CSM_FINANCE_CHANGE", "CSM_RELEASE", "CSM_CLOSE")),
    ChartRequirement("csm_trans", "Financial position", "CSM", "Insurance CSM by disclosed transition category", "Adapt",
                     ("INS_CSM_FV_CLOSE", "INS_CSM_MOD_CLOSE", "INS_CSM_OTHER_CLOSE", "INS_NONPAA_CSM_CLOSE"),
                     "Each percentage is the category's closing CSM divided by matching closing non-PAA insurance CSM. Other insurance contracts are not a transition method. Grey bars mean the complete split is unavailable, not zero; reinsurance held is excluded."),
    ChartRequirement("csm_comp_lat", "Financial position", "CSM", "CSM movements before release", "Adapt",
                     ("CSM_NEW", "CSM_ESTIMATE_CHANGE", "CSM_FINANCE_CHANGE")),
    ChartRequirement("csm_comp_pre", "Financial position", "CSM", "Comparative CSM movements before release", "Adapt",
                     ("CSM_NEW", "CSM_ESTIMATE_CHANGE", "CSM_FINANCE_CHANGE")),
    ChartRequirement("csm_ratio_trend", "Financial position", "CSM", "CSM amortization and replenishment trends", "Conditional",
                     ("CSM_CLOSE", "CSM_NEW", "CSM_RELEASE"),
                     "Amortization = |CSM released| / (|closing CSM| + |CSM released|). Replenishment = |new-business CSM| / |CSM released|; 100% is 1×. Each ratio uses matching insurance CSM lines from one filing and note page."),
    ChartRequirement("equity_trend", "Financial position", "Equity", "Equity movement waterfall", "Adapt",
                     ("EQUITY_OPEN", "PROFIT", "OCI_TOTAL", "EQUITY_DIVIDENDS", "EQUITY_NEW_CAPITAL", "EQUITY_OTHER", "EQUITY")),
    ChartRequirement("csm_equity", "Financial position", "Equity", "Proprietary adjusted net assets", "Exclude", (),
                     "Adding an assumed after-tax CSM to equity is not a reported HKFRS 17 amount."),
    ChartRequirement("nb_csm", "New business", "Initial recognition", "New profitable insurance contract CSM", "Reuse",
                     ("NB_INS_PROFIT_CSM",)),
    ChartRequirement("nb_lost", "New business", "Initial recognition", "Initial loss component from new onerous business", "Conditional",
                     ("NB_INS_ONEROUS_LOSS",),
                     "Do not substitute the initial net contract balance or total onerous contract amount for an explicit loss component."),
    ChartRequirement("nb_struct", "New business", "Initial recognition", "New business IFRS profit margin", "Adapt",
                     ("NB_INS_PROFIT_CSM", "NB_INS_ONEROUS_LOSS", "NB_INS_PROFIT_PV_IN", "NB_INS_ONEROUS_PV_IN"),
                     "An analytical ratio from disclosed initial-recognition items, not a reported IFRS margin."),
    ChartRequirement("nb_margin_trend", "New business", "Initial recognition", "New profitable contract CSM to PV inflows", "Conditional",
                     ("NB_INS_PROFIT_CSM", "NB_INS_PROFIT_PV_IN"),
                     "Uses matching profitable, non-PAA insurance-contract columns; it is an analytical ratio, not a reported IFRS margin."),
    ChartRequirement("discount_rate", "Key disclosures", "Assumptions", "Discount rates and illiquidity premiums by tenor", "Reuse",
                     tuple(f"DISCOUNT_{currency}_{tenor}_{basis}" for currency in ("CNY", "HKD", "USD")
                           for tenor in ("1Y", "5Y", "10Y", "15Y", "20Y") for basis in ("RF", "ILP"))
                     + tuple(f"DISCOUNT_{currency}_{tenor}_SPOT_{bound}"
                             for currency in ("CNY", "HKD", "USD")
                             for tenor in ("1Y", "5Y", "10Y", "15Y", "20Y")
                             for bound in ("LOW", "HIGH"))
                     + tuple(f"DISCOUNT_CNY_{tenor}_PREMIUM"
                             for tenor in ("1Y", "5Y", "10Y", "15Y", "20Y"))
                     + tuple(f"DISCOUNT_OTHER_PORTFOLIOS_{tenor}_{basis}"
                             for tenor in ("1Y", "5Y", "10Y", "15Y", "20Y")
                             for basis in ("RF", "PREMIUM_UP_TO"))),
    ChartRequirement("confidence_level", "Key disclosures", "Assumptions", "Risk adjustment confidence level", "Reuse",
                     ("RA_CONFIDENCE_PCT",)),
    ChartRequirement("csm_maturity_table", "Key disclosures", "CSM", "Expected insurance CSM recognition by disclosed maturity bucket", "Adapt",
                     ("CSM_MAT_INS_1Y", "CSM_MAT_INS_1_5Y", "CSM_MAT_INS_5_10Y", "CSM_MAT_INS_GT10Y"),
                     ""),
    ChartRequirement("six_dimensional_charts", "Performance indicators", "HK measures", "Financial performance ratios", "Adapt",
                     ("PROFIT", "EQUITY_OPEN", "EQUITY", "CSM_OPEN", "CSM_CLOSE", "TOTAL_ASSETS"),
                     ""),
    ChartRequirement("report_detail", "Appendix", "Insurance service", "Insurance service result detail", "Adapt",
                     ("INS_REVENUE", "INS_EXPENSE", "INS_SERVICE_RESULT", "REINS_RESULT",
                      "REV_CSM_SERVICE", "REV_RA_RELEASE", "REV_EXPECTED_CLAIMS", "REV_ACQ_RECOVERY",
                      "REV_POLICYHOLDER_TAX", "REV_NONPAA_TOTAL", "REV_PAA_TOTAL", "INS_EXP_NONPAA",
                      "INS_EXP_PAA", "INS_EXP_CLAIMS", "INS_EXP_ACQ_AMORT", "INS_EXP_ONEROUS",
                      "INS_EXP_LIC")),
    ChartRequirement("nbv_table", "Appendix", "New business", "New business information", "Adapt",
                     ("NB_INS_PROFIT_CSM", "NB_INS_PROFIT_PV_IN", "NB_INS_ONEROUS_PV_IN",
                      "NB_INS_ONEROUS_LOSS", "CSM_NEW", "CSM_RELEASE")),
)

SOURCE_TABLE_PREFERENCE = (
    "Profit or loss", "Comprehensive income", "Financial position", "Equity movement", "Cash flows",
    "Insurance revenue note", "Investment result analysis", "Financial investment classification",
    "Contract asset and liability summary", "Insurance non-PAA remaining/incurred movement",
    "Insurance non-PAA measurement reconciliation", "Insurance PAA remaining/incurred movement",
    "Insurance service expense analysis",
    "Reinsurance non-PAA remaining/incurred movement", "Reinsurance non-PAA measurement reconciliation",
    "Reinsurance PAA remaining/incurred movement", "Initially recognised insurance contracts",
    "Initially recognised reinsurance contracts", "Expected CSM recognition", "Risk adjustment confidence level",
    "Discount rates · CNY", "Discount rates · HKD", "Discount rates · USD",
    "Discount rates · Sun Life disclosed portfolio groups",
)


def source_table_for(code: str) -> str | None:
    return next((table for table in SOURCE_TABLE_PREFERENCE if code in TABLE_METRICS.get(table, ())), None)


def chart_source_rows() -> list[dict[str, str]]:
    """One auditable Step-7-to-HK mapping row per source chart module."""
    return [
        {
            "Source Step 7 ID": item.source_id,
            "HK section": item.section,
            "HK subsection": item.subsection,
            "HK chart / indicator": item.hk_title,
            "Decision": item.decision,
            "Required metrics": ", ".join(item.metrics),
            "Source tables": ", ".join(dict.fromkeys(filter(None, (source_table_for(code) for code in item.metrics)))),
            "Scope note": item.note,
        }
        for item in CHART_REQUIREMENTS
    ]


def validate_blueprint() -> None:
    ids = [item.source_id for item in CHART_REQUIREMENTS]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source Step 7 chart ID.")
    for item in CHART_REQUIREMENTS:
        for code in item.metrics:
            if code not in METRIC_BY_CODE or source_table_for(code) is None:
                raise ValueError(f"Unmapped chart metric: {item.source_id} / {code}")


validate_blueprint()
