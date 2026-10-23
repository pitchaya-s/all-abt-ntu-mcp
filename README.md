# All About NTU MCP

An MCP server for NTU Singapore schedules, learning materials, campus navigation, research, faculty, library discovery, news, and campus services.

[STARS](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/stars/README.md) · [NTULearn](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/ntulearn/README.md) · [MazeMap](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/mazemap/README.md) · [DR-NTU](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/drntu/README.md) · [Library](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/library/README.md) · [Faculty](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/faculty/README.md) · [News](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/news/README.md) · [Campus services](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/service/README.md).

For local stdio usage, install [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer. Run the public tools from PyPI:

```sh
uvx --from all-abt-ntu-mcp==0.1.0-beta.1 all-abt-ntu
```

The client examples below include the `personal` extra for authenticated tools.

## Custom MCP for Cloud AI

In a cloud AI client that supports custom remote MCP servers:

1. Open the MCP or connector settings and add a server with any name you like.
2. Enter this server URL:

   ```text
   https://all-abt-ntu-mcp.vercel.app/mcp
   ```

3. Select **No authentication** and, if asked, **Streamable HTTP** as the transport.
4. Save and enable the server.

The hosted server provides **public tools only**. No NTU credentials are needed. Personal tools, such as NTULearn and saving STARS plans, require the local setup below.

## Chromium

For authenticated STARS, NTULearn and LibFacilities tools, install Chromium once:

```sh
uvx --from 'playwright>=1.50,<2' playwright install chromium
```

## Credentials

Public tools need no credentials. For personal tools, opt into native OS keyring storage by running this **yourself in a local terminal**:

```sh
uvx --from all-abt-ntu-mcp==0.1.0-beta.1 all-abt-ntu auth save
```

Your password is hidden while typing and stored encrypted in your OS keyring, rather than in plaintext files. The server never includes it in MCP responses sent to the LLM.

The prompts save one account for STARS, NTULearn and LibFacilities and enable automatic login/session recovery. Run `auth save` again to update it, `auth status` to check storage without revealing credentials, or `auth delete` to remove it. Replace `auth save` at the end of the command above with the action you want.

The keyring must be available and unlocked: Secret Service or KWallet on Linux, Keychain on macOS, Credential Manager on Windows. There is no plaintext fallback. Passwords are not accepted through MCP, command arguments, environment variables, `.env`, or client configuration. Remove any credentials left in your old configuration; the server no longer reads them. More details: [shared credential storage](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/shared/README.md#credential-storage).

Some Linux installations do not include a keyring service. Install a provider such as GNOME Keyring or KWallet using your distribution's package manager, then follow your desktop's setup instructions to start and unlock it before running `auth save`.

## Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.all-abt-ntu-mcp]
command = "uvx"
args = ["--from", "all-abt-ntu-mcp[personal]==0.1.0-beta.1", "all-abt-ntu"]
env_vars = ["DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"] # for Linux
startup_timeout_sec = 120
tool_timeout_sec = 240
```

Restart Codex and check `codex mcp list`. Personal tools use your locally saved keyring account. The `env_vars` line forwards the Linux desktop session needed for keyring access; start Codex from a terminal where `auth status` succeeds. These variables contain no NTU credentials.

## Claude Code

Register for your user:

```sh
claude mcp add --scope user all-abt-ntu-mcp \
  -- uvx --from 'all-abt-ntu-mcp[personal]==0.1.0-beta.1' all-abt-ntu
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
      "command": ["uvx", "--from", "all-abt-ntu-mcp[personal]==0.1.0-beta.1", "all-abt-ntu"],
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
git clone --branch main https://github.com/pitchaya-s/all-abt-ntu-mcp.git all-abt-ntu-mcp
cd all-abt-ntu-mcp
uv sync
uv run all-abt-ntu
```

For personal tools, run `uv sync --extra personal`, then `uv run all-abt-ntu auth save` in your own terminal. Use `uv run all-abt-ntu auth status` or `auth delete` to inspect storage status or remove the account. These commands manage credentials; starting the server still uses `uv run all-abt-ntu`.

The process uses MCP stdio, so it stays open while its MCP client is connected. Course responses are cached in memory for one hour by default; vacancy snapshots are cached for at most 60 seconds. Set `NTU_CACHE_TTL_SECONDS` to change the cache time or use `0` to disable caching.

## Source layout

```text
src/
├── shared/                 Local/public runtimes, HTTP app, keyring, and parsing
├── stars/
│   ├── mcp_server.py        STARS tool registration and input schemas
│   ├── personal_tools.py    Local authenticated STARS tools
│   ├── room_tools.py        Teaching-based room tool registration
│   ├── room_schemas.py      Typed room constraints and results
│   ├── domain/             Course models, timetable matching and room searches
│   ├── client/             Public NTU requests and caching
│   ├── parser/             Schedule and personal-page parsing
│   └── wish/               WISH login and saved-plan editing
├── ntulearn/
│   ├── mcp_server.py        NTULearn tool registration and input schemas
│   ├── models/             Typed responses grouped by domain
│   ├── client/             Login, sessions, and REST requests
│   ├── parser/             Response and document parsing
│   └── services/           Content, files, mailbox, people, and activity
├── mazemap/
│   ├── mcp_server.py        Public map tool registration and input schemas
│   ├── models.py           Typed place and direction responses
│   ├── client.py           HTTP requests, pacing, and caching
│   └── parser.py           Place and route normalization
├── drntu/
│   ├── mcp_server.py        Public repository tool registration and schemas
│   ├── models.py           Shared metadata, snapshots, and errors
│   ├── rest/               DSpace search, files, and Dataverse datasets
│   └── oai/                OAI-PMH client, parser, models, and service
├── library/
│   ├── mcp_server.py        Library tool registration and schemas
│   ├── personal_tools.py    Local authenticated facility tool
│   ├── models.py           Catalogue, access and facility responses
│   ├── client.py           OneSearch requests and pagination
│   ├── facilities.py       Public facility directory and map availability
│   ├── session.py          Optional facility login and daily time grids
│   ├── schedule.py         Time-grid validation and normalization
│   └── parser.py           Primo record normalization
├── faculty/
│   ├── mcp_server.py        Public faculty tools and input schemas
│   ├── models.py           Typed profile and research-interest responses
│   ├── client.py           Directory requests, filters, and pagination
│   └── parser.py           Profile cards and interest form parsing
├── news/
│   ├── mcp_server.py        Public news tools and input schemas
│   ├── models.py           Typed story, category, and article responses
│   ├── client.py           News search and bounded article retrieval
│   └── parser.py           Story cards and article body extraction
└── service/
    ├── mcp_server.py        Public campus service tools and input schemas
    ├── models.py           Typed location and filter responses
    ├── client.py           Complete directory collection and local search
    └── parser.py           Contact, hours, and map normalization
tests/
├── stars/                  STARS tests and fictionalized fixtures
├── ntulearn/               NTULearn tests and synthetic fixtures
├── mazemap/                MazeMap tests and synthetic fixtures
├── repository/             DR-NTU tests and synthetic fixtures
├── library/                OneSearch and LibFacilities tests and fixtures
├── faculty/                Faculty directory tests and synthetic fixtures
├── news/                   News search and article tests with synthetic fixtures
├── service/                Campus directory tests and synthetic fixtures
├── hosted/                 Public HTTP protocol, isolation, and deployment checks
├── test_*.py               Keyring, local CLI, and shared lifecycle tests
└── typescript_smoke.mjs     Shared MCP interoperability check
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
| `stars_find_available_rooms` | Teaching-observed rooms with no scheduled classes in a time/week window | No |
| `stars_get_room_schedule` | Courses, indexes and lessons using a room | No |
| `stars_get_graduate_course_schedule` | Graduate course class groups and scheduled sessions | No |
| `stars_get_undergraduate_exam_schedule` | Undergraduate exam date, time, duration, and published-term notice | No |
| `stars_auth_status` | Whether optional WISH credentials are configured and a session has been verified | No |
| `stars_get_stars_planner` | Your registered courses and saved Plans 1–3 with timetables | Yes |
| `stars_save_stars_plan` | Replace a saved plan's course/index list and verify the saved result | Yes |
| `stars_get_degree_audit` | Your AU requirements, results, and registered courses | Yes |

Vacancies are available **09:00–22:00 Singapore time**; unknown counts are `null`. Saving a plan replaces its entire course/index list. See the [STARS guide](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/stars/README.md) for parameters, examples, and sources.

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

Start with `ntulearn_list_courses`, then use the returned IDs. See the [NTULearn guide](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/ntulearn/README.md) for parameters, examples, and sources.

### MazeMap

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `mazemap_list_campuses` | NTU campuses and their map IDs | No |
| `mazemap_list_buildings` | Buildings and floor IDs, names, and levels | No |
| `mazemap_search_places` | Find rooms, venues, and amenities by code or name | No |
| `mazemap_get_place` | One place's location, aliases, building, and floor | No |
| `mazemap_get_directions` | Walking instructions, distance, time, and accessibility | No |

Search for a place first, then use its POI ID for details or directions. See the [MazeMap guide](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/mazemap/README.md) for parameters, examples, and sources.

### DR-NTU

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `drntu_search` | Find publications by keywords, repository scope, and facet filters | No |
| `drntu_get_item` | Published metadata, abstracts, citations, and rights | No |
| `drntu_browse` | Explore communities, subcommunities, and collections | No |
| `drntu_get_facets` | Available search filters, values, and result counts | No |
| `drntu_list_bundles` | An item's file groups, including original documents | No |
| `drntu_list_files` | File names, sizes, checksums, rights, and content links | No |
| `drntu_get_dataset` | Published dataset metadata, versions, and file inventories | No |
| `drntu_oai_identify` | Repository identity, date precision, and deletion policy | No |
| `drntu_oai_list_metadata_formats` | Available OAI metadata formats and schemas | No |
| `drntu_oai_list_sets` | OAI collection and community sets | No |
| `drntu_oai_list_records` | Metadata or identifiers filtered by modification date and set | No |
| `drntu_oai_get_record` | One record by its OAI identifier | No |

Public metadata can describe restricted files. See the [DR-NTU guide](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/drntu/README.md) for parameters, examples, and sources.

### Library

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `library_search` | Search OneSearch by keywords, title, author, ISBN, or resource type | No |
| `library_get_record` | Bibliographic metadata, identifiers, descriptions, and access links | No |
| `library_get_availability` | Physical holdings and institutional full-text service links | No |
| `library_list_facilities` | Library facilities, floor maps, and closure notices | No |
| `library_get_map_availability` | Seat and room statuses at a Singapore date and time | No |
| `library_get_facility_schedule` | Daily room and seat time grids and facility descriptions | Yes |

Use the returned record ID and context for details. See the [Library guide](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/library/README.md) for parameters and access limitations.

### Faculty

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `faculty_search` | Find faculty by name or research interest, with public profile details | No |
| `faculty_list_interests` | Research-interest labels and IDs for faculty search | No |

See the [Faculty guide](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/faculty/README.md) for parameters, pagination, and sources.

### News

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `news_search` | Search news by keyword, category, and latest or oldest order | No |
| `news_list_categories` | Published news category labels and filter IDs | No |
| `news_get_article` | Read an article's text in bounded chunks | No |

See the [News guide](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/news/README.md) for parameters and sources.

### Campus services

| Tool | Purpose | Credentials |
| --- | --- | --- |
| `service_search` | Find food outlets, shops, clinics, and services with hours and contacts | No |
| `service_list_filters` | Official directory type and category filter IDs | No |

See the [Campus services guide](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/service/README.md) for parameters and directory coverage.

## Tests

Personal-data, map, repository, library, faculty, news, and service fixtures are synthetic. Timetable fixtures use fictional course labels and indexes while retaining the HTML structures needed for parser tests. Opt-in live tests print counts and statuses; they do not save academic records or learning materials in the repository.

The offline tests cover keyring storage and failure handling, local credential prompts, session recovery, parsing, scheduling, lossless compaction, output-schema validation, tool calls/errors, and resource discovery. Protocol tests use Python SDK clients and an independent JSON-RPC client over stdio, including protocol versions `2025-06-18` and `2025-11-25`:

```sh
uv run python -m unittest discover -s tests -t . -v
```

An optional check uses the official TypeScript SDK. Node dependencies stay in a temporary directory:

```sh
NTU_MCP_TEST_SDK="$(mktemp -d)"
npm install --prefix "$NTU_MCP_TEST_SDK" --ignore-scripts --no-audit --no-fund @modelcontextprotocol/sdk@1.32.1
uv run node tests/typescript_smoke.mjs "$NTU_MCP_TEST_SDK"
```

These interoperability checks use offline fixtures and never edit saved plans.

Hosted HTTP checks cover public-only registration, rejected personal calls, output schemas, both modern and legacy Python SDK clients, Host/Origin validation, request-size limits, and independent serverless event loops. See the [HTTP test instructions](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/shared/README.md#http-tests) for the TypeScript client and opt-in live smoke.

Live checks and service-specific testing instructions: [STARS](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/stars/README.md#tests) · [NTULearn](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/ntulearn/README.md#tests) · [MazeMap](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/mazemap/README.md#tests) · [DR-NTU](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/drntu/README.md#tests) · [Library](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/library/README.md#tests) · [Faculty](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/faculty/README.md#tests) · [News](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/news/README.md#tests) · [Campus services](https://github.com/pitchaya-s/all-abt-ntu-mcp/blob/main/src/service/README.md#tests).

## Limitation

- Access depends on service availability and NTU permissions.
- Timetables are published schedules; vacancies are snapshots.
- NTULearn may restrict content, and large collections can return partial results. Inline document reading extracts text without OCR.
- MazeMap directions are estimates. Map data does not establish room availability or current physical access.
- DR-NTU file metadata does not establish download permission. The dataset service may interrupt requests with CAPTCHA.
- Room searches cover published undergraduate teaching only, excluding occupancy, graduate classes, exams, other bookings, and access permissions. Unplaced lesson venues remain outside room-specific coverage.
- Library records and access labels do not establish subscription entitlement, anonymous full-text access, or a loanable copy.
- Facility booking statuses do not establish occupancy. MFA stops library login; no borrowing or facility bookings are submitted.

## Disclaimer

This is an independent project and is not affiliated with, sponsored by, or endorsed by Nanyang Technological University (NTU), Singapore.

Your NTU credentials are retrieved locally from your OS keyring and submitted over HTTPS to NTU or its Microsoft sign-in service. They are never returned through MCP. Academic data returned by tools is visible to the AI client. Keyring storage protects credentials at rest; it does not isolate them from other programs or agents allowed to access your unlocked keyring or the server process.
