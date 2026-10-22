# STARS tool guide

These tools run in the shared `all-abt-ntu-mcp` server. See the [main README](../../README.md) for installation and client configuration.

## Inputs and results

Undergraduate schedule tools take a `course_code`, `academic_year`, and `semester`. The year is the first year of the academic year; semester is `1`, `2`, or `"S"` for Special Term. Course codes contain letters and digits, up to 10 characters. Keep index numbers as strings.

Examples below use fictional course codes, indexes, and years. Replace them with the course and published term you want to query.

Times use 24-hour `HH:MM` in Singapore time. Days use `MON` through `SUN`. Teaching-week numbers refer to the requested semester, rather than calendar weeks. Missing information remains unknown; it is not treated as zero or an empty requirement.

Every tool publishes an output schema. Index sessions inherit the course/index identifiers from their enclosing result. Unrecognized schedule values remain in raw fields, and uncertain matches are labeled explicitly.

## Tools

### `stars_search_courses`

Find scheduled undergraduate offerings by partial code or title words.

**Inputs:** `query` of 2–80 characters, `academic_year`, `semester`; optional `study_mode` of `"full_time"` or `"part_time"`, `limit` of 1–100 with default 20, and nonnegative `offset` with default 0. Wildcards are not accepted.

**Returns:** course codes, names, AUs, `total_count`, `has_more`, and source/retrieval metadata. Continue with a larger offset to read another page. Results cover scheduled offerings for that term and study mode, rather than the entire historical catalogue or graduate courses.

```json
{"query":"ZZ00","academic_year":2030,"semester":1,"limit":20}
```

### `stars_get_course_metadata`

**Inputs:** `course_code`, `academic_year`, `semester`.

**Returns:** course name, AU, prerequisites when published, course description, course notes, term, and source metadata. `course_description_status` distinguishes `available`, `not_listed`, and `unavailable`. This tool returns metadata rather than index timetables.

### `stars_get_course_indexes`

**Inputs:** `course_code`, `academic_year`, `semester`.

**Returns:** every index, its complete associated sessions, schedule completeness, vacancies, waitlist length, and vacancy metadata. Shared lectures remain attached to each applicable index. Sessions include lesson type, group, day, times, venue, teaching weeks, and remarks.

### `stars_get_index`

**Inputs:** `course_code`, `index`, `academic_year`, `semester`.

**Returns:** one index's sessions and matching-term vacancy snapshot. Use an index returned by `stars_get_course_indexes`; an unknown index produces an error rather than an empty timetable.

```json
{"course_code":"ZZ0001","index":"00001","academic_year":2030,"semester":1}
```

### `stars_compare_indexes`

**Inputs:** `course_code`, `academic_year`, `semester`, at least two unique `indexes`; optional `against_sessions`.

**Returns:** `common_sessions`, `unique_sessions_by_index`, and an optional `clash_check`. Common sessions apply to every entry in `indexes_compared`. Clash checks distinguish definite overlaps from comparisons with unknown week/day/time information.

```json
{"course_code":"ZZ0001","academic_year":2030,"semester":1,"indexes":["00001","00002"],"against_sessions":[{"day":"TUE","start_time":"14:00","end_time":"16:00","teaching_weeks":[2,4,6]}]}
```

### `stars_find_matching_indexes`

**Inputs:** `course_code`, `academic_year`, `semester`; optional `constraints` and `against_sessions`.

Supported constraints:

| Field | Meaning |
| --- | --- |
| `avoid_days` | Reject sessions on the listed days |
| `earliest_start` | Every session must start at or after this time |
| `latest_end` | Every session must end by this time |
| `avoid_windows` | Reject overlaps with listed day/start/end windows |
| `require_sessions` | Each rule must match a session by lesson type, day, or start-time bounds |
| `teaching_weeks` | Evaluate sessions in the specified weeks, from 1–20 |

Required-session rules accept `lesson_type`, `day`, `starts_at_or_after`, and `starts_at_or_before`. Supply at least one condition per rule. Use lesson types as returned by NTU.

**Returns:** matching indexes with schedules, `status` of `confirmed` or `uncertain`, and reasons for uncertainty. Against-schedule slots accept `day`, `start_time`, `end_time`, and optional `teaching_weeks`. Use slots from the same academic year and semester. Overlaps in disjoint known teaching weeks do not clash.

```json
{"course_code":"ZZ0001","academic_year":2030,"semester":1,"constraints":{"avoid_days":["FRI"],"latest_end":"17:00","require_sessions":[{"lesson_type":"TUT","day":"TUE","starts_at_or_after":"13:00"}]}}
```

### `stars_get_graduate_course_schedule`

**Input:** `course_code`.

**Returns:** the latest published graduate term, class groups, coordinators when provided, sessions, commencement dates, and schedule remarks. Graduate results use class groups rather than undergraduate indexes. GSLink/PGR does not publish teaching-week rules through this lookup.

### `stars_get_undergraduate_exam_schedule`

**Inputs:** `course_code`; optionally both `academic_year` and `semester` of `1` or `2`. Omitting both selects NTU's latest published exam term.

**Returns:** exam date, day, start/end time, duration, publication notice, source, and retrieval time. `exam_status` distinguishes `available` from `not_listed`. General Access does not provide personal exam-seat assignments.

### `stars_auth_status`

**Inputs:** none. Does not log in.

**Returns:** whether shared credentials are configured, whether this process has verified a WISH session, its last verification time, and personal-cache settings. No credential or cookie values are returned.

### `stars_get_stars_planner`

**Input:** optional `refresh`, default `false`. Requires credentials.

**Returns:** the published Planner term, registered courses and timetable information, and saved Plans 1–3 with their course/index lists and sessions. Registered courses and saved plans are separate sections. Status fields distinguish empty, parsed, and unavailable data. Use `refresh: true` after editing a plan.

### `stars_save_stars_plan`

**Inputs:** `plan_number` of 1–3, the complete `courses` list of 1–13 course/index pairs, `academic_year`, and `semester` of `1` or `2`. Requires credentials, and the term must match the Planner's current term.

**Returns:** the saved plan and verification time after reloading it. This replaces the plan's entire course/index list; omitted courses are removed. It does not register, drop, or swap registered courses. If persistence is uncertain, refresh the Planner before retrying; an uncertain save is not automatically repeated.

```json
{"plan_number":1,"academic_year":2030,"semester":1,"courses":[{"course_code":"ZZ0001","index":"00001"}]}
```

### `stars_get_degree_audit`

**Inputs:** none. Requires credentials.

**Returns:** published degree/AU requirements, examination results, registered courses, and status/source/cache metadata. Academic tables retain their published headers and records. Identity/contact tables are excluded; unknown or missing academic information is not inferred.

## Vacancy and cache behavior

Vacancy lookup runs only from **09:00–22:00 Singapore time**. Counts are attached only when NTU's published vacancy term matches the requested schedule. Index status may be `available`, `not_listed`, `closed`, `term_mismatch`, or `unavailable`. Unknown vacancy/waitlist values are `null`; a reported zero is a known value. Schedules remain usable when vacancy data is unavailable.

Public responses are cached in memory for one hour by default. `NTU_CACHE_TTL_SECONDS` changes that lifetime; `0` disables it. Vacancy snapshots are cached for at most 60 seconds. Personal WISH records use `NTU_PERSONAL_CACHE_TTL_SECONDS`, default 300 seconds. Sessions and personal records are not persisted to disk, and expired sessions trigger an authorized fresh login.

## Sources

Only NTU endpoints supply timetable and academic records. Forms are followed with their current request fields; this server does not use third-party course databases.

| Service | Official entry and response endpoints | Why used |
| --- | --- | --- |
| Class Schedule | [Current form](https://wish.wis.ntu.edu.sg/webexe/owa/AUS_schedule_NEW.class), [schedule response](https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SCHEDULE_NEW.main_display1) | Search offerings and retrieve indexes, sessions, AUs, prerequisites, and remarks |
| Course descriptions | [Content of Courses form](https://wish.wis.ntu.edu.sg/webexe/owa/aus_subj_cont.main), [content response](https://wish.wis.ntu.edu.sg/webexe/owa/AUS_SUBJ_CONT.main_display1) | Course descriptions when published |
| Vacancies | [Public vacancy form](https://wish.wis.ntu.edu.sg/webexe/owa/aus_vacancy.check_vacancy), [vacancy response](https://wish.wis.ntu.edu.sg/webexe/owa/aus_vacancy.check_vacancy2) | Published vacancy term, per-index vacancies, and waitlist lengths |
| Graduate timetable | [GSLink/PGR entry](https://wish.wis.ntu.edu.sg/pls/webexe/pgr%24subrs_timetable.mmenu), [class timetable](https://wish.wis.ntu.edu.sg/pls/webexe/pgr%24subrs_timetable.examTimetable) | Currently published graduate groups and sessions |
| Undergraduate exams | [General Access entry](https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.main), [selection](https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.MainSubmit), [term page](https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.query_page), [exam response](https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.Get_detail) | Published exam dates/times through the public form workflow |
| STARS Planner | [Authenticated entry](https://wish.wis.ntu.edu.sg/pls/webexe/aus_stars_planner.main), [selection](https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.time_table), [Planner view](https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.planner), [load plan](https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.load_time_table), [save plan](https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.save_time_table) | Registered courses and saved plans; saving is limited to the chosen saved plan |
| Degree Audit | [Authenticated audit](https://wish.wis.ntu.edu.sg/pls/webexe/DARS_RESULT_RO.main_display) | The student's published degree requirements and academic tables |

WISH authentication follows NTU's [login workflow](https://wish.wis.ntu.edu.sg/pls/webexe/ldap_login.login). Credentials come from the shared `NTU_USERNAME` and `NTU_PASSWORD`; access restrictions and challenges are respected.

## Tests

Run commands from the repository root. Offline fixtures use fictional course labels/indexes and synthetic personal records.

```sh
uv run python -m unittest discover -s tests -v
uv run python tests/ntu_stars/live_smoke.py --course-code COURSE_CODE --academic-year YEAR --semester 1
uv run python tests/ntu_stars/live_search_smoke.py --query SEARCH_TEXT --academic-year YEAR --semester 1
uv run python tests/ntu_stars/live_exam_smoke.py --course-code COURSE_CODE
uv run --extra personal python tests/ntu_stars/live_personal_smoke.py
```

Replace placeholders for opt-in live checks. Public smoke tests accept caller-selected courses and terms. The personal smoke test reads records without editing saved plans; output is limited to counts and statuses.
