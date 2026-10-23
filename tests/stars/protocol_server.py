"""Offline stdio server for client interoperability tests; never contacts NTU."""

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from mcp_fixtures import COURSE, EXAM_COURSE, GRADUATE_COURSE
from room_fixtures import snapshot as room_snapshot
from shared.server import main
from stars.client import NTURequestError, validate_course_code
from stars.client.validation import _academic_term


def course_fixture(course_code, academic_year, semester):
    code = validate_course_code(course_code)
    year, term, _ = _academic_term(academic_year, semester)
    if (code, year, term) != ("ZZ0001", 2026, "1"):
        raise NTURequestError("Course is unavailable in the offline protocol fixture.")
    return COURSE


if __name__ == "__main__":
    with ExitStack() as stack:
        stack.enter_context(patch("stars.room_tools.get_teaching_snapshot", side_effect=room_snapshot))
        stack.enter_context(patch("stars.mcp_server.fetch_course", side_effect=course_fixture))
        stack.enter_context(patch("stars.client.search._fetch_html", return_value=(
            (Path(__file__).parent / "fixtures" / "search-zz00-2026-1.html").read_text(),
            "https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE_NEW.main_display1",
        )))
        stack.enter_context(patch("stars.mcp_server.fetch_course_vacancies", return_value={
            "status": "term_mismatch", "academic_year": 2026, "semester": "2", "indexes": {},
            "retrieved_at": "2026-10-21T00:00:00+00:00",
        }))
        stack.enter_context(patch("stars.mcp_server.fetch_graduate_course_schedule", return_value=GRADUATE_COURSE))
        stack.enter_context(patch("stars.mcp_server.fetch_undergraduate_exam_schedule", return_value=EXAM_COURSE))
        for target in ("persist_stars_plan", "fetch_stars_planner", "fetch_degree_audit"):
            stack.enter_context(patch(f"stars.mcp_server.{target}", side_effect=NTURequestError("Personal actions are disabled in protocol fixtures.")))
        stack.enter_context(patch("shared.credentials.keyring.get_keyring", side_effect=RuntimeError("Offline test has no keyring")))
        stack.enter_context(patch("stars.client.http.urlopen", side_effect=AssertionError("Offline test attempted HTTP")))
        main()
