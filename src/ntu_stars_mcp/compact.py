"""Lossless reductions at the MCP boundary; cached/parser data stays unchanged."""

from fractions import Fraction
import re
from typing import Any


def session_fields(session: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in session.items()
            if key not in {"course_code", "index", "shared_by"}
            and not (key in {"raw_day", "raw_time"} and value is None)}


def timetable_fields(result: dict[str, Any]) -> dict[str, Any]:
    """Comparison/search results need timetable provenance, not course descriptions."""
    return {key: result[key] for key in ("course_code", "academic_year", "semester", "retrieved_at", "official_source")}


def graduate_fields(result: dict[str, Any]) -> dict[str, Any]:
    groups = []
    for group in result["class_groups"]:
        parsed = bool(group["sessions"]) and not group["schedule_remarks"] and all(
            session["day"] and session["start_time"] and session["end_time"] for session in group["sessions"]
        )
        groups.append({key: value for key, value in group.items() if key != "schedule_text" or not parsed})
    return {**result, "class_groups": groups}


def exam_fields(result: dict[str, Any]) -> dict[str, Any]:
    def redundant_duration(exam):
        match = re.fullmatch(r"(\d{1,4}(?:\.\d{1,6})?)\s*(hr|hrs|hour|hours|min|mins|minute|minutes)", exam["duration_text"], re.I)
        return match is not None and Fraction(match[1]) * (60 if match[2].lower().startswith("h") else 1) == exam["duration_minutes"]
    return {**result, "exams": [
        {key: value for key, value in exam.items()
         if not (key == "duration_text" and redundant_duration(exam))
         and not (key in {"raw_day", "raw_time"} and value is None)}
        for exam in result["exams"]
    ]}


def table_fields(table: dict[str, Any]) -> dict[str, Any]:
    headers, rows, records = table["headers"], table["rows"], table["records"]
    reconstructible = (
        bool(headers) and all(headers) and len(set(headers)) == len(headers)
        and len(rows) == len(records)
        and all(len(row) == len(headers) and dict(zip(headers, row)) == record for row, record in zip(rows, records))
    )
    return {key: value for key, value in table.items() if key != "rows" or not reconstructible}


def saved_plan_fields(plan: dict[str, Any]) -> dict[str, Any]:
    indexes = {course["course_code"]: course["index"] for course in plan["courses"]}
    return {**plan, "sessions": [
        {key: value for key, value in session.items()
         if not (key == "index" and session["course_code"] in indexes and value == indexes[session["course_code"]])
         and not (key == "raw_time" and value is None)}
        for session in plan["sessions"]
    ]}


def personal_fields(result: dict[str, Any]) -> dict[str, Any]:
    tables = {"planner_tables", "timetable_tables", "requirements", "examination_results", "courses_registered"}
    return {
        key: [table_fields(table) for table in value] if key in tables else
        [saved_plan_fields(plan) for plan in value] if key == "saved_plans" else value
        for key, value in result.items()
    }
