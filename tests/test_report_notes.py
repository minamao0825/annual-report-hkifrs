"""Identical company disclosures appear once in Step 6."""

from hkifrs17.report_notes import combine_company_notes


def test_identical_company_notes_are_combined_in_first_occurrence_order():
    notes = [
        "Intro",
        "FWD Life Bermuda: Same explanation.",
        "YF Life: Different explanation.",
        "Sun Life Hong Kong: Same explanation.",
        "YF Life: Same explanation.",
    ]
    assert combine_company_notes(notes, ["FWD Life Bermuda", "Sun Life Hong Kong", "YF Life"]) == [
        "Intro",
        "FWD Life Bermuda, Sun Life Hong Kong and YF Life: Same explanation.",
        "YF Life: Different explanation.",
    ]


def test_notes_for_unselected_companies_are_not_rewritten():
    assert combine_company_notes(
        ["FWD Life Bermuda: Same explanation.", "YF Life: Same explanation."],
        ["FWD Life Bermuda"],
    ) == ["FWD Life Bermuda: Same explanation.", "YF Life: Same explanation."]
