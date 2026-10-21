from pathlib import Path

from ntu_stars_mcp.parser import parse_course_description, parse_course_page, parse_graduate_course_page
from ntu_stars_mcp.parser.exam import parse_undergraduate_exam_schedule


FIXTURE = Path(__file__).parent / "fixtures" / "sc2001-2026-1.html"
HTML = FIXTURE.read_bytes().decode("windows-1252")
COURSE = parse_course_page(HTML, "SC2001").with_request_metadata(
    academic_year=2026,
    semester="1",
    retrieved_at="2026-10-21T00:00:00+00:00",
    source_url="https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE_NEW.main_display1",
).with_course_description(
    description=parse_course_description(
        (Path(__file__).parent / "fixtures" / "sc2001-content-2026-1.html").read_bytes().decode("windows-1252"),
        "SC2001",
    ),
    status="available",
    source_url="https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SUBJ_CONT.main_display1",
)
GRADUATE_HTML = (Path(__file__).parent / "fixtures" / "ee6102-graduate-2026-1.html").read_bytes().decode("windows-1252")
GRADUATE_COURSE = {
    **parse_graduate_course_page(GRADUATE_HTML, "EE6102"),
    "source_url": "https://wish.wis.ntu.edu.sg/pls/webexe/pgr$subrs_timetable.examTimetable?bOption=Next&choiceSubj=EE6102",
}
EXAM_COURSE = {**parse_undergraduate_exam_schedule(
    (Path(__file__).parent / "fixtures" / "undergrad-exam-sc2001-2026-1.html").read_bytes().decode("windows-1252"),
    "SC2001",
), "source_url": "https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.Get_detail",
    "retrieved_at": "2026-10-21T00:00:00+00:00"}
