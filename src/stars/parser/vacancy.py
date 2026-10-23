from __future__ import annotations

import re
from typing import Any

from .common import NTUPageError, _Rows


def parse_course_vacancies(html: str, expected_code: str) -> dict[str, Any]:
    """Read NTU's public vacancy snapshot, verifying its term, course, and table."""
    parser = _Rows()
    parser.feed(html)
    text = " ".join(" ".join(parser.text_parts).split())
    term = re.search(r"Check Vacancies,\s*(20\d{2})\s+([12S])\b", text, re.IGNORECASE)
    if term is None or not re.search(rf"\b{re.escape(expected_code)}\b", text, re.IGNORECASE):
        raise NTUPageError("Missing vacancy term or requested course code.")

    headings = ["INDEX NUMBER", "VACANCIES AVAILABLE", "WAITLIST LENGTH", "CLASS TYPE", "GROUP", "DAY", "TIME", "VENUE"]
    header = next((i for i, row in enumerate(parser.rows) if [cell.upper() for cell in row] == headings), None)
    if header is None:
        raise NTUPageError("No recognized vacancy table was found.")

    indexes: dict[str, dict[str, int | None]] = {}
    for row in parser.rows[header + 1:]:
        if not any(row):
            continue
        if len(row) != len(headings):
            raise NTUPageError("Unexpected vacancy table row structure.")
        index, vacancies, waitlist = row[:3]
        if not index:
            if not indexes or vacancies or waitlist:
                raise NTUPageError("Vacancy counts without an index number.")
            continue
        if not re.fullmatch(r"[0-9]{1,12}", index) or index in indexes:
            raise NTUPageError("Invalid or duplicate vacancy index number.")
        counts: list[int | None] = []
        for count in (vacancies, waitlist):
            if count.upper() in {"", "-", "N/A"}:
                counts.append(None)
            elif re.fullmatch(r"[0-9]{1,9}", count):
                counts.append(int(count))
            else:
                raise NTUPageError("Unrecognized vacancy or waitlist count.")
        indexes[index] = {"vacancies_available": counts[0], "waitlist_length": counts[1]}
    if not indexes:
        raise NTUPageError("NTU returned no vacancy index rows.")
    return {
        "academic_year": int(term.group(1)),
        "semester": term.group(2).upper(),
        "indexes": indexes,
    }
