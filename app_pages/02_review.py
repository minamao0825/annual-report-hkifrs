"""Extract confirmed source tables and review their cells in the app or Excel."""

from __future__ import annotations

import hashlib
import importlib
import json
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from hkifrs17 import data as _data_module
if getattr(_data_module, "DATA_WORKFLOW_VERSION", 0) < 2:
    importlib.reload(_data_module)
from hkifrs17 import source_templates as _source_templates_module
if getattr(_source_templates_module, "SOURCE_TEMPLATE_VERSION", 0) < 1:
    importlib.reload(_source_templates_module)
from hkifrs17 import extraction_plan as _extraction_plan_module
if getattr(_extraction_plan_module, "EXTRACTION_PLAN_VERSION", 0) < 1:
    importlib.reload(_extraction_plan_module)
from hkifrs17 import review_flow as _review_flow_module
if getattr(_review_flow_module, "SOURCE_REVIEW_VERSION", 0) < 4:
    importlib.reload(_review_flow_module)
from hkifrs17 import pdf as _pdf_module
if getattr(_pdf_module, "PDF_EXTRACTION_VERSION", 0) < 9:
    importlib.reload(_pdf_module)
from hkifrs17 import storage as _storage_module
if getattr(_storage_module, "REVIEW_WORKFLOW_VERSION", 0) < 4:
    importlib.reload(_storage_module)
from hkifrs17 import review as _review_module
if getattr(_review_module, "REVIEW_WORKFLOW_VERSION", 0) < 11:
    importlib.reload(_review_module)

from hkifrs17.catalog import METRICS
from hkifrs17.data import COLUMNS, UNIT_FACTORS, normalize_records
from hkifrs17.demo import demo_records
from hkifrs17.extraction_plan import RECORD_KEYS, TABLE_METRICS, extract_confirmed_batch, merge_extracted
from hkifrs17.pdf import extract_model_page, page_count, page_png
from hkifrs17.review import read_review_workbook, source_review_workbook_bytes
from hkifrs17.review_flow import confirm_source_rows, source_table_labels
from hkifrs17.storage import (all_filings, filing_by_id, load_confirmed_pages,
                              load_draft, pdf_path, save_draft, stage_draft_for_checks)
from hkifrs17.vision_settings import shared_vision_settings


st.title("Extract and review tables")
st.caption("Step 2 · Extract confirmed pages and send candidate cells directly to Step 3. Source editing here is optional.")
filings = all_filings()
ids = [item["document_id"] for item in filings]
preferred = st.session_state.get("review_filing_id", ids[0])
document_id = st.selectbox("Filing", ids, index=ids.index(preferred) if preferred in ids else 0,
                           format_func=lambda value: filing_by_id(value)["company"] + " · "
                           + filing_by_id(value)["period_end"])
st.session_state["review_filing_id"] = document_id
filing = filing_by_id(document_id)
if document_id == "YF_2025":
    filing = {**filing, "page_rotation_hints": {**filing.get("page_rotation_hints", {}), 113: 90}}
path = pdf_path(filing)
tasks = load_confirmed_pages(document_id, path)
if not tasks and path.exists():
    # Existing browser sessions may have confirmed pages before disk persistence was added.
    current_stamp = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
    discovery = st.session_state.get(f"discovery_result_v11_{document_id}", {})
    if discovery.get("stamp") == current_stamp:
        tasks = [tuple(pair) for pair in st.session_state.get(f"confirmed_discovery_v11_{document_id}", [])]
tasks = sorted(set(tasks), key=lambda pair: (pair[0], pair[1]))

st.subheader("Confirmed table pages")
if tasks:
    st.dataframe(pd.DataFrame(tasks, columns=["Physical PDF page", "Table"]),
                 hide_index=True, width="stretch")
else:
    st.info("Confirm physical table pages in Step 1 to start a model extraction. Existing drafts can still be reviewed below.")

vision = shared_vision_settings(st.session_state)
base_url = str(vision["base_url"])
model = str(vision["model"])
api_key = str(vision["api_key"])
is_kimi = model.strip().lower() == "kimi-k2.6" and base_url.strip().lower().startswith(
    ("https://api.moonshot.cn/", "https://api.moonshot.ai/"))
fast_kimi = is_kimi and bool(vision["fast_kimi"])
read_timeout = int(vision["timeout"])
st.caption(f"Vision model from Step 1: {model or 'not configured'} · "
           f"{urlparse(base_url).hostname or 'model service'} · "
           f"timeout {read_timeout}s · API key {'available' if api_key.strip() else 'missing'}")
if not all((base_url.strip(), model.strip(), api_key.strip())):
    st.info("Configure the model service once in the Step 1 model settings, then return here to extract confirmed pages.")

stamp = (str(path), path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else ()
signature = hashlib.sha256(json.dumps([document_id, stamp, tasks]).encode("utf-8")).hexdigest()[:12]
consent = st.checkbox(f"Send all {len(tasks)} confirmed table-page image(s) to this model service",
                      key=f"extraction_consent_{document_id}_{signature}", disabled=not tasks)
st.caption("Each physical page is processed separately. A successful retry replaces that table-page's Pending set; Verified cells and failed pages are preserved.")
selected_for_run = st.multiselect(
    "Extract only selected table pages (for a later retry)", tasks,
    format_func=lambda pair: f"PDF p.{pair[0]} · {pair[1]}",
    key=f"selected_table_pages_{document_id}_{signature}",
)
previous = st.session_state.get(f"batch_results_{document_id}", {})
failed_tasks = []
if isinstance(previous, dict) and previous.get("signature") == signature:
    failed_tasks = [(int(row["Physical PDF page"]), str(row["Table"]))
                    for _, row in previous["rows"].iterrows() if row["Status"] != "Saved as Pending"]
with st.container(horizontal=True):
    run_all = st.button("Extract all confirmed tables", type="primary", icon=":material/batch_prediction:",
                        disabled=not tasks or not consent or not all((base_url.strip(), model.strip(), api_key.strip())))
    retry_failed = st.button(f"Retry {len(failed_tasks)} failed table page(s)", icon=":material/replay:",
                             disabled=not failed_tasks or not consent or not all((base_url.strip(), model.strip(), api_key.strip())))
    run_selected = st.button("Extract selected pages", icon=":material/play_arrow:",
                             disabled=not selected_for_run or not consent or not all((base_url.strip(), model.strip(), api_key.strip())))
if run_all or retry_failed or run_selected:
    selected_tasks = tasks if run_all else failed_tasks if retry_failed else selected_for_run
    if not path.exists():
        st.error("The source PDF is missing.")
    elif not all((base_url.strip(), model.strip(), api_key.strip())):
        st.error("Enter the model service URL, model and API key before extraction.")
    else:
        progress_bar = st.progress(0, text=f"Extracting 0/{len(selected_tasks)} table pages...")

        def update_progress(done: int, total: int, physical_page: int, table: str) -> None:
            progress_bar.progress(done / total,
                                  text=f"Processed {done}/{total} · PDF p.{physical_page} · {table}")

        def extract_one(physical_page: int, table: str) -> pd.DataFrame:
            return extract_model_page(path, filing, physical_page, filings,
                                      base_url=base_url, model=model, api_key=api_key,
                                      fast_kimi=fast_kimi, read_timeout=int(read_timeout),
                                      metric_codes=set(TABLE_METRICS[table]), table_names=[table])

        results = extract_confirmed_batch(selected_tasks, extractor=extract_one,
                                          load_current=lambda: load_draft(document_id),
                                          save_current=lambda frame: save_draft(document_id, frame),
                                          progress=update_progress, max_workers=2)
        st.session_state[f"batch_results_{document_id}"] = {"signature": signature, "rows": results}
        st.session_state[f"review_revision_{document_id}"] = st.session_state.get(
            f"review_revision_{document_id}", 0) + 1
        progress_bar.progress(1.0, text=f"Completed {len(results)} table-page tasks")
        previous = st.session_state[f"batch_results_{document_id}"]

if isinstance(previous, dict) and previous.get("signature") == signature:
    results = previous["rows"]
    failures = results[results["Status"] != "Saved as Pending"]
    if failures.empty:
        st.success(f"Completed {len(results)} table-page tasks. Review the extracted cells below.")
    else:
        st.warning(f"{len(results) - len(failures)} succeeded; {len(failures)} failed. Successful cells remain in the draft.")
        st.dataframe(failures[["Table", "Physical PDF page", "Detail"]], hide_index=True, width="stretch")
    with st.expander("Full extraction results"):
        st.dataframe(results, hide_index=True, width="stretch")

if document_id in {"YF_2025", "FWD_2025", "CTF_2025", "SUN_2025"}:
    with st.expander("Pilot transcription aids", icon=":material/table_chart:"):
        if st.button("Load pilot draft", icon=":material/table_chart:"):
            if load_draft(document_id).empty:
                leads = demo_records(document_id)
                save_draft(document_id, leads[leads["Period end"].eq(filing["period_end"])])
                st.rerun()
            else:
                st.warning("A draft already exists and was preserved.")
        if document_id == "FWD_2025" and st.button("Add FWD note 4/13 transcription leads"):
            leads = demo_records(document_id)
            leads = leads[leads["Period end"].eq(filing["period_end"])
                          & leads["PDF page"].astype(int).ge(51)].copy()
            current = load_draft(document_id)
            present = set(map(tuple, current[RECORD_KEYS].itertuples(index=False, name=None)))
            leads = leads[[key not in present for key in leads[RECORD_KEYS].itertuples(index=False, name=None)]]
            combined, counts = merge_extracted(current, leads)
            if counts["added"]:
                save_draft(document_id, combined)
            st.success(f"Added {counts['added']} Pending note cells; existing records were preserved.")

draft = load_draft(document_id)
if draft.empty:
    st.info("No extracted cells are available yet.")
    st.stop()
revision = st.session_state.get(f"review_revision_{document_id}", 0)
buffer_key = f"review_buffer_{document_id}_{revision}"
if buffer_key not in st.session_state:
    st.session_state[buffer_key] = draft.copy().reset_index(drop=True)
buffer = st.session_state[buffer_key]
with st.container(horizontal=True):
    st.metric("Draft cells", len(buffer), border=True)
    st.metric("Verified", int(buffer["Review status"].eq("Verified").sum()), border=True)
    st.metric("Pending", int(buffer["Review status"].eq("Pending").sum()), border=True)
st.caption("Draft cells count populated year-and-metric records, not a fixed PDF grid. Newly discovered metrics add records; repeat extraction replaces prior Pending records for the same table page.")

st.subheader("Review by source table")
st.caption("Select a table to inspect its cells and original PDF page. Edits remain available while you switch tables; confirm all Pending cells together when review is complete.")
labels = source_table_labels(buffer, tasks)
table_names = list(dict.fromkeys(labels))
overview = pd.DataFrame([
    {"Source table": table, "Cells": labels.count(table),
     "Pending": sum(labels[i] == table and buffer.iloc[i]["Review status"] == "Pending"
                    for i in range(len(labels))),
     "Verified": sum(labels[i] == table and buffer.iloc[i]["Review status"] == "Verified"
                     for i in range(len(labels))),
     "PDF pages": ", ".join(map(str, sorted(buffer.iloc[[i for i, label in enumerate(labels) if label == table]]
                                            ["PDF page"].dropna().astype(int).unique())))}
    for table in table_names
])
st.dataframe(overview, hide_index=True, width="stretch")
selected_table = st.selectbox(
    "Table to review", table_names, key=f"source_table_selector_{document_id}",
    format_func=lambda table: f"{table} · {overview.loc[overview['Source table'].eq(table), 'Pending'].iloc[0]} Pending",
)
positions = [position for position, label in enumerate(labels) if label == selected_table]
group = buffer.iloc[positions]
review_columns = ["Metric", "Metric code", "Period end", "Original value", "Source unit",
                  "Value (millions)", "PDF page", "Source label", "Audit status",
                  "Review status", "Reviewer note"] + [column for column in COLUMNS if column not in {
                      "Metric", "Metric code", "Period end", "Original value", "Source unit",
                      "Value (millions)", "PDF page", "Source label", "Audit status",
                      "Review status", "Reviewer note"}]
locked = ["Document ID", "Company ID", "Company", "Legal entity", "Scope", "Metric", "Section",
          "Currency", "Value (millions)"]
editor_key = f"source_review_{document_id}_{revision}_{selected_table}"


def retain_editor_changes() -> None:
    changes = st.session_state.get(editor_key, {}).get("edited_rows", {})
    for row_number, fields in changes.items():
        for column, value in fields.items():
            if column in COLUMNS:
                buffer.at[positions[int(row_number)], column] = value
    st.session_state[buffer_key] = buffer


edited = st.data_editor(group[review_columns].reset_index(drop=True),
                        hide_index=True, num_rows="fixed", disabled=locked,
                        key=editor_key, on_change=retain_editor_changes,
                        column_config={
                            "Metric code": st.column_config.SelectboxColumn(options=[m.code for m in METRICS], required=True),
                            "Source unit": st.column_config.SelectboxColumn(options=list(UNIT_FACTORS), required=True),
                            "Review status": st.column_config.SelectboxColumn(options=["Pending", "Verified", "Excluded"], required=True),
                            "Value status": st.column_config.SelectboxColumn(options=["Reported", "Derived from disclosed items", "Not disclosed", "Not applicable"], required=True),
                            "Original value": st.column_config.NumberColumn(format="%.6f"),
                            "PDF page": st.column_config.NumberColumn(min_value=1, step=1),
                        }, width="stretch")
buffer.loc[positions, COLUMNS] = edited[COLUMNS].to_numpy()
st.session_state[buffer_key] = buffer
source_pages = sorted(group["PDF page"].dropna().astype(int).unique().tolist())
if source_pages:
    preview = st.expander("Original PDF page", expanded=False,
                          key=f"source_preview_{document_id}_{selected_table}",
                          icon=":material/picture_as_pdf:", on_change="rerun")
    with preview:
        if preview.open:
            visible_page = st.selectbox("Physical PDF page to inspect", source_pages,
                                        key=f"source_preview_page_{document_id}_{selected_table}")
            try:
                st.image(page_png(path, visible_page,
                                  rotate=int(filing.get("page_rotation_hints", {}).get(visible_page, 0))),
                         caption=f"Original full PDF page {visible_page}; check year, entity, unit, row and column.",
                         width="stretch")
            except Exception as exc:
                st.warning(f"Page preview failed: {exc}")

try:
    checked = normalize_records(buffer, filings)
    pending_positions = checked.index[checked["Review status"].eq("Pending")].tolist()
    if st.button(f"Confirm all pending tables ({len(pending_positions)} cells) — optional",
                 icon=":material/check_circle:", disabled=not pending_positions):
        checked = confirm_source_rows(checked, pending_positions, filing, filings)
        save_draft(document_id, checked)
        st.session_state[f"review_revision_{document_id}"] = revision + 1
        st.success(f"Confirmed {len(pending_positions)} source cells across all tables. You can send them to Step 3.")
        st.rerun()
    with st.container(horizontal=True):
        if st.button("Save source edits", icon=":material/save:"):
            save_draft(document_id, checked)
            st.session_state[f"review_revision_{document_id}"] = revision + 1
            st.success("Source edits saved.")
            st.rerun()
        st.download_button("Download source review Excel",
                           data=source_review_workbook_bytes(checked, filings, source_table_labels(checked, tasks)),
                           file_name=f"{document_id}_source_review.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           icon=":material/download:")
        if st.button("Send extracted cells to Step 3 checks", type="primary", icon=":material/arrow_forward:",
                     disabled=not checked["Value status"].isin(("Reported", "Derived from disclosed items")).any()):
            save_draft(document_id, checked)
            count = stage_draft_for_checks(document_id)
            st.success(f"Sent {count} candidate source cells to Step 3. Pending cells will be screened there.")
except Exception as exc:
    st.error(f"Correct the source review data: {exc}")

with st.expander("Upload edited source review Excel", icon=":material/upload_file:"):
    uploaded = st.file_uploader("Source review Excel workbook", type="xlsx", key=f"source_upload_{document_id}")
    confirm_excel = st.checkbox("I checked the included source cells against the original PDF",
                                key=f"source_upload_confirm_{document_id}")
    if st.button("Import reviewed workbook", disabled=uploaded is None):
        try:
            imported = read_review_workbook(uploaded.getvalue(), filings)
            if imported.empty or not imported["Document ID"].eq(document_id).all():
                raise ValueError("The workbook must contain source cells for the selected filing only.")
            if confirm_excel:
                imported = confirm_source_rows(imported, list(range(len(imported))), filing, filings)
            save_draft(document_id, imported)
            st.session_state[f"review_revision_{document_id}"] = revision + 1
            st.success(f"Imported {len(imported)} source cells. "
                       + ("Included cells were confirmed." if confirm_excel else "Confirm all pending tables in the platform."))
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with st.expander("Add a missing source cell", icon=":material/add:"):
    with st.form(f"add_record_{document_id}"):
        metric_code = st.selectbox("Metric", [metric.code for metric in METRICS],
                                   format_func=lambda code: next(metric.label for metric in METRICS if metric.code == code))
        year = int(filing["period_end"][:4])
        period = st.selectbox("Period end", [filing["period_end"], f"{year - 1}{filing['period_end'][4:]}"])
        unit = st.selectbox("Source unit", [item for item, (currency, _) in UNIT_FACTORS.items()
                                            if currency == filing["currency"]])
        value = st.number_input("Original value", value=0.0, format="%.6f")
        page = st.number_input("Physical PDF page", min_value=1, max_value=page_count(path), step=1, value=1)
        label = st.text_input("Exact source row and column label")
        add = st.form_submit_button("Add pending cell")
    if add:
        try:
            if not label.strip():
                raise ValueError("Enter the original source row and column label.")
            row = dict.fromkeys(COLUMNS, "")
            row.update({"Document ID": document_id, "Period end": period, "Metric code": metric_code,
                        "Original value": value, "Source unit": unit, "Value status": "Reported",
                        "PDF page": page, "Source label": label, "Audit status": "Check source",
                        "Review status": "Pending", "Reviewer note": "Manually entered; verify against PDF."})
            save_draft(document_id, pd.concat([draft, pd.DataFrame([row])], ignore_index=True))
            st.session_state[f"review_revision_{document_id}"] = revision + 1
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
