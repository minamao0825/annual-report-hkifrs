"""English HK IFRS 17 annual-report processing platform."""

from __future__ import annotations

from urllib.parse import urlsplit
import streamlit as st

from hkifrs17.report_ui import inject_styles


st.set_page_config(
    page_title="HK IFRS 17 | Annual report platform",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)
pages = [
    st.Page("app_pages/00_library.py", title="Step 0 · Filing monitor", icon=":material/travel_explore:", url_path="filings"),
    st.Page("app_pages/01_extract.py", title="Step 1 · Locate & extract", icon=":material/document_scanner:", url_path="extract"),
    st.Page("app_pages/02_review.py", title="Step 2 · Review", icon=":material/fact_check:", url_path="review"),
    st.Page("app_pages/03_publish.py", title="Step 3 · Publish", icon=":material/publish:", url_path="publish"),
    st.Page("app_pages/04_integrate.py", title="Step 4 · Integrate", icon=":material/merge_type:", url_path="integrate"),
    st.Page("app_pages/05_insurer.py", title="Step 5 · Insurer explorer", icon=":material/analytics:", url_path="insurer"),
    st.Page("app_pages/06_peers.py", title="Step 6 · Peer comparison", icon=":material/bar_chart:", url_path="peers"),
]
navigation = st.navigation(pages, position="hidden")
current_path = urlsplit(str(st.context.url or "")).path.strip("/")
active_href = current_path if any(page.url_path == current_path for page in pages[1:]) else ""
inject_styles()
active_selector = f'.st-key-step_tabs a[data-testid="stPageLink-NavLink"][href="{active_href}"]'
st.html(
    f'<style>{active_selector} {{ color:var(--screen-red)!important; '
    'border-bottom-color:var(--screen-red)!important; }'
    f'{active_selector} p {{ color:var(--screen-red)!important; }}</style>'
)
with st.container(key="app_header"):
    st.markdown("# HK IFRS 17 Annual Report Processing & Analysis Platform")
    st.caption("Annual financial statements  |  Cross-insurer and year-on-year comparison")
with st.container(key="step_tabs", horizontal=True, gap="small"):
    for page in pages:
        # Native page links keep the same Streamlit session when changing steps.
        st.page_link(page, label=page.title, width="content")
navigation.run()
