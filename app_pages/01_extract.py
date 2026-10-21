"""PDF page selection, visual inspection and draft extraction."""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import streamlit as st

from hkifrs17.catalog import METRIC_BY_CODE
from hkifrs17.demo import demo_records
from hkifrs17.extraction_plan import (
    RECORD_KEYS, TABLE_FAMILIES, TABLE_METRICS, extract_confirmed_batch, merge_extracted,
)
from hkifrs17.locator import locate_model_pages, page_groups, parse_physical_pages
from hkifrs17.metric_blueprint import CHART_REQUIREMENTS, chart_source_rows
from hkifrs17.pdf import extract_model_page, page_count, page_png
from hkifrs17.storage import all_filings, filing_by_id, load_draft, pdf_path, save_draft


st.title("Locate and extract")
st.caption("Step 1 · Locate candidate pages with a vision model, confirm them against the PDF, then extract an unpublished review draft.")
filings = all_filings()
document_id = st.selectbox("Filing", [item["document_id"] for item in filings],
                           format_func=lambda value: filing_by_id(value)["company"] + " · " + filing_by_id(value)["period_end"])
filing = filing_by_id(document_id)
path = pdf_path(filing)
if not path.exists():
    st.error("The PDF is not available in the platform's disclosures folder.")
    st.stop()

count = page_count(path)
quick_pages = {label: filing.get(key, 0) for label, key in (
    ("Profit or loss", "page_profit"), ("Financial position", "page_balance"),
    ("Cash flows", "page_cashflow"), ("CSM / contract note", "page_csm"))
    if filing.get(key, 0) and (label != "CSM / contract note" or not filing.get("note_page_hints"))}
st.caption("Suggested pilot pages (manually checked physical PDF pages): " +
           (" · ".join(f"{label}: {page}" for label, page in quick_pages.items()) or "None yet. Inspect the PDF."))
if filing.get("note_page_hints"):
    st.caption(f"{len(filing['note_page_hints'])} pre-checked source-page leads are available for this pilot filing. "
               "Load them below, inspect each full PDF page, then confirm the page numbers.")
st.caption("Physical PDF page 1 is the first page of the file; printed page numbers in the report may differ.")
st.caption(f"Extraction target: {filing['period_end']} only · {filing['scope']} · {filing['source_unit']}. "
           "Comparative-year figures and other reporting scopes are excluded from new Step 1 extractions.")

with st.expander("Chart-driven indicator and source-table map"):
    st.caption(f"All {len(CHART_REQUIREMENTS)} source Step 7 modules have an HK disposition. "
               "Excluded mainland-specific measures remain visible here for audit but are not extracted or charted. "
               "Conditional ratios require matching disclosed inputs.")
    st.dataframe(pd.DataFrame(chart_source_rows()), width="stretch", hide_index=True)

with st.expander("Vision model settings", icon=":material/settings:"):
    st.caption("Used for page discovery and table extraction. Credentials stay in this browser session.")
    base_url = st.text_input("OpenAI-compatible base URL", value="https://api.openai.com/v1", key="extract_base_url")
    model = st.text_input("Vision model", key="extract_model")
    api_key = st.text_input("API key", type="password", key="extract_api_key")
    is_kimi_k26 = model.strip().lower() == "kimi-k2.6" and base_url.strip().lower().startswith(
        ("https://api.moonshot.cn/", "https://api.moonshot.ai/"))
    fast_kimi = st.checkbox("Use fast response for Kimi K2.6", value=True,
                            help="Disables Kimi's default thinking mode for page recognition and transcription.") if is_kimi_k26 else False
    read_timeout = st.slider("Model response timeout (seconds)", min_value=120, max_value=600,
                             value=300, step=30, help="A failed request is not retried automatically.")

review_pending = False
with st.expander("Model-assisted page discovery", expanded=True, icon=":material/manage_search:"):
    st.caption("Scan a PDF page range as numbered contact-sheet images. The model suggests pages only; "
               "you must inspect the original page and confirm its table type before extraction.")
    range_left, range_right = st.columns(2)
    with range_left:
        first_page = st.number_input("First physical PDF page to scan", min_value=1, max_value=count,
                                     value=1, key=f"discovery_first_{document_id}")
    with range_right:
        last_page = st.number_input("Last physical PDF page to scan", min_value=1, max_value=count,
                                    value=count, key=f"discovery_last_{document_id}")
    focus = st.selectbox("Discovery focus", list(TABLE_FAMILIES),
                         index=2 if document_id == "FWD_2025" else 0,
                         key=f"discovery_focus_{document_id}")
    discovery_tables = st.multiselect(
        "Find these table types", options=list(TABLE_FAMILIES[focus]),
        default=list(TABLE_FAMILIES[focus]),
        key=f"discovery_tables_{document_id}_{focus}",
    )
    if filing.get("note_page_hints") and st.button("Load pre-checked report page leads", icon=":material/playlist_add:"):
        stamp = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
        key = f"discovery_result_{document_id}"
        previous = st.session_state.get(key, {})
        earlier = previous.get("candidates", []) if previous.get("stamp") == stamp else []
        # Run primary statements first: a note must not silently replace an
        # identically coded statement cell with a different accounting scope.
        seeds = [
            {"Physical PDF page": int(page), "Table": table,
             "Visible evidence": "Pre-checked primary statement page lead; inspect before confirming",
             "Confidence": "Page lead"}
            for table, page in quick_pages.items()
            if table in TABLE_METRICS and 1 <= int(page) <= count
        ]
        seeds.extend(
            {"Physical PDF page": int(page), "Table": table,
             "Visible evidence": "Pre-checked pilot page lead; inspect the original PDF before confirming",
             "Confidence": "Page lead"}
            for page, table in filing["note_page_hints"]
            if 1 <= int(page) <= count and table in TABLE_METRICS
        )
        combined = {(row["Physical PDF page"], row["Table"]): row for row in seeds}
        combined.update({(row["Physical PDF page"], row["Table"]): row for row in earlier})
        tables = list(dict.fromkeys([*(previous.get("tables", []) if previous.get("stamp") == stamp else []),
                                    *(row["Table"] for row in seeds)]))
        st.session_state[key] = {
            "stamp": stamp, "tables": tables,
            "candidates": sorted(combined.values(), key=lambda row: (row["Physical PDF page"], row["Table"])),
            "failures": previous.get("failures", []) if previous.get("stamp") == stamp else [],
        }
        st.session_state[f"discovery_result_revision_{document_id}"] = (
            st.session_state.get(f"discovery_result_revision_{document_id}", 0) + 1
        )
        st.success(f"Loaded {len(seeds)} page leads. Inspect original pages and confirm all reviewed table pages below.")
    pages_per_image = st.select_slider("Physical pages per model image", options=[4, 6, 8], value=6,
                                        help="Fewer pages make headings easier to read; more pages use fewer model requests.")
    valid_range = first_page <= last_page
    groups = page_groups(int(first_page), int(last_page), int(pages_per_image)) if valid_range else []
    if not valid_range:
        st.warning("The last page must be at least the first page.")
    st.caption(f"{max(0, int(last_page) - int(first_page) + 1) if valid_range else 0} pages · "
               f"{len(groups)} model image requests. Scan smaller ranges if you want to control time and cost; "
               "results from several ranges are combined in this session.")
    location_signature = hashlib.sha256(json.dumps([document_id, first_page, last_page,
                                                      pages_per_image, discovery_tables]).encode("utf-8")).hexdigest()[:12]
    discovery_consent = st.checkbox(
        f"Send physical PDF pages {first_page}–{last_page} as {len(groups)} numbered image(s) to this model service",
        key=f"discovery_consent_{location_signature}", disabled=not valid_range or not discovery_tables,
    )
    if st.button("Locate candidate pages", type="primary", icon=":material/search:",
                 disabled=not discovery_consent or not valid_range or not discovery_tables):
        if not all((base_url.strip(), model.strip(), api_key.strip())):
            st.error("Enter the model service URL, model and API key in Vision model settings.")
        else:
            discovery_progress = st.progress(0, text="Locating candidate pages...")
            try:
                stamp = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
                new_candidates, failures = locate_model_pages(
                    path, filing, first=int(first_page), last=int(last_page),
                    tables=discovery_tables, base_url=base_url, model=model, api_key=api_key,
                    pages_per_image=int(pages_per_image), fast_kimi=fast_kimi,
                    read_timeout=int(read_timeout),
                    progress=lambda done, total: discovery_progress.progress(
                        done / total, text=f"Scanned {done}/{total} page images"),
                )
                result_key = f"discovery_result_{document_id}"
                previous = st.session_state.get(result_key, {})
                earlier = previous.get("candidates", []) if previous.get("stamp") == stamp else []
                earlier_tables = previous.get("tables", []) if previous.get("stamp") == stamp else []
                combined = {(row["Physical PDF page"], row["Table"]): row for row in earlier}
                combined.update({(row["Physical PDF page"], row["Table"]): row for row in new_candidates})
                st.session_state[result_key] = {"stamp": stamp,
                                                "tables": list(dict.fromkeys([*earlier_tables, *discovery_tables])),
                                                "candidates": sorted(combined.values(), key=lambda row: (
                                                    row["Physical PDF page"], row["Table"])),
                                                "failures": failures}
                st.session_state[f"discovery_result_revision_{document_id}"] = (
                    st.session_state.get(f"discovery_result_revision_{document_id}", 0) + 1)
                st.success(f"Found {len(new_candidates)} candidates in this scan. Inspect each original page below.")
                if failures:
                    st.warning(f"{len(failures)} image request(s) failed; those pages were not assessed. "
                               "Review the failed ranges below and scan them again if needed.")
                    st.write(failures)
            except Exception as exc:
                st.error(f"Page discovery failed: {exc}")
    result = st.session_state.get(f"discovery_result_{document_id}", {})
    if result.get("failures"):
        with st.expander("Page ranges the model did not assess"):
            st.write(result["failures"])
    if result and result.get("stamp") != (str(path), path.stat().st_size, path.stat().st_mtime_ns):
        st.warning("The PDF changed after page discovery. Run discovery again before confirming pages.")
    elif result:
        candidates = result.get("candidates", [])
        review_tables = result.get("tables") or discovery_tables
        revision = st.session_state.get(f"discovery_result_revision_{document_id}", 0)
        confirmed_key = f"confirmed_discovery_{document_id}"
        confirmed = set(map(tuple, st.session_state.get(confirmed_key, [])))
        if not candidates:
            st.info("The model found no candidate pages. Enter physical page numbers manually and compare them with the original PDF.")
        else:
            overview = pd.DataFrame(candidates)
            overview["Human confirmation"] = [
                "Confirmed" if (row["Physical PDF page"], row["Table"]) in confirmed else "To review"
                for row in candidates
            ]
            st.dataframe(overview, width="stretch", hide_index=True)

        review_left, review_space, preview_right = st.columns([1, 0.05, 1.2], gap="small")
        reviewed_pages: dict[str, list[int]] = {}
        invalid_entries: dict[str, list[str]] = {}
        with review_left:
            st.markdown("#### Page-number review")
            st.caption("Edit every target table's physical PDF pages. Separate continuation pages with commas, for example 26, 27.")
            for table in review_tables:
                matches = [row for row in candidates if row["Table"] == table]
                suggested = sorted({int(row["Physical PDF page"]) for row in matches})
                raw = st.text_input(
                    table, value=", ".join(map(str, suggested)),
                    key=f"review_pages_{document_id}_{revision}_{table}",
                )
                pages, invalid = parse_physical_pages(raw, count)
                reviewed_pages[table] = pages
                if invalid:
                    invalid_entries[table] = invalid
                    st.warning(f"{table}: invalid physical page(s): {', '.join(invalid)}")
                elif pages and all((number, table) in confirmed for number in pages):
                    st.caption("Confirmed · " + ", ".join(map(str, pages)))
                elif matches:
                    st.caption("Model suggestion · " + "; ".join(
                        f"p.{row['Physical PDF page']} {row['Confidence']}" for row in matches
                    ))
                else:
                    st.caption("No model match · enter page number if disclosed.")
            reviewed_pairs = {
                (number, table) for table, pages in reviewed_pages.items() for number in pages
            }
            confirmed_for_review = {pair for pair in confirmed if pair[1] in review_tables}
            review_pending = reviewed_pairs != confirmed_for_review
            if candidates:
                with st.expander("Model page evidence"):
                    st.dataframe(
                        pd.DataFrame(candidates)[["Table", "Physical PDF page", "Confidence", "Visible evidence"]],
                        width="stretch", hide_index=True,
                    )
            if st.button(
                "Confirm all reviewed table pages",
                width="stretch", icon=":material/check_circle:",
                disabled=bool(invalid_entries) or not any(reviewed_pages.values()),
            ):
                pairs = [(number, table) for table, pages in reviewed_pages.items() for number in pages]
                earlier = {pair for pair in confirmed if pair[1] not in review_tables}
                st.session_state[confirmed_key] = sorted(earlier.union(pairs))
                st.session_state.pop(f"batch_results_{document_id}", None)
                review_pending = False
                st.success(
                    f"Confirmed {len(pairs)} table-page selections across "
                    f"{len({number for number, _ in pairs})} physical PDF pages. "
                    "All confirmed tables are ready for extraction below."
                )
        with preview_right:
            st.markdown("#### Page preview · original full PDF page")
            table_to_preview = st.selectbox(
                "Choose a table to preview", review_tables,
                key=f"review_preview_table_{document_id}_{revision}",
            )
            pages_to_preview = reviewed_pages[table_to_preview]
            if not pages_to_preview:
                st.info("No valid physical page is entered for this table. Enter a page number on the left to preview it.")
            else:
                if len(pages_to_preview) > 1:
                    preview_page = st.radio(
                        "This table spans multiple pages", pages_to_preview,
                        horizontal=True,
                        key=f"review_preview_page_{document_id}_{revision}_{table_to_preview}",
                    )
                else:
                    preview_page = pages_to_preview[0]
                try:
                    st.image(
                        page_png(path, preview_page, rotate=int(
                            filing.get("page_rotation_hints", {}).get(preview_page, 0))),
                        caption=f"Original full PDF page {preview_page} of {count} · "
                                "check heading, reporting period, entity scope and table columns",
                        width="stretch",
                    )
                except Exception as exc:
                    st.warning(f"Page preview failed: {exc}")


st.subheader("Extract confirmed tables")
st.caption("All confirmed table pages are extracted automatically. Each resulting cell remains Pending until Step 2 review.")
with st.expander("Supported fields and note-scope guidance"):
    st.caption("For a multi-column note, transcribe the named total or component column only; never mix PAA and non-PAA, assets and liabilities, or company and group. A blank or dash is not zero.")
    st.dataframe(pd.DataFrame([
        {"Table": table, "Metric code": code, "Field": METRIC_BY_CODE[code].label}
        for table, codes in TABLE_METRICS.items() for code in codes
    ]), hide_index=True, width="stretch")
active_result = st.session_state.get(f"discovery_result_{document_id}", {})
active_stamp = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
confirmed_pairs = set(map(tuple, st.session_state.get(f"confirmed_discovery_{document_id}", [])))
active_tables = active_result.get("tables", [])
tasks = [
    (number, table)
    for table in active_tables
    for number in sorted(page for page, name in confirmed_pairs if name == table and 1 <= page <= count)
] if active_result.get("stamp") == active_stamp else []
if tasks:
    st.dataframe(pd.DataFrame(tasks, columns=["Physical PDF page", "Table"]),
                 width="stretch", hide_index=True)
    st.caption(f"{len(tasks)} confirmed table-page tasks. Each is extracted separately so one failure does not stop the others.")
else:
    st.info("Locate the needed pages, inspect their original PDF images, and confirm all reviewed table pages above.")
if review_pending:
    st.warning("The edited page numbers have not been confirmed. Check the original pages above, "
               "then confirm all reviewed pages before extracting.")
task_signature = hashlib.sha256(json.dumps([document_id, active_stamp, tasks]).encode("utf-8")).hexdigest()[:12]
extraction_consent = st.checkbox(
    f"Send all {len(tasks)} confirmed table-page image(s) to this model service",
    key=f"extraction_consent_{document_id}_{task_signature}",
    disabled=not tasks or review_pending,
)
st.caption("One model request is sent per confirmed table-page task. Failed tasks are not retried automatically.")
if st.button("Extract all confirmed tables", type="primary", icon=":material/batch_prediction:",
             disabled=not tasks or review_pending or not extraction_consent):
    if not all((base_url.strip(), model.strip(), api_key.strip())):
        st.error("Enter the model service URL, model and API key before starting extraction.")
    else:
        progress_bar = st.progress(0, text=f"Extracting 0/{len(tasks)} tables...")
        completed = [0]
        def update_progress(done: int, total: int, physical_page: int, table: str) -> None:
            completed[0] = done
            progress_bar.progress(done / total,
                                  text=f"Processed {done}/{total} · PDF p.{physical_page} · {table}")

        def extract_one(physical_page: int, table: str) -> pd.DataFrame:
            progress_bar.progress(completed[0] / len(tasks),
                                  text=f"Extracting {completed[0] + 1}/{len(tasks)} · PDF p.{physical_page} · {table}")
            return extract_model_page(
                path, filing, physical_page, filings, base_url=base_url,
                model=model, api_key=api_key, fast_kimi=fast_kimi,
                read_timeout=int(read_timeout), metric_codes=set(TABLE_METRICS[table]),
                table_names=[table],
            )

        results = extract_confirmed_batch(
            tasks, extractor=extract_one,
            load_current=lambda: load_draft(document_id),
            save_current=lambda frame: save_draft(document_id, frame),
            progress=update_progress,
        )
        st.session_state[f"batch_results_{document_id}"] = {"signature": task_signature, "rows": results}
        progress_bar.progress(1.0, text=f"Completed {len(results)}/{len(tasks)} table-page tasks")

batch_result = st.session_state.get(f"batch_results_{document_id}", {})
if isinstance(batch_result, dict) and batch_result.get("signature") == task_signature:
    results = batch_result["rows"]
    failures = results[results["Status"].ne("Saved as Pending")]
    successes = len(results) - len(failures)
    if failures.empty:
        st.success(f"Completed {len(results)} table-page tasks. All extracted cells were saved as Pending for Step 2 review.")
    else:
        st.warning(f"Completed {len(results)} table-page tasks: {successes} succeeded and {len(failures)} failed. "
                   "Successful cells were saved as Pending for Step 2 review.")
        st.markdown("#### Failed tables")
        st.dataframe(failures[["Table", "Physical PDF page", "Detail"]], width="stretch", hide_index=True)
    with st.expander("Full extraction results"):
        st.dataframe(results, width="stretch", hide_index=True)

if document_id in {"YF_2025", "FWD_2025", "CTF_2025", "SUN_2025"}:
    with st.expander("Pilot transcription aids", icon=":material/table_chart:"):
        st.caption("Optional unpublished transcription leads. All imported cells remain Pending until Step 2 review.")
        if st.button("Load pilot draft", icon=":material/table_chart:"):
            if not load_draft(document_id).empty:
                st.warning("A draft already exists; it was preserved. Edit it in Step 2.")
            else:
                leads = demo_records(document_id)
                save_draft(document_id, leads[leads["Period end"].eq(filing["period_end"])])
                st.success("Pilot transcription loaded as Pending. Check the source before verification.")
        if document_id == "FWD_2025" and st.button(
            "Add FWD note 4/13 transcription leads", icon=":material/playlist_add:"
        ):
            leads = demo_records(document_id)
            leads = leads[leads["Period end"].eq(filing["period_end"])
                          & leads["PDF page"].astype(int).ge(51)].copy()
            current = load_draft(document_id)
            present = set(map(tuple, current[RECORD_KEYS].itertuples(index=False, name=None)))
            leads = leads[[key not in present for key in leads[RECORD_KEYS].itertuples(index=False, name=None)]]
            combined, counts = merge_extracted(current, leads)
            if counts["added"]:
                save_draft(document_id, combined)
            st.success(
                f"Added {counts['added']} Pending note cells. All existing draft cells were preserved; "
                "check every cited page in Step 2."
            )
