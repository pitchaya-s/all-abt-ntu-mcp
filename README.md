# all-abt-ntu-mcp

A local MCP server for NTU Singapore STARS and NTULearn: course schedules, vacancies, exam timetables, saved plans, learning materials, announcements, calendar entries, and grades. Data comes directly from NTU's systems.

[STARS guide](src/ntu_stars_mcp/README.md) · [NTULearn guide](src/ntulearn_mcp/README.md).

Install [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer.

## Chromium

For authenticated STARS and NTULearn tools, install Chromium once:

```sh
uvx --from 'playwright>=1.50,<2' playwright install chromium
```

## Credentials

Public tools need no credentials. For personal tools, opt into native OS keyring storage by running this **yourself in a local terminal**:

```sh
uvx --from git+https://github.com/pitchaya-s/ntu-stars-mcp.git@all-abt all-abt-ntu-mcp auth save
```

The hidden prompts save one account for STARS and NTULearn and enable automatic login/session recovery. Run `auth save` again to update it, `auth status` to check storage without revealing credentials, or `auth delete` to remove it. Replace `auth save` at the end of the command above with the action you want.

The keyring must be available and unlocked: Secret Service or KWallet on Linux, Keychain on macOS, Credential Manager on Windows. There is no plaintext fallback. Passwords are not accepted through MCP, command arguments, environment variables, `.env`, or client configuration. Remove any credentials left in your old configuration; the server no longer reads them. More details: [credential storage](src/ntulearn_mcp/README.md#credentials-and-sessions).

## Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.all-abt-ntu-mcp]
command = "uvx"
args = ["--with", "playwright>=1.50,<2", "--from", "git+https://github.com/pitchaya-s/ntu-stars-mcp.git@all-abt", "all-abt-ntu-mcp"]
startup_timeout_sec = 120
tool_timeout_sec = 240
```

Restart Codex and check `codex mcp list`. Personal tools use your locally saved keyring account.

## Claude Code

Register for your user:

```sh
claude mcp add --scope user all-abt-ntu-mcp \
  -- uvx --with 'playwright>=1.50,<2' --from git+https://github.com/pitchaya-s/ntu-stars-mcp.git@all-abt all-abt-ntu-mcp
claude mcp list
```

Personal tools use your locally saved keyring account. Check `claude mcp list` or `/mcp` inside Claude Code. See [Claude Code's MCP guide](https://code.claude.com/docs/en/mcp) for details.

## OpenCode

Add to `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "all-abt-ntu-mcp": {
      "type": "local",
      "command": ["uvx", "--with", "playwright>=1.50,<2", "--from", "git+https://github.com/pitchaya-s/ntu-stars-mcp.git@all-abt", "all-abt-ntu-mcp"],
      "enabled": true,
      "timeout": 240000
    }
  }
}
```

Personal tools use your locally saved keyring account. Check `opencode mcp list`. See [OpenCode's MCP guide](https://docs.opencode.ai/docs/mcp-servers/) for details.

## Manual install

Clone the repository and run the server from a local checkout:

```sh
git clone --branch all-abt https://github.com/pitchaya-s/ntu-stars-mcp.git all-abt-ntu-mcp
cd all-abt-ntu-mcp
uv sync
uv run all-abt-ntu-mcp
```

For personal tools, run `uv sync --extra personal`, then `uv run all-abt-ntu-mcp auth save` in your own terminal. Use `uv run all-abt-ntu-mcp auth status` or `auth delete` to inspect storage status or remove the account. These commands manage credentials; starting the server still uses `uv run all-abt-ntu-mcp`.

The process uses MCP stdio, so it stays open while its MCP client is connected. Course responses are cached in memory for one hour by default; vacancy snapshots are cached for at most 60 seconds. Set `NTU_CACHE_TTL_SECONDS` to change the cache time or use `0` to disable caching.

## Source layout

```text
src/
├── shared/                 Shared MCP runtime, local CLI, and keyring
├── ntu_stars_mcp/
│   ├── mcp_server.py        STARS tool registration and input schemas
│   ├── domain/             Course models and timetable matching
│   ├── ntu_client/         Public NTU requests and caching
│   ├── parser/             Schedule and personal-page parsing
│   └── wish/               WISH login and saved-plan editing
└── ntulearn_mcp/
    ├── mcp_server.py        NTULearn tool registration and input schemas
    ├── models/             Typed responses grouped by domain
    ├── ntu_client/         Login, sessions, and REST requests
    ├── parser/             Response and document parsing
    └── services/           Content, files, mailbox, people, and activity
tests/
├── ntu_stars/              STARS tests and fictionalized fixtures
├── ntulearn/               NTULearn tests and synthetic fixtures
└── test_*.py               Keyring, local CLI, and shared lifecycle tests
```

## Tools

### STARS

Public lookups work without credentials. Planner and Degree Audit use the shared NTU credentials.

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `stars_search_courses` | Find undergraduate courses by partial code or title keywords in a published term | No |
| `stars_get_course_metadata` | Course name, AUs, prerequisites, description, and term metadata | No |
| `stars_get_course_indexes` | All indexes with complete schedules, vacancies, and waitlist lengths | No |
| `stars_get_index` | One index's complete schedule, vacancies, and waitlist length | No |
| `stars_compare_indexes` | Shared sessions, index-specific sessions, and optional clash checks | No |
| `stars_find_matching_indexes` | Filter by days, times, lesson types, teaching weeks, and supplied schedule clashes | No |
| `stars_get_graduate_course_schedule` | Graduate course class groups and scheduled sessions | No |
| `stars_get_undergraduate_exam_schedule` | Undergraduate exam date, time, duration, and published-term notice | No |
| `stars_auth_status` | Whether optional WISH credentials are configured and a session has been verified | No |
| `stars_get_stars_planner` | Your registered courses and saved Plans 1–3 with timetables | Yes |
| `stars_save_stars_plan` | Replace a saved plan's course/index list and verify the saved result | Yes |
| `stars_get_degree_audit` | Your AU requirements, results, and registered courses | Yes |

Vacancies are available **09:00–22:00 Singapore time**; unknown counts are `null`. Saving a plan replaces its entire course/index list. See the [STARS guide](src/ntu_stars_mcp/README.md) for parameters, examples, and sources.

### NTULearn

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `ntulearn_auth_status` | Credential configuration and last verified session | No |
| `ntulearn_list_courses` | Your enrolled courses and organizations, with availability and IDs | Yes |
| `ntulearn_get_course_contents` | One level of course content, with `parent_id` to open a folder | Yes |
| `ntulearn_get_announcements` | Published announcements for one course | Yes |
| `ntulearn_get_calendar` | Calendar entries and published deadlines | Yes |
| `ntulearn_get_upcoming` | All calendar pages across enrolled or selected courses | Yes |
| `ntulearn_get_gradebook` | Gradebook columns and your own visible scores and status | Yes |
| `ntulearn_get_content_attachments` | Attached files for a leaf content item | Yes |
| `ntulearn_read_file_content` | Read PDF, Office, and text attachments inline | Yes |
| `ntulearn_download_file` | Save an attachment to a new, explicit local file path | Yes |
| `ntulearn_list_messages` | List inbox or sent messages from course conversations | Yes |
| `ntulearn_read_message` | Full message body and published conversation recipients | Yes |
| `ntulearn_list_course_users` | Visible course users and their roles | Yes |
| `ntulearn_list_course_groups` | Course groups and group sets | Yes |
| `ntulearn_get_group_members` | Visible members of a course group | Yes |
| `ntulearn_search_course_content` | Recursive substring search within one course | Yes |
| `ntulearn_search_all_courses` | Search course content with course IDs and breadcrumbs | Yes |
| `ntulearn_get_content_tree` | Nested course content tree bounded by depth and size | Yes |
| `ntulearn_download_course` | Download course attachments into local folders | Yes |
| `ntulearn_whats_new` | Recent announcements, upcoming events, and grade snapshots | Yes |

Start with `ntulearn_list_courses`, then use the returned IDs. See the [NTULearn guide](src/ntulearn_mcp/README.md) for parameters, examples, and sources.

## Tests

Personal-data fixtures are synthetic. Timetable fixtures use fictional course labels and indexes while retaining the HTML structures needed for parser tests. Opt-in live tests print counts and statuses; they do not save academic records or learning materials in the repository.

The offline tests cover keyring storage and failure handling, hidden credential prompts, session recovery, parsing, scheduling, lossless compaction, output-schema validation, tool calls/errors, and resource discovery. Protocol tests use Python SDK clients and an independent JSON-RPC client over stdio, including protocol versions `2025-06-18` and `2025-11-25`:

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

Live checks and service-specific testing instructions: [STARS](src/ntu_stars_mcp/README.md#tests) · [NTULearn](src/ntulearn_mcp/README.md#tests).

## Limitation

Access depends on NTU permissions and service availability. Timetables are published schedules; vacancies are snapshots. NTULearn may restrict content, and large collections can return partial results. Inline document reading extracts text without OCR.

## Disclaimer

This is an independent project and is not affiliated with, sponsored by, or endorsed by Nanyang Technological University (NTU), Singapore.

Your NTU credentials are retrieved locally from your OS keyring and submitted over HTTPS to NTU or its Microsoft sign-in service. They are never returned through MCP. Academic data returned by tools is visible to the AI client. Keyring storage protects credentials at rest; it does not isolate them from other programs or agents allowed to access your unlocked keyring or the server process.
