# NTU STARS MCP

A local MCP server for NTU Singapore course schedules, index vacancies, exam timetables, saved STARS plans, and course-registration requests. It fetches data directly from NTU's public systems without third-party course databases.

Undergraduate indexes, sessions, and prerequisites come from NTU's [current Class Schedule form](https://wish.wis.ntu.edu.sg/webexe/owa/AUS_schedule_NEW.class); vacancy and waitlist counts come from its [public vacancy form](https://wish.wis.ntu.edu.sg/webexe/owa/aus_vacancy.check_vacancy); descriptions come from its [Content of Courses form](https://wish.wis.ntu.edu.sg/webexe/owa/aus_subj_cont.main); exam dates come from the [undergraduate Exam Timetable General Access form](https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.main). Graduate groups come from the [public GSLink/PGR timetable](https://wish.wis.ntu.edu.sg/pls/webexe/pgr%24subrs_timetable.mmenu).

Install [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer.

## Chromium

For personal STARS Planner and Degree Audit tools, install Chromium once:

```sh
uvx --from 'playwright>=1.50,<2' playwright install chromium
```

## Codex

Add to `~/.codex/config.toml`, replacing the credentials with your NTU network account:

```toml
[mcp_servers.ntu-stars-mcp]
command = "uvx"
args = ["--with", "playwright>=1.50,<2", "--from", "git+https://github.com/pitchaya-s/ntu-stars-mcp.git", "ntu-stars-mcp"]

[mcp_servers.ntu-stars-mcp.env]
NTU_WISH_USERNAME = "your-network-username"
NTU_WISH_PASSWORD = "your-network-password"
```

Omit the `env` table for public tools only. Restart Codex and check `codex mcp list`.

## Claude Code

Register for your user with your NTU network credentials:

```sh
claude mcp add --scope user ntu-stars-mcp \
  --env 'NTU_WISH_USERNAME=your-network-username' \
  --env 'NTU_WISH_PASSWORD=your-network-password' \
  -- uvx --with 'playwright>=1.50,<2' --from git+https://github.com/pitchaya-s/ntu-stars-mcp.git ntu-stars-mcp
claude mcp get ntu-stars-mcp
```

Omit the `--env` options for public tools only. Check `claude mcp list` or `/mcp` inside Claude Code. See [Claude Code's MCP guide](https://code.claude.com/docs/en/mcp) for details.

## OpenCode

Add to `~/.config/opencode/opencode.json`, replacing the credentials with your NTU network account:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "ntu-stars-mcp": {
      "type": "local",
      "command": ["uvx", "--with", "playwright>=1.50,<2", "--from", "git+https://github.com/pitchaya-s/ntu-stars-mcp.git", "ntu-stars-mcp"],
      "enabled": true,
      "timeout": 120000,
      "environment": {
        "NTU_WISH_USERNAME": "your-network-username",
        "NTU_WISH_PASSWORD": "your-network-password"
      }
    }
  }
}
```

Omit `environment` for public tools only. Check `opencode mcp list`. See [OpenCode's MCP guide](https://docs.opencode.ai/docs/mcp-servers/) for details.

## Manual install

Clone the repository and run the server from a local checkout:

```sh
git clone https://github.com/pitchaya-s/ntu-stars-mcp.git
cd ntu-stars-mcp
uv sync
uv run ntu-stars-mcp
```

For personal tools in a local checkout, run `uv sync --extra wish` and set `NTU_WISH_USERNAME` and `NTU_WISH_PASSWORD` in your environment.

The process uses MCP stdio, so it stays open while its MCP client is connected. Course responses are cached in memory for one hour by default; vacancy snapshots are cached for at most 60 seconds. Set `NTU_CACHE_TTL_SECONDS` to change the cache time or use `0` to disable caching.

## Source layout

```text
src/ntu_stars_mcp/
├── mcp_server.py  MCP tools and input/output schemas
├── domain/        Course/session models, index comparison, and timetable matching
├── ntu_client/    Public course, vacancy, graduate, and exam requests, caching, and rate limits
├── parser/        Course, vacancy, exam, Degree Audit, and Planner calendar HTML parsers
└── wish/          Shared login, personal cache, saved-plan editing, and confirmed registration requests
tests/            Offline tests, sanitized fixtures, and optional live MCP smoke tests
```

## Tools

Class schedule tools take `academic_year` and `semester`. NTU labels academic years by their first year, so `academic_year: 2026` means AY2026/27. Semester is `1`, `2`, or `"S"` for Special Term. The exam lookup defaults to the latest published exam term; pass both `academic_year` and semester (`1` or `2`) to request a specific published term. It uses General Access, returns exam dates and times, and does not include exam-seat assignments. `get_graduate_course_schedule` returns the latest term published by GSLink/PGR.

| Tool | Purpose | Credentials |
| --- | --- | --- |
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
| `register_courses` | Preview and submit a real course-registration request after fresh user confirmation | Yes |
| `get_degree_audit` | Your AU requirements, results, and registered courses | Yes |

Course metadata includes NTU's course description when the official Content of Courses page provides one. `course_description_status` distinguishes `available`, `not_listed`, and `unavailable`.

Vacancy lookup is available **09:00–22:00 Singapore time (UTC+8)**, without login. Both index tools return `vacancies_available`, `waitlist_length`, and `vacancy_status`, with snapshot time and cache age in `vacancy_metadata`. Counts are attached only when NTU's published vacancy term matches the requested timetable. Outside those hours (`closed`), on a term mismatch (`term_mismatch`), for an unlisted index (`not_listed`), or on an NTU error (`unavailable`), counts are `null` and schedules remain available. A reported `0` is distinct from an unknown count.

Personal Planner results include registered courses and saved Plans 1–3 for NTU's published term. Pass `{"refresh": true}` after editing a plan to bypass the personal cache. `save_stars_plan` replaces the chosen plan with the complete supplied list of 1–13 courses; omitted courses are removed from that plan. It verifies the saved result and does not register, drop, or swap registered courses. An uncertain save is never retried automatically; refresh the Planner before retrying.

**Registration is very dangerous: it can change official enrolment.** `register_courses` first returns a preview without submitting. The agent must show the exact courses/indexes, ask **“Are you sure?”**, and wait for a new explicit affirmative reply before calling again with the same courses/term, `confirmation_token`, and `user_confirmed: true`. Tokens expire after five minutes and are single-use. The tool sends at most one registration request and checks registered courses afterward; extra NTU choices or confirmation pages require manual completion.

Graduate schedules use class groups rather than undergraduate index numbers. PGR reports the currently published term and does not provide teaching weeks.

Example inputs:

```json
{"course_code":"SC2001","academic_year":2026,"semester":1}
```

Save Plan 1 for the current Planner term:

```json
{"plan_number":1,"academic_year":2026,"semester":2,"courses":[{"course_code":"SC2001","index":"10243"}]}
```

Preview a registration request without submitting:

```json
{"academic_year":2026,"semester":2,"courses":[{"course_code":"SC2001","index":"10243"}]}
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

## Verify

The offline parser, scheduling, error-handling, and MCP-client tests use saved official HTML fixtures:

```sh
uv run python -m unittest discover -s tests -v
```

The live stdio smoke test launches through `uvx` and makes real requests to NTU for SC2001, SC2207, and MH2802 in AY2026 semester 1, plus SC2001 in AY2025 semester 2. It also checks vacancies through both index tools for SC2001 and SC2207 in AY2026 semester 2, or verifies the closed status outside service hours:

```sh
uv run python tests/live_smoke.py
```

The undergraduate exam smoke test exercises NTU's public General Access flow through MCP:

```sh
uv run python tests/live_exam_smoke.py
```

With WISH credentials and Chromium configured, the personal smoke test checks saved plans, Degree Audit, caching, and refresh, printing only statuses and counts:

```sh
uv run --extra wish python tests/live_personal_smoke.py
```

## Verified response examples

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

## Limits

Vacancies reflect NTU's reported snapshot for its currently published term and can change before registration. Outside 09:00–22:00 Singapore time, vacancy requests are skipped; timetable tools still work.

The registration form, preview, and one explicitly confirmed submission were checked live. That submission produced no confirmed registration in NTU's refreshed records. Successful registration and subsequent NTU confirmation pages remain unverified; an `unverified` result must be checked manually before another attempt.
