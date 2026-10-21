"""Step 0: public-report monitoring, Excel watchlist, and PDF intake."""

from __future__ import annotations

from datetime import date
import hashlib
from io import BytesIO

import pandas as pd
import streamlit as st

from hkifrs17.data import UNIT_FACTORS
from hkifrs17.monitor import load_links, save_links, scan_link, scan_links, validate_links, workbook_bytes
from hkifrs17.pdf import page_count, page_text
from hkifrs17.storage import all_filings, pdf_path, register_upload


def scan_excel(frame: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Scan results", index=False)
    return output.getvalue()


st.title("Annual financial statement monitoring")
if "insurer_links" not in st.session_state:
    st.session_state["insurer_links"] = load_links()
else:
    st.session_state["insurer_links"] = validate_links(st.session_state["insurer_links"])
links = st.session_state["insurer_links"]
active_links = links[links["Active"]].copy()

year_col, period_col = st.columns(2)
with year_col:
    scan_year = st.number_input("Reporting year", min_value=2020, max_value=2050, value=2025, step=1)
with period_col:
    st.selectbox("Reporting period", ["Annual"], disabled=True)
peer_groups = sorted(active_links["Peer group"].dropna().unique().tolist())
selected_groups = st.multiselect(
    "Peer groups", peer_groups, default=peer_groups,
    help="Filter the company table and batch scan by the classifications in the Excel company list.",
)
filtered_links = active_links[active_links["Peer group"].isin(selected_groups)].reset_index(drop=True)
st.caption(f"{len(active_links)} active insurers in the company list · {len(filtered_links)} currently selected. Links are maintained in the Excel company list below.")
st.dataframe(
    filtered_links[["Insurer", "Peer group", "Report page URL"]],
    width="stretch", hide_index=True,
    column_config={"Report page URL": st.column_config.LinkColumn("Report page", display_text="Open page")},
)

st.subheader("Check one insurer")
if filtered_links.empty:
    st.warning("Select at least one insurer to check.")
else:
    selected_company = st.selectbox("Select an insurer", filtered_links["Insurer"].tolist())
    selected_row = filtered_links.loc[filtered_links["Insurer"].eq(selected_company)].iloc[0]
    open_col, check_col = st.columns(2)
    with open_col:
        if selected_row["Report page URL"]:
            st.link_button("Open this insurer's report page", selected_row["Report page URL"], width="stretch")
        else:
            st.button("Report page link missing", disabled=True, width="stretch")
    with check_col:
        if st.button("Check this insurer for updates", type="primary", width="stretch"):
            with st.spinner(f"Checking {selected_company}..."):
                st.session_state["single_scan_result"] = scan_link(selected_row.to_dict(), int(scan_year))
    if "single_scan_result" in st.session_state:
        single_result = st.session_state["single_scan_result"]
        st.info(f"{single_result['Insurer']}: {single_result['Status']}")
        st.dataframe(pd.DataFrame([single_result]), width="stretch", hide_index=True,
                     column_config={"Report link": st.column_config.LinkColumn("Potential report")})

st.subheader("Check all selected insurers")
with st.expander("Batch scan settings"):
    worker_count = st.slider("Concurrent websites", min_value=1, max_value=8, value=4,
                             help="More concurrent requests can be faster, but a report website may restrict automated access.")
if st.button(f"Check all {len(filtered_links)} selected insurers", width="stretch", disabled=filtered_links.empty):
    with st.spinner("Checking public report pages..."):
        st.session_state["filing_scan_results"] = scan_links(filtered_links, int(scan_year), max_workers=worker_count)
if "filing_scan_results" in st.session_state:
    results = st.session_state["filing_scan_results"]
    st.dataframe(results, width="stretch", hide_index=True,
                 column_config={"Report link": st.column_config.LinkColumn("Potential report")})
    st.download_button("Download scan results Excel", scan_excel(results),
                       file_name=f"HK_IFRS17_scan_{scan_year}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption("A scan match is a lead for manual PDF confirmation; dynamic pages and access blocks still require manual checking.")

with st.expander("Maintain insurer list and report-page links (Excel)"):
    st.caption("Edit links here and save them to the Excel source file, or download, edit and import the workbook.")
    links_editor = st.data_editor(
        links, width="stretch", hide_index=True, num_rows="dynamic",
        column_config={
            "Insurer": st.column_config.TextColumn(required=True, width="medium"),
            "Peer group": st.column_config.TextColumn(help="Used for the Step 0 category filter."),
            "Report page URL": st.column_config.TextColumn(width="large"),
            "Report terms": st.column_config.TextColumn(help="Separate alternative phrases with semicolons."),
            "Year end": st.column_config.TextColumn(),
            "Active": st.column_config.CheckboxColumn(),
        }, key=f"insurer_links_editor_{st.session_state.get('company_list_revision', 0)}",
    )
    try:
        downloadable_links = validate_links(links_editor)
        list_error = None
    except ValueError as exc:
        downloadable_links = None
        list_error = str(exc)
        st.warning(f"Correct the company list before saving: {exc}")
    with st.container(horizontal=True):
        if st.button("Save company list", icon=":material/save:"):
            try:
                checked = validate_links(links_editor)
                save_links(checked)
                st.session_state["insurer_links"] = checked
                st.session_state["company_list_revision"] = st.session_state.get("company_list_revision", 0) + 1
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        st.download_button("Download company list Excel", workbook_bytes(downloadable_links) if downloadable_links is not None else b"",
                           file_name="HK_IFRS17_insurer_links.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           disabled=list_error is not None)
    uploaded_list = st.file_uploader("Import edited company list Excel", type="xlsx", key="company_list_upload")
    if st.button("Apply uploaded company list", disabled=uploaded_list is None):
        try:
            imported = validate_links(pd.read_excel(BytesIO(uploaded_list.getvalue()), sheet_name="Insurer links"))
            save_links(imported)
            st.session_state["insurer_links"] = imported
            st.session_state["company_list_revision"] = st.session_state.get("company_list_revision", 0) + 1
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

st.divider()
st.subheader("Local filing library")
filings = all_filings()
rows = []
for item in filings:
    path = pdf_path(item)
    rows.append({"Filing": item["document_id"], "Insurer": item["company"],
                 "Legal entity": item["legal_entity"], "Scope": item["scope"],
                 "Period end": item["period_end"], "Source unit": item["source_unit"],
                 "PDF available": path.exists()})
st.dataframe(pd.DataFrame(rows), hide_index=True)
selected_id = st.selectbox("Inspect a filing", [item["document_id"] for item in filings],
                           format_func=lambda value: next(item["company"] + " · " + item["period_end"] for item in filings if item["document_id"] == value))
selected = next(item for item in filings if item["document_id"] == selected_id)
path = pdf_path(selected)
with st.container(border=True):
    st.subheader(selected["legal_entity"])
    st.write(selected["note"])
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        first_page_text = page_text(path, selected.get("page_profit") or 1)
        st.caption(f"{page_count(path)} PDF pages · SHA-256 prefix {digest} · "
                   + ("Text layer detected on the profit page" if len(first_page_text.strip()) > 100 else "Profit page is image based"))
    else:
        st.warning("The pilot PDF is missing. Copy it into disclosures/pilot or upload a new filing.")
with st.expander("Add a filing", icon=":material/upload_file:"):
    with st.form("upload_filing", clear_on_submit=False):
        pdf = st.file_uploader("Financial statement PDF", type="pdf")
        company = st.text_input("Insurer name")
        legal_entity = st.text_input("Legal entity on the report cover")
        first, second = st.columns(2)
        with first:
            period_end = st.date_input("Fiscal year end", value=date(2025, 12, 31))
            scope = st.selectbox("Reporting scope", ["Company", "Consolidated"])
        with second:
            currency = st.selectbox("Source currency", ["HKD", "USD"])
            options = [unit for unit, (unit_currency, _) in UNIT_FACTORS.items() if unit_currency == currency]
            source_unit = st.selectbox("Source statement unit", options)
        submitted = st.form_submit_button("Register PDF", type="primary")
    if submitted:
        try:
            if pdf is None or not company.strip() or not legal_entity.strip():
                raise ValueError("Choose a PDF and enter both the insurer and legal entity names.")
            item = register_upload(pdf.getvalue(), filename=pdf.name, company=company,
                                   legal_entity=legal_entity, scope=scope,
                                   period_end=period_end.isoformat(), currency=currency,
                                   source_unit=source_unit)
            st.success(f"Registered {item['document_id']}. Locate pages in Step 1.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
