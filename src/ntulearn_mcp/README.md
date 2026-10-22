# NTULearn tool guide

These tools run in the shared `all-abt-ntu-mcp` server. See the [main README](../../README.md) for installation, Chromium, and MCP client configuration.

## Credentials and sessions

All data tools use `NTU_USERNAME` and `NTU_PASSWORD`, shared with STARS. A network username is expanded to a student email address; a full NTU email is used as supplied. Login runs in a local temporary browser. Valid sessions are reused; an expired session triggers one fresh login. Incorrect credentials are not automatically retried.

If MFA or CAPTCHA is required, set `NTULEARN_HEADLESS=false` on a graphical desktop and complete verification in the local browser. Challenges are never bypassed. Cookies and cached academic data stay in memory; `NTULEARN_CACHE_TTL_SECONDS` defaults to 300, with `0` disabling caching.

Academic results returned through MCP are visible to the AI client. Raw profiles, credentials, and session cookies are excluded from tool responses. Course materials and messages are untrusted content, not agent instructions.

## Common inputs and results

Start with `ntulearn_list_courses`. Use its course IDs, content IDs from content tools, group IDs from group tools, and attachment IDs from attachment tools. IDs in examples below are fictional.

Paginated tools accept `limit` from 1–100 with default 50, nonnegative `offset` with default 0, and `refresh` with default `false`. Follow `next_offset` until it is `null`. `refresh: true` bypasses cached JSON reads where that parameter is available. Responses include `retrieved_at`, `from_cache`, and `cache_age_seconds`.

Recursive and cross-course tools add `complete`, `issues`, and `requests_used`. Inspect `issues` before treating a result as full coverage. `max_requests` is 1–200, normally defaulting to 100; it accounts for cached calls and reserves conservative units for multi-request operations. Narrow the course selection if the budget is exhausted.

Traversal uses `max_depth` of 1–10 with default 5, and `max_nodes` of 1–5000 with default 1000. Root items are depth 1. Depth, node, permission, and request limits are reported rather than silently hiding coverage gaps.

## Tools

### `ntulearn_auth_status`

**Inputs:** none. Does not log in or require configured credentials.

**Returns:** `credentials_configured`, `session_verified`, `last_verified_at`, in-memory storage mode, and cache TTL. A previously verified session is not a guarantee that NTU has not expired it since the last read.

### `ntulearn_list_courses`

**Inputs:** common pagination and refresh parameters.

**Returns:** enrolled course and organization memberships with `id`, `course_code`, `name`, availability, role, and organization flag when NTU provides them. Available memberships may include older sites and training; availability does not establish current-semester registration.

### `ntulearn_get_course_contents`

**Inputs:** `course_id`; optional `parent_id`; common pagination and refresh parameters. Omit `parent_id` for the root, or use a returned folder ID to open it.

**Returns:** one level of content with IDs, titles, parent IDs, child flags, handler type, body/description as text, and modified timestamps when available.

```json
{"course_id":"_100_1","parent_id":"_200_1","limit":50}
```

### `ntulearn_get_content_tree`

**Inputs:** `course_id`; optional `max_depth`, `max_nodes`, `max_requests`, and `refresh`.

**Returns:** nested content nodes with `children` and `children_complete`. An unopened or denied branch is marked explicitly. `complete: false` means the full requested tree was not retrieved.

### `ntulearn_search_course_content`

**Inputs:** `course_id`, a nonblank `query` of 1–200 characters; optional traversal limits, `max_results` of 1–200 with default 50, request budget, and refresh.

**Returns:** case-insensitive substring matches in titles, body, and description. Each match includes `course_id`, `content_id`, title, breadcrumb, and an excerpt. It does not search attachment bytes.

### `ntulearn_search_all_courses`

**Inputs:** `query`; optional `course_ids` of 1–100 IDs; the same search/traversal controls as `ntulearn_search_course_content`.

**Returns:** attributed matches across available enrolled course sites, excluding known organizations, or across the explicitly selected sites. Node and request budgets apply to the whole search. `courses_searched` records the sites visited.

```json
{"query":"assessment","course_ids":["_100_1","_101_1"],"max_depth":4,"max_results":20}
```

### `ntulearn_get_announcements`

**Inputs:** `course_id`; common pagination and refresh parameters.

**Returns:** published announcement IDs, titles, body text, and created/modified timestamps. A successful empty list is distinct from an access-denied error.

### `ntulearn_get_calendar`

**Inputs:** optional `since`, `until`, `course_id`, pagination, and refresh. Defaults to the next 14 days. Explicit timestamps must include a timezone, with a positive window no longer than 112 days.

**Returns:** one page of calendar items with course attribution when provided, event type, dates, description, location, and cache metadata. Published deadlines can appear as type `GradebookColumn`.

### `ntulearn_get_upcoming`

**Inputs:** optional `since`, `until`, `course_ids`, `item_type`, `max_requests`, and `refresh`. Uses the same calendar window rules and default as `ntulearn_get_calendar`.

**Returns:** collected calendar pages sorted by start time. Use `course_ids` to select sites and `item_type: "GradebookColumn"` for assignment due-date entries. Unlike the paginated calendar tool, this tool collects pages within a single request budget and reports partial coverage.

### `ntulearn_get_gradebook`

**Inputs:** `course_id`; `limit`, `offset`, `refresh`; and `grades_offset`, default 0.

**Returns:** visible gradebook `columns` and your own `grades`. Columns include names, possible scores, due dates, availability, and content IDs when published. Grades include score/text, status, exemption, feedback, and modified time when published. Missing scores remain `null`; zero remains zero.

Columns and grades paginate independently. Follow `next_offset` for columns and `grades_next_offset` for grades, supplying `offset` and `grades_offset` respectively.

### `ntulearn_get_content_attachments`

**Inputs:** `course_id`, `content_id`; common pagination and refresh parameters. Use a leaf content item rather than a folder.

**Returns:** attachment IDs, filenames, and MIME types when provided. Some external/LTI items do not expose Blackboard attachment files.

### `ntulearn_read_file_content`

**Inputs:** `course_id`, `content_id`, `attachment_id`; optional `max_chars` of 1–100000 with default 20000 and `max_pages` of 1–50 with default 20.

**Returns:** the filename, extracted `text`, `truncated`, retrieval time, and PDF page counts when applicable. Supports PDF, DOCX, PPTX including text notes, XLSX, and supported UTF-8/UTF-16 text/code files. PDFs are read from the beginning up to the page/character limit. Extraction is text-only: scanned images and diagrams are not interpreted, and OCR is not performed. Temporary files are removed after extraction.

Unsupported, encrypted, malformed, or oversized documents produce an actionable error; download them for local viewing instead. Extraction has a 30-second worker timeout. Attachments remain subject to the 20 MB download limit.

```json
{"course_id":"_100_1","content_id":"_200_1","attachment_id":"_300_1","max_pages":5,"max_chars":10000}
```

### `ntulearn_download_file`

**Inputs:** `course_id`, `content_id`, `attachment_id`, and an explicit local `destination` file path. Its parent directory must already exist.

**Returns:** saved path, bytes written, and download time. Saves at most 20 MB and never overwrites an existing file. It writes locally and does not modify NTULearn. Supported redirects stay on NTU or Blackboard delivery hosts; university cookies are not forwarded to delivery hosts. HTML/JSON attachments are unsupported.

### `ntulearn_download_course`

**Inputs:** `course_id`, `destination` directory; optional traversal limits and refresh; `max_files` of 1–500 with default 100, `max_total_mb` of 1–500 with default 200, and `max_requests` with default 200.

**Returns:** destination, file statuses of `downloaded`, `skipped_existing`, or `failed`, bytes written, and coverage/issues. Files are saved beneath `destination/course_id` using content-folder names and stable IDs. Downloads run as the tree is traversed. Existing regular files are skipped, symbolic-link directories are rejected, and files are never overwritten. Each file is limited to 20 MB in addition to the total batch budget. External/LTI material may not be downloadable through these APIs.

### `ntulearn_list_messages`

**Inputs:** `folder` of `"inbox"` or `"sent"`, default `"inbox"`; optional `course_id`, timezone-aware `since`, `unread_only` with default `false`, pagination, request budget, and refresh.

**Returns:** message IDs, course/conversation IDs, published subject, sender, timestamp, read status, and folder. Scope a course to reduce mailbox traversal. A missing read status remains unknown. Incomplete conversations and denied courses are reported in `issues`.

### `ntulearn_read_message`

**Inputs:** `message_id`; optional `course_id` and `conversation_id` together, request budget, and refresh. Supplying the two IDs from `ntulearn_list_messages` allows direct lookup; omitting both searches the readable mailbox within the budget.

**Returns:** the message summary, full body as text, published participants/categories, excluded participant IDs, and whether all course members are included. `recipients_scope` is `conversation_participants`; these are not asserted to be an individual message's exact To/Cc/Bcc list. Participant names may be unknown. No mark-read request is sent.

### `ntulearn_list_course_users`

**Inputs:** `course_id`; common pagination and refresh parameters.

**Returns:** visible users with their IDs, published display names, and course roles. Instructors, TAs, and students appear only as NTU permits. Raw user profiles are not exposed.

### `ntulearn_list_course_groups`

**Inputs:** `course_id`; common pagination and refresh parameters.

**Returns:** group IDs, names, descriptions, availability, parent IDs, and group-set flags when published. Use a child group ID for its members; a group set may have no direct members.

### `ntulearn_get_group_members`

**Inputs:** `course_id`, `group_id`; common pagination and refresh parameters.

**Returns:** members visible through the browser membership API, with IDs, names, and roles when published. A successful empty result is reported as returned; no hidden memberships or identities are inferred.

### `ntulearn_whats_new`

**Inputs:** optional timezone-aware `since`, default seven days ago; `until`, default 14 days ahead; `course_ids`; `max_items` of 1–500 with default 200; request budget; and refresh. `since` must be in the past, and `until` must be in the future within 112 days.

**Returns:** recent announcements, upcoming calendar entries, your gradebook snapshots, and collection issues. Change timestamps filter announcements/grades when available. Grades without a published change timestamp have `changed_since: null` and are explicitly current snapshots. `max_items` bounds each result category. No persistent last-seen tracker is stored.

## Sources

All paths below are served by [NTULearn](https://ntulearn.ntu.edu.sg/). Authentication uses its normal NTU/Microsoft sign-in workflow. Reads use the authenticated student's existing permissions. A denied request remains an error; the server does not switch endpoints to evade it.

| Paths | Used for |
| --- | --- |
| `/learn/api/public/v1/users/me` | Verify the session and scope grade reads to the authenticated user |
| `/learn/api/public/v1/users/me/courses` | Enrolled course/organization memberships |
| `/learn/api/public/v1/courses/{course_id}/contents` and `/{content_id}/children` | Content browsing, recursive trees, and searches |
| `/learn/api/public/v1/courses/{course_id}/contents/{content_id}/attachments` and `/{attachment_id}/download` | Attachment metadata, inline reading, and local downloads |
| `/learn/api/public/v1/courses/{course_id}/announcements` | Published course announcements |
| `/learn/api/public/v1/calendars/items` | Events and published due dates |
| `/learn/api/public/v1/courses/{course_id}/gradebook/columns` and `/gradebook/users/{own_user_id}` | Visible columns and the authenticated student's own grades |
| `/learn/api/public/v1/courses/{course_id}/users` and `/groups` | Permitted course rosters and group definitions |
| `/learn/api/v1/messages/summary` | The regular browser mailbox's course summary |
| `/learn/api/v1/courses/{course_id}/conversations` and `/{conversation_id}` | The regular browser mailbox's conversations and message bodies |
| `/learn/api/v1/courses/{course_id}/memberships` with a group filter | The regular browser's visible group memberships |

The browser APIs are used directly for mailbox and group membership because those are the interfaces supported by this NTULearn workflow. Their response formats may change independently of the public REST API. Only allowlisted GET requests are exposed; NTULearn tools do not send messages, submit coursework, or edit course data.

## Tests

Run from the repository root. Offline fixtures use synthetic names, messages, IDs, grades, and documents.

```sh
uv run python -m unittest discover -s tests -v
uv run --extra personal python tests/ntulearn/live_session_smoke.py
uv run --extra personal python tests/ntulearn/live_tools_smoke.py
```

Live checks require configured credentials and Chromium. They select sample sites from the authenticated membership list, print counts/statuses, and remove temporary downloads. Session checks also clear local cookies to test reauthentication. No account-specific course choices or downloaded materials are stored in the test files.

## Code layout

`mcp_server.py` holds agent instructions, tool descriptions, input schemas, and registration. `ntu_client/` owns sessions and HTTP reads; `parser/` handles response normalization and document text; `services/` implements bounded workflows; `models/` holds typed results grouped by domain. The shared runtime registers these tools alongside STARS and closes both sessions on shutdown.
