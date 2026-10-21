# NTU STARS MCP

A local, read-only MCP server for NTU Singapore course and exam schedules. It fetches undergraduate course data from NTU's public Class Schedule and General Access exam timetable, and graduate course-group schedules from NTU's GSLink/PGR timetable. It does not use third-party course databases.

Undergraduate indexes, sessions, and prerequisites come from NTU's [current Class Schedule form](https://wish.wis.ntu.edu.sg/webexe/owa/AUS_schedule_NEW.class); descriptions come from its [Content of Courses form](https://wish.wis.ntu.edu.sg/webexe/owa/aus_subj_cont.main); exam dates come from the [undergraduate Exam Timetable General Access form](https://wis.ntu.edu.sg/webexe/owa/exam_timetable_und.main). Graduate groups come from the [public GSLink/PGR timetable](https://wish.wis.ntu.edu.sg/pls/webexe/pgr%24subrs_timetable.mmenu).

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
      "timeout": 30000,
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

The process uses MCP stdio, so it stays open while its MCP client is connected. Course responses are cached in memory for one hour by default. Set `NTU_CACHE_TTL_SECONDS` to change the cache time or use `0` to disable caching.

## Source layout

```text
src/ntu_stars_mcp/
├── mcp_server.py  MCP tools and input/output schemas
├── domain/        Course/session models, index comparison, and timetable matching
├── ntu_client/    Public course, graduate, and exam requests, caching, and rate limits
├── parser/        Course, exam, Degree Audit, and Planner calendar HTML parsers
└── wish/          Shared browser login, personal cache, and read-only saved-plan loading
tests/            Offline tests, sanitized fixtures, and optional live MCP smoke tests
```

## Tools

Class schedule tools take `academic_year` and `semester`. NTU labels academic years by their first year, so `academic_year: 2026` means AY2026/27. Semester is `1`, `2`, or `"S"` for Special Term. The exam lookup defaults to the latest published exam term; pass both `academic_year` and semester (`1` or `2`) to request a specific published term. It uses General Access, returns exam dates and times, and does not include exam-seat assignments. `get_graduate_course_schedule` returns the latest term published by GSLink/PGR.

| Tool | Purpose |
| --- | --- |
| `get_course_metadata` | Course name, AUs, prerequisites, description, and term metadata |
| `get_course_indexes` | All indexes and complete lesson schedules |
| `get_index_schedule` | Full schedule for one index |
| `compare_indexes` | Shared sessions, index-specific sessions, and optional clash checks |
| `find_matching_indexes` | Filter by days, times, lesson types, teaching weeks, and supplied schedule clashes |
| `get_graduate_course_schedule` | Graduate course class groups and scheduled sessions |
| `get_undergraduate_exam_schedule` | Undergraduate exam date, time, duration, and published-term notice |
| `ntu_auth_status` | Whether optional WISH credentials are configured and a session has been verified |
| `get_my_stars_planner` | Your registered courses and saved Plans 1–3 with timetables (credentials required) |
| `get_my_degree_audit` | Your AU requirements, results, and registered courses (credentials required) |

Course metadata includes NTU's course description when the official Content of Courses page provides one. `course_description_status` distinguishes `available`, `not_listed`, and `unavailable`.

Personal Planner results include registered courses and saved Plans 1–3 for NTU's published term. Pass `{"refresh": true}` after editing a plan to bypass the personal cache.

Graduate schedules use class groups rather than undergraduate index numbers. PGR reports the currently published term and does not provide teaching weeks.

Example inputs:

```json
{"course_code":"SC2001","academic_year":2026,"semester":1}
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

The live stdio smoke test launches through `uvx` and makes real requests to NTU for SC2001, SC2207, and MH2802 in AY2026 semester 1, plus SC2001 in AY2025 semester 2:

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

`get_index_schedule` returns a structured object shaped like:

```json
{
  "course_code":"SC2001",
  "index":"10143",
  "schedule_complete":true,
  "sessions":[
    {"lesson_type":"TUT","group":"SCEA","day":"TUE","start_time":"16:30","end_time":"17:20","venue":"TR+7","teaching_weeks":[2,3,4,5,6,7,8,9,10,11,12,13],"remarks":"Teaching Wk2-13"}
  ]
}
```

The public exam timetable currently lists SC2001's AY2026 Semester 1 exam on 2026-11-23 at 13:00 for 120 minutes. The response carries NTU's notice that the timetable may change; exam-seat assignments are published separately.

## Limits

STARS vacancy lookup is not implemented yet.
