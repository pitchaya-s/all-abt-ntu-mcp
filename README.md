# NTU Course Index MCP

A local, read-only MCP server for NTU Singapore course schedules. It fetches course data from NTU's public Class Schedule endpoint, queries the full-time schedule option, and does not use third-party course databases.

## Install and run

Install [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer. For development and offline tests, run:

```sh
uv sync
```

To start the MCP server in an isolated `uvx` environment from this local checkout, run:

```sh
uvx --from /path/to/ntu-stars-mcp ntu-course-index
```

Replace the path with the repository's absolute path. The process uses MCP stdio, so it stays open while its MCP client is connected. Course responses are cached in memory for one hour by default. Set `NTU_CACHE_TTL_SECONDS` to change the cache time or use `0` to disable caching.

## Codex setup

Register the local server with the Codex CLI:

```sh
codex mcp add ntu-course-index -- uvx --from /path/to/ntu-stars-mcp ntu-course-index
codex mcp list
```

Replace the directory with the repository's absolute path on your machine. Codex stores this server in `~/.codex/config.toml`. The equivalent entry is:

```toml
[mcp_servers.ntu-course-index]
command = "uvx"
args = ["--from", "/path/to/ntu-stars-mcp", "ntu-course-index"]
```

Restart Codex after adding or changing the server.

## Claude Code setup

Register the server for your user so it is available across Claude Code projects:

```sh
claude mcp add --scope user ntu-course-index -- uvx --from /path/to/ntu-stars-mcp ntu-course-index
claude mcp get ntu-course-index
```

Replace the path with the repository's absolute path. Check the connection with `claude mcp list` or `/mcp` inside Claude Code. See [Claude Code's MCP guide](https://code.claude.com/docs/en/mcp) for scope and configuration details.

## Tools

Every tool takes `academic_year` and `semester`. NTU labels academic years by their first year, so `academic_year: 2026` means AY2026/27. Semester is `1`, `2`, or `"S"` for Special Term.

| Tool | Purpose |
| --- | --- |
| `get_course` | Course metadata and every index with all sessions |
| `get_course_indexes` | All indexes and complete lesson schedules |
| `get_index_schedule` | Full schedule for one index |
| `compare_indexes` | Shared sessions, index-specific sessions, and optional clash checks |
| `find_matching_indexes` | Filter by days, times, lesson types, teaching weeks, and supplied schedule clashes |

Example inputs:

```json
{"course_code":"SC2001","academic_year":2026,"semester":1}
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
