"""Cell-level reconciliation review, Excel round trip and publication."""

from __future__ import annotations

import importlib
import pandas as pd
import streamlit as st

from hkifrs17 import data as _data_module
if getattr(_data_module, "DATA_WORKFLOW_VERSION", 0) < 2:
    importlib.reload(_data_module)
from hkifrs17 import checks as _checks_module
if getattr(_checks_module, "CHECKS_WORKFLOW_VERSION", 0) < 2:
    importlib.reload(_checks_module)
from hkifrs17 import review_flow as _review_flow_module
if getattr(_review_flow_module, "SOURCE_REVIEW_VERSION", 0) < 4:
    importlib.reload(_review_flow_module)
from hkifrs17 import storage as _storage_module
if getattr(_storage_module, "REVIEW_WORKFLOW_VERSION", 0) < 4:
    importlib.reload(_storage_module)
from hkifrs17 import review as _review_module
if getattr(_review_module, "REVIEW_WORKFLOW_VERSION", 0) < 11:
    importlib.reload(_review_module)
from hkifrs17 import vision_settings as _vision_settings_module
if getattr(_vision_settings_module, "VISION_SETTINGS_VERSION", 0) < 2:
    importlib.reload(_vision_settings_module)
from hkifrs17 import source_audit as _source_audit_module
if getattr(_source_audit_module, "SOURCE_AUDIT_VERSION", 0) < 3:
    importlib.reload(_source_audit_module)

from hkifrs17.checks import (ASSESSMENTS, FORMULA_BASES, METHODS, NOTE_SCOPES, RULES,
                             automatic_arithmetic_checks, normalize_plan, require_resolved_checks)
from hkifrs17.data import COLUMNS, check_candidates, reconciliation_checks
from hkifrs17.investigation import investigate_check_issues
from hkifrs17.review import (read_check_plan_workbook, read_manual_source_reviews,
                             read_review_workbook,
                             step3_workbook_bytes, validate_step3_check_workbook)
from hkifrs17.review_flow import per_cell_checks
from hkifrs17.scope_corroboration import PAIR_CODES, statement_note_corroboration
from hkifrs17.source_audit import (audit_rows, confirmed_amount_repairs,
                                  _fingerprint, pdf_stamp, source_results)
from hkifrs17.storage import (all_filings, approved_ids, filing_by_id, load_approved,
                              load_check_plan, load_confirmed_pages, load_published,
                              load_source_audit, pdf_path, publish_selected,
                              save_approved_check_plan, save_source_audit,
                              apply_confirmed_repairs)
from hkifrs17.vision_settings import remember_page_input, shared_vision_settings


@st.cache_data(show_spinner="Preparing check Excel...", max_entries=8)
def cached_check_workbook(rows: pd.DataFrame, filings: list[dict], plan: pd.DataFrame,
                          confirmed_pages: tuple[int, ...], source_audit: pd.DataFrame) -> bytes:
    return step3_workbook_bytes(rows, filings, plan, confirmed_pages, source_audit)


st.title("Check cells and publish")
st.caption("Step 3 · Automatically screen every extracted source cell, including Pending candidates. Investigate flagged source or reconciliation issues before publishing.")
ids = approved_ids()
if ids:
    chosen = st.selectbox("Reviewed filing", ids,
                          format_func=lambda value: filing_by_id(value)["company"] + " · " + value)
    filings = all_filings()
    approved = load_approved(chosen)
    incoming = check_candidates(approved, filings)
    include_pending = incoming["Review status"].eq("Pending").any()
    source_pdf = pdf_path(filing_by_id(chosen))
    confirmed_pages = {page for page, _ in load_confirmed_pages(chosen, source_pdf)}
    st.metric("Source cells ready for checks", len(incoming), border=True)
    repaired_notice = st.session_state.pop(f"step3_auto_repairs_{chosen}", 0)
    if repaired_notice:
        st.success(f"Automatically corrected {repaired_notice} amount(s) after a full-page read "
                   "and an independent, isolated numeric-cell reread. All checks have been recalculated.")
    source_checks = source_results(incoming, source_pdf, load_source_audit(chosen))
    unchecked = source_checks[source_checks["Source check"].ne("Match")]
    note_codes = {pair[1] for pair in PAIR_CODES.values()}
    legacy_scope_notes = source_checks[
        source_checks["Source check"].eq("Match")
        & source_checks["Metric code"].isin(note_codes)
        & source_checks["Scope basis"].fillna("").astype(str).str.strip().eq("")
    ]
    to_recheck = pd.concat([unchecked, legacy_scope_notes], ignore_index=True)
    st.subheader("Independent PDF image check")
    st.caption("The shared Step 1 model rereads each original page without seeing stored amounts. "
               "A mismatch or unreadable cell remains an exception; no value is changed to force a rule to balance.")
    with st.container(horizontal=True):
        st.metric("Image matches", int(source_checks["Source check"].eq("Match").sum()), border=True)
        st.metric("Awaiting image check", int(source_checks["Source check"].eq("Not checked").sum()), border=True)
        st.metric("Image findings to review", int(source_checks["Source check"].isin(("Mismatch", "Unclear")).sum()), border=True)
    scope_conflicts = int(source_checks["Reason"].fillna("").str.contains("entity scope differs", regex=False).sum())
    if scope_conflicts:
        st.info(f"{scope_conflicts} saved image findings report a Company/Consolidated conflict. "
                "The revised check inherits the confirmed primary-statement scope for note "
                "tables unless the note explicitly switches scope. Recheck these cells; "
                "inspect any remaining explicit conflicts against the original PDF in Step 2.")
    if not legacy_scope_notes.empty:
        st.caption(f"{len(legacy_scope_notes)} previously matched statement-to-note cell(s) "
                   "also need a scope-basis reread under the revised instructions.")
    vision = shared_vision_settings(st.session_state)
    missing_model_fields = [label for field, label in (
        ("base_url", "service URL"), ("model", "vision model"), ("api_key", "API key"))
        if not str(vision[field]).strip()]
    if missing_model_fields:
        st.warning("PDF image checking is waiting for: " + ", ".join(missing_model_fields)
                   + ". Step 1 settings live only in this browser session; a page reload, "
                   "new tab or server restart can clear the API key. Reconnect below to continue.")
    for field in ("base_url", "model", "api_key"):
        widget_key = f"step3_vision_{field}"
        if st.session_state.get(widget_key) != str(vision[field]):
            st.session_state[widget_key] = str(vision[field])
    def save_model_setting(field: str) -> None:
        remember_page_input(st.session_state, field, f"step3_vision_{field}")
    with st.expander("Shared model connection", expanded=bool(missing_model_fields),
                     icon=":material/settings:"):
        st.caption("Uses the same settings as Steps 1 and 2. The API key stays in this browser session.")
        st.text_input("OpenAI-compatible base URL", key="step3_vision_base_url",
                      on_change=save_model_setting, args=("base_url",))
        st.text_input("Vision model", key="step3_vision_model",
                      on_change=save_model_setting, args=("model",))
        st.text_input("API key", type="password", key="step3_vision_api_key",
                      on_change=save_model_setting, args=("api_key",))
    vision = shared_vision_settings(st.session_state)
    model_ready = all(str(vision[field]).strip() for field in ("base_url", "model", "api_key"))
    consent = st.checkbox(f"Send {len(to_recheck)} source cell(s) on their PDF pages to the shared model service",
                          key=f"step3_source_consent_{chosen}")
    if st.button("Check PDF cells needing review", icon=":material/fact_check:",
                 disabled=to_recheck.empty or not consent or not model_ready):
        remaining = incoming.merge(to_recheck[["Period end", "Metric code"]],
                                   on=["Period end", "Metric code"], how="inner")
        bar = st.progress(0, text="Reading original PDF pages...")
        def audit_progress(done: int, total: int, page: int) -> None:
            bar.progress(done / total, text=f"Checked {done}/{total} image batches · PDF p.{page}")
        findings = audit_rows(remaining, filing_by_id(chosen), source_pdf,
                              base_url=str(vision["base_url"]), model=str(vision["model"]),
                              api_key=str(vision["api_key"]), timeout=int(vision["timeout"]),
                              progress=audit_progress)
        repairs = confirmed_amount_repairs(
            remaining, findings, source_pdf, base_url=str(vision["base_url"]),
            model=str(vision["model"]), api_key=str(vision["api_key"]),
            timeout=int(vision["timeout"]))
        if repairs:
            updated = apply_confirmed_repairs(chosen, repairs)
            revised = {(row["Period end"], row["Metric code"]): row
                       for _, row in updated.iterrows()}
            repaired = {(item["Period end"], item["Metric code"]) for item in repairs}
            stamp = pdf_stamp(source_pdf)
            for finding in findings:
                key = (finding["Period end"], finding["Metric code"])
                if key in repaired:
                    finding["Source check"] = "Match"
                    finding["Reason"] = "Amount corrected after full-page and isolated-cell image reads."
                    finding["Fingerprint"] = _fingerprint(revised[key], stamp)
            st.session_state[f"step3_auto_repairs_{chosen}"] = len(repairs)
        save_source_audit(chosen, findings)
        st.rerun()
    if not to_recheck.empty:
        with st.expander("Unreviewed cells and image findings"):
            st.dataframe(to_recheck, hide_index=True, width="stretch")

    plan = load_check_plan(chosen, stage="approved")
    revision = st.session_state.get(f"step3_plan_revision_{chosen}", 0)
    with st.expander("Optional exception notes and sign choices"):
        st.caption("Built-in checks run without filling this table. Use it to explain a truly inapplicable rule or a disclosed gap, or to correct a source sign convention. For an absent full PAA/non-PAA method split, enter both the reason and original note with physical PDF page before selecting Not applicable. Source amount corrections belong in Step 2.")
        edited_plan = st.data_editor(
            plan.drop(columns=["Document ID"]), hide_index=True, num_rows="fixed",
            disabled=["Period end", "Check ID"], key=f"step3_plan_{chosen}_{revision}",
            column_config={
                "Assessment": st.column_config.SelectboxColumn(options=list(ASSESSMENTS), required=True),
                "Measurement method": st.column_config.SelectboxColumn(options=list(METHODS), required=True),
                "Note scope": st.column_config.SelectboxColumn(options=list(NOTE_SCOPES), required=True),
                "Formula basis": st.column_config.SelectboxColumn(options=list(FORMULA_BASES), required=True),
            }, width="stretch",
        )
    edited_plan.insert(0, "Document ID", chosen)
    try:
        checked_plan = normalize_plan(edited_plan, filings, {chosen})
        arithmetic = automatic_arithmetic_checks(incoming, filings, checked_plan,
                                                verified_only=not include_pending)
        scope_bridge = statement_note_corroboration(incoming, arithmetic, source_checks)
        if not scope_bridge.empty:
            st.subheader("Statement-to-note scope corroboration")
            st.caption("The same-year statement and note totals are compared only where their "
                       "metric definitions and gross/net basis permit. A numeric match supports "
                       "the selected Company/Consolidated scope after both source cells have "
                       "passed PDF review; it does not replace the page evidence.")
            st.dataframe(scope_bridge, hide_index=True, width="stretch")
        checks = reconciliation_checks(incoming, filings, checked_plan,
                                       verified_only=not include_pending, automatic=True)
        cells = per_cell_checks(incoming, checks, arithmetic, allow_pending=include_pending,
                                confirmed_pages=confirmed_pages if include_pending else None,
                                source_audit=source_checks)
        st.subheader("Automatic arithmetic screening")
        st.caption("Runs immediately for both reporting years. Profit-or-loss/OCI changes and cash flows are checked as separate inputs; gross insurance balances and signed acquisition assets are bridged to net liabilities. Match means the available numbers reconcile and still requires source-scope review.")
        arithmetic_issues = arithmetic[arithmetic["Arithmetic result"].ne("Match")]
        with st.container(horizontal=True):
            st.metric("Arithmetic differences", int(arithmetic["Arithmetic result"].eq("Difference").sum()), border=True)
            st.metric("Missing source cells", int(arithmetic["Arithmetic result"].eq("Missing source cells").sum()), border=True)
        if not arithmetic_issues.empty:
            st.dataframe(arithmetic_issues, hide_index=True, width="stretch")
        with st.expander("All automatic rule results"):
            st.dataframe(arithmetic, hide_index=True, width="stretch")
        investigation = investigate_check_issues(incoming, checks, confirmed_pages)
        if not investigation.empty:
            st.subheader("Automatic investigation")
            st.caption("These are source-based leads, not automatic changes to extracted amounts. Select an issue, inspect its original PDF pages in Step 2, and correct the source cell there if needed.")
            st.dataframe(investigation[["Period end", "Check ID", "Result",
                                        "Difference (millions)", "Missing metric codes"]],
                         hide_index=True, width="stretch")
            selected_issue = st.selectbox(
                "Issue to inspect", range(len(investigation)),
                format_func=lambda index: (f"{investigation.iloc[index]['Period end']} · "
                                           f"{investigation.iloc[index]['Check ID']} · "
                                           f"{investigation.iloc[index]['Result']}"),
            )
            selected = investigation.iloc[selected_issue]
            st.write("Source cells and physical pages:", selected["Source cells and physical pages"])
            st.warning(selected["Automatic leads"])
            st.info(selected["Review action"])
            with st.expander("How to resolve a flagged cell"):
                st.markdown(
                    "1. Read the rule, difference or missing metric code, and the listed physical PDF pages.\n"
                    "2. Open the original page in Step 2. Verify year, legal entity, insurance/reinsurance, "
                    "PAA/non-PAA, row, column, sign and printed unit.\n"
                    "3. Correct a wrong source value, unit, year or metric mapping in Step 2 and send the reviewed cells again.\n"
                    "4. For a missing metric, inspect the relevant note pages. Extract it if disclosed; "
                    "otherwise document the note reference and reason in Optional exception notes. "
                    "Never infer a movement from opening and closing balances.\n"
                    "5. Return to Step 3 and check that the affected cells and rule are resolved before publishing."
                )
        st.subheader("Every source cell")
        st.caption("Every row shows source-reference completeness, unit conversion, automatic arithmetic and the final rule result. Pending candidates can pass screening; an arithmetic match alone does not confirm the original PDF column or scope.")
        st.dataframe(cells, hide_index=True, width="stretch")
        status = checks["Result"].value_counts()
        with st.container(horizontal=True):
            st.metric("Cells passing", int(cells["Cell result"].eq("Pass").sum()), border=True)
            st.metric("Cells to investigate", int(cells["Cell result"].eq("Investigate").sum()), border=True)
            for name in ("Pass", "Difference", "Missing inputs", "Not applicable", "Not evaluated"):
                st.metric(name, int(status.get(name, 0)), border=True)
        st.subheader("Built-in reconciliation rules")
        st.dataframe(checks, hide_index=True, width="stretch")
        with st.expander("Built-in rule catalogue"):
            st.dataframe(pd.DataFrame([
                {"Check ID": rule.id, "Check": rule.name, "Required": rule.mandatory,
                 "Total metric": rule.total or "Coverage only",
                 "Component metrics": ", ".join(rule.parts)}
                for rule in RULES
            ]), hide_index=True, width="stretch")
        with st.container(horizontal=True):
            if st.button("Save exception notes", icon=":material/save:"):
                save_approved_check_plan(chosen, checked_plan)
                st.success("Step 3 exception notes saved.")
            st.download_button(
                "Download check Excel",
                data=cached_check_workbook(incoming, filings, checked_plan,
                                           tuple(sorted(confirmed_pages)), source_checks),
                file_name=f"{chosen}_cell_checks.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                icon=":material/download:",
            )
            if st.button("Publish checked filing", type="primary", icon=":material/publish:"):
                if cells["Cell result"].eq("Investigate").any():
                    count = int(cells["Cell result"].eq("Investigate").sum())
                    first = cells[cells["Cell result"].eq("Investigate")].iloc[0]
                    raise ValueError(
                        f"{count} source cells need review. First: {first['Period end']} "
                        f"{first['Metric code']} on physical PDF page {first['Physical PDF page']}; "
                        f"related rules: {first['Rule results']}. See Every source cell and Automatic arithmetic screening."
                    )
                require_resolved_checks(checks, automatic=True)
                save_approved_check_plan(chosen, checked_plan)
                count = publish_selected([chosen], checked_candidates=True)
                st.success(f"Published {count} checked cells. The Step 4 dataset was refreshed automatically.")
    except Exception as exc:
        st.error(f"Resolve the Step 3 checks: {exc}")

    with st.expander("Upload checked Excel", icon=":material/upload_file:"):
        st.caption("Excel formulas recalculate when opened in Excel. You may transcribe unresolved PDF source cells on the Manual source review sheet. The platform checks those observations and independently recalculates every rule on upload.")
        uploaded = st.file_uploader("Checked Excel workbook", type="xlsx", key=f"step3_upload_{chosen}")
        confirmed = st.checkbox("I checked the Excel cell and reconciliation formulas against the source report",
                                key=f"step3_excel_confirm_{chosen}")
        if st.button("Import checked Excel", disabled=uploaded is None or not confirmed):
            try:
                validate_step3_check_workbook(uploaded.getvalue(), len(incoming))
                imported = read_review_workbook(uploaded.getvalue(), filings)
                expected = incoming.reset_index(drop=True)
                if len(imported) != len(expected) or not imported["Document ID"].eq(chosen).all():
                    raise ValueError("The workbook does not match this approved filing.")
                pd.testing.assert_frame_equal(imported[COLUMNS].reset_index(drop=True),
                                              expected[COLUMNS].reset_index(drop=True),
                                              check_dtype=False, check_exact=False, rtol=0, atol=1e-9)
                manual = read_manual_source_reviews(uploaded.getvalue(), incoming, source_pdf)
                if manual:
                    save_source_audit(chosen, manual)
                    source_checks = source_results(incoming, source_pdf, load_source_audit(chosen))
                imported_plan = read_check_plan_workbook(uploaded.getvalue(), filings, chosen)
                imported_checks = reconciliation_checks(incoming, filings, imported_plan,
                                                        verified_only=not include_pending, automatic=True)
                imported_cells = per_cell_checks(incoming, imported_checks,
                                                 allow_pending=include_pending,
                                                 confirmed_pages=confirmed_pages if include_pending else None,
                                                 source_audit=source_checks)
                if imported_cells["Cell result"].eq("Investigate").any():
                    raise ValueError("The uploaded workbook still has cell-level issues. Review the check plan and source evidence.")
                require_resolved_checks(imported_checks, automatic=True)
                save_approved_check_plan(chosen, imported_plan)
                st.session_state[f"step3_plan_revision_{chosen}"] = revision + 1
                st.success("Excel review imported. The platform independently confirmed every cell and reconciliation rule; the filing is ready to publish.")
                st.rerun()
            except AssertionError:
                st.error("Source cells changed in Excel. Upload those edits in Step 2 and review them again before Step 3.")
            except Exception as exc:
                st.error(str(exc))
else:
    st.info("Send extracted source cells from Step 2 to start automatic checks.")

published = load_published()
st.subheader("Published coverage")
if published.empty:
    st.caption("No values have been published yet.")
else:
    coverage = published.groupby(["Company", "Period end", "Currency", "Scope"]).size().reset_index(name="Verified cells")
    st.dataframe(coverage, hide_index=True, width="stretch")
