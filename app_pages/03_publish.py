"""Review gate and versioned integration."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from hkifrs17.data import reconciliation_checks, verified_records
from hkifrs17.storage import all_filings, approved_ids, filing_by_id, load_approved, load_published, plans_for_records, publish_selected


st.title("Validate and publish")
st.caption("Step 3 · Preview approved workbooks, then update matching cells in the published store. Other filings remain available.")
ids = approved_ids()
if ids:
    chosen = st.multiselect("Approved workbooks", ids, default=ids,
                            format_func=lambda value: filing_by_id(value)["company"] + " · " + value)
    if chosen:
        incoming = pd.concat([verified_records(load_approved(i), all_filings()) for i in chosen], ignore_index=True)
        st.metric("Verified cells ready to publish", len(incoming), border=True)
        st.dataframe(incoming[["Company", "Period end", "Metric", "Original value", "Source unit", "PDF page", "Review status"]],
                     hide_index=True)
        checks = reconciliation_checks(incoming, all_filings(), plans_for_records(incoming, "approved"))
        if not checks.empty:
            st.subheader("Final checks")
            st.caption("Publication requires every check to be Pass or documented Not applicable.")
            st.dataframe(checks, hide_index=True)
        if st.button("Publish selected workbooks", type="primary", icon=":material/publish:"):
            try:
                count = publish_selected(chosen)
                st.success(f"Published {count} reviewed cells. Build the shared dataset in Step 4.")
            except Exception as exc:
                st.error(str(exc))
else:
    st.info("No approved workbooks yet. Review a draft and approve verified cells in Step 2.")

published = load_published()
st.subheader("Published coverage")
if published.empty:
    st.caption("No values have been published. The analysis pages offer an explicitly labelled demo preview.")
else:
    coverage = (published.groupby(["Company", "Period end", "Currency", "Scope"])
                .size().reset_index(name="Verified cells"))
    st.dataframe(coverage, hide_index=True)
