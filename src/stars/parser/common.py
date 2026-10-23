from __future__ import annotations

from html.parser import HTMLParser

class NTUPageError(ValueError):
    pass

class CourseUnavailable(NTUPageError):
    pass

class _Rows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.text_parts: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored += 1
        elif tag == "tr":
            if self._row is not None:
                self.rows.append(self._row)
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
        elif tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).replace("\xa0", " ").split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.text_parts.append(data)
            if self._cell is not None:
                self._cell.append(data)

class _CourseContentRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[dict[str, str | None], str]]] = []
        self._row: list[tuple[dict[str, str | None], str]] | None = None
        self._cell: tuple[dict[str, str | None], list[str]] | None = None
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored += 1
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = (dict(attrs), [])
        elif tag == "br" and self._cell is not None:
            self._cell[1].append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
        elif tag in {"td", "th"} and self._row is not None and self._cell is not None:
            attrs, parts = self._cell
            text = "\n".join(" ".join(line.split()) for line in "".join(parts).splitlines())
            self._row.append((attrs, text.strip()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if not self._ignored and self._cell is not None:
            self._cell[1].append(data.replace("\xa0", " "))
