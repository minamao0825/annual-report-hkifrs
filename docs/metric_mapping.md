# HK IFRS 17 metric and source-page mapping

The live Step 1 **Chart-driven indicator and source-table map** lists the disposition of all 42 chart modules from the source annual-report platform's Step 7. Each row shows an English HK chart or indicator, the required metric codes, the preferred source-table types, and any limitation. The map is defined in `hkifrs17/metric_blueprint.py`; this document explains the decisions that matter when locating and reviewing pages.

Step 5 and Step 6 display all 40 applicable source modules in the source order and use the original four primary sections: key financial statement analysis, key disclosures, key performance indicators and appendix. Each primary module has its original secondary topic and chart-level entry in the sidebar. The two excluded modules remain visible in Step 1's mapping for audit. Twenty-six supplementary HKFRS 17 groups follow the source modules and show indicators that do not belong to an original Step 7 chart. No unavailable metric is filled with a fabricated zero.

## Chart-led extraction scope

| HK chart area | Required disclosure families | Treatment |
| --- | --- | --- |
| Financial results | Profit or loss, comprehensive income and OCI analysis, insurance revenue, service expenses, operating/management expenses, investment results | Keep profit-or-loss values separate from totals including OCI. Keep general expense-note categories separate from insurance-service expense components. Preserve signed source values. |
| Financial position | Statement assets, liabilities and equity; financial investment categories and asset-class note; contract assets and liabilities | Match the stated legal entity and consolidation scope. A net contract balance is not a gross statement asset or liability. |
| Insurance and reinsurance contracts | Non-PAA and PAA remaining/incurred coverage; non-PAA measurement components; CSM transition and movements | Keep issued insurance and reinsurance held separate; retain method and note cohort. |
| New business | Initially recognised profitable and onerous insurance contracts; reinsurance held | Show disclosed CSM, risk adjustment and cash-flow components. Display a new-business loss only when an explicit loss component is disclosed. |
| Assumptions | Currency-specific discount-rate grid, risk-adjustment confidence level, expected CSM recognition | Rates are percentages; maturity buckets follow the actual filing. |
| Analytical ratios | Matching, reviewed cells in the same filing period | Show **Missing inputs** when required cells are absent. Withhold CSM/BEL when no matching BEL denominator is disclosed. |

The following source modules are **excluded** from HK chart defaults: the mainland acquisition/maintenance/non-fulfilment expense structure and proprietary equity plus after-tax CSM. The mainland comprehensive solvency adequacy ratio is omitted from the adapted performance module. HKRBC measures belong to their own regulatory source and are not inferred from HKFRS 17 financial statements. Other source modules can be conditional where the filing lacks matching components.

## FWD 2025 physical PDF page leads

These are starting leads, not approved extractions. A reviewer must compare the full original page with the table type and confirm the physical page numbers in Step 1. The report's printed page number differs from its physical PDF page number. For this 2025 filing, Step 1 targets 2025 columns and movement tables only; 2024-only pages are deliberately omitted.

| Physical PDF page | Table or disclosure | Extraction boundary |
| --- | --- | --- |
| 8 | Statement of profit or loss | Reported profit-or-loss amounts. |
| 9 | Statement of comprehensive income | OCI components and total comprehensive income. |
| 10–11 | Statement of financial position | Two-page statement with gross contract assets/liabilities, total assets/liabilities/equity and stated financial-investment categories. |
| 12 | Statement of changes in equity | 2025 equity movement fields. Page 13 contains the 2024-only statement and is excluded. |
| 14–15 | Statement of cash flows | 2025 operating, investing and financing cash flows, cash movement and closing balance. |
| 51 | Note 4 insurance revenue | Revenue split and disclosed components. |
| 52–53 | Note 5 investment result | Select 2025 totals including OCI; ignore the 2024 comparative column. |
| 54 | Note 6 expenses | Claims/benefits, acquisition/commission, staff, depreciation, amortisation, marketing, professional, IT, investment-management and other disclosed expenses. Use the note's stated recognised total, not an unrelated gross subtotal. |
| 62 | Note 13 contract asset/liability summary | Net note balances; avoid replacing gross statement balances. |
| 63 | Insurance contracts **not** measured under PAA: remaining/incurred coverage | 2025 method-specific movement rows. Page 64 is 2024-only. |
| 65 | Insurance contracts **not** measured under PAA: measurement components | 2025 present value, risk adjustment, CSM subtotal, transition columns and CSM movements. Page 66 is 2024-only. |
| 67 | Insurance contracts measured under PAA: remaining/incurred coverage | 2025 PAA movement rows. Page 68 is 2024-only. |
| 69 | Reinsurance contracts held **not** measured under PAA: remaining/incurred coverage | 2025 reinsurance movement rows. Page 70 is 2024-only. |
| 71 | Reinsurance contracts held **not** measured under PAA: measurement components | 2025 reinsurance present value, risk adjustment, CSM and transition columns. Page 72 is 2024-only. |
| 73 | Reinsurance contracts held measured under PAA: remaining/incurred coverage | 2025 PAA reinsurance movement rows. Page 74 is 2024-only. |
| 75 | Initially recognised insurance contracts | Profitable and onerous columns. An initial amount included in contract assets/liabilities is **not** automatically a new-business loss. |
| 76 | Initially recognised reinsurance contracts and expected CSM recognition | Distinct reinsurance and maturity tables on the same page; FWD uses within 1 year, 1–5 years, 5–10 years and over 10 years. |
| 77–78 | Narrative/methodology | No pre-checked numeric-table lead. A reviewer can add a page if a required table is actually present. |
| 79 | Discount-rate grids and risk-adjustment confidence | CNY, HKD and USD; 1-, 5-, 10-, 15- and 20-year risk-free and illiquidity-adjusted rates, plus the stated confidence percentile. |
| 81–82, 84–85 | Note 14 financial assets | 2025 debt securities, equity securities and investment funds, including disclosed asset-class totals. Page 83 is 2024-only. |

YF Life's 2025 consolidated primary statements are on physical pages 27–33: profit or loss (27), OCI (28), financial position (29–30), equity movement (31) and cash flows (32–33). Page 31 is rendered upright for review and extraction. Sun Life Hong Kong's 2025 company statements are on pages 13–19: profit or loss (13), OCI (14), financial position (15–16), equity movement (17) and cash flows (18–19). Both PDFs are image-only, so their note pages must be located by the configured vision model and confirmed against the full original page.

FWD reports 2025 net investment result of **US$17,861 thousand** in profit or loss on physical page 8. Its note on page 52 reports **US$113,534 thousand** including OCI. These are different metric codes (`NET_INV_RESULT` and `NET_INV_RESULT_TOTAL`) and must not be substituted for each other. The same distinction applies to investment return and insurance/reinsurance finance result.

The insurer explorer and peer pages use only values that have reached the appropriate review and publication state, unless the user explicitly enables the labelled unpublished pilot preview. Source-page evidence, company/group scope, currency, unit, measurement method and note population remain part of the review record.
