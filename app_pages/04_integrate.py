"""Reviewed cross-insurer integration step."""

from __future__ import annotations

from io import BytesIO
import pandas as pd
import streamlit as st

from hkifrs17.data import reconciliation_checks
from hkifrs17.storage import all_filings, integrate_published, integration_status, load_integrated, load_published, plans_for_records


st.title("Integrate insurer data")
st.caption("Step 4 · Combine all published and reviewed insurer filings into one versioned analysis dataset.")
published = load_published()
if published.empty:
    st.info("No reviewed filings have been published. Complete Step 3 first.")
    st.stop()

coverage = (published.groupby(["Company", "Legal entity", "Scope", "Period end", "Currency"], dropna=False)
            .size().reset_index(name="Verified cells"))
st.subheader("Source coverage")
st.dataframe(coverage, hide_index=True)
st.caption("Integration preserves disclosed currencies and source amounts, and adds a separate HKD comparison amount using the matching calendar year's 31 December USD/HKD rate.")

checks = reconciliation_checks(published, all_filings(), plans_for_records(published, "published"))
with st.expander("Cross-filing validation", expanded=False):
    st.dataframe(checks, hide_index=True)
    st.caption("Checks stay within each filing, scope, currency and period. Missing inputs and differences stop integration.")

status = integration_status()
if status["current"]:
    st.success(f"Current integrated snapshot · {status['insurers']} insurers · {status['cells']} cells · {status['integrated_at_utc']} UTC")
else:
    st.warning("No current integrated snapshot. The insurer and peer pages can show labelled pilot previews until you integrate.")

if st.button("Build integrated dataset", type="primary", icon=":material/merge_type:"):
    try:
        count = integrate_published()
        st.session_state["analysis_data_active"] = True
        st.success(f"Integrated {count} reviewed source cells. Steps 5 and 6 can now use this dataset.")
        st.rerun()
    except Exception as exc:
        st.error(str(exc))

integrated = load_integrated()
if not integrated.empty:
    st.subheader("Integrated dataset")
    st.dataframe(integrated[["Company", "Scope", "Period end", "Metric", "Original value", "Source unit",
                             "Value (millions)", "HKD value (millions)", "USD/HKD rate", "FX rate date",
                             "PDF page", "Review status"]], hide_index=True,
                 column_config={"Value (millions)": st.column_config.NumberColumn(format="%.2f"),
                                "HKD value (millions)": st.column_config.NumberColumn(format="%.2f")})
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        integrated.to_excel(writer, sheet_name="Integrated records", index=False)
        coverage.to_excel(writer, sheet_name="Coverage", index=False)
        checks.to_excel(writer, sheet_name="Checks", index=False)
    st.download_button("Download integrated Excel", output.getvalue(),
                       file_name="HK_IFRS17_integrated_reviewed.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/download:")
