"""Parse prerequisite text and collect referenced courses."""

from __future__ import annotations

from collections import defaultdict, deque
import re
from collections.abc import Callable
from typing import Any

from ..models import Course

_TOKEN_PATTERN = re.compile(
    r"(?P<and>AND\b)|(?P<or>OR\b)|(?P<symbol>[&()])|"
    r"(?P<course>[A-Z0-9]{2,10}(?:\s*\(\s*COREQUISITE\s*\))?)",
    re.IGNORECASE,
)
_COURSE_TOKEN = re.compile(
    r"(?P<code>[A-Z0-9]{2,10})(?:\s*\(\s*(?P<coreq>COREQUISITE)\s*\))?",
    re.IGNORECASE,
)
_MENTIONED_CODE = re.compile(
    r"(?<![A-Z0-9])([A-Z0-9]{2,10})(?![A-Z0-9])", re.IGNORECASE
)


def _tokens(text: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        match = _TOKEN_PATTERN.match(text, position)
        if match is None:
            raise ValueError("Unsupported prerequisite expression")
        position = match.end()
        if match.lastgroup == "and" or match.group("symbol") == "&":
            result.append(("AND", "AND"))
        elif match.lastgroup == "or":
            result.append(("OR", "OR"))
        elif match.group("symbol") in {"(", ")"}:
            result.append((match.group("symbol"), match.group("symbol")))
        else:
            course_match = _COURSE_TOKEN.fullmatch(match.group("course"))
            if course_match is None:
                raise ValueError("Unsupported prerequisite expression")
            code = course_match.group("code").upper()
            if not any(character.isalpha() for character in code) or not any(
                character.isdigit() for character in code
            ):
                raise ValueError("Unsupported prerequisite expression")
            result.append(
                (
                    "COURSE",
                    code + (" (COREQUISITE)" if course_match.group("coreq") else ""),
                )
            )
    return result


def _group(kind: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    flattened: list[dict[str, Any]] = []
    for child in children:
        if child.get("type") == kind:
            flattened.extend(child["children"])
        else:
            flattened.append(child)
    return {"type": kind, "children": flattened}


def _parse_expression(text: str) -> dict[str, Any]:
    tokens = _tokens(text)
    if not tokens:
        raise ValueError("Empty prerequisite expression")
    position = 0

    def parse_primary() -> dict[str, Any]:
        nonlocal position
        if position >= len(tokens):
            raise ValueError("Incomplete prerequisite expression")
        kind, value = tokens[position]
        if kind == "(":
            position += 1
            expression = parse_or()
            if position >= len(tokens) or tokens[position][0] != ")":
                raise ValueError("Unclosed prerequisite expression")
            position += 1
            return expression
        if kind != "COURSE":
            raise ValueError("Expected a course code in prerequisite expression")
        position += 1
        course_match = _COURSE_TOKEN.fullmatch(value)
        assert course_match is not None
        return {
            "type": "course",
            "course_code": course_match.group("code").upper(),
            "relation": "corequisite"
            if course_match.group("coreq")
            else "prerequisite",
        }

    def parse_and() -> dict[str, Any]:
        nonlocal position
        children = [parse_primary()]
        while position < len(tokens) and tokens[position][0] == "AND":
            position += 1
            children.append(parse_primary())
        return children[0] if len(children) == 1 else _group("all_of", children)

    def parse_or() -> dict[str, Any]:
        nonlocal position
        children = [parse_and()]
        while position < len(tokens) and tokens[position][0] == "OR":
            position += 1
            children.append(parse_and())
        return children[0] if len(children) == 1 else _group("any_of", children)

    expression = parse_or()
    if position != len(tokens):
        raise ValueError("Unexpected token in prerequisite expression")
    return expression


def _mentioned_codes(text: str) -> list[str]:
    codes: list[str] = []
    for match in _MENTIONED_CODE.finditer(text):
        code = match.group(1).upper()
        if any(character.isalpha() for character in code) and any(
            character.isdigit() for character in code
        ):
            if code not in codes:
                codes.append(code)
    return codes


def _parse_prerequisite_text(text: str | None) -> dict[str, Any]:
    if not text:
        return {"status": "not_listed", "text": None, "expression": None}
    try:
        expression = _parse_expression(text)
    except ValueError:
        expression = {
            "type": "unparsed",
            "raw_text": text,
            "mentioned_course_codes": _mentioned_codes(text),
        }
        return {"status": "unparsed", "text": text, "expression": expression}
    return {"status": "parsed", "text": text, "expression": expression}


def _expression_references(
    expression: dict[str, Any] | None, *, include_corequisites: bool
) -> list[tuple[str, str, str]]:
    if expression is None:
        return []
    kind = expression["type"]
    if kind == "course":
        relation = expression["relation"]
        if relation == "corequisite" and not include_corequisites:
            return []
        return [(expression["course_code"], relation, "confirmed")]
    if kind == "unparsed":
        return [
            (code, "unknown", "possible")
            for code in expression["mentioned_course_codes"]
        ]
    references: list[tuple[str, str, str]] = []
    for child in expression["children"]:
        references.extend(
            _expression_references(child, include_corequisites=include_corequisites)
        )
    return references


def collect_prerequisite_courses(
    root_course_code: str,
    term_courses: tuple[Course, ...] | list[Course],
    *,
    max_depth: int,
    max_nodes: int,
    include_corequisites: bool,
    fetch_course: Callable[[str], Course | None],
) -> tuple[list[Course], set[str], set[str], bool]:
    """Load off-term course metadata needed to expand the upstream prerequisite branch."""
    if max_depth == 0:
        return [], set(), set(), False

    courses_by_code: dict[str, list[Course]] = defaultdict(list)
    for course in term_courses:
        courses_by_code[course.course_code].append(course)
    additional: list[Course] = []
    unavailable: set[str] = set()
    not_loaded: set[str] = set()
    visited: set[str] = set()
    queue = deque([(root_course_code, 0)])
    truncated = False

    while queue:
        course_code, depth = queue.popleft()
        if course_code in visited:
            continue
        if len(visited) >= max_nodes:
            not_loaded.add(course_code)
            not_loaded.update(code for code, _ in queue)
            truncated = True
            break
        visited.add(course_code)
        course_records = courses_by_code.get(course_code, [])
        if not course_records:
            fetched_course = fetch_course(course_code)
            if fetched_course is None:
                unavailable.add(course_code)
                continue
            course_records = [fetched_course]
            courses_by_code[course_code] = course_records
            additional.append(fetched_course)

        if depth >= max_depth:
            continue
        for course in course_records:
            parsed = _parse_prerequisite_text(course.details.get("prerequisite"))
            references = _expression_references(
                parsed["expression"], include_corequisites=include_corequisites
            )
            for required_code, _, _ in references:
                if required_code not in visited:
                    queue.append((required_code, depth + 1))

    return additional, unavailable, not_loaded, truncated
