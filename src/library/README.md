# NTU Library tools

Catalogue discovery and library facility information in the shared `all-abt-ntu-mcp` server. Public tools need no credentials or API key. Detailed facility schedules use the shared native-keyring credentials and optional Chromium installation. See the [main README](../../README.md) for installation and client configuration.

## Tools

Results are typed and include `retrieved_at`, `source_url`, and `cached`. The shared public HTTP client caches responses for five minutes, bounds the cache to 64 entries, serializes requests at least 500 ms apart, applies a 20-second timeout, retries transient failures once, and limits each response to 8 MB. Public tools do not access account cookies, the keyring or a browser.

### `library_search`

Required: `query`. Optional: `field`, one of `any`, default, `title`, `creator`, `isbn`, `issn`, or `sub`; `match`, `contains`, default, or `exact`; `resource_type`; `limit`, 1–50, default 10; `offset`, default 0; and `refresh`.

Searches NTU's configured `Everything` tab with `MyInst_and_CI` scope, combining local records and the central discovery index. A result does not establish ownership, subscription entitlement, or full-text access. `resource_type` is a Primo resource-type facet token, such as `books` or `articles`.

Returns concise titles, resource types, authors, publication dates, canonical record IDs, search contexts, catalogue links, and published access signals. Follow `next_offset` until `null`. Local and central-index counts remain unknown when the source omits them. The service can limit deep paging; refine the query rather than assuming all millions of matches can be collected.

```json
{"query": "algorithms", "resource_type": "books", "limit": 5}
```

```json
{"query": "9780262046305", "field": "isbn", "match": "exact"}
```

Search text must be nonblank, at most 500 characters, and contain no semicolons or control characters, which could alter Primo's multi-clause query syntax. Use the structured field/match inputs for these lookups.

### `library_get_record`

Required: `record_id`. Optional: `context`, `L`, default, for local records, or `PC` for central-index records; and `refresh`.

Copy both values from search results. Returns bibliographic metadata including alternate titles, contributors, publishers, editions, languages, subjects, descriptions, ISBN/ISSN/DOI identifiers, and published access links when supplied. Search-highlight HTML and the secondary `$$Q` indexing form are removed from visible text. Cover-thumbnail links are omitted.

Primo's internal `@id` link can contain a numeric source ID that does not work for record retrieval. The tool uses the canonical PNX `control.recordid`, including prefixes such as `alma`, and supplies `adaptor=Primo Central` for central-index retrieval. An HTTP 200 response with an empty record set is treated as not found.

`open_access`, `availability_codes`, and `availability_label` preserve separate source statements. In testing, the source could simultaneously report open-access or `not_restricted` metadata and a display label of `Not available`. Those values are returned without converting them into a confirmed available copy or anonymous download entitlement. Missing fields remain `null`.

### `library_get_availability`

Required: `record_id`. Optional: `context`, default `L`, and `refresh`.

Returns published physical holdings with library, sublocation, call number and source availability. Electronic records can include institutional service links and access notes, such as concurrent-user or download restrictions. Service links come from the same resolver used by OneSearch. The tool does not follow them, download licensed books or verify subscription entitlement. Missing holdings/services do not establish that none exist. Copy-level counts, personal loans and hold requests are not exposed.

### `library_list_facilities`

Optional: `refresh`. Lists facilities by library, floor-map identifiers, direct room IDs or location/group IDs, and published closure notices from the LibFacilities homepage.

### `library_get_map_availability`

Required: `map_slug` from the directory, `date` as `YYYY-MM-DD`, and `time` as `HH:MM`. Optional: `refresh`.

Returns public seat/room booking statuses for that Singapore date and time: `available`, `available_later`, `unavailable`, or `unknown`. Original numeric source statuses are retained; non-bookable map amenities are excluded. Availability at one instant is not availability throughout an interval or actual occupancy.

### `library_get_facility_schedule`

Required: `date` as `YYYY-MM-DD`, and either `space_id` or both `location_id` and `group_id`, copied from facility results. Optional: `refresh`.

Uses saved NTU student network credentials to read a facility's description and daily room/seat time grid. Slots have `available` or `unavailable` status, matching the page's verified `formatEventsForFullCalendar` convention: a nonempty `className` marks unavailability, and an absent/empty class marks availability. Original classes remain in `source_classes`. Adjacent slots with identical classes are combined without losing timing information. Omitted intervals remain unknown. All times include Singapore's UTC offset. Booking identities and checksums are excluded.

The browser starts only for authenticated calls and is reused with in-memory cookies. Results are cached in memory for 60 seconds, with at most 32 entries; deleting or updating keyring credentials invalidates access to cached personal results. Session expiry initiates a fresh login, with a one-minute cooldown against repeated password submissions. CAPTCHA, MFA, unexpected login hosts and rejected credentials stop the operation. Staff/NIE login formats are not verified. No booking, cart, checkout, loan, hold or renewal action is exposed.

One request covers one day and up to 180 resources, following resource pages. For larger groups, request a particular `space_id`. Empty grids do not prove spaces are free or within the booking window.

## Sources and endpoint choice

The deployment is linked from [NTU Library](https://www.ntu.edu.sg/education/libraries/); see also the [NTU OneSearch guide](https://libguides.ntu.edu.sg/OneSearch).

| Endpoint | Purpose |
| --- | --- |
| `https://ntu-sp.primo.exlibrisgroup.com/primaws/rest/pub/pnxs` | Catalogue search |
| `https://ntu-sp.primo.exlibrisgroup.com/primaws/rest/pub/pnxs/{context}/{record_id}` | Local or central-index record details |
| `https://ntu-sp.primo.exlibrisgroup.com/primaws/rest/pub/edelivery/{record_id}` | Published institutional full-text services and access notes |
| `https://libcalendar.ntu.edu.sg/` | Facility directory and notices |
| `https://libcalendar.ntu.edu.sg/map/{slug}` | Public floor-map configuration |
| `https://libcalendar.ntu.edu.sg/maps/search/spaces` | Public date/time map availability |
| `https://libcalendar.ntu.edu.sg/space/{id}` and `/spaces?lid=…&gid=…` | Authenticated facility descriptions and resource configuration |
| `https://libcalendar.ntu.edu.sg/spaces/availability/grid` | Read-only daily time-grid query |

LibFacilities redirects through `au.libauth.com` to NTU's `loginfs.ntu.edu.sg/adfs/ls/` login. The implementation submits the saved password only to that NTU host using the verified student network-account format, and reuses the resulting session. The time-grid POST is a read query matching the page's request; booking endpoints are not called. OneSearch's separate Microsoft login required MFA during testing, so authenticated OneSearch account access and licensed full-text retrieval are not implemented.

Search parameters include `vid=65NTU_INST:65NTU_INST`, `tab=Everything`, `scope=MyInst_and_CI`, `q={field},{match},{query}`, `limit`, and `offset`. Resource filtering uses `qInclude=facet_rtype,exact,{resource_type}`.

The supplied `/rest/pub/pnxs` and `/rest/external/pnxs` endpoints were compared with an algorithms search, exact ISBN, and an article-filtered machine-learning search. Ordered canonical record IDs and total counts matched in those samples. The first two samples also had identical record payloads; the article comparison differed in some source, facet, ranking, and delivery metadata. This does not prove universal equivalence.

The implementation uses `/pub/pnxs` consistently because its search and both local/central record-detail workflows were verified. It avoids duplicate requests and does not switch endpoints to evade service errors. The separate Ex Libris API-key gateway is not used.

The [Ex Libris PNX API documentation](https://developers.exlibrisgroup.com/primo/apis/webservices/rest/pnxs/) and [search documentation](https://developers.exlibrisgroup.com/primo/apis/docs/primoSearch/R0VUIC9wcmltby92MS9zZWFyY2g%3D/) explain the general PNX/search conventions; the deployment-specific public routes and response formats were tested directly.

## Tests

Offline tests use synthetic catalogue and facility responses and cover normalization, query encoding, pagination, canonical IDs, the central adaptor, missing data, conflicting access signals, input rejection, source-status preservation, compact time grids, credential-cache checks, error redaction, and MCP schemas:

```sh
uv run python -m unittest discover -s tests/library -t . -v
```

Opt-in live stdio checks search pages, local and central record details, resource filtering, and ISBN search. Only statuses are printed:

```sh
uv run python -m tests.library.live_smoke
```

To also query a facility schedule using saved local credentials and Chromium:

```sh
uv run --extra personal python -m tests.library.live_smoke --personal
```

Live tests print statuses and counts only; they do not save credentials, bookings or account records.

## Limitation

These deployment-specific endpoints and HTML structures may change. No authenticated OneSearch account, loans, reservations, renewals, licensed file downloads or live copy-level loan checks are implemented. Catalogue and facility statuses are snapshots and may be incomplete or inconsistent. Personal facility reads stop at MFA/CAPTCHA; no bypass is attempted.
