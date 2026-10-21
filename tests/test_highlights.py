import pandas as pd

from hkifrs17.charts import period_bars
from hkifrs17.demo import demo_records
from hkifrs17.external import load_analysis_records
from hkifrs17.highlights import financial_highlights_source_rows, financial_highlights_table


def test_highlights_stack_only_balance_sheet_components():
    records = demo_records("FWD_2025")
    chart = period_bars(records, ["TOTAL_LIABS", "EQUITY"], stacked=True)
    encoding = chart.to_dict(validate=True)["layer"][0]["encoding"]
    assert encoding["y"]["stack"] == "zero"
    assert "xOffset" not in encoding
    assert encoding["x"]["sort"] == ["2024YE", "2025YE"]


def test_highlights_require_disclosed_inputs_and_comparable_years():
    records = demo_records("FWD_2025")
    table = financial_highlights_table(records, ["FWD Life Bermuda"], "2025-12-31")
    assert list(table)[:2] == ["Company", "Net assets growth"]
    assert pd.notna(table.loc[0, "Insurance service revenue growth"])
    assert pd.notna(table.loc[0, "CSM amortization ratio"])
    single_year = records[records["Period end"].eq("2025-12-31")]
    table = financial_highlights_table(single_year, ["FWD Life Bermuda"], "2025-12-31")
    assert pd.isna(table.loc[0, "Net profit growth"])
    assert pd.isna(table.loc[0, "Insurance service revenue growth"])


def test_highlights_use_checked_comparatives_and_skip_prior_only_insurer():
    records = load_analysis_records()
    table = financial_highlights_table(
        records,
        ["Sun Life Hong Kong", "Sun Life Hong Kong (Consolidated)", "YF Life"],
        "2025-12-31", include_source_comparatives=True,
    ).set_index("Company")
    assert "Sun Life Hong Kong (Consolidated)" not in table.index
    assert table.loc["Sun Life Hong Kong", "Net profit growth"] == 85
    assert table.loc["Sun Life Hong Kong", "New business CSM growth"] == 75
    assert table.loc["YF Life", "New business CSM growth"] == 139
    assert table.loc["YF Life", "CSM amortization ratio"] == 7
    assert table.loc["YF Life", "Net insurance contract liabilities growth"] == 19
    source = financial_highlights_source_rows(["Sun Life Hong Kong"], "2025-12-31")
    assert set(source["Audit status"]) == {"Unaudited comparative"}

