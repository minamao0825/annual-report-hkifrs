"""PDF page selection and original-page confirmation."""

from __future__ import annotations

import hashlib
import importlib
import json

import pandas as pd
import streamlit as st

# Streamlit can rerun this page while retaining older helper modules in memory.
# Reload this discovery revision once so the page and model protocol match.
from hkifrs17 import catalog as _catalog_module
if getattr(_catalog_module, "EXTRACTION_COMPONENT_VERSION", 0) < 2:
    importlib.reload(_catalog_module)
    from hkifrs17 import data as _data_module
    importlib.reload(_data_module)
    from hkifrs17 import pdf as _pdf_module
    importlib.reload(_pdf_module)
from hkifrs17 import pdf as _pdf_module
if getattr(_pdf_module, "PDF_EXTRACTION_VERSION", 0) < 4:
    importlib.reload(_pdf_module)
from hkifrs17 import extraction_plan as _plan_module
if getattr(_plan_module, "PAGE_DISCOVERY_VERSION", 0) < 10:
    importlib.reload(_plan_module)
from hkifrs17 import source_templates as _templates_module
if getattr(_templates_module, "PAGE_DISCOVERY_VERSION", 0) < 13:
    importlib.reload(_templates_module)
from hkifrs17 import page_radar as _radar_module
if getattr(_radar_module, "PAGE_DISCOVERY_VERSION", 0) < 13:
    importlib.reload(_radar_module)
from hkifrs17 import discovery_runtime as _runtime_module
if getattr(_runtime_module, "DISCOVERY_RUNTIME_VERSION", 0) < 3:
    importlib.reload(_runtime_module)
from hkifrs17 import locator as _locator_module
if getattr(_locator_module, "PAGE_DISCOVERY_VERSION", 0) < 13:
    importlib.reload(_locator_module)
from hkifrs17 import storage as _storage_module
if getattr(_storage_module, "REVIEW_WORKFLOW_VERSION", 0) < 2:
    importlib.reload(_storage_module)

from hkifrs17.locator import locate_model_pages, page_groups, parse_physical_pages
from hkifrs17.page_radar import build_navigation, guided_groups
from hkifrs17.source_templates import (
    AUDITOR_BY_DOCUMENT, AUDITOR_TEMPLATES, table_examples,
    verified_table_options,
)
from hkifrs17.pdf import page_count, page_png
from hkifrs17.storage import (all_filings, filing_by_id, load_confirmed_pages,
                              pdf_path, save_confirmed_pages)
from hkifrs17.vision_settings import remember_step1_input, restore_step1_inputs


st.title("Locate table pages")
st.caption("Step 1 · Locate table pages, check the original PDF and confirm physical page numbers. Extract and review cells in Step 2.")
filings = all_filings()
document_id = st.selectbox("Filing", [item["document_id"] for item in filings],
                           format_func=lambda value: filing_by_id(value)["company"] + " · " + filing_by_id(value)["period_end"])
filing = filing_by_id(document_id)
st.session_state["review_filing_id"] = document_id
if document_id == "YF_2025":
    # Keep the checked landscape table upright in an already-running session
    # whose storage module still holds the previous pilot profile.
    filing = {**filing, "page_rotation_hints": {
        **filing.get("page_rotation_hints", {}), 113: 90,
    }}
path = pdf_path(filing)
if not path.exists():
    st.error("The PDF is not available in the platform's disclosures folder.")
    st.stop()

count = page_count(path)
discovery_result_key = f"discovery_result_v11_{document_id}"
confirmed_discovery_key = f"confirmed_discovery_v11_{document_id}"
source_stamp = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
source_stamp_key = f"confirmed_source_stamp_{document_id}"
existing_discovery = st.session_state.get(discovery_result_key, {})
if (source_stamp_key not in st.session_state and confirmed_discovery_key in st.session_state
        and existing_discovery.get("stamp") == source_stamp):
    save_confirmed_pages(document_id, path, st.session_state[confirmed_discovery_key])
elif st.session_state.get(source_stamp_key) != source_stamp:
    st.session_state[confirmed_discovery_key] = load_confirmed_pages(document_id, path)
st.session_state[source_stamp_key] = source_stamp
st.caption("Physical PDF page 1 is the first page of the file; printed page numbers in the report may differ.")
report_year = int(filing["period_end"][:4])
st.caption(f"Extraction target: {report_year} and {report_year - 1} from this filing · "
           f"{filing['scope']} · {filing['source_unit']}. Each year is stored separately for comparison.")

restore_step1_inputs(st.session_state)


def remember_model_field(field: str) -> None:
    remember_step1_input(st.session_state, field)


with st.expander("Vision model settings", icon=":material/settings:"):
    st.caption("Used for page discovery. Credentials stay in this browser session and carry into Step 2.")
    base_url = st.text_input("OpenAI-compatible base URL", key="extract_base_url",
                             on_change=remember_model_field, args=("base_url",))
    model = st.text_input("Vision model", key="extract_model",
                          on_change=remember_model_field, args=("model",))
    api_key = st.text_input("API key", type="password", key="extract_api_key",
                            on_change=remember_model_field, args=("api_key",))
    is_kimi_k26 = model.strip().lower() == "kimi-k2.6" and base_url.strip().lower().startswith(
        ("https://api.moonshot.cn/", "https://api.moonshot.ai/"))
    fast_kimi = st.checkbox("Use fast response for Kimi K2.6", key="extract_fast_kimi",
                            on_change=remember_model_field, args=("fast_kimi",),
                            help="Disables Kimi's default thinking mode for page recognition and transcription.") if is_kimi_k26 else False
    read_timeout = st.slider("Model response timeout (seconds)", min_value=120, max_value=600,
                             step=30, key="extract_timeout",
                             on_change=remember_model_field, args=("timeout",),
                             help="A failed request is not retried automatically.")

review_pending = False
with st.expander("Model-assisted page discovery", expanded=True, icon=":material/manage_search:"):
    range_left, range_right = st.columns(2)
    with range_left:
        first_page = st.number_input("First physical PDF page to scan", min_value=1, max_value=count,
                                     value=min(count, int(filing.get("page_profit") or 1)),
                                     key=f"discovery_first_v10_{document_id}")
    with range_right:
        last_page = st.number_input("Last physical PDF page to scan", min_value=1, max_value=count,
                                    value=count, key=f"discovery_last_v10_{document_id}")
    template_options = ["", *AUDITOR_TEMPLATES]
    suggested_template = filing.get("auditor_template") or AUDITOR_BY_DOCUMENT.get(document_id, "")
    auditor_template = st.selectbox(
        "Auditor layout template", template_options,
        index=template_options.index(suggested_template) if suggested_template in template_options else 0,
        key=f"auditor_template_{document_id}",
        format_func=lambda value: value or "All source table types",
        help="Reference note and table titles help identify source tables; each page must be checked in the current filing.",
    )
    discovery_tables = st.multiselect(
        "Source tables to locate", options=verified_table_options(auditor_template),
        default=[], key=f"discovery_tables_v10_{document_id}_{auditor_template or 'all'}",
    )
    examples = table_examples(auditor_template, discovery_tables)
    if examples:
        st.caption("Example note and table titles from reviewed reports; numbering may differ in this filing.")
        st.dataframe(pd.DataFrame(examples), hide_index=True, width="stretch")
    discovery_method = st.selectbox(
        "Page discovery method", ["Contents, titles and note radar", "Full visual scan"],
        key=f"discovery_method_v10_{document_id}",
        help="The note radar learns source labels from verified, directly reported Step 6 cells. All leads still require current-page image checks and human confirmation.",
    )
    use_text_navigation = discovery_method != "Full visual scan"
    pages_per_image = st.select_slider("Physical pages per model request", options=[1, 2, 4, 6, 8], value=2,
                                        help="Each page is sent as a separately numbered full-page image. One or two pages keep dense note headings and years readable.")
    valid_range = first_page <= last_page
    if filing.get("page_profit") and int(first_page) < int(filing["page_profit"]):
        st.warning(f"This pilot filing's audited statements start near physical PDF page {filing['page_profit']}. "
                   "Earlier pages include front matter and may produce irrelevant candidates.")
    groups = page_groups(int(first_page), int(last_page), int(pages_per_image)) if valid_range else []
    model_groups = groups
    navigation_info = None
    if valid_range and discovery_tables and use_text_navigation:
        try:
            navigation_info = build_navigation(path, filing, int(first_page), int(last_page), discovery_tables)
            pairs = {(lead.page, lead.table) for lead in navigation_info.leads}
            model_groups = guided_groups(int(first_page), int(last_page), discovery_tables,
                                         pairs, navigation_info.image_pages, int(pages_per_image))
            st.caption(
                f"Local index: {navigation_info.readable_pages} pages with readable text · "
                f"{len(navigation_info.image_pages)} image-only pages. "
                f"Source vocabulary learned from {navigation_info.experience.record_count} verified reported cells "
                f"across {navigation_info.experience.document_count} saved Step 6 filings."
            )
            if navigation_info.readable_pages:
                st.caption("One text request reads physical pages 1–60 as numbered navigation summaries (up to 1,200 characters each). "
                           "Business Review and accounting-policy prose is shortened; contents and statement titles are retained. "
                           "Candidate pages and neighbours then receive image checks. A target without clues keeps a full-range visual scan.")
            else:
                st.caption("Scanned PDF: a local OCR index will be built when you start discovery, then reused for later searches. "
                           "Titles and note clues guide a smaller set of original-page checks. If OCR is unavailable, visual scanning remains available.")
            with st.expander("Local page clues and learned source labels"):
                st.caption(navigation_info.scope_evidence + ". Historical page numbers and figures are not reused.")
                if navigation_info.leads:
                    st.dataframe(pd.DataFrame([
                        {"Physical PDF page": lead.page, "Table": lead.table, "Lead source": lead.source,
                         "Scope": lead.scope or navigation_info.scope, "Text clue": lead.evidence}
                        for lead in navigation_info.leads
                    ]), width="stretch", hide_index=True)
                st.dataframe(pd.DataFrame([
                    {"Table": table, "Learned source labels": "; ".join(navigation_info.experience.aliases(table)[:12])}
                    for table in discovery_tables
                ]), width="stretch", hide_index=True)
        except Exception as exc:
            st.caption(f"Local navigation is unavailable; the full visual scan will be used. {exc}")
    if not valid_range:
        st.warning("The last page must be at least the first page.")
    st.caption(f"{max(0, int(last_page) - int(first_page) + 1) if valid_range else 0} pages · "
               f"Up to {len(groups)} visual image groups before local indexing; the final request count is shown after discovery. "
               "Results from several ranges are combined in this session.")
    location_signature = hashlib.sha256(json.dumps([document_id, first_page, last_page,
                                                      pages_per_image, auditor_template,
                                                      discovery_tables, discovery_method, base_url, model,
                                                      path.stat().st_size, path.stat().st_mtime_ns,
                                                      navigation_info.experience.profiles if navigation_info else []]).encode("utf-8")).hexdigest()[:12]
    send_label = (f"Send first-60-page navigation summaries and note clues, plus original-page images as needed within physical PDF pages {first_page}–{last_page}, to this model service"
                  if use_text_navigation else
                  f"Send physical PDF pages {first_page}–{last_page} as separately numbered images to this model service")
    discovery_consent = st.checkbox(
        send_label,
        key=f"discovery_consent_{location_signature}",
        disabled=not valid_range or not discovery_tables,
    )
    if st.button("Locate candidate pages", type="primary", icon=":material/search:",
                 disabled=not discovery_consent or not valid_range or not discovery_tables):
        if not all((base_url.strip(), model.strip(), api_key.strip())):
            st.error("Enter the model service URL, model and API key in Vision model settings.")
        else:
            discovery_progress = st.progress(0, text="Locating candidate pages...")
            phase_status = st.empty()
            try:
                stamp = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
                diagnostics = []
                new_candidates, failures = locate_model_pages(
                    path, {**filing, "auditor_template": auditor_template},
                    first=int(first_page), last=int(last_page),
                    tables=discovery_tables, base_url=base_url, model=model, api_key=api_key,
                    pages_per_image=int(pages_per_image), fast_kimi=fast_kimi,
                    read_timeout=int(read_timeout), verify_pages=True,
                    use_text_navigation=use_text_navigation,
                    status=phase_status.caption,
                    diagnostics=diagnostics,
                    progress=lambda done, total: discovery_progress.progress(
                        done / total, text=f"Page discovery {done}%"),
                )
                previous = st.session_state.get(discovery_result_key, {})
                earlier = previous.get("candidates", []) if previous.get("stamp") == stamp else []
                earlier_tables = previous.get("tables", []) if previous.get("stamp") == stamp else []
                combined = {(row["Physical PDF page"], row["Table"]): row for row in earlier}
                combined.update({(row["Physical PDF page"], row["Table"]): row for row in new_candidates})
                st.session_state[discovery_result_key] = {"stamp": stamp,
                                                "tables": list(dict.fromkeys([*earlier_tables, *discovery_tables])),
                                                "candidates": sorted(combined.values(), key=lambda row: (
                                                    row["Physical PDF page"], row["Table"])),
                                                "failures": failures,
                                                "diagnostics": diagnostics}
                st.session_state[f"discovery_result_revision_v11_{document_id}"] = (
                    st.session_state.get(f"discovery_result_revision_v11_{document_id}", 0) + 1)
                st.success(f"Located {len(new_candidates)} page leads. Inspect each original page below.")
                if failures:
                    st.warning(f"{len(failures)} image request(s) failed; those pages were not assessed. "
                               "Review the failed ranges below and scan them again if needed.")
                    st.write(failures)
            except Exception as exc:
                st.error(f"Page discovery failed: {exc}")
    result = st.session_state.get(discovery_result_key, {})
    if result.get("failures"):
        with st.expander("Page ranges the model did not assess"):
            st.write(result["failures"])
    if result.get("diagnostics"):
        summaries = [row for row in result["diagnostics"] if row.get("Phase") == "Run summary"]
        if summaries:
            last_summary = summaries[-1]
            st.caption(f"Last discovery: {last_summary.get('Duration (seconds)', 0):.1f}s · "
                       f"{last_summary.get('Model requests', 0)} model requests. "
                       "Per-request timings and rejection reasons are available below.")
        with st.expander("Model proposals and local filtering"):
            st.caption("Shows what the model proposed and what the page-evidence rules retained. "
                       "A filtered proposal is not a confirmed source page.")
            st.dataframe(pd.DataFrame(result["diagnostics"]), width="stretch", hide_index=True)
            st.download_button("Download discovery diagnostics", json.dumps(result["diagnostics"], ensure_ascii=False, indent=2),
                               file_name=f"{document_id}_page_discovery_diagnostics.json", mime="application/json")
    if result and result.get("stamp") != (str(path), path.stat().st_size, path.stat().st_mtime_ns):
        st.warning("The PDF changed after page discovery. Run discovery again before confirming pages.")
    elif result:
        candidates = result.get("candidates", [])
        review_tables = result.get("tables") or discovery_tables
        revision = st.session_state.get(f"discovery_result_revision_v11_{document_id}", 0)
        confirmed_key = confirmed_discovery_key
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
                    source_label = "Model suggestion"
                    st.caption(source_label + " · " + "; ".join(
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
                        pd.DataFrame(candidates)[[column for column in (
                            "Table", "Physical PDF page", "Confidence",
                            "Financial-statement evidence", "Reporting-year evidence", "Table years",
                            "Scope evidence", "Visible evidence")
                            if column in pd.DataFrame(candidates).columns]],
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
                save_confirmed_pages(document_id, path, st.session_state[confirmed_key])
                st.session_state.pop(f"batch_results_{document_id}", None)
                review_pending = False
                st.success(
                    f"Confirmed {len(pairs)} table-page selections across "
                    f"{len({number for number, _ in pairs})} physical PDF pages. "
                    "Open Step 2 to extract and review these tables."
                )
        with preview_right:
            st.markdown("#### Page preview · original full PDF page")
            table_to_preview = st.selectbox(
                "Choose a table to preview", review_tables,
                key=f"review_preview_table_{document_id}_{revision}",
            )
            pages_to_preview = reviewed_pages.get(table_to_preview, [])
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


st.subheader("Confirmed pages ready for Step 2")
confirmed = load_confirmed_pages(document_id, path)
if confirmed:
    st.dataframe(pd.DataFrame(confirmed, columns=["Physical PDF page", "Table"]),
                 hide_index=True, width="stretch")
    st.caption(f"{len(confirmed)} table-page tasks are ready for extraction and table-by-table review in Step 2.")
else:
    st.info("Locate and confirm the original PDF pages above. They will appear in Step 2.")


