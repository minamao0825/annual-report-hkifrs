"""PDF page preview and opt-in model-assisted draft extraction."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import fitz
import pandas as pd
import requests
from pypdf import PdfReader

from .catalog import METRICS, METRIC_BY_CODE
from .data import COLUMNS, as_number, normalize_records


ALIASES = {
    "Insurance revenue": "INS_REVENUE",
    "Insurance service expenses": "INS_EXPENSE",
    "Net expenses from reinsurance contracts held": "REINS_RESULT",
    "Net income/(expenses) from reinsurance contracts": "REINS_RESULT",
    "Net (expenses)/income from reinsurance contracts held": "REINS_RESULT",
    "Reinsurance contracts held net expenses": "REINS_RESULT",
    "Insurance service result": "INS_SERVICE_RESULT",
    "Net insurance service result": "INS_SERVICE_RESULT",
    "Investment return": "INV_RETURN",
    "Net investment income": "NET_INV_INCOME",
    "Profit before tax": "PBT",
    "Profit before income tax": "PBT",
    "Profit before taxation": "PBT",
    "Profit for the year": "PROFIT",
    "Total assets": "TOTAL_ASSETS",
    "Total liabilities": "TOTAL_LIABS",
    "Total equity": "EQUITY",
    "Net assets": "EQUITY",
    "Insurance contract liabilities": "INS_LIABS",
    "Reinsurance contract assets": "REINS_ASSETS",
    "Reinsurance contract held assets": "REINS_ASSETS",
    "Net cash from operating activities": "OPERATING_CF",
    "Net cash generated from operating activities": "OPERATING_CF",
    "CSM recognised for services provided": "REV_CSM_SERVICE",
    "Change in risk adjustment for non-financial risk for risk expired": "REV_RA_RELEASE",
    "Expected incurred claims and other insurance service expenses": "REV_EXPECTED_CLAIMS",
    "Recovery of insurance acquisition cash flows": "REV_ACQ_RECOVERY",
    "Contracts measured under the PAA": "REV_PAA_TOTAL",
    "Total insurance revenue": "INS_REVENUE_NOTE_TOTAL",
}
NUMBER = re.compile(r"(?<![A-Za-z])\(?-?\d[\d,]*\)?(?![A-Za-z])")


def page_count(path: Path) -> int:
    with fitz.open(path) as document:
        return len(document)


def page_text(path: Path, page_number: int) -> str:
    with fitz.open(path) as document:
        if page_number < 1 or page_number > len(document):
            raise ValueError("PDF page is outside the document.")
        return document[page_number - 1].get_text("text")


def page_png(path: Path, page_number: int, scale: float = 1.45, *, rotate: int = 0) -> bytes:
    with fitz.open(path) as document:
        if page_number < 1 or page_number > len(document):
            raise ValueError("PDF page is outside the document.")
        if rotate not in (0, 90, 180, 270):
            raise ValueError("Page rotation must be 0, 90, 180 or 270 degrees.")
        pix = document[page_number - 1].get_pixmap(
            matrix=fitz.Matrix(scale, scale).prerotate(rotate), alpha=False,
        )
        return pix.tobytes("png")


def text_page_candidates(path: Path) -> dict[str, list[int]]:
    terms = {
        "Profit or loss": ("statement of profit or loss", "statement of comprehensive income"),
        "Financial position": ("statement of financial position",),
        "Cash flows": ("statement of cash flows", "cash flow statement"),
        "Contract balances": ("insurance and reinsurance contract balances",),
        "Insurance revenue note": ("csm recognised for services provided", "expected incurred claims and other insurance service expenses"),
        "Contract note movement": ("net opening balance", "net closing balance"),
        "Measurement components": ("analysis by measurement component",),
    }
    found = {key: [] for key in terms}
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").lower()
            if len(text) < 100:
                continue
            for key, phrases in terms.items():
                if any(phrase in text for phrase in phrases):
                    found[key].append(index)
    return {key: pages[:12] for key, pages in found.items()}


def _row(filing: dict, code: str, period: str, value: object, page: int, label: str,
         source_unit: str | None = None) -> dict:
    return {
        "Document ID": filing["document_id"], "Company ID": filing["company_id"],
        "Company": filing["company"], "Legal entity": filing["legal_entity"],
        "Scope": filing["scope"], "Period end": period, "Metric code": code,
        "Metric": "", "Section": "", "Original value": value,
        "Source unit": source_unit or ("percent" if code.startswith("DISCOUNT_") or code == "RA_CONFIDENCE_PCT"
                                         else filing["source_unit"]), "Currency": filing["currency"],
        "Value (millions)": None, "Value status": "Reported", "PDF page": page,
        "Source label": label, "Audit status": "Unaudited comparative" if filing["company_id"] == "SUN" and period[:4] == "2024" else "Check source",
        "Review status": "Pending", "Reviewer note": "Automatically extracted draft; verify against the PDF.",
    }


def extract_text_page(path: Path, filing: dict, page_number: int, filings: list[dict],
                      metric_codes: set[str] | None = None) -> pd.DataFrame:
    """Conservative two-column text parser. Scanned pages return an empty draft."""
    # pypdf commonly preserves financial table rows on one line where the PDF
    # display layer returned by PyMuPDF splits labels and numbers into lines.
    text = PdfReader(str(path)).pages[page_number - 1].extract_text() or ""
    period = filing["period_end"]
    previous = period.replace(period[:4], str(int(period[:4]) - 1), 1)
    rows = []
    matched = set()
    lines = text.splitlines()
    for line in lines:
        clean = " ".join(line.split())
        for alias, code in sorted(ALIASES.items(), key=lambda item: -len(item[0])):
            if code in matched or (metric_codes is not None and code not in metric_codes) or not clean.lower().startswith(alias.lower()):
                continue
            numbers = NUMBER.findall(clean[len(alias):])
            if len(numbers) < 2:
                continue
            current, comparative = (as_number(item) for item in numbers[-2:])
            if current is None or comparative is None:
                continue
            rows.extend((_row(filing, code, period, current, page_number, alias),
                         _row(filing, code, previous, comparative, page_number, alias)))
            matched.add(code)
            break
    # Some two-year notes print the non-PAA subtotal as an unlabelled numeric
    # row immediately after its four named revenue components. Keep the source
    # position explicit; never derive the subtotal by adding those components.
    if metric_codes and "REV_NONPAA_TOTAL" in metric_codes and "REV_NONPAA_TOTAL" not in matched:
        if "Contracts not measured under the PAA" in text and "Total insurance revenue" in text:
            for index, line in enumerate(lines[:-1]):
                if not line.strip().startswith("Recovery of insurance acquisition cash flows"):
                    continue
                following = " ".join(lines[index + 1].split())
                numbers = NUMBER.findall(following)
                if len(numbers) == 2 and following.replace(numbers[0], "", 1).replace(numbers[1], "", 1).strip() == "":
                    current, comparative = (as_number(value) for value in numbers)
                    if current is not None and comparative is not None:
                        label = "Unlabelled non-PAA revenue subtotal after acquisition recovery"
                        rows.extend((_row(filing, "REV_NONPAA_TOTAL", period, current, page_number, label),
                                     _row(filing, "REV_NONPAA_TOTAL", previous, comparative, page_number, label)))
                break
    return normalize_records(pd.DataFrame(rows, columns=COLUMNS), filings) if rows else pd.DataFrame(columns=COLUMNS)


def _chat_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


def _moonshot_kimi_k26(base_url: str, model: str) -> bool:
    host = urlparse(_chat_url(base_url)).hostname
    return host in {"api.moonshot.cn", "api.moonshot.ai"} and model.strip().lower() == "kimi-k2.6"


def extract_model_page(path: Path, filing: dict, page_number: int, filings: list[dict],
                       *, base_url: str, model: str, api_key: str,
                       fast_kimi: bool = True, read_timeout: int = 300,
                       metric_codes: set[str] | None = None,
                       table_names: list[str] | None = None) -> pd.DataFrame:
    """Send one selected page to an OpenAI-compatible vision model, with no key persistence."""
    if not all((base_url.strip(), model.strip(), api_key.strip())):
        raise ValueError("Base URL, model and API key are required for vision extraction.")
    if not 30 <= read_timeout <= 600:
        raise ValueError("Model response timeout must be between 30 and 600 seconds.")
    rotation = int(filing.get("page_rotation_hints", {}).get(page_number, 0))
    image = base64.b64encode(page_png(path, page_number, scale=1.6, rotate=rotation)).decode("ascii")
    selected_metrics = [metric for metric in METRICS if metric_codes is None or metric.code in metric_codes]
    if not selected_metrics:
        raise ValueError("Select at least one supported metric for this table.")
    metric_text = "\n".join(f"{metric.code}: {metric.label}" for metric in selected_metrics)
    example = selected_metrics[0]
    example_unit = "percent" if example.kind == "rate" else filing["source_unit"]
    table_scope = ", ".join(table_names) if table_names else "the selected financial statement table"
    prompt = f"""Extract quantitative cells only from this insurer financial statement PDF page.
Company: {filing['legal_entity']}. Reporting scope: {filing['scope']}. Current period end: {filing['period_end']}.
Extract ONLY the {filing['period_end'][:4]} reporting year. Ignore all comparative-year columns and comparative-only pages. Source unit hint: {filing['source_unit']}.
Target table(s): {table_scope}. Ignore other tables on this page.
Use only metric codes below. Return JSON only: {{"records":[{{"metric_code":"{example.code}","period_end":"{filing['period_end']}","original_value":123,"source_unit":"{example_unit}","source_label":"{example.label}"}}]}}. In source_label include the exact row label plus the column heading and note cohort/method when the page has multiple columns.
Preserve original amounts and parentheses signs. Return period_end exactly "{filing['period_end']}" for every extracted cell.
Use only the {filing['scope']} statement or note population. Do not combine a Company statement with a Consolidated statement.
An opening balance dated at the end of the prior year may be used only when it is explicitly the opening balance of the {filing['period_end'][:4]} movement table; do not extract prior-year movements or closing balances as current-year results.
For *_MOVEMENT or CSM_NET_MOVEMENT, return a value only if the same note explicitly discloses a signed net movement total. Never calculate it from opening and closing or sum selected rows.
For note-cohort fields, select one named contract population and method column consistently (for example non-PAA or PAA); use the displayed Total column only when its scope matches the metric label. Do not sum different methods, years, assets and liabilities, or company and group columns to create a missing figure.
For REV_* fields, use only the insurance revenue analysis, not similarly named CSM or risk-adjustment figures elsewhere in the contract reconciliation. For *_NOTE_PL_OCI and *_NOTE_CASHFLOWS use explicitly disclosed total movement rows.
For INV_RETURN, INS_FINANCE_PL, REINS_FINANCE_PL and NET_INV_RESULT use only amounts recognised in profit or loss. The corresponding *_TOTAL codes explicitly include OCI from the investment-result note; never put a PL-only figure in a total code or vice versa.
For a method-specific metric, match the exact insurance/reinsurance and PAA/non-PAA heading. For movement and measurement reconciliations use the printed Total or CSM Subtotal column named by the metric; do not substitute another column. Keep opening/closing assets, liabilities and net balances distinct.
For initially recognised contracts distinguish profitable, onerous and reinsurance-held columns. A disclosed initial amount included in contract balances is not automatically a new-business loss component.
For the expenses note, keep its raw expense categories distinct from insurance-service expense reconciliation categories. EXP_NOTE_TOTAL is the final recognised Total after acquisition-cash-flow attribution and amortisation where those rows exist, not a pre-allocation gross subtotal or a depreciation-only subtotal. For investment assets, use an explicit asset-class Total column; do not add subcategories or mix investment populations.
For DISCOUNT_*, RA_CONFIDENCE_PCT and INV_YIELD, source_unit must be "percent" and original_value is the printed percentage number (for example 3.44, not 0.0344). INV_YIELD requires an explicit investment-yield percentage; never calculate it from investment return and assets. Match currency, tenor, risk-free versus illiquidity-adjusted column and year exactly where relevant.
Do not map a net insurance/reinsurance balance to a gross asset or liability metric. Leave unmatched note cells blank for reviewer assessment.
RA_CONFIDENCE_PCT may be taken from an explicit numerical percentile in the risk-adjustment disclosure prose; other prose is not a quantitative source.
Never infer a zero from a dash. Do not extract note numbers, page numbers or invented values.
If a heading/unit is ambiguous, omit the cell. Allowed metrics:\n{metric_text}"""
    request_body = {"model": model, "messages": [
            {"role": "system", "content": "You transcribe financial statement tables. Return JSON only; never invent data."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image}},
            ]},
        ], "max_tokens": 5000}
    if fast_kimi and _moonshot_kimi_k26(base_url, model):
        request_body["thinking"] = {"type": "disabled"}
    try:
        response = requests.post(
            _chat_url(base_url),
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            json=request_body,
            timeout=(10, read_timeout),
        )
    except requests.exceptions.ReadTimeout as exc:
        raise TimeoutError(
            f"The model did not return a response within {read_timeout} seconds. "
            "The existing draft was not changed. Try Kimi fast response mode or a longer timeout, then retry manually."
        ) from exc
    except requests.exceptions.ConnectTimeout as exc:
        raise TimeoutError("Could not connect to the model service within 10 seconds. The existing draft was not changed.") from exc
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    text = re.sub(r"^\s*```(?:json)?|\s*```\s*$", "", str(content), flags=re.I).strip()
    if not text.startswith("{"):
        text = text[text.find("{"):text.rfind("}") + 1]
    parsed = json.loads(text)
    if not isinstance(parsed.get("records"), list):
        raise ValueError("Model response does not contain a records list.")
    allowed = {metric.code for metric in selected_metrics}
    rows = []
    for item in parsed["records"]:
        if not isinstance(item, dict) or item.get("metric_code") not in allowed:
            continue
        period = str(item.get("period_end", ""))
        if period != filing["period_end"]:
            continue
        value = as_number(item.get("original_value"))
        if value is None:
            continue
        source_unit = "percent" if METRIC_BY_CODE[item["metric_code"]].kind == "rate" else (
            str(item["source_unit"]) if item.get("source_unit") else None
        )
        rows.append(_row(filing, item["metric_code"], period, value, page_number,
                         str(item.get("source_label", "")).strip(), source_unit))
    return normalize_records(pd.DataFrame(rows, columns=COLUMNS), filings) if rows else pd.DataFrame(columns=COLUMNS)
