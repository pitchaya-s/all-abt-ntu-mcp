from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re

from .common import NTUPageError

_COURSE_CODE = re.compile(r"\b[A-Z]{2,4}\d{4}[A-Z]?\b", re.IGNORECASE)
_HEADER_WORDS = {
    "academic year", "au", "au earned", "au required", "balance au", "course", "course au",
    "course group", "course type", "day", "grade", "index", "index no", "index number",
    "semester", "start time", "time", "venue", "week", "study year", "course code",
    "course title", "index no.", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
}

@dataclass
class _Table:
    order: int
    section: str
    rows: list[list[tuple[str, bool, int, int]]] = field(default_factory=list)
    row: list[tuple[str, bool, int, int]] | None = None
    cell: list[str] | None = None
    cell_is_header: bool = False
    rowspan: int = 1
    colspan: int = 1

class _PersonalPage(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[tuple[int, _Table]] = []
        self.stack: list[_Table] = []
        self.text: list[str] = []
        self.headings: list[str] = []
        self._heading: list[str] | None = None
        self._title: list[str] | None = None
        self.title = ""
        self._ignored = 0
        self._order = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored += 1
            return
        if self._ignored:
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading = []
        elif tag == "title":
            self._title = []
        elif tag == "table":
            section = self.headings[-1] if self.headings else ""
            self.stack.append(_Table(self._order, section))
            self._order += 1
        elif self.stack:
            table = self.stack[-1]
            if tag == "tr":
                self._finish_row(table)
                table.row = []
            elif tag in {"td", "th"}:
                if table.row is None:
                    table.row = []
                table.cell = []
                table.cell_is_header = tag == "th"
                attributes = dict(attrs)
                spans = [attributes.get(name) or "1" for name in ("rowspan", "colspan")]
                if any(not span.isdigit() or not 1 <= int(span) <= 100 for span in spans):
                    raise NTUPageError("NTU's personal table contains an unsupported cell span.")
                table.rowspan, table.colspan = map(int, spans)
            elif tag == "br" and table.cell is not None:
                table.cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
            return
        if self._ignored:
            return
        if tag in {"h1", "h2", "h3", "h4"} and self._heading is not None:
            heading = _clean("".join(self._heading))
            if heading:
                self.headings.append(heading)
            self._heading = None
        elif tag == "title" and self._title is not None:
            self.title = _clean("".join(self._title))
            self._title = None
        elif tag in {"td", "th"} and self.stack:
            table = self.stack[-1]
            if table.cell is not None and table.row is not None:
                table.row.append((_clean("".join(table.cell)), table.cell_is_header, table.rowspan, table.colspan))
            table.cell = None
        elif tag == "tr" and self.stack:
            self._finish_row(self.stack[-1])
        elif tag == "table" and self.stack:
            table = self.stack.pop()
            self._finish_row(table)
            self.tables.append((table.order, table))

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        self.text.append(data)
        if self._heading is not None:
            self._heading.append(data)
        if self._title is not None:
            self._title.append(data)
        if self.stack and self.stack[-1].cell is not None:
            self.stack[-1].cell.append(data)
        if re.fullmatch(r"(?:courses registered|registered courses)(?:\s+\d[\w\s/-]*)?", _clean(data), re.I):
            self.headings.append(_clean(data))
            if self.stack:
                self.stack[-1].section = _clean(data)

    @staticmethod
    def _finish_row(table: _Table) -> None:
        if table.row:
            table.rows.append(table.row)
        table.row = None
        table.cell = None

def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())

def _table_data(table: _Table) -> dict[str, object]:
    expanded: list[list[tuple[str, bool]]] = []
    pending: dict[int, tuple[str, bool, int]] = {}
    for source in table.rows:
        cells = {column: (value, header) for column, (value, header, _) in pending.items()}
        pending = {column: (value, header, count - 1) for column, (value, header, count) in pending.items() if count > 1}
        column = 0
        for value, header, rowspan, colspan in source:
            while column in cells:
                column += 1
            for offset in range(colspan):
                position = column + offset
                if position in cells:
                    raise NTUPageError("NTU's personal table has overlapping cells.")
                cells[position] = (value, header)
                if rowspan > 1:
                    pending[position] = (value, header, rowspan - 1)
            column += colspan
        expanded.append([cells.get(i, ("", False)) for i in range(max(cells, default=-1) + 1)])
    rows = [[value for value, _ in row] for row in expanded]
    heading_row = next((i for i, row in enumerate(expanded) if any(header for _, header in row)), None)
    if heading_row is None:
        heading_row = next(
            (
                i for i, row in enumerate(rows)
                if len({_clean(cell).casefold() for cell in row} & _HEADER_WORDS) >= 2
            ),
            None,
        )
    headers = rows[heading_row] if heading_row is not None else []
    data_rows = rows[heading_row + 1 :] if heading_row is not None else rows
    records: list[dict[str, str]] = []
    for row in data_rows:
        if not any(row):
            continue
        record: dict[str, str] = {}
        for column, value in zip(headers, row):
            key = _clean(column)
            if key:
                record[key] = value
        if record:
            records.append(record)
    return {
        "section": table.section or None,
        "headers": headers,
        "rows": data_rows,
        "records": records,
    }

def _parse(html: str) -> tuple[str, str, list[dict[str, object]]]:
    parser = _PersonalPage()
    parser.feed(html)
    parser.close()
    text = _clean(" ".join(parser.text))
    tables = [_table_data(table) for _, table in sorted(parser.tables)]
    return parser.title, text, tables

def _records_with_course_code(tables: list[dict[str, object]]) -> list[dict[str, str]]:
    courses: list[dict[str, str]] = []
    for table in tables:
        for record in table["records"]:
            values = list(record.values())
            course_value = next(
                (record[key] for key in record if "course" in key.casefold() and "type" not in key.casefold()),
                "",
            )
            match = _COURSE_CODE.search(course_value) or _COURSE_CODE.search(" ".join(values))
            if match:
                courses.append({"course_code": match.group().upper(), **record})
    return courses

def _table_status(tables: list[dict[str, object]]) -> str:
    if not tables:
        return "not_present"
    if any(table["records"] for table in tables):
        return "parsed"
    if any(table["rows"] for table in tables):
        return "unparsed"
    return "empty"

def _course_status(tables: list[dict[str, object]], courses: list[dict[str, str]]) -> str:
    if courses:
        return "parsed"
    status = _table_status(tables)
    return "unparsed" if status == "parsed" else status

def parse_degree_audit_page(html: str) -> dict[str, object]:
    title, text, tables = _parse(html)
    normalized = text.casefold()
    marker_present = any(
        marker in normalized
        for marker in ("degree audit", "au requirements", "examination results", "courses registered")
    )
    if not marker_present:
        raise NTUPageError("NTU's Degree Audit response was not recognizable; refusing to return an empty result.")

    requirements: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    registered: list[dict[str, object]] = []
    for table in tables:
        headers = " ".join(str(value) for value in table["headers"]).casefold()
        section = str(table["section"] or "").casefold()
        if "course type" in headers and ("au required" in headers or "balance au" in headers or "au requirements" in section):
            requirements.append(table)
        elif "course" in headers and "grade" in headers:
            results.append(table)
        elif "course" in headers and ("index no" in headers or "index number" in headers):
            registered.append(table)

    if not requirements and not results and not registered:
        raise NTUPageError("NTU's Degree Audit page was recognized, but its academic tables changed or were missing.")
    return {
        "service": "degree_audit",
        "page_title": title or None,
        "requirements": requirements,
        "requirements_status": _table_status(requirements),
        "examination_results": results,
        "examination_results_status": _table_status(results),
        "courses_registered": registered,
        "courses_registered_status": _table_status(registered),
    }
