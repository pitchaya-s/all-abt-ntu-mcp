The timetable fixtures preserve HTML structures from NTU's public systems.
Course labels, selected course titles, and index identifiers were fictionalized
so the fixture selection does not publish a user's course choices. These are
parser examples, not verified schedules for the fictional course codes.

These public timetable responses were fetched from NTU's official class schedule
on 2026-10-21 for offline parser tests. The endpoint returns Windows-1252 HTML.
The ZZ0001 course-description response was fetched from NTU's official Content
of Courses endpoint on 2026-10-21; it also uses Windows-1252 HTML.
The EE6102 graduate schedule response was fetched from NTU GSLink/PGR on
2026-10-21; public enrolment-count cells were blanked in this test fixture.
The ZZ0001 undergraduate exam response was fetched from NTU's public General
Access exam timetable on 2026-10-21. It uses Windows-1252 HTML and contains
the timetable-change and later seat-assignment notice returned by NTU.

Source: https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE.main_display1
Course content source: https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SUBJ_CONT.main_display1
Graduate schedule source: https://wish.wis.ntu.edu.sg/pls/webexe/pgr$subrs_timetable.examTimetable?bOption=Next&choiceSubj=EE6102
Undergraduate exam source: https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.Get_detail

The personal STARS Planner and Degree Audit HTML fixtures are synthetic,
sanitized examples used only to test the authenticated-page parsers. They do
not contain real student information or represent verified live responses.

personal-planner-calendar-sanitized.html is a fully synthetic calendar using
NTU's observed table structure. Course/index codes, class groups, venues,
meeting times, teaching weeks, and registration status are fictional.
Saved-plan Load form tests use synthetic fields matching the observed form;
they never contain live tokens or student identifiers.

The four search-* fixtures are public Class Schedule search responses fetched
on 2026-10-22 for AY2026 Semester 1: ZZ00 full-time and part-time, DATA
STRUCTURES title keywords, and an unmatched code. Search uses the same schedule
source above; r_search_type is F for full-time or P for part-time.
