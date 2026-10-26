# STARS tool guide

These tools run in the shared `all-abt-ntu-mcp` server. See the [main README](../../README.md) for installation and client configuration.

Public tools are registered in `mcp_server.py` and `room_tools.py`. Authenticated tools live in `personal_tools.py` and are registered only by the local stdio server; the hosted HTTP server exposes public tools only.

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

### `stars_get_prerequisite_tree`

Build a tree around one course, with a **before** branch for its prerequisites and an **after** branch for courses that depend on it.

**Inputs:** `course_code`, `academic_year`, `semester`; optional `prerequisite_depth` and `dependent_depth`, each 0–5 with default 2; `completed_courses` (up to 100 course codes); `only_eligible` (default false); `include_corequisites` (default false); and `max_nodes` per branch, 1–100 with default 100. The center course is treated as completed for eligibility evaluation. `only_eligible` requires `completed_courses` and filters the **after** branch.

**Returns:** a nested tree with published prerequisite expressions on each course. Recognized `AND`/`OR` rules preserve their alternative paths; `completed_courses` marks which paths are satisfied. The **before** branch uses NTU course-content metadata for prerequisite courses that are not offered in the selected term. The **after** branch searches scheduled undergraduate offerings in that term across full-time and part-time study modes. `source_urls` lists the official endpoints used, and each expanded course includes its source when available.

Unrecognized expressions, conflicting full-time/part-time records, and unavailable off-term course metadata remain labeled uncertain. Possible text matches are not treated as confirmed prerequisite rules. The tree is bounded by both depth inputs and `max_nodes`; `prerequisites_truncated` and `dependents_truncated` identify a branch cut short. This is not a historical or complete course-catalogue search.

```json
{"course_code":"ZZ0001","academic_year":2030,"semester":1,"prerequisite_depth":2,"dependent_depth":2,"completed_courses":["MH1812"]}
```

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

### `stars_find_available_rooms`

Find a teaching-observed room with no known scheduled undergraduate classes throughout a requested interval.

**Inputs:** `academic_year`, `semester`, and `window` with `day`, `start_time`, and `end_time`. Optional `window.teaching_weeks` selects semester teaching weeks, from 1–20; the room must be free in **every** selected week. Omitting weeks checks every published meeting conservatively across the term. `window.buffer_minutes`, default 0 and maximum 120, requires additional teaching-free time before and after the interval. The interval plus buffer must fit in one day.

Optional `filters`:

| Field | Meaning |
| --- | --- |
| `room_types` | `tutorial_room`, `seminar_room`, `lecture_theatre`, `laboratory`, or `other`, inferred from venue labels |
| `venue_contains` | Case-insensitive literal text within a normalized venue code |
| `venue_prefixes` | Any matching code prefix, such as `LHN`, `LHS`, `SPMS`, or `S4` |
| `exclude_venues` | Exact venue codes or equivalent normalized aliases to omit |
| `used_for_lesson_types` | Require observed use for any listed lesson type, such as `TUT` or `LAB` |

All lesson types still block availability, regardless of filters. `limit` is 1–100, default 20; `offset` defaults to 0. `refresh: true` reloads the complete shared teaching snapshot.

**Returns:** room codes, inferred types, observed aliases/lesson types, `free_from`/`free_until` teaching-free bounds on that day, total `match_count`, and pagination. A `free_until` of `24:00` is the end of the day, not a building opening-hours statement. Conflicting unknown days, times or teaching weeks exclude a room and contribute to `excluded_uncertain_count`; known clashes contribute to `excluded_busy_count`.

The first lookup fetches two public schedule pages: a blank-course search for full-time offerings and another for part-time offerings. Every published index/session is checked; no course-by-course crawl, course-description lookup or vacancy request is needed. Both pages must parse successfully before results are returned. The normalized snapshot is shared with room timetable lookups, cached for `NTU_CACHE_TTL_SECONDS`, and bounded to four terms.

Only recognizable room labels actually observed in teaching are candidates. Online, placeholder, date-like, course-reference and unrecognized venue labels are excluded. Common punctuation, quotation and tutorial-number variants are merged conservatively; multi-room cells block each independently observed component. Unknown raw venue text is retained in room timetable results. Coverage reports course/index/lesson counts, courses without published indexes, observed room count, excluded venue-label count and unplaced lesson count. Empty official index tables remain missing data; they do not establish that a course has no classes.

```json
{"academic_year":2030,"semester":1,"window":{"day":"WED","start_time":"14:00","end_time":"16:00","teaching_weeks":[7],"buffer_minutes":10},"filters":{"room_types":["tutorial_room","seminar_room"],"venue_prefixes":["LHN","LHS"]}}
```

### `stars_get_room_schedule`

Retrieve the courses and indexes using a room, from the same complete full-time/part-time undergraduate teaching snapshot.

**Inputs:** `venue`, `academic_year`, `semester`. Optional `day`, `teaching_weeks`, and both `start_time`/`end_time` restrict the result to potentially overlapping lessons. Unknown timing/week data remains included rather than being silently discarded. `limit` is 1–100, default 50; `offset` defaults to 0. `refresh` reloads the shared snapshot.

**Returns:** the canonical venue and aliases, inferred room type, observed lesson types, and paginated sessions. Shared sessions are grouped with every associated index in `indexes`. Course codes and indexes remain strings. Sessions retain teaching weeks, unusual remarks, raw day/time values and original venue labels when they differ from the enclosing room. An unidentified venue returns an error rather than an empty or apparently free timetable.

```json
{"venue":"TR+7","academic_year":2030,"semester":1,"day":"TUE","teaching_weeks":[7]}
```

These tools report **no known scheduled undergraduate teaching**, not guaranteed room availability or occupancy. Graduate classes, exams, private bookings, closures and access restrictions are outside coverage. Room types are inferred from names; capacities, equipment, accessibility and opening hours are not supplied by this source. Bare `TR`/`LT` codes do not establish North/South Spine or a building location; use MazeMap for verified location information.

### `stars_get_graduate_course_schedule`

**Input:** `course_code`.

**Returns:** the latest published graduate term, class groups, coordinators when provided, sessions, commencement dates, and schedule remarks. Graduate results use class groups rather than undergraduate indexes. GSLink/PGR does not publish teaching-week rules through this lookup.

### `stars_get_undergraduate_exam_schedule`

**Inputs:** `course_code`; optionally both `academic_year` and `semester` of `1` or `2`. Omitting both selects NTU's latest published exam term.

**Returns:** exam date, day, start/end time, duration, publication notice, source, and retrieval time. `exam_status` distinguishes `available` from `not_listed`. General Access does not provide personal exam-seat assignments.

### `stars_auth_status`

**Inputs:** none. Does not log in.

**Returns:** whether a shared keyring account is stored, `credential_storage` of `os_keyring`, a sanitized `credential_error` when unavailable, whether this process has verified a WISH session, its last verification time, and personal-cache settings. No credential or cookie values are returned.

`credentials_configured: null` means the store could not be read; it does not mean the account was never saved. `false` means a readable store has no account.

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

Public responses are cached in memory for one hour by default. Room tools share a separate term-wide full-time/part-time snapshot with the same lifetime and a four-term cache bound. `NTU_CACHE_TTL_SECONDS` changes that lifetime; `0` disables it. Vacancy snapshots are cached for at most 60 seconds. Personal WISH records use `NTU_PERSONAL_CACHE_TTL_SECONDS`, default 300 seconds. Sessions and personal records are not persisted to disk, and expired sessions trigger an authorized fresh login.

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

WISH authentication follows NTU's [login workflow](https://wish.wis.ntu.edu.sg/pls/webexe/ldap_login.login). Credentials come from the [shared credential store](../shared/README.md#credential-storage), also used by NTULearn and LibFacilities; access restrictions and challenges are respected. Manage it locally with `all-abt-ntu auth save`, `auth status`, and `auth delete`. Passwords are never accepted as MCP arguments or read from environment variables/config files.

## Tests

Run commands from the repository root. Offline fixtures use fictional course labels/indexes and synthetic personal records.

```sh
uv run python -m unittest discover -s tests -t . -v
uv run python tests/stars/live_smoke.py --course-code COURSE_CODE --academic-year YEAR --semester 1
uv run python tests/stars/live_search_smoke.py --query SEARCH_TEXT --academic-year YEAR --semester 1
uv run python tests/stars/live_rooms_smoke.py --academic-year YEAR --semester 1 --day WED --start-time 14:00 --end-time 16:00 --week WEEK
uv run python tests/stars/live_exam_smoke.py --course-code COURSE_CODE
uv run --extra personal python tests/stars/live_personal_smoke.py
```

Replace placeholders for opt-in live checks. Public smoke tests accept caller-selected courses and terms. The personal smoke test reads records without editing saved plans; output is limited to counts and statuses.
