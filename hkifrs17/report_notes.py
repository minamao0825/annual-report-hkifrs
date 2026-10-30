"""Shared formatting for company-specific report notes."""

from __future__ import annotations

import re


def combine_year_notes(notes: list[str], companies) -> list[str]:
    """Join matching company notes for several years into one caption."""
    names = sorted(set(companies), key=len, reverse=True)
    output: list[tuple[str, list[str], str] | str] = []
    by_identity: dict[tuple[str, str], list[str]] = {}
    for note in notes:
        company = next((name for name in names if note.startswith(name + " ")), None)
        if company is None:
            output.append(note)
            continue
        match = re.fullmatch(r"(\d{4}YE): (.+)", note[len(company) + 1:])
        if match is None:
            output.append(note)
            continue
        year, body = match.groups()
        identity = (company, body)
        if identity not in by_identity:
            by_identity[identity] = [year]
            output.append((company, by_identity[identity], body))
        elif year not in by_identity[identity]:
            by_identity[identity].append(year)
    result = []
    for entry in output:
        if isinstance(entry, str):
            result.append(entry)
            continue
        company, years, body = entry
        result.append(f"{company} {' and '.join(sorted(years))}: {body}")
    return result


def combine_company_notes(notes: list[str], companies) -> list[str]:
    """Join identical company-prefixed notes without changing their text."""
    names = sorted(set(companies), key=len, reverse=True)
    output: list[tuple[list[str], str] | str] = []
    by_body: dict[str, list[str]] = {}
    for note in notes:
        company = next((name for name in names if note.startswith(name + ": ")), None)
        if company is None:
            output.append(note)
            continue
        body = note[len(company) + 2:]
        if body not in by_body:
            by_body[body] = [company]
            output.append((by_body[body], body))
        elif company not in by_body[body]:
            by_body[body].append(company)
    result = []
    for entry in output:
        if isinstance(entry, str):
            result.append(entry)
            continue
        grouped_names, body = entry
        label = (grouped_names[0] if len(grouped_names) == 1 else
                 ", ".join(grouped_names[:-1]) + " and " + grouped_names[-1])
        result.append(f"{label}: {body}")
    return result
