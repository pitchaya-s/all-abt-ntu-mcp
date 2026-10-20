# NTU Course Index MCP

A local, read-only MCP server for NTU Singapore course schedules. It fetches undergraduate course data from NTU's public Class Schedule endpoint and graduate course-group schedules from NTU's GSLink/PGR timetable. It does not use third-party course databases.

Undergraduate indexes, sessions, and prerequisites come from NTU's [current Class Schedule form](https://wish.wis.ntu.edu.sg/webexe/owa/AUS_schedule_NEW.class); descriptions come from its [Content of Courses form](https://wish.wis.ntu.edu.sg/webexe/owa/aus_subj_cont.main). Graduate groups come from the [public GSLink/PGR timetable](https://wish.wis.ntu.edu.sg/pls/webexe/pgr%24subrs_timetable.mmenu).

## Install and run

Install [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer. Run the MCP server directly from GitHub with:

```sh
uvx --from git+https://github.com/pitchaya-s/ntu-stars-mcp.git ntu-course-index
```

For development and offline tests from a local checkout, run:

```sh
uv sync
```

The process uses MCP stdio, so it stays open while its MCP client is connected. Course responses are cached in memory for one hour by default. Set `NTU_CACHE_TTL_SECONDS` to change the cache time or use `0` to disable caching.

## Codex setup

Register the local server with the Codex CLI:

```sh
codex mcp add ntu-course-index -- uvx --from git+https://github.com/pitchaya-s/ntu-stars-mcp.git ntu-course-index
codex mcp list
```

Replace the directory with the repository's absolute path on your machine. Codex stores this server in `~/.codex/config.toml`. The equivalent entry is:

```toml
[mcp_servers.ntu-course-index]
command = "uvx"
args = ["--from", "git+https://github.com/pitchaya-s/ntu-stars-mcp.git", "ntu-course-index"]
```

Restart Codex after adding or changing the server.

## Claude Code setup

Register the server for your user so it is available across Claude Code projects:

```sh
claude mcp add --scope user ntu-course-index -- uvx --from git+https://github.com/pitchaya-s/ntu-stars-mcp.git ntu-course-index
claude mcp get ntu-course-index
```

Check the connection with `claude mcp list` or `/mcp` inside Claude Code. See [Claude Code's MCP guide](https://code.claude.com/docs/en/mcp) for scope and configuration details.

## Tools

Undergraduate tools take `academic_year` and `semester`. NTU labels academic years by their first year, so `academic_year: 2026` means AY2026/27. Semester is `1`, `2`, or `"S"` for Special Term. `get_graduate_course_schedule` returns the latest term published by GSLink/PGR.

| Tool | Purpose |
| --- | --- |
| `get_course` | Course metadata and every index with all sessions |
| `get_course_indexes` | All indexes and complete lesson schedules |
| `get_graduate_course_schedule` | Graduate course class groups and scheduled sessions |
| `get_index_schedule` | Full schedule for one index |
| `compare_indexes` | Shared sessions, index-specific sessions, and optional clash checks |
| `find_matching_indexes` | Filter by days, times, lesson types, teaching weeks, and supplied schedule clashes |

Course metadata includes NTU's course description when the official Content of Courses page provides one. `course_description_status` distinguishes `available`, `not_listed`, and `unavailable`.

Graduate schedules use class groups rather than undergraduate index numbers. PGR reports the currently published term and does not provide teaching weeks.

Example inputs:

```json
{"course_code":"SC2001","academic_year":2026,"semester":1}
```

Graduate lookup uses only the course code and returns NTU's currently published term:

```json
{"course_code":"EE6102"}
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

## Limits

STARS vacancy lookup is not implemented yet.
