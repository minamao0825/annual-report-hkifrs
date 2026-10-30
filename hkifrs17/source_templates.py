"""Reviewed source-table leads from the 2024-25 EY, Deloitte and KPMG filings.

These are layout examples, not page-number predictions for another insurer.
Every model lead still needs the original page and reporting scope confirmed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .extraction_plan import DISCOVERY_TARGETS

PAGE_DISCOVERY_VERSION = 13
SOURCE_TEMPLATE_VERSION = 1


# These leads belong to one checked PDF, not to every KPMG report. A changed
# filing or a different insurer must go through model discovery again.
VERIFIED_PDF_SHA256 = {
    "FWD_2025": "2b6022b49b3cbe1f1a8874918c13467bae441501790860cd4a8f90a01aed3d15",
    "SUN_2025": "1d9228e71463158cf70000e04b03d27d7fea379a93063e0bba1d19044b9fbda0",
    "YF_2025": "3caadf736b8076323916a9be5579f048754b8f2cbb6ab28d984244b9dcd0eb7a",
}
VERIFIED_COMPARATIVE_ONLY_PAGES = {
    # These pages carry the 2024 comparison in the same 2025 consolidated
    # filing. Keep them as separate physical-page leads.
    "YF_2025": frozenset({121, 123, 125, 127}),
}
VERIFIED_CONTRACT_PAGE_YEARS = {
    "YF_2025": {
        120: ("2025",), 121: ("2024",),
        122: ("2025",), 123: ("2024",),
        124: ("2025",), 125: ("2024",),
        126: ("2025",), 127: ("2024",),
    },
}
VERIFIED_CONTRACT_SUBTABLES = {
    "YF_2025": {
        97: ("Insurance revenue note",),
        119: ("Contract asset and liability summary",),
        120: ("Insurance non-PAA remaining/incurred movement",
              "Insurance PAA remaining/incurred movement", "Insurance service expense analysis"),
        121: ("Insurance non-PAA remaining/incurred movement",
              "Insurance PAA remaining/incurred movement", "Insurance service expense analysis"),
        122: ("Insurance non-PAA measurement reconciliation",
              "Insurance measurement components", "CSM / contract note"),
        123: ("Insurance non-PAA measurement reconciliation",
              "Insurance measurement components", "CSM / contract note"),
        124: ("Reinsurance net movement", "Reinsurance contract balances",
              "Reinsurance non-PAA remaining/incurred movement",
              "Reinsurance PAA remaining/incurred movement"),
        125: ("Reinsurance net movement", "Reinsurance contract balances",
              "Reinsurance non-PAA remaining/incurred movement",
              "Reinsurance PAA remaining/incurred movement"),
        126: ("Reinsurance non-PAA measurement reconciliation",
              "Reinsurance measurement components"),
        127: ("Reinsurance non-PAA measurement reconciliation",
              "Reinsurance measurement components"),
        129: ("Initially recognised insurance contracts",),
        130: ("Initially recognised reinsurance contracts", "Expected CSM recognition"),
        133: ("Risk adjustment confidence level",),
    },
}


def verified_comparative_only_pages(path: Path, filing: dict) -> frozenset[int]:
    """Return known comparative pages only for byte-identical reviewed PDFs."""
    document_id = str(filing.get("document_id", ""))
    expected = VERIFIED_PDF_SHA256.get(document_id)
    if not expected or document_id not in VERIFIED_COMPARATIVE_ONLY_PAGES:
        return frozenset()
    return (VERIFIED_COMPARATIVE_ONLY_PAGES[document_id]
            if hashlib.sha256(path.read_bytes()).hexdigest() == expected else frozenset())


def verified_contract_years_map(path: Path, filing: dict) -> dict[int, tuple[str, ...]]:
    """Read the checked table years only for a byte-identical source filing."""
    document_id = str(filing.get("document_id", ""))
    expected = VERIFIED_PDF_SHA256.get(document_id)
    if not expected or document_id not in VERIFIED_CONTRACT_PAGE_YEARS:
        return {}
    return (VERIFIED_CONTRACT_PAGE_YEARS[document_id]
            if hashlib.sha256(path.read_bytes()).hexdigest() == expected else {})


def verified_contract_subtables(path: Path, filing: dict, page: int) -> tuple[str, ...]:
    """Use reviewed page layouts only for the identical source file."""
    document_id = str(filing.get("document_id", ""))
    expected = VERIFIED_PDF_SHA256.get(document_id)
    if not expected or page not in VERIFIED_CONTRACT_SUBTABLES.get(document_id, {}):
        return ()
    return (VERIFIED_CONTRACT_SUBTABLES[document_id][page]
            if hashlib.sha256(path.read_bytes()).hexdigest() == expected else ())


VERIFIED_SOURCE_PAGES = {
    "FWD_2025": {
        "Profit or loss": ((8, "Statement of profit or loss"),),
        "Comprehensive income": ((9, "Statement of comprehensive income"),),
        "Financial position": ((10, "Statement of financial position"),
                               (11, "Statement of financial position continued")),
        "Equity movement": ((12, "Statement of changes in equity"),),
        "Cash flows": ((14, "Statement of cash flows"),
                       (15, "Statement of cash flows continued")),
        "Investment result analysis": ((52, "Note 5 investment result reconciliation"),
                                       (53, "Note 5 investment result continued")),
        "Financial investment classification": (
            (10, "Statement of financial position investment categories"),
            (103, "Financial investments by measurement category")),
        "Insurance and reinsurance contracts": tuple(
            (page, "Reviewed current-year insurance/reinsurance note and Step 6 source rows")
            for page in (51, 62, 63, 65, 67, 69, 71, 73, 75, 76, 79)
        ),
        "Discount rates and illiquidity premiums": (
            (79, "Discount rates and illiquidity premiums by tenor"),),
    },
    "SUN_2025": {
        "Profit or loss": ((13, "Statement of profit or loss"),),
        "Comprehensive income": ((14, "Statement of comprehensive income"),),
        "Financial position": ((15, "Statement of financial position"),
                               (16, "Statement of financial position continued")),
        "Equity movement": ((17, "Statement of changes in equity"),),
        "Cash flows": ((18, "Statement of cash flows"),
                       (19, "Statement of cash flows continued")),
        "Investment result analysis": (
            (83, "Note 10 investment income and finance result"),
            (85, "Note 10 investment income and finance result continued")),
        "Financial investment classification": (
            (108, "Investments in securities by measurement category"),
            (109, "Investments in securities continued")),
        "Insurance and reinsurance contracts": tuple(
            (page, "Reviewed current-year insurance/reinsurance note and Step 6 source rows")
            for page in (81, 94, 95, 96, 97, 98, 99, 100, 101, 102)
        ),
        "Discount rates and illiquidity premiums": (
            (106, "Discount rates and illiquidity premiums by tenor"),),
    },
    "YF_2025": {
        "Profit or loss": ((27, "Consolidated statement of profit or loss"),),
        "Comprehensive income": ((28, "Consolidated statement of profit or loss and OCI"),),
        "Financial position": ((29, "Consolidated statement of financial position"),
                               (30, "Consolidated statement of financial position continued")),
        "Equity movement": ((31, "Consolidated statement of changes in equity"),),
        "Cash flows": ((32, "Consolidated statement of cash flows"),
                       (33, "Consolidated statement of cash flows continued")),
        "Investment result analysis": ((98, "Note 6 Net financial result, main reconciliation"),
                                       (99, "Note 6(a)-(b) finance and interest revenue components"),
                                       (100, "Note 6(c) other investment revenue, underlying items"),
                                       (101, "Note 6(c) other investment revenue, other items and total"),
                                       (102, "Note 6(d) net impairment loss on financial assets")),
        "Financial investment classification": ((113, "Note 19 investments by measurement category"),),
        "Insurance and reinsurance contracts": (
            (97, "Note 5 insurance revenue by PAA and non-PAA"),
            (119, "Note 22 contract asset and liability summary, 2025"),
            (120, "Note 22(a)(i) insurance remaining coverage and incurred claims, 2025"),
            (121, "Note 22(a)(i) insurance remaining coverage and incurred claims, 2024 comparative"),
            (122, "Note 22(a)(i) insurance measurement components, 2025"),
            (123, "Note 22(a)(i) insurance measurement components, 2024 comparative"),
            (124, "Note 22(a)(ii) reinsurance remaining coverage and incurred claims, 2025"),
            (125, "Note 22(a)(ii) reinsurance remaining coverage and incurred claims, 2024 comparative"),
            (126, "Note 22(a)(ii) reinsurance measurement components, 2025"),
            (127, "Note 22(a)(ii) reinsurance measurement components, 2024 comparative"),
            (129, "Note 22(c) initially recognised insurance contracts, 2025"),
            (130, "Note 22(c)-(d) new reinsurance and expected CSM recognition, 2025"),
            (133, "Note 22 risk adjustment confidence level, 2025"),
        ),
        "Discount rates and illiquidity premiums": (
            (133, "Note 22 discount rates and illiquidity premiums by tenor, 2025"),
        ),
    },
}


def verified_pdf_page_leads(path: Path, filing: dict, first: int, last: int,
                            tables: list[str]) -> tuple[list[dict], set[str]]:
    """Use reviewed pages only when the file bytes match the reviewed filing."""
    document_id = str(filing.get("document_id", ""))
    expected = VERIFIED_PDF_SHA256.get(document_id)
    if not expected or document_id not in VERIFIED_SOURCE_PAGES:
        return [], set()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        return [], set()
    sources = VERIFIED_SOURCE_PAGES[document_id]
    covered = set(tables) & set(sources)
    leads = [
        {"Physical PDF page": page, "Table": table,
         "Visible evidence": evidence,
         "Financial-statement evidence": "Reviewed audited statement or note",
         "Reporting-year evidence": (str(int(filing["period_end"][:4]) - 1) + " comparative table"
                                     if page in VERIFIED_COMPARATIVE_ONLY_PAGES.get(document_id, ())
                                     else filing["period_end"][:4] + " current-year table"),
         "Table years": (str(int(filing["period_end"][:4]) - 1)
                         if page in VERIFIED_COMPARATIVE_ONLY_PAGES.get(document_id, ())
                         else filing["period_end"][:4]),
         "Scope evidence": filing["scope"] + " filing; verify on page",
         "Confidence": "Source-checked"}
        for table in tables if table in sources
        for page, evidence in sources[table] if first <= page <= last
    ]
    return leads, covered


AUDITOR_BY_DOCUMENT = {
    "FWD_2024": "EY", "FWD_2025": "EY",
    "SUN_2024": "Deloitte", "SUN_2025": "Deloitte",
    "YF_2024": "KPMG", "YF_2025": "KPMG",
}

# Physical pages were checked against the 2025 filings. A page is shown to the
# reviewer as an example; it is deliberately excluded from model prompts.
AUDITOR_TEMPLATES = {
    "EY": {
        "reference": "FWD Life Bermuda 2025 company financial statements",
        "tables": {
            "Profit or loss": ("Statement of profit or loss", "8"),
            "Comprehensive income": ("Statement of comprehensive income", "9"),
            "Financial position": ("Statement of financial position", "10-11"),
            "Equity movement": ("Statement of changes in equity", "12"),
            "Cash flows": ("Statement of cash flows", "14-15"),
            "Insurance revenue note": ("Insurance revenue analysis", "51"),
            "Insurance service expense analysis": ("Insurance service expense movement", "63"),
            "Investment result analysis": ("Investment result note", "52-53"),
            "Financial investment classification": ("Financial assets by category", "10, 81-85, 103"),
            "Contract asset and liability summary": ("Insurance and reinsurance contract balances", "62"),
            "Insurance contract balances": ("Insurance contract balances", "62-67"),
            "Insurance net movement": ("Insurance contract movement reconciliation", "63-67"),
            "Insurance measurement components": ("Insurance contract measurement components", "65"),
            "CSM / contract note": ("Insurance CSM movement", "65"),
            "Reinsurance contract balances": ("Reinsurance contract balances", "69-73"),
            "Reinsurance net movement": ("Reinsurance contract movement reconciliation", "69-73"),
            "Reinsurance measurement components": ("Reinsurance contract measurement components", "71"),
            "Insurance non-PAA remaining/incurred movement": ("Insurance contracts not measured under PAA: remaining coverage and incurred claims", "63"),
            "Insurance non-PAA measurement reconciliation": ("Insurance contracts not measured under PAA: measurement components", "65"),
            "Insurance PAA remaining/incurred movement": ("Insurance contracts measured under PAA: remaining coverage and incurred claims", "67"),
            "Reinsurance non-PAA remaining/incurred movement": ("Reinsurance held not measured under PAA: remaining coverage and incurred claims", "69"),
            "Reinsurance non-PAA measurement reconciliation": ("Reinsurance held not measured under PAA: measurement components", "71"),
            "Reinsurance PAA remaining/incurred movement": ("Reinsurance held measured under PAA: remaining coverage and incurred claims", "73"),
            "Initially recognised insurance contracts": ("Insurance contracts initially recognised in the year", "75"),
            "Initially recognised reinsurance contracts": ("Reinsurance contracts initially recognised in the year", "76"),
            "Expected CSM recognition": ("Expected recognition of CSM by maturity bucket", "76"),
            "Discount rates · CNY": ("CNY discount rates by tenor", "79"),
            "Discount rates · HKD": ("HKD discount rates by tenor", "79"),
            "Discount rates · USD": ("USD discount rates by tenor", "79"),
            "Risk adjustment confidence level": ("Risk adjustment confidence percentile", "79"),
        },
    },
    "Deloitte": {
        "reference": "Sun Life Hong Kong 2025 company financial statements",
        "tables": {
            "Profit or loss": ("Statement of profit or loss", "13"),
            "Comprehensive income": ("Statement of profit or loss and other comprehensive income", "14"),
            "Financial position": ("Statement of financial position", "15-16"),
            "Equity movement": ("Statement of changes in equity", "17"),
            "Cash flows": ("Statement of cash flows", "18-19"),
            "Insurance revenue note": ("Insurance revenue and fee income", "81"),
            "Insurance service expense analysis": ("Insurance service expenses", "81"),
            "Investment result analysis": ("Investment income and finance result notes", "83, 85"),
            "Financial investment classification": ("Investments in securities", "108-109"),
            "Insurance contract balances": ("Insurance contract balances", "94-98"),
            "Insurance net movement": ("Insurance contract movement reconciliation", "94-98"),
            "Insurance measurement components": ("Insurance contract measurement components", "95"),
            "CSM / contract note": ("Insurance CSM movement", "95"),
            "Reinsurance contract balances": ("Reinsurance contract balances", "96-99"),
            "Reinsurance net movement": ("Reinsurance contract movement reconciliation", "96-99"),
            "Reinsurance measurement components": ("Reinsurance contract measurement components", "97"),
            "Insurance non-PAA remaining/incurred movement": ("Insurance non-PAA remaining coverage and incurred claims", "94"),
            "Insurance non-PAA measurement reconciliation": ("Insurance non-PAA measurement components", "95"),
            "Insurance PAA remaining/incurred movement": ("Insurance PAA remaining coverage and incurred claims", "98"),
            "Reinsurance non-PAA remaining/incurred movement": ("Reinsurance non-PAA remaining coverage and incurred claims", "96"),
            "Reinsurance non-PAA measurement reconciliation": ("Reinsurance non-PAA measurement components", "97"),
            "Reinsurance PAA remaining/incurred movement": ("Reinsurance PAA remaining coverage and incurred claims", "99"),
            "Initially recognised insurance contracts": ("Insurance contracts initially recognised in the year", "100"),
            "Initially recognised reinsurance contracts": ("Reinsurance contracts initially recognised in the year", "101"),
            "Expected CSM recognition": ("Expected recognition of CSM", "101"),
            "Discount rates · CNY": ("RMB discount rates by portfolio and tenor", "106"),
            "Discount rates · Sun Life disclosed portfolio groups": ("Portfolio discount rates and illiquidity premiums", "106"),
        },
    },
    "KPMG": {
        "reference": "YF Life 2025 consolidated financial statements",
        "tables": {
            "Profit or loss": ("Consolidated statement of profit or loss", "27"),
            "Comprehensive income": ("Consolidated statement of profit or loss and other comprehensive income", "28"),
            "Financial position": ("Consolidated statement of financial position", "29-30"),
            "Equity movement": ("Consolidated statement of changes in equity", "31"),
            "Cash flows": ("Consolidated statement of cash flows", "32-33"),
            "Insurance revenue note": ("Insurance revenue analysis", "97"),
            "Insurance service expense analysis": ("Note 22(a)(i): Insurance service expenses within the insurance contract balance movement table", "120"),
            "Investment result analysis": ("Net financial result and investment component continuations", "98-102"),
            "Financial investment classification": ("Investments and derivatives", "113"),
            "Insurance contract balances": ("Insurance contract balances", "120-124"),
            "Insurance net movement": ("Insurance contract movement reconciliation", "120-124"),
            "Insurance measurement components": ("Insurance contract measurement components", "122"),
            "CSM / contract note": ("Insurance CSM movement", "122"),
            "Reinsurance contract balances": ("Reinsurance contract balances", "124-126"),
            "Reinsurance net movement": ("Reinsurance contract movement reconciliation", "124-126"),
            "Reinsurance measurement components": ("Reinsurance contract measurement components", "126"),
            "Insurance non-PAA remaining/incurred movement": ("Insurance non-PAA remaining coverage and incurred claims", "120-122"),
            "Insurance non-PAA measurement reconciliation": ("Insurance non-PAA measurement components", "122"),
            "Reinsurance non-PAA remaining/incurred movement": ("Reinsurance non-PAA remaining coverage and incurred claims", "126"),
            "Reinsurance non-PAA measurement reconciliation": ("Reinsurance non-PAA measurement components", "126"),
            "Reinsurance PAA remaining/incurred movement": ("Reinsurance PAA remaining coverage and incurred claims", "124"),
            "Initially recognised insurance contracts": ("Insurance contracts initially recognised in the year", "129"),
            "Initially recognised reinsurance contracts": ("Reinsurance contracts initially recognised in the year", "130"),
            "Expected CSM recognition": ("Expected recognition of CSM", "130"),
            "Discount rates · HKD": ("HKD discount rates by tenor", "133"),
            "Discount rates · USD": ("USD discount rates by tenor", "133"),
            "Risk adjustment confidence level": ("Risk adjustment confidence percentile", "133"),
        },
    },
}

# A report table may contain several rows, currencies or contract populations.
# Discovery sees one target; extraction retains all of its detailed metric codes.
DISCOVERY_REFERENCES = {
    "EY": {
        "Investment result analysis": (
            "Investment result", "52-53"),
        "Insurance and reinsurance contracts": (
            "Insurance revenue analysis; Insurance contracts; Reinsurance contracts held; "
            "Analysis by remaining coverage and incurred claims; Analysis by measurement "
            "component; Contracts initially recognised; Expected CSM recognition; "
            "Risk adjustment confidence level", "51, 62-76, 79"),
        "Discount rates and illiquidity premiums": ("Discount rates and illiquidity premiums by currency and tenor", "79"),
    },
    "Deloitte": {
        "Investment result analysis": (
            "Investment income and finance results", "83, 85"),
        "Insurance and reinsurance contracts": (
            "Insurance revenue and expenses; Insurance contracts; Reinsurance contracts "
            "held; Analysis by remaining coverage and incurred claims; Analysis by "
            "measurement component; Contracts initially recognised; Expected CSM "
            "recognition", "81, 94-101"),
        "Discount rates and illiquidity premiums": ("Discount rates and illiquidity premiums by portfolio and tenor", "106"),
    },
    "KPMG": {
        "Investment result analysis": (
            "Net financial result; interest revenue; other investment revenue; impairment components", "98-102"),
        "Insurance and reinsurance contracts": (
            "Insurance revenue analysis; Insurance and reinsurance contracts; "
            "Insurance contracts, analysis by remaining coverage and incurred claims; "
            "Insurance contracts, analysis by measurement component; Reinsurance "
            "contracts held; Contracts initially recognised; Expected CSM recognition; "
            "Risk adjustment confidence level", "97, 119-133"),
        "Discount rates and illiquidity premiums": ("Discount rates by currency and tenor", "133"),
    },
}


def verified_table_options(auditor: str | None = None) -> list[str]:
    """Show report-level source tables, not their individual metric columns."""
    selected = (AUDITOR_TEMPLATES[auditor],) if auditor in AUDITOR_TEMPLATES else AUDITOR_TEMPLATES.values()
    available = {table for profile in selected for table in profile["tables"]}
    return [target for target, members in DISCOVERY_TARGETS.items()
            if any(member in available for member in members)]


def table_examples(auditor: str, tables: list[str]) -> list[dict[str, str]]:
    profile = AUDITOR_TEMPLATES.get(auditor)
    if not profile:
        return []
    examples = []
    for table in tables:
        reference = DISCOVERY_REFERENCES.get(auditor, {}).get(table)
        if reference is None and table in profile["tables"]:
            reference = profile["tables"][table]
        if reference is not None:
            examples.append({"Target table": table,
                             "Example note / table title": _without_old_note_numbers(reference[0])})
    return examples


def _without_old_note_numbers(heading: str) -> str:
    """Retain title words while discarding a prior filing's arbitrary note index."""
    return re.sub(
        r"\bNote\s+\d+(?:\([a-z0-9]+\))*(?:\s*[-–]\s*\(?[a-z0-9]+\)?)?\s*:?\s*",
        "", heading, flags=re.I,
    ).strip(" ;,:")


def heading_cue(auditor: str | None, table: str) -> str:
    profile = AUDITOR_TEMPLATES.get(auditor or "")
    reference = DISCOVERY_REFERENCES.get(auditor or "", {}).get(table)
    heading = (reference[0] if reference is not None else
               profile["tables"][table][0] if profile and table in profile["tables"] else "")
    return _without_old_note_numbers(heading)
