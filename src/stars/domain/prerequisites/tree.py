"""Build bounded prerequisite and dependent-course trees."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..models import Course
from .expressions import (
    _expression_references,
    _mentioned_codes,
    _parse_prerequisite_text,
)


def _annotate_expression(
    expression: dict[str, Any] | None,
    completed: set[str] | None,
) -> tuple[dict[str, Any] | None, bool | None]:
    if expression is None:
        return None, None
    kind = expression["type"]
    if kind == "course":
        annotated = dict(expression)
        if completed is None:
            annotated["satisfaction"] = "not_evaluated"
            return annotated, None
        code = expression["course_code"]
        if code in completed:
            annotated["satisfaction"] = "satisfied"
            return annotated, True
        if expression["relation"] == "corequisite":
            annotated["satisfaction"] = "can_be_taken_concurrently"
            return annotated, True
        annotated["satisfaction"] = "not_satisfied"
        return annotated, False
    if kind == "unparsed":
        annotated = dict(expression)
        annotated["satisfaction"] = (
            "unknown" if completed is not None else "not_evaluated"
        )
        return annotated, None

    children: list[dict[str, Any]] = []
    values: list[bool | None] = []
    for child in expression["children"]:
        annotated_child, value = _annotate_expression(child, completed)
        assert annotated_child is not None
        children.append(annotated_child)
        values.append(value)

    annotated = {"type": kind, "children": children}
    if completed is None:
        annotated["satisfaction"] = "not_evaluated"
        return annotated, None
    if kind == "all_of":
        value = (
            False
            if False in values
            else (True if all(item is True for item in values) else None)
        )
    else:
        value = (
            True
            if True in values
            else (False if all(item is False for item in values) else None)
        )
    annotated["satisfaction"] = (
        "satisfied"
        if value is True
        else "not_satisfied"
        if value is False
        else "unknown"
    )
    return annotated, value


def _course_prerequisite_summary(
    raw_texts: list[str | None],
    completed: set[str] | None,
) -> dict[str, Any]:
    if len(raw_texts) > 1:
        conflicting_expression = {
            "type": "conflicting_records",
            "raw_texts": raw_texts,
            "mentioned_course_codes": sorted(
                {code for text in raw_texts if text for code in _mentioned_codes(text)}
            ),
            "satisfaction": "unknown" if completed is not None else "not_evaluated",
        }
        return {
            "status": "conflicting_records",
            "text": None,
            "texts": raw_texts,
            "expression": conflicting_expression,
            "eligibility": "unknown" if completed is not None else "not_evaluated",
        }

    parsed = _parse_prerequisite_text(raw_texts[0] if raw_texts else None)
    expression, value = _annotate_expression(parsed["expression"], completed)
    if parsed["status"] == "not_listed":
        eligibility = "not_listed"
    elif completed is None:
        eligibility = "not_evaluated"
    elif value is True:
        eligibility = "eligible"
    elif value is False:
        eligibility = "not_eligible"
    else:
        eligibility = "unknown"
    return {
        "status": parsed["status"],
        "text": parsed["text"],
        "texts": raw_texts,
        "expression": expression,
        "eligibility": eligibility,
    }


def build_prerequisite_tree(
    course_code: str,
    courses: tuple[Course, ...] | list[Course],
    *,
    prerequisite_courses: tuple[Course, ...] | list[Course] = (),
    unavailable_prerequisite_codes: set[str] | None = None,
    not_loaded_prerequisite_codes: set[str] | None = None,
    academic_year: int,
    semester: str,
    prerequisite_depth: int = 2,
    dependent_depth: int = 2,
    completed_courses: set[str] | None = None,
    include_corequisites: bool = False,
    only_eligible: bool = False,
    max_nodes: int = 100,
    prerequisite_catalog_truncated: bool = False,
    source_url: str,
    retrieved_at: str,
) -> dict[str, Any]:
    """Build bounded prerequisite and dependent-course branches around one course."""
    records: dict[str, dict[str, Any]] = {}

    def add_course(course: Course, *, offered_this_term: bool) -> None:
        record = records.setdefault(
            course.course_code,
            {
                "course_name": course.course_name,
                "au": course.au,
                "raw_texts": [],
                "offered_this_term": offered_this_term,
                "source_url": course.source_url,
                "retrieved_at": course.retrieved_at,
            },
        )
        record["offered_this_term"] = record["offered_this_term"] or offered_this_term
        raw_text = course.details.get("prerequisite")
        if raw_text not in record["raw_texts"]:
            record["raw_texts"].append(raw_text)

    term_course_codes: set[str] = set()
    for course in courses:
        term_course_codes.add(course.course_code)
        add_course(course, offered_this_term=True)
    for course in prerequisite_courses:
        add_course(course, offered_this_term=False)

    unavailable = unavailable_prerequisite_codes or set()
    not_loaded = not_loaded_prerequisite_codes or set()

    def record_references(record: dict[str, Any]) -> list[tuple[str, str, str]]:
        conflict = len(record["raw_texts"]) > 1
        references: dict[tuple[str, str], str] = {}
        for raw_text in record["raw_texts"]:
            parsed = _parse_prerequisite_text(raw_text)
            refs = _expression_references(
                parsed["expression"], include_corequisites=include_corequisites
            )
            if conflict:
                refs = [(code, relation, "possible") for code, relation, _ in refs]
            for required_code, relation, match_status in refs:
                key = (required_code, relation)
                if references.get(key) == "possible" or match_status == "possible":
                    references[key] = "possible"
                else:
                    references[key] = "confirmed"
        return [
            (code, relation, status) for (code, relation), status in references.items()
        ]

    dependents: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for scheduled_course_code in term_course_codes:
        record = records[scheduled_course_code]
        for required_code, relation, match_status in record_references(record):
            current = dependents[required_code].setdefault(
                scheduled_course_code,
                {"match_status": match_status, "relations": set()},
            )
            if current["match_status"] == "possible" or match_status == "possible":
                current["match_status"] = "possible"
            current["relations"].add(relation)

    completed = set(completed_courses) if completed_courses is not None else None
    if completed is not None:
        completed.add(course_code)

    coverage = {
        "scheduled_course_count": len(term_course_codes),
        "off_term_prerequisite_course_count": sum(
            not record["offered_this_term"] for record in records.values()
        ),
        "unparsed_prerequisite_count": 0,
        "conflicting_prerequisite_count": 0,
        "prerequisite_not_listed_count": 0,
    }
    for record in records.values():
        summary = _course_prerequisite_summary(record["raw_texts"], None)
        coverage["unparsed_prerequisite_count"] += summary["status"] == "unparsed"
        coverage["conflicting_prerequisite_count"] += (
            summary["status"] == "conflicting_records"
        )
        coverage["prerequisite_not_listed_count"] += summary["status"] == "not_listed"

    prerequisite_node_count = 1
    dependent_node_count = 1
    prerequisite_truncated = prerequisite_catalog_truncated
    dependent_truncated = False
    included_prerequisites: set[str] = set()
    included_dependents: set[str] = set()

    def make_node(
        course_code: str,
        depth: int,
        match_status: str,
        path_status: str,
        relations: list[str],
    ) -> dict[str, Any]:
        record = records.get(course_code)
        if record is None:
            data_status = "unavailable" if course_code in unavailable else "not_loaded"
            prerequisite: dict[str, Any] = {
                "status": data_status,
                "text": None,
                "texts": [],
                "expression": None,
                "eligibility": "unknown"
                if data_status == "unavailable"
                else "not_evaluated",
            }
            return {
                "course_code": course_code,
                "course_name": None,
                "au": None,
                "offered_this_term": False,
                "course_data_status": data_status,
                "official_source": None,
                "retrieved_at": None,
                "depth": depth,
                "match_status": match_status,
                "path_status": path_status,
                "matched_relations": relations,
                "prerequisite_status": prerequisite["status"],
                "prerequisite_text": prerequisite["text"],
                "prerequisite_texts": prerequisite["texts"],
                "prerequisite_expression": prerequisite["expression"],
                "eligibility_status": prerequisite["eligibility"],
                "prerequisites": [],
                "dependents": [],
            }
        prerequisite = _course_prerequisite_summary(record["raw_texts"], completed)
        return {
            "course_code": course_code,
            "course_name": record["course_name"],
            "au": record["au"],
            "offered_this_term": record["offered_this_term"],
            "course_data_status": "available",
            "official_source": record["source_url"]
            or (source_url if record["offered_this_term"] else None),
            "retrieved_at": record["retrieved_at"] or retrieved_at,
            "depth": depth,
            "match_status": match_status,
            "path_status": path_status,
            "matched_relations": relations,
            "prerequisite_status": prerequisite["status"],
            "prerequisite_text": prerequisite["text"],
            "prerequisite_texts": prerequisite["texts"],
            "prerequisite_expression": prerequisite["expression"],
            "eligibility_status": prerequisite["eligibility"],
            "prerequisites": [],
            "dependents": [],
        }

    root_node = make_node(course_code, 0, "root", "root", [])
    root_node["eligibility_status"] = "not_evaluated"

    def expand_prerequisites(
        parent_code: str, parent_node: dict[str, Any], depth: int, ancestry: set[str]
    ) -> None:
        nonlocal prerequisite_node_count, prerequisite_truncated
        if depth >= prerequisite_depth:
            return
        parent_record = records.get(parent_code)
        if parent_record is None:
            return
        children = record_references(parent_record)
        for course_code, relation, match_status in sorted(children):
            child = make_node(
                course_code,
                depth + 1,
                match_status,
                "possible"
                if parent_node["path_status"] == "possible"
                or match_status == "possible"
                else "confirmed",
                [relation],
            )
            if prerequisite_node_count >= max_nodes:
                parent_node["prerequisites_truncated"] = True
                prerequisite_truncated = True
                break
            prerequisite_node_count += 1
            if course_code in ancestry:
                child["cycle_detected"] = True
            else:
                expand_prerequisites(
                    course_code, child, depth + 1, ancestry | {course_code}
                )
            parent_node["prerequisites"].append(child)
            included_prerequisites.add(course_code)

    def expand_dependents(
        parent_code: str, parent_node: dict[str, Any], depth: int, ancestry: set[str]
    ) -> None:
        nonlocal dependent_node_count, dependent_truncated
        if depth >= dependent_depth:
            return
        children = dependents.get(parent_code, {})
        for course_code in sorted(children):
            edge = children[course_code]
            child = make_node(
                course_code,
                depth + 1,
                edge["match_status"],
                "possible"
                if parent_node["path_status"] == "possible"
                or edge["match_status"] == "possible"
                else "confirmed",
                sorted(edge["relations"]),
            )
            if only_eligible and child["eligibility_status"] != "eligible":
                continue
            if dependent_node_count >= max_nodes:
                parent_node["dependents_truncated"] = True
                dependent_truncated = True
                break
            dependent_node_count += 1
            included_dependents.add(course_code)
            if course_code in ancestry:
                child["cycle_detected"] = True
            else:
                expand_dependents(
                    course_code, child, depth + 1, ancestry | {course_code}
                )
            parent_node["dependents"].append(child)

    expand_prerequisites(course_code, root_node, 0, {course_code})
    expand_dependents(course_code, root_node, 0, {course_code})
    prerequisite_truncated = prerequisite_truncated or bool(not_loaded)
    total_node_count = prerequisite_node_count + dependent_node_count - 1
    source_urls = [source_url]
    for course in prerequisite_courses:
        if course.source_url and course.source_url not in source_urls:
            source_urls.append(course.source_url)
    return {
        "course_code": course_code,
        "academic_year": academic_year,
        "semester": semester,
        "prerequisite_depth": prerequisite_depth,
        "dependent_depth": dependent_depth,
        "include_corequisites": include_corequisites,
        "only_eligible": only_eligible,
        "completed_courses": sorted(completed) if completed is not None else None,
        "prerequisite_course_count": len(included_prerequisites),
        "dependent_course_count": len(included_dependents),
        "tree_node_count": total_node_count,
        "prerequisites_truncated": prerequisite_truncated,
        "dependents_truncated": dependent_truncated,
        "truncated": prerequisite_truncated or dependent_truncated,
        "coverage": coverage,
        "root": root_node,
        "source_urls": source_urls,
        "retrieved_at": retrieved_at,
    }
