"""Offline stdio server for client interoperability tests; never contacts NTU."""

from contextlib import ExitStack
from unittest.mock import patch

from mcp_fixtures import COURSE, EXAM_COURSE, GRADUATE_COURSE
from ntu_stars_mcp.mcp_server import main
from ntu_stars_mcp.ntu_client import NTURequestError, validate_course_code
from ntu_stars_mcp.ntu_client.validation import _academic_term


def course_fixture(course_code, academic_year, semester):
    code = validate_course_code(course_code)
    year, term, _ = _academic_term(academic_year, semester)
    if (code, year, term) != ("SC2001", 2026, "1"):
        raise NTURequestError("Course is unavailable in the offline protocol fixture.")
    return COURSE


if __name__ == "__main__":
    with ExitStack() as stack:
        stack.enter_context(patch("ntu_stars_mcp.mcp_server.fetch_course", side_effect=course_fixture))
        stack.enter_context(patch("ntu_stars_mcp.mcp_server.fetch_course_vacancies", return_value={
            "status": "term_mismatch", "academic_year": 2026, "semester": "2", "indexes": {},
            "retrieved_at": "2026-10-21T00:00:00+00:00",
        }))
        stack.enter_context(patch("ntu_stars_mcp.mcp_server.fetch_graduate_course_schedule", return_value=GRADUATE_COURSE))
        stack.enter_context(patch("ntu_stars_mcp.mcp_server.fetch_undergraduate_exam_schedule", return_value=EXAM_COURSE))
        for target in ("persist_stars_plan", "fetch_stars_planner", "fetch_degree_audit"):
            stack.enter_context(patch(f"ntu_stars_mcp.mcp_server.{target}", side_effect=NTURequestError("Personal actions are disabled in protocol fixtures.")))
        stack.enter_context(patch("ntu_stars_mcp.ntu_client.http.urlopen", side_effect=AssertionError("Offline test attempted HTTP")))
        main()
