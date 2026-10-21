"""Editable review workbench with Excel round trip and validation."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from hkifrs17.catalog import METRICS
from hkifrs17.checks import ASSESSMENTS, FORMULA_BASES, METHODS, NOTE_SCOPES, normalize_plan
from hkifrs17.data import COLUMNS, UNIT_FACTORS, normalize_records, reconciliation_checks
from hkifrs17.review import read_check_plan_workbook, read_review_workbook, review_workbook_bytes
from hkifrs17.storage import all_filings, approve_draft, filing_by_id, load_check_plan, load_draft, save_check_plan, save_draft


st.title("Review source data")
st.caption("Step 2 · Review source cells, assess note applicability, resolve reconciliation checks, then approve.")
filings = all_filings()
document_id = st.selectbox("Filing", [item["document_id"] for item in filings],
                           format_func=lambda value: filing_by_id(value)["company"] + " · " + filing_by_id(value)["period_end"])
filing = filing_by_id(document_id)
draft = load_draft(document_id)
if draft.empty:
    st.info("This filing has no draft. Use Step 1 to extract a page or load its pilot transcription.")
    st.stop()

with st.container(horizontal=True):
    st.metric("Draft cells", len(draft), border=True)
    st.metric("Verified", int(draft["Review status"].eq("Verified").sum()), border=True)
    st.metric("Pending", int(draft["Review status"].eq("Pending").sum()), border=True)

st.subheader("Records")
st.caption("Click a value to edit it. The normalised value is recalculated from the reviewed original and unit when saved.")
locked = ["Document ID", "Company ID", "Company", "Legal entity", "Scope", "Metric", "Section", "Currency", "Value (millions)"]
review_columns = [
    "Metric", "Metric code", "Period end", "Original value", "Source unit", "Value (millions)",
    "PDF page", "Source label", "Audit status", "Review status", "Reviewer note",
] + [column for column in COLUMNS if column not in {
    "Metric", "Metric code", "Period end", "Original value", "Source unit", "Value (millions)",
    "PDF page", "Source label", "Audit status", "Review status", "Reviewer note",
}]
edited = st.data_editor(
    draft[review_columns],
    hide_index=True,
    num_rows="fixed",
    disabled=locked,
    column_config={
        "Metric code": st.column_config.SelectboxColumn("Metric code", options=[metric.code for metric in METRICS], required=True),
        "Source unit": st.column_config.SelectboxColumn("Source unit", options=list(UNIT_FACTORS), required=True),
        "Value status": st.column_config.SelectboxColumn("Value status", options=["Reported", "Not disclosed", "Not applicable"], required=True),
        "Review status": st.column_config.SelectboxColumn("Review status", options=["Pending", "Verified", "Excluded"], required=True),
        "Original value": st.column_config.NumberColumn("Original value", format="%.2f"),
        "PDF page": st.column_config.NumberColumn("PDF page", min_value=1, step=1),
    },
    key=f"review_editor_{document_id}",
)
try:
    checked = normalize_records(edited, filings)
    st.subheader("Check plan · applicability and note scope")
    st.caption("For each period, confirm whether a note check applies. 'Not applicable' needs a reason. Confirm the company/group, gross or net balance basis, currency and sign presentation. Set Formula basis for the service bridge when expenses are displayed positive. Rollforward movements must be disclosed in the same note; never derive them from opening and closing.")
    plan = load_check_plan(document_id)
    plan_view = plan.drop(columns=["Document ID"])
    edited_plan = st.data_editor(
        plan_view, hide_index=True, num_rows="fixed",
        disabled=["Period end", "Check ID"], key=f"check_plan_{document_id}",
        column_config={
            "Assessment": st.column_config.SelectboxColumn(options=list(ASSESSMENTS), required=True),
            "Measurement method": st.column_config.SelectboxColumn(options=list(METHODS), required=True),
            "Note scope": st.column_config.SelectboxColumn(options=list(NOTE_SCOPES), required=True),
            "Formula basis": st.column_config.SelectboxColumn(options=list(FORMULA_BASES), required=True),
        },
    )
    edited_plan.insert(0, "Document ID", document_id)
    checked_plan = normalize_plan(edited_plan, filings, {document_id})
    checks = reconciliation_checks(checked, filings, checked_plan, verified_only=True)
    st.subheader("Reconciliation checklist")
    st.caption("Pass = reconciled; Difference = values disagree; Missing inputs = a required field or applicability confirmation is missing; Not applicable = documented exclusion. Only Verified reported cells count toward approval.")
    status_counts = checks["Result"].value_counts()
    with st.container(horizontal=True):
        for status in ("Pass", "Difference", "Missing inputs", "Not applicable"):
            st.metric(status, int(status_counts.get(status, 0)), border=True)
    st.dataframe(checks, hide_index=True, width="stretch")
    with st.container(horizontal=True):
        if st.button("Save draft", icon=":material/save:"):
            save_draft(document_id, checked)
            save_check_plan(document_id, checked_plan)
            st.success("Source cells and check plan saved.")
        st.download_button("Download review workbook", data=review_workbook_bytes(checked, filings, checked_plan),
                           file_name=f"{document_id}_review.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           icon=":material/download:")
        if st.button("Approve verified cells", type="primary", icon=":material/check_circle:"):
            save_draft(document_id, checked)
            save_check_plan(document_id, checked_plan)
            count = approve_draft(document_id)
            st.success(f"Approved {count} verified cells. Publish them in Step 3, then integrate in Step 4.")
except Exception as exc:
    st.error(f"Review data needs correction: {exc}")

with st.expander("Import a reviewed workbook", icon=":material/upload_file:"):
    st.caption("Older workbooks without a Check plan can be imported; their optional checks will need assessment before approval.")
    uploaded = st.file_uploader("Reviewed Excel workbook", type="xlsx", key=f"review_upload_{document_id}")
    if st.button("Import workbook", disabled=uploaded is None):
        try:
            imported = read_review_workbook(uploaded.getvalue(), filings)
            if not imported["Document ID"].eq(document_id).all():
                raise ValueError("The workbook contains another filing. Select its filing first.")
            imported_plan = read_check_plan_workbook(uploaded.getvalue(), filings, document_id)
            save_draft(document_id, imported)
            save_check_plan(document_id, imported_plan)
            st.success(f"Imported {len(imported)} rows.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with st.expander("Add a missing source cell", icon=":material/add:"):
    with st.form(f"add_record_{document_id}"):
        metric_code = st.selectbox("Metric", [metric.code for metric in METRICS],
                                   format_func=lambda code: next(metric.label for metric in METRICS if metric.code == code))
        report_year = int(filing["period_end"][:4])
        period = st.selectbox("Period end", [filing["period_end"], f"{report_year - 1}{filing['period_end'][4:]}"])
        source_unit = st.selectbox("Source unit", [unit for unit, (currency, _) in UNIT_FACTORS.items() if currency == filing["currency"]])
        amount = st.number_input("Original value", value=0.0, format="%.6f")
        page = st.number_input("Physical PDF page", min_value=1, step=1, value=1)
        source_label = st.text_input("Exact source row label")
        add = st.form_submit_button("Add pending cell")
    if add:
        try:
            if not source_label.strip():
                raise ValueError("Enter the source row label.")
            row = dict.fromkeys(COLUMNS, "")
            row.update({"Document ID": document_id, "Period end": period, "Metric code": metric_code,
                        "Original value": amount, "Source unit": source_unit, "Value status": "Reported",
                        "PDF page": page, "Source label": source_label, "Audit status": "Check source",
                        "Review status": "Pending", "Reviewer note": "Manually entered; verify against source."})
            combined = pd.concat([draft, pd.DataFrame([row])], ignore_index=True)
            save_draft(document_id, combined)
            st.success("Pending cell added.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
