These public timetable responses were fetched from NTU's official class schedule
on 2026-10-21 for offline parser tests. The endpoint returns Windows-1252 HTML.
The SC2001 course-description response was fetched from NTU's official Content
of Courses endpoint on 2026-10-21; it also uses Windows-1252 HTML.
The EE6102 graduate schedule response was fetched from NTU GSLink/PGR on
2026-10-21; public enrolment-count cells were blanked in this test fixture.
The SC2001 undergraduate exam response was fetched from NTU's public General
Access exam timetable on 2026-10-21. It uses Windows-1252 HTML and contains
the timetable-change and later seat-assignment notice returned by NTU.
SC2001 and SC2207 are AY2026 Semester 1; MH2802 is AY2026 Semester 1;
SC2001 2025-2 covers a separate academic term.

Source: https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE.main_display1
Course content source: https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SUBJ_CONT.main_display1
Graduate schedule source: https://wish.wis.ntu.edu.sg/pls/webexe/pgr$subrs_timetable.examTimetable?bOption=Next&choiceSubj=EE6102
Undergraduate exam source: https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.Get_detail

The personal STARS Planner and Degree Audit HTML fixtures are synthetic,
sanitized examples used only to test the authenticated-page parsers. They do
not contain real student information or represent verified live responses.

personal-planner-calendar-sanitized.html is a reduced calendar and empty
registration section from a live read-only Planner response on 2026-10-21.
The course/index were replaced with fictional ZZ0001/00001. Account identity,
forms, credentials, session fields, scripts, and event handlers were removed.
Saved-plan Load form tests use synthetic fields matching the observed form;
they never contain live tokens or student identifiers.

The four search-* fixtures are public Class Schedule search responses fetched
on 2026-10-22 for AY2026 Semester 1: SC20 full-time and part-time, DATA
STRUCTURES title keywords, and an unmatched code. Search uses the same schedule
source above; r_search_type is F for full-time or P for part-time.
