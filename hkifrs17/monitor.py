"""Editable insurer-link workbook and conservative public-page monitoring."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import pandas as pd
import requests

from .storage import ROOT


LINK_FILE = ROOT / "config" / "insurer_links.xlsx"
LINK_COLUMNS = ["Insurer", "Peer group", "Report page URL", "Report terms", "Year end", "Active"]
RESULT_COLUMNS = ["Insurer", "Status", "HTTP", "Evidence", "Report link", "Checked at (UTC)"]
DEFAULT_LINKS = [
    ["YF Life", "Life insurer", "https://www.yflife.com/en/about-us/financial-information/", "audited financial statements", "31 December", True],
    ["FWD Life Bermuda", "Life insurer", "https://www.bma.bm/documents-centre/financial-statements", "FWD Life Insurance Company Bermuda", "31 December", True],
    ["CTF Life", "Life insurer", "https://corpweb.ctflife.com.hk/en/support/regulatory-disclosures", "audited financial statement", "30 June", True],
    ["Sun Life Hong Kong", "Life insurer", "https://www.sunlife.com.hk/en/about-us/financials/audited-financial-statements/", "audited financial statements", "31 December", True],
]


def workbook_bytes(frame: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame[LINK_COLUMNS].to_excel(writer, sheet_name="Insurer links", index=False)
    return output.getvalue()


def validate_links(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(LINK_COLUMNS) - {"Peer group"} - set(frame.columns)
    if missing:
        raise ValueError("Missing workbook columns: " + ", ".join(sorted(missing)))
    if "Peer group" not in frame.columns:
        frame = frame.assign(**{"Peer group": "Life insurer"})
    result = frame[LINK_COLUMNS].copy().fillna("")
    for column in LINK_COLUMNS[:-1]:
        result[column] = result[column].astype(str).str.strip()
    result["Active"] = result["Active"].map(lambda x: x if isinstance(x, bool) else str(x).strip().lower() in {"true", "1", "yes", "y"})
    result = result[result["Insurer"].ne("")].reset_index(drop=True)
    result.loc[result["Peer group"].eq(""), "Peer group"] = "Life insurer"
    if result["Insurer"].duplicated().any():
        raise ValueError("Insurer names must be unique in the company list.")
    for url in result["Report page URL"]:
        if url:
            validate_public_url(url)
    return result


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Report links must be public HTTPS URLs.")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("Local network addresses cannot be scanned.")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("Private network addresses cannot be scanned.")
    except ValueError as exc:
        if "cannot be scanned" in str(exc):
            raise


def load_links() -> pd.DataFrame:
    if not LINK_FILE.exists():
        return pd.DataFrame(DEFAULT_LINKS, columns=LINK_COLUMNS)
    return validate_links(pd.read_excel(LINK_FILE, sheet_name="Insurer links"))


def save_links(frame: pd.DataFrame) -> None:
    checked = validate_links(frame)
    LINK_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = LINK_FILE.with_suffix(".tmp.xlsx")
    temporary.write_bytes(workbook_bytes(checked))
    temporary.replace(LINK_FILE)


def _fetch(url: str) -> requests.Response:
    current = url
    for _ in range(4):
        validate_public_url(current)
        host = urlparse(current).hostname
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("The link resolves to a private address.")
        response = requests.get(current, timeout=(5, 10), stream=True, allow_redirects=False,
                                headers={"User-Agent": "Mozilla/5.0 HKIFRS17-Filing-Monitor/1.0"})
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                raise ValueError("Redirect has no destination.")
            current = urljoin(current, location)
            continue
        return response
    raise ValueError("Too many redirects.")


def scan_link(row: dict, year: int) -> dict:
    """Look for period and report wording; a hit always requires human confirmation."""
    result = {"Insurer": row["Insurer"], "Status": "", "HTTP": "", "Evidence": "",
              "Report link": "", "Checked at (UTC)": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
    url = str(row.get("Report page URL", "")).strip()
    if not url:
        result["Status"] = "Link missing"
        return result
    try:
        response = _fetch(url)
        result["HTTP"] = response.status_code
        response.raise_for_status()
        size = 0
        chunks = []
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 3_000_000:
                raise ValueError("Page exceeds the 3 MB scan limit; open it manually.")
            chunks.append(chunk)
        content = b"".join(chunks)
        final_url = response.url
        content_type = response.headers.get("Content-Type", "").lower()
        response.close()
        if "pdf" in content_type or content.startswith(b"%PDF"):
            result["Status"] = "Direct PDF — check period"
            result["Report link"] = final_url
            result["Evidence"] = "PDF link found; inspect the cover and audit opinion."
            return result
        soup = BeautifulSoup(content, "html.parser")
        page_text = soup.get_text(" ", strip=True).lower()
        year_found = str(year) in page_text
        terms = [term.strip().lower() for term in str(row.get("Report terms", "")).split(";") if term.strip()]
        report_found = not terms or any(term in page_text for term in terms)
        links = []
        for anchor in soup.find_all("a", href=True):
            label = (anchor.get_text(" ", strip=True) + " " + anchor["href"]).lower()
            if str(year) in label or any(term in label for term in terms):
                candidate = urljoin(final_url, anchor["href"])
                try:
                    validate_public_url(candidate)
                except ValueError:
                    continue
                links.append((label[:140], candidate))
        if year_found and report_found:
            result["Status"] = "Potential filing — confirm PDF"
            result["Evidence"] = f"{year} and report wording found on page"
        elif year_found:
            result["Status"] = "Year found — inspect manually"
            result["Evidence"] = f"{year} found; report wording not confirmed"
        else:
            result["Status"] = "No static-page match"
            result["Evidence"] = "Dynamic sites may need manual checking"
        if links:
            result["Report link"] = links[0][1]
        return result
    except requests.RequestException:
        result["Status"] = "Site unavailable — open manually"
        result["Evidence"] = "The website could not be reached from this computer."
        return result
    except Exception as exc:
        result["Status"] = "Scan failed — inspect manually"
        result["Evidence"] = str(exc)[:180]
        return result


def scan_links(frame: pd.DataFrame, year: int, max_workers: int = 4) -> pd.DataFrame:
    active = validate_links(frame)
    active = active[active["Active"]]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return pd.DataFrame(list(pool.map(lambda row: scan_link(row, year), active.to_dict("records"))), columns=RESULT_COLUMNS)
