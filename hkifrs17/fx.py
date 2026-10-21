"""Auditable USD/HKD year-end rates for peer presentation."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.request import Request, urlopen


SOURCE_URL = "https://www.federalreserve.gov/releases/h10/hist/dat00_hk.htm"
RATES_FILE = Path(__file__).resolve().parents[1] / "config" / "year_end_fx_rates.json"
_fetched: dict[int, tuple[float, str]] = {}
_retry_after: dict[int, datetime] = {}


class _RateTable(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _published_rate(year: int) -> tuple[float, str] | None:
    """Use 31 December, or the last published December observation if it is ND."""
    if date.today() < date(year, 12, 31):
        return None
    if year in _fetched:
        return _fetched[year]
    if datetime.now() < _retry_after.get(year, datetime.min):
        return None
    try:
        request = Request(SOURCE_URL, headers={"User-Agent": "HKIFRS17/1.0"})
        with urlopen(request, timeout=8) as response:
            html = response.read().decode("utf-8", errors="replace")
        table = _RateTable()
        table.feed(html)
        observations = []
        for row in table.rows:
            if len(row) < 2:
                continue
            try:
                day = datetime.strptime(row[0].upper(), "%d-%b-%y").date()
                value = float(row[1])
            except ValueError:
                continue
            if day.year == year and day.month == 12 and day.day <= 31:
                observations.append((day, value))
        if not observations:
            raise ValueError(f"No published December {year} USD/HKD observation")
        day, rate = max(observations)
        _fetched[year] = rate, day.isoformat()
        return _fetched[year]
    except (OSError, ValueError):
        _retry_after[year] = datetime.now() + timedelta(hours=1)
        return None


def year_end_usd_hkd(year: int) -> tuple[float, str, str] | None:
    """Return HKD per USD, observation date, and source; never invent a rate."""
    local = json.loads(RATES_FILE.read_text(encoding="utf-8"))
    entry = local.get(str(year))
    if entry is not None:
        return float(entry["usd_hkd"]), str(entry["date"]), SOURCE_URL
    published = _published_rate(year)
    return (*published, SOURCE_URL) if published is not None else None
