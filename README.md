# all-abt-ntu-mcp

A local MCP server for NTU Singapore STARS and NTULearn: course schedules, vacancies, exam timetables, saved plans, learning materials, announcements, calendar entries, and grades. Data comes directly from NTU's systems.

Undergraduate indexes, sessions, and prerequisites come from NTU's [current Class Schedule form](https://wish.wis.ntu.edu.sg/webexe/owa/AUS_schedule_NEW.class); vacancy and waitlist counts come from its [public vacancy form](https://wish.wis.ntu.edu.sg/webexe/owa/aus_vacancy.check_vacancy); descriptions come from its [Content of Courses form](https://wish.wis.ntu.edu.sg/webexe/owa/aus_subj_cont.main); exam dates come from the [undergraduate Exam Timetable General Access form](https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.main). Graduate groups come from the [public GSLink/PGR timetable](https://wish.wis.ntu.edu.sg/pls/webexe/pgr%24subrs_timetable.mmenu).

Install [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer.

## Chromium

For authenticated STARS and NTULearn tools, install Chromium once:

```sh
uvx --from 'playwright>=1.50,<2' playwright install chromium
```

## Codex

Add to `~/.codex/config.toml`, replacing the credentials with your NTU network account:

```toml
[mcp_servers.all-abt-ntu-mcp]
command = "uvx"
args = ["--with", "playwright>=1.50,<2", "--from", "git+https://github.com/pitchaya-s/ntu-stars-mcp.git@all-abt", "all-abt-ntu-mcp"]
startup_timeout_sec = 120
tool_timeout_sec = 240

[mcp_servers.all-abt-ntu-mcp.env]
NTU_USERNAME = "your-network-username"
NTU_PASSWORD = "your-network-password"
```

Omit the `env` table for public tools only. One username and password enable both authenticated STARS and NTULearn tools. Restart Codex and check `codex mcp list`.

## Claude Code

Register for your user with your NTU network credentials:

```sh
claude mcp add --scope user all-abt-ntu-mcp \
  --env 'NTU_USERNAME=your-network-username' \
  --env 'NTU_PASSWORD=your-network-password' \
  -- uvx --with 'playwright>=1.50,<2' --from git+https://github.com/pitchaya-s/ntu-stars-mcp.git@all-abt all-abt-ntu-mcp
claude mcp list
```

Omit the `--env` options for public tools only. Check `claude mcp list` or `/mcp` inside Claude Code. See [Claude Code's MCP guide](https://code.claude.com/docs/en/mcp) for details.

## OpenCode

Add to `~/.config/opencode/opencode.json`, replacing the credentials with your NTU network account:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "all-abt-ntu-mcp": {
      "type": "local",
      "command": ["uvx", "--with", "playwright>=1.50,<2", "--from", "git+https://github.com/pitchaya-s/ntu-stars-mcp.git@all-abt", "all-abt-ntu-mcp"],
      "enabled": true,
      "timeout": 240000,
      "environment": {
        "NTU_USERNAME": "your-network-username",
        "NTU_PASSWORD": "your-network-password"
      }
    }
  }
}
```

Omit `environment` for public tools only. Check `opencode mcp list`. See [OpenCode's MCP guide](https://docs.opencode.ai/docs/mcp-servers/) for details.

## Manual install

Clone the repository and run the server from a local checkout:

```sh
git clone --branch all-abt https://github.com/pitchaya-s/ntu-stars-mcp.git all-abt-ntu-mcp
cd all-abt-ntu-mcp
uv sync
uv run all-abt-ntu-mcp
```

For authenticated tools, run `uv sync --extra personal` and set `NTU_USERNAME` and `NTU_PASSWORD` in your environment. A network username is used directly for WISH and expanded to `username@e.ntu.edu.sg` for NTULearn. You may instead supply your full NTU email; WISH uses its username portion and NTULearn uses the full address. An optional local `.env` can supply the same shared variables.

The process uses MCP stdio, so it stays open while its MCP client is connected. Course responses are cached in memory for one hour by default; vacancy snapshots are cached for at most 60 seconds. Set `NTU_CACHE_TTL_SECONDS` to change the cache time or use `0` to disable caching.

## Source layout

```text
src/
├── shared/           MCP runtime, credentials, and username/email normalization
├── ntu_stars_mcp/
│   ├── mcp_server.py  STARS tools and NTULearn tool registration
│   ├── schemas.py     Typed public results
│   ├── compact.py     Remove redundant output fields
│   ├── domain/        Course/session models and timetable matching
│   ├── ntu_client/    Official public requests, caching, and rate limits
│   ├── parser/        Course, vacancy, exam, Degree Audit, and Planner parsers
│   └── wish/          Login, personal cache, and saved-plan editing
└── ntulearn_mcp/
    ├── tools.py       NTULearn tools registered on the shared server
    ├── models.py      Typed academic results
    ├── normalize.py   Academic-field extraction and pagination validation
    ├── auth.py        Microsoft login, session reuse, and HTTP reads
    └── client.py      Courses, content, announcements, calendar, grades, and files
tests/
├── ntu_stars/         STARS tests, fixtures, and live smoke tests
├── ntulearn/          NTULearn tests, synthetic responses, and live smoke test
└── test_shared.py     Shared credential configuration and server lifecycle tests
```

## Tools

### STARS

Class schedule tools take `academic_year` and `semester`. NTU labels academic years by their first year, so `academic_year: 2026` means AY2026/27. Semester is `1`, `2`, or `"S"` for Special Term. The exam lookup defaults to the latest published exam term; pass both `academic_year` and semester (`1` or `2`) to request a specific published term. It uses General Access, returns exam dates and times, and does not include exam-seat assignments. `get_graduate_course_schedule` returns the latest term published by GSLink/PGR.

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `search_courses` | Find undergraduate courses by partial code or title keywords in a published term | No |
| `get_course_metadata` | Course name, AUs, prerequisites, description, and term metadata | No |
| `get_course_indexes` | All indexes with complete schedules, vacancies, and waitlist lengths | No |
| `get_index` | One index's complete schedule, vacancies, and waitlist length | No |
| `compare_indexes` | Shared sessions, index-specific sessions, and optional clash checks | No |
| `find_matching_indexes` | Filter by days, times, lesson types, teaching weeks, and supplied schedule clashes | No |
| `get_graduate_course_schedule` | Graduate course class groups and scheduled sessions | No |
| `get_undergraduate_exam_schedule` | Undergraduate exam date, time, duration, and published-term notice | No |
| `ntu_auth_status` | Whether optional WISH credentials are configured and a session has been verified | No |
| `get_stars_planner` | Your registered courses and saved Plans 1–3 with timetables | Yes |
| `save_stars_plan` | Replace a saved plan's course/index list and verify the saved result | Yes |
| `get_degree_audit` | Your AU requirements, results, and registered courses | Yes |

Course metadata includes NTU's course description when the official Content of Courses page provides one. `course_description_status` distinguishes `available`, `not_listed`, and `unavailable`.

`search_courses` uses the same official Class Schedule endpoint. It returns codes, names, and AUs for the requested term, with `study_mode` defaulting to `"full_time"` or optionally `"part_time"`. Results use `limit` (default 20, maximum 100) and `offset`, with `total_count` and `has_more`; pages share the cached search response. It searches scheduled undergraduate offerings, not the complete course catalogue or graduate courses.

All tools publish concrete `outputSchema` definitions. Responses are compact by default, with no detail-level setting: sessions inherit course/index identifiers from their enclosing result, and empty raw fields are omitted. Comparison/search results keep timetable provenance rather than repeating course descriptions. Teaching weeks, venues, groups, remarks, unknown raw values, and safety warnings are retained. Personal tables omit `rows` only when `headers` and `records` reconstruct them exactly; saved-plan sessions inherit their index from the plan's course list. Raw graduate schedules and exam duration text remain when they contain information not represented by parsed fields.

Vacancy lookup is available **09:00–22:00 Singapore time (UTC+8)**, without login. Both index tools return `vacancies_available`, `waitlist_length`, and `vacancy_status`, with snapshot time and cache age in `vacancy_metadata`. Counts are attached only when NTU's published vacancy term matches the requested timetable. Outside those hours (`closed`), on a term mismatch (`term_mismatch`), for an unlisted index (`not_listed`), or on an NTU error (`unavailable`), counts are `null` and schedules remain available. A reported `0` is distinct from an unknown count.

Personal Planner results include registered courses and saved Plans 1–3 for NTU's published term. Pass `{"refresh": true}` after editing a plan to bypass the personal cache. `save_stars_plan` replaces the chosen plan with the complete supplied list of 1–13 courses; omitted courses are removed from that plan. It verifies the saved result and does not register, drop, or swap registered courses. An uncertain save is never retried automatically; refresh the Planner before retrying.

Graduate schedules use class groups rather than undergraduate index numbers. PGR reports the currently published term and does not provide teaching weeks.

Example inputs:

Search by partial code or title words:

```json
{"query":"SC20","academic_year":2026,"semester":1}
```

```json
{"query":"DATA STRUCTURES","academic_year":2026,"semester":1}
```

Get a course's metadata or indexes:

```json
{"course_code":"SC2001","academic_year":2026,"semester":1}
```

Save Plan 1 for the current Planner term:

```json
{"plan_number":1,"academic_year":2026,"semester":2,"courses":[{"course_code":"SC2001","index":"10243"}]}
```

Graduate lookup uses only the course code and returns NTU's currently published term:

```json
{"course_code":"EE6102"}
```

Undergraduate exam lookup uses the latest public term, or an explicitly requested published semester:

```json
{"course_code":"SC2001"}
```

```json
{
  "course_code":"SC2001",
  "academic_year":2026,
  "semester":1,
  "constraints":{
    "avoid_days":["FRI"],
    "latest_end":"17:00",
    "require_sessions":[{"lesson_type":"TUT","day":"TUE","starts_at_or_after":"13:00"}]
  }
}
```

Pass a schedule from the same academic year and semester to `against_sessions` as time slots. The server accepts the `day`, `start_time`, `end_time`, and optional `teaching_weeks` fields from sessions returned by the other tools; extra fields such as course code and index are ignored. Two sessions clash only when their days and times overlap and their explicit teaching-week sets intersect. If week information is absent, overlap remains possible.

Unrecognized NTU day or time values are retained in `raw_day` or `raw_time`. Matching results with incomplete schedule information are marked `status: "uncertain"` rather than reported as confirmed matches.

### NTULearn

NTULearn tools are available through the same `all-abt-ntu-mcp` server and shared credentials as STARS. NTULearn authenticates through a local temporary browser, then uses Blackboard's authenticated REST endpoints. All NTULearn requests are reads.

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `ntulearn_auth_status` | Credential configuration and last verified session | No |
| `list_courses` | Your enrolled courses and organizations, with availability and IDs | Yes |
| `get_course_contents` | One level of course content, with `parent_id` to open a folder | Yes |
| `get_announcements` | Published announcements for one course | Yes |
| `get_calendar` | Calendar entries and published deadlines | Yes |
| `get_gradebook` | Gradebook columns and your own visible scores and status | Yes |
| `get_content_attachments` | Attached files for a leaf content item | Yes |
| `download_file` | Save an attachment to a new, explicit local file path | Yes |

Start with `list_courses` and use the returned IDs. List tools accept `limit` (default 50, maximum 100), `offset`, and `refresh`. Continue with `next_offset` when present. Gradebook columns and grades paginate independently using `offset` and `grades_offset`. Missing scores remain unknown rather than becoming zero.

```json
{"course_id":"_100_1","parent_id":"_200_1"}
```

Calendar defaults to the next 14 days. Explicit windows must include timezones and be no longer than 112 days:

```json
{"since":"2026-10-22T00:00:00+08:00","until":"2026-11-05T00:00:00+08:00"}
```

Sessions and cached academic data stay in memory. Valid sessions are reused, and expired sessions trigger one fresh login. `NTULEARN_CACHE_TTL_SECONDS` defaults to 300; `0` disables caching. Responses include retrieval time and cache freshness. Incorrect credentials are not automatically retried. If Microsoft requires MFA or CAPTCHA, headless login stops; on a graphical desktop, set `NTULEARN_HEADLESS=false` and complete verification in the local browser. No security checks are bypassed.

## Verify

The offline tests cover parsing, scheduling, lossless compaction, output-schema validation, tool calls/errors, and resource discovery. Protocol tests use Python SDK clients and an independent JSON-RPC client over stdio, including protocol versions `2025-06-18` and `2025-11-25`:

```sh
uv run python -m unittest discover -s tests -v
```

An optional check uses the official TypeScript SDK. Node dependencies stay in a temporary directory:

```sh
NTU_MCP_TEST_SDK="$(mktemp -d)"
npm install --prefix "$NTU_MCP_TEST_SDK" --ignore-scripts --no-audit --no-fund @modelcontextprotocol/sdk@1.32.1
uv run node tests/ntu_stars/typescript_smoke.mjs "$NTU_MCP_TEST_SDK"
```

These interoperability checks use offline fixtures and never edit saved plans.

The live stdio smoke test launches through `uvx` and makes real requests to NTU for SC2001, SC2207, and MH2802 in AY2026 semester 1, plus SC2001 in AY2025 semester 2. It also checks vacancies through both index tools for SC2001 and SC2207 in AY2026 semester 2, or verifies the closed status outside service hours:

```sh
uv run python tests/ntu_stars/live_smoke.py
```

The course search smoke test checks partial codes, title keywords, full-time and part-time offerings, pagination, empty results, and two published semesters:

```sh
uv run python tests/ntu_stars/live_search_smoke.py
```

The undergraduate exam smoke test exercises NTU's public General Access flow through MCP:

```sh
uv run python tests/ntu_stars/live_exam_smoke.py
```

With WISH credentials and Chromium configured, the personal smoke test checks saved plans, Degree Audit, caching, and refresh, printing only statuses and counts:

```sh
uv run --extra personal python tests/ntu_stars/live_personal_smoke.py
```

With NTULearn credentials configured, its opt-in live test reads academic data, downloads a sample attachment to a temporary directory when available, and clears local cookies to test reauthentication. It prints only counts and statuses:

```sh
uv run --extra personal python tests/ntulearn/live_smoke.py
```

## Verified response examples

### STARS

Live official pages fetched on 2026-10-21 returned 36 indexes for SC2001, 13 for SC2207, and 12 for MH2802 in AY2026 semester 1. For SC2001 index `10143`, the endpoint lists two shared `LEC/STUDIO` sessions, a Tuesday `TUT` from 16:30 to 17:20 in `TR+7` during weeks 2–13, and a Monday `LAB` from 10:30 to 12:20 in `HWLAB2` during odd weeks 1–13.

`get_index` returns a structured object shaped like:

```json
{
  "course_code":"SC2001",
  "index":"10143",
  "vacancies_available":null,
  "waitlist_length":null,
  "vacancy_status":"term_mismatch",
  "vacancy_metadata":{"status":"term_mismatch","academic_year":2026,"semester":"2","retrieved_at":"2026-10-21T03:00:00+00:00","source_url":"https://wish.wis.ntu.edu.sg/webexe/owa/aus_vacancy.check_vacancy2","from_cache":false,"cache_age_seconds":0},
  "schedule_complete":true,
  "sessions":[
    {"lesson_type":"TUT","group":"SCEA","day":"TUE","start_time":"16:30","end_time":"17:20","venue":"TR+7","teaching_weeks":[2,3,4,5,6,7,8,9,10,11,12,13],"remarks":"Teaching Wk2-13"}
  ]
}
```

The public exam timetable currently lists SC2001's AY2026 Semester 1 exam on 2026-11-23 at 13:00 for 120 minutes. The response carries NTU's notice that the timetable may change; exam-seat assignments are published separately.

### NTULearn

Live authenticated reads on 2026-10-22 verified course and organization listing, course folders and content, announcements, calendar entries, gradebook columns and personal grades, attachment listing, and a temporary file download. Clearing local session cookies triggered a successful automatic fresh login. No student records or downloaded learning materials are included in this repository.

## Limits

Vacancies reflect NTU's reported snapshot for its currently published term and can change before registration. Outside 09:00–22:00 Singapore time, vacancy requests are skipped; timetable tools still work.

NTULearn access follows your student permissions and published availability. Folders and external/LTI tools may not expose attachment files. Downloads are limited to 20 MB, never overwrite files, and use only NTU or Blackboard file-delivery hosts. HTML/JSON attachments are not supported. University session cookies are not forwarded to delivery hosts. Messaging, rosters, groups, submission attempts, recursive search, bulk downloads, and document text extraction are not implemented.

## Disclaimer

This is an independent project and is not affiliated with, sponsored by, or endorsed by Nanyang Technological University (NTU), Singapore.

Your NTU credentials are read locally and submitted over HTTPS to NTU or its Microsoft sign-in service for login; they are not included in MCP tool responses. Academic data returned by tools is visible to the AI client. Keep your credentials private: agents with access to your configuration files or environment may still be able to read them.
