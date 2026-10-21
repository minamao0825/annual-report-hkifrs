"""Empty analysis pages require explicit data or demo selection."""

from pathlib import Path
from unittest.mock import patch

import pytest
import pandas as pd
from streamlit.testing.v1 import AppTest

from hkifrs17.data import empty_records
from hkifrs17.demo import demo_records
from hkifrs17.report_modules import REPORT_MODULES


@pytest.mark.parametrize("page", ["05_insurer.py", "06_peers.py"])
def test_empty_analysis_starts_without_charts_and_demo_requires_opt_in(page):
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    with patch("hkifrs17.external.load_analysis_records", return_value=empty_records()):
        app = AppTest.from_file(str(path), default_timeout=30).run()
        assert not app.exception
        preview = next(item for item in app.toggle
                       if item.label == "Preview unpublished pilot transcriptions")
        assert preview.value is False
        assert not app.get("vega_lite_chart")
        assert any("No dataset is active" in item.value for item in app.info)

        preview.set_value(True).run()
        assert not app.exception
        assert app.get("vega_lite_chart")


@pytest.mark.parametrize("page", ["05_insurer.py", "06_peers.py"])
def test_saved_analysis_requires_explicit_activation_in_each_new_session(page):
    path = Path(__file__).resolve().parents[1] / "app_pages" / page
    with patch("hkifrs17.external.load_analysis_records",
               return_value=demo_records("FWD_2025")):
        app = AppTest.from_file(str(path), default_timeout=30).run()
        assert not app.exception
        assert not app.get("vega_lite_chart")
        assert any("saved verified source cells are available" in item.value
                   for item in app.caption)

        next(item for item in app.button
             if item.label == "Use saved verified data").click().run()
        assert not app.exception
        assert app.get("vega_lite_chart")
        key = "insurer" if page == "05_insurer.py" else "peers"
        secondary = app.radio(key=f"{key}_secondary")
        assert secondary.value == "Profitability"
        initial_charts = len(app.get("vega_lite_chart"))
        secondary.set_value("__all_in_selection__").run()
        assert not app.exception
        assert len(app.get("vega_lite_chart")) > initial_charts

        reopened = AppTest.from_file(str(path), default_timeout=30).run()
        assert not reopened.exception
        assert not reopened.get("vega_lite_chart")


def test_import_resets_previous_all_charts_selection():
    path = Path(__file__).resolve().parents[1] / "app_pages" / "05_insurer.py"
    records = demo_records("FWD_2025")
    checks = pd.DataFrame(columns=[
        "Company", "Period end", "Check", "Result", "Missing inputs", "Detail",
    ])
    with (patch("hkifrs17.external.load_analysis_records", return_value=records),
          patch("hkifrs17.external.save_external_workbook", return_value=(len(records), checks))):
        app = AppTest.from_file(str(path), default_timeout=30).run()
        app.file_uploader[0].set_value(("reviewed.xlsx", b"PKdummy", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
        app.session_state["insurer_primary"] = "All charts"
        next(item for item in app.button if item.label == "Import verified data").click().run()
    assert not app.exception
    assert app.radio(key="insurer_primary").value == REPORT_MODULES[0].section
    assert app.radio(key="insurer_secondary").value == "Profitability"
    assert len(app.get("vega_lite_chart")) < 10
    assert app.success


def test_step5_import_is_visible_in_step6_without_reactivation():
    main = Path(__file__).resolve().parents[1] / "ifrs17_app.py"
    records = demo_records("FWD_2025")
    checks = pd.DataFrame(columns=[
        "Company", "Period end", "Check", "Result", "Missing inputs", "Detail",
    ])
    with (patch("hkifrs17.external.load_analysis_records", return_value=records),
          patch("hkifrs17.external.save_external_workbook", return_value=(len(records), checks))):
        app = AppTest.from_file(str(main), default_timeout=60).run()
        app.switch_page("app_pages/05_insurer.py").run()
        assert not app.get("vega_lite_chart")

        app.file_uploader[0].set_value((
            "reviewed.xlsx", b"PKdummy",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )).run()
        next(item for item in app.button
             if item.label == "Import verified data").click().run()
        assert app.session_state["analysis_data_active"] is True

        app.switch_page("app_pages/06_peers.py").run()
        assert not app.exception
        assert any("Loaded" in item.value and "verified source cells" in item.value
                   for item in app.caption)
        assert app.get("vega_lite_chart")
        assert not any(item.label == "Use saved verified data" for item in app.button)
