"""Keep chart regressions independent of the mutable reviewed data store.

The pinned workbook is a historical chart fixture. Runtime analysis continues to
use the current published and externally reviewed filings.
"""

from functools import lru_cache
from pathlib import Path

import pytest


CHART_SNAPSHOT_MODULES = {
    "test_appendix_tables.py", "test_csm_pre_release.py", "test_csm_ratio_mean.py",
    "test_csm_transition.py", "test_csm_waterfall.py", "test_equity_waterfall.py",
    "test_financial_investments.py", "test_investment_note.py",
    "test_new_business_ratios.py", "test_oci_analysis.py", "test_oci_waterfall.py",
    "test_report_modules.py",
}
CHART_REFERENCE = Path(__file__).parent / "fixtures" / "chart_reference_2024_2025.xlsx"


@lru_cache(maxsize=1)
def _chart_reference_records():
    from hkifrs17.external import validate_external_workbook

    records, _, _ = validate_external_workbook(CHART_REFERENCE.read_bytes())
    return records


@pytest.fixture(autouse=True)
def pinned_chart_data(request, monkeypatch):
    if Path(request.module.__file__).name not in CHART_SNAPSHOT_MODULES:
        return
    from hkifrs17 import external

    def records():
        return _chart_reference_records().copy()

    monkeypatch.setattr(external, "load_analysis_records", records)
    if hasattr(request.module, "load_analysis_records"):
        monkeypatch.setattr(request.module, "load_analysis_records", records)
