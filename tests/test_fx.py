"""Year-specific HKD presentation rates and future-year retrieval."""

from io import BytesIO
from datetime import date as real_date

from hkifrs17 import fx


def test_historical_year_end_rates_are_distinct_and_sourced():
    assert fx.year_end_usd_hkd(2024) == (7.7677, "2024-12-31", fx.SOURCE_URL)
    assert fx.year_end_usd_hkd(2025) == (7.7833, "2025-12-31", fx.SOURCE_URL)


def test_future_year_can_use_published_december_31_rate(monkeypatch):
    class Response(BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *_):
            self.close()

    html = b'<table><tr><td>30-DEC-26</td><td>7.8000</td></tr><tr><td>31-DEC-26</td><td>7.8123</td></tr></table>'
    monkeypatch.setattr(fx, "urlopen", lambda *_args, **_kwargs: Response(html))
    class ClockDate:
        @staticmethod
        def today():
            return real_date(2027, 1, 2)
        def __new__(cls, *args):
            return real_date(*args)
    monkeypatch.setattr(fx, "date", ClockDate)
    fx._fetched.pop(2026, None)
    assert fx.year_end_usd_hkd(2026) == (7.8123, "2026-12-31", fx.SOURCE_URL)
