# DR-NTU tools

Public publication, dataset, and OAI-PMH metadata lookups in the shared `all-abt-ntu-mcp` server. No credentials, keyring, Chromium, or extra dependencies are needed. See the [main README](../../README.md) for installation and MCP client configuration.

## Tools

All results have `retrieved_at`, `source_url`, and `cached`. Responses are cached in memory for five minutes, with at most 64 entries per REST/OAI client. `refresh: true` refetches the requested response. Each client pools HTTPS connections, permits up to two in-flight reads with 250 ms default request pacing, limits responses to 8 MB, and uses a 20-second timeout. It retries transient failures once and honors short `Retry-After` delays; longer server-requested delays return an error rather than retrying early. Public HTTP settings are documented in the [shared runtime guide](../shared/README.md#public-http-reads).

DSpace listings use zero-based `page` and `page_size` from 1–50. Follow `pagination.next_page` until `null`. Total counts remain `null` when the source omits them, as happens with individual search facets. Malformed records or inconsistent result pages fail rather than silently appearing complete.

### `drntu_search`

Required: `query`, up to 500 characters. Optional: `scope_id`, `entity_type`, `filters`, `page`, `page_size`, default 10, and `refresh`.

Searches publications by default. General DR-NTU search also returns researcher profiles; select `entity_type: "Person"` or `"all"` explicitly for those results. Each match returns the item UUID, title, entity type, authors, dates, identifiers, published rights, and repository URL. Use `drntu_get_item` for full published metadata and abstracts.

Queries support the repository's Solr syntax. `scope_id` restricts results to a community or collection UUID from `drntu_browse`. Structured filters have `field`, `value`, and `operator`, one of `equals`, `contains`, or `authority`, default `equals`. Up to ten filters are accepted; repeated fields are retained. Facet operators and field support depend on repository configuration.

```json
{"query": "machine learning", "page_size": 5}
```

```json
{"query": "machine learning", "filters": [{"field": "dateIssued", "value": "[2020 TO 2026]", "operator": "equals"}]}
```

### `drntu_get_item`

Required: `item_id`, a UUID from search results. Optional: `refresh`.

Returns title, entity type, repository URL, last-modified/withdrawn information when supplied, and a dictionary of published metadata fields. Metadata values retain their language tags. Abstracts are normally in `dc.description.abstract`; citations, DOI, subjects, degree information, and rights appear when the source provides them. Unknown field names are retained. A single title identical to the top-level title is omitted from metadata only when it has no language tag; alternative and multilingual titles remain.

Public metadata does not prove that a paper's full text is publicly downloadable.

### `drntu_browse`

Optional: `kind`, either `communities`, default, or `collections`; `community_id`; pagination; and `refresh`.

Without `community_id`, lists repository communities or collections. With a community UUID, lists its subcommunities or collections. Returns container IDs, names, published descriptions, and archived-item counts when known. DSpace's `-1` count means unavailable and becomes `null`. Use a returned `container_id` as `drntu_search.scope_id`.

```json
{"kind": "collections", "page_size": 10}
```

### `drntu_get_facets`

Optional: `facet`, `query`, `scope_id`, `entity_type`, `filters`, pagination, and `refresh`. The query/scope/filter options match search; entity type defaults to `Publication`.

Omit `facet` to discover filter definitions, such as `author`, `subject`, `dateIssued`, or `entityType`. Supply a name to get values and counts. Definitions are configuration metadata and have no result counts.

Each value includes a ready-to-use `filter` object extracted from the repository's own search link, when supplied. Copy it into `drntu_search.filters`. Display labels can differ from query values: a date label such as `2020 - 2026` may require `[2020 TO 2026]`. Authority-based values can also differ from their labels. Missing filter links remain `null`.

```json
{"facet": "dateIssued", "query": "machine learning", "page_size": 5}
```

### `drntu_list_bundles`

Required: `item_id`. Optional: pagination and `refresh`.

Returns named file groups and their UUIDs. `ORIGINAL` usually contains deposited papers; `TEXT`, `LICENSE`, and `THUMBNAIL` are different groups. Pass a returned `bundle_id` to `drntu_list_files`. Follow bundle pagination before assuming an item has no originals.

### `drntu_list_files`

Required: `bundle_id`. Optional: pagination and `refresh`.

Returns published file UUIDs, names, byte sizes, checksums, rights, and content URLs. No file bodies are fetched, and download permission is not tested. The example supplied for development has public metadata with `restricted` rights; the integration preserves those rights. Missing rights remain an empty list of published statements, which does not establish open access.

### `drntu_get_dataset`

Required: `persistent_id` in `doi:` form. Optional: `version` such as `1.0`, `limit` from 1–50, default 50, `offset`, default 0, and `refresh`.

Reads a published DR-NTU (Data) dataset's citation metadata and file inventory: title, authors, descriptions, subjects, release version/state, publication date, license, filenames, sizes, media types, directory labels, restriction flags, and checksums where provided. Omit `version` for the latest published version. Draft versions are unsupported. Unknown restriction flags remain `null`.

The dataset API returns the complete version metadata; `limit` and `offset` bound the files returned through MCP. Follow `next_offset` until `null`. Very large source responses may exceed the HTTP size limit. Additional discipline-specific dataset metadata is not exposed by this concise citation view.

```json
{"persistent_id": "doi:10.21979/N9/UD1IM9", "version": "1.0", "limit": 10}
```

HTML responses, including CAPTCHA pages with HTTP 200, and access denials stop retrieval with an actionable error. The integration does not start a browser, collect credentials, solve CAPTCHA, or reuse personal NTU sessions.

### `drntu_oai_identify`

Optional: `refresh`.

Returns the OAI repository name, base URL, protocol version, administrator contacts, earliest modification datestamp, deletion policy, date precision, response date, and repository descriptions as XML. These are public repository details, not a student's profile.

### `drntu_oai_list_metadata_formats`

Optional: `identifier`, an OAI identifier from the record tools, and `refresh`.

Lists metadata prefixes, schema URLs, and namespaces supported by the repository, or by one identifier. Schemas are reported without downloading or resolving them. The current public endpoint advertises formats including `oai_dc`, `qdc`, `mods`, and `dim`; discover available values instead of assuming a format applies to every record.

### `drntu_oai_list_sets`

Optional: `resumption_token`, `limit` from 1–50, default 20, `offset`, default 0, and `refresh`.

Lists OAI sets with `set_spec`, name, and any descriptions as XML. Set specs are OAI identifiers, not REST community/collection UUIDs. Use them as `set_spec` in record listings.

### `drntu_oai_list_records`

Optional: `metadata_prefix`, defaulting to `oai_dc` when omitted on an initial request; `set_spec`; `from_date`; `until_date`; `resumption_token`; `headers_only`, default false; `limit` from 1–50, default 10; `offset`, default 0; and `refresh`.

Uses `ListRecords`, or `ListIdentifiers` when `headers_only` is true. Date bounds are inclusive repository modification/deletion datestamps, **not publication dates**. Use valid `YYYY-MM-DD` dates or UTC `YYYY-MM-DDTHH:MM:SSZ` timestamps. When both bounds are present, their precision must match and the start must not exceed the end.

```json
{"from_date": "2026-01-01", "until_date": "2026-01-02", "limit": 5}
```

Each result preserves the OAI identifier, datestamp, set specs, and deleted status. Deleted records and identifier-only listings have no metadata. Flat Dublin Core is normalized into repeated `dc.*` fields with values and language tags. Other formats, nested metadata, and unknown field attributes retain `metadata_xml`; provenance is preserved in `about_xml`. Identifiers and rights inside metadata do not establish permission to download the underlying files. `noRecordsMatch` returns an empty result; malformed responses and other OAI errors fail clearly.

OAI pagination differs from REST pagination. NTU chooses its own response-page size; `limit` and `offset` slice that page locally. `pagination.page_count` is the number of records in that provider page, not the repository total. Follow `next_offset` using the same arguments, including the current token and filters. Once it is null, use the returned `resumption_token` with `offset: 0`, omit **all** selection filters including `metadata_prefix`, and keep `headers_only` unchanged. A null token means no further provider page. Cursor, complete-list size, and token expiration are returned only when supplied by NTU; cursor values are preserved without interpreting them as local offsets.

```json
{"resumption_token": "TOKEN_RETURNED_BY_NTU", "limit": 5}
```

Tokens are opaque and can expire. On `badResumptionToken`, restart with the original filters and `refresh: true`. The server never follows every continuation automatically or stores a harvested database.

### `drntu_oai_get_record`

Required: `identifier`. Optional: `metadata_prefix`, default `oai_dc`, and `refresh`.

Retrieves one OAI record in the same representation as record listings. Supply an OAI identifier returned by OAI listing, **not** a UUID from `drntu_search`. A deleted record preserves its header without inventing metadata.

## Sources

| Endpoint | Purpose |
| --- | --- |
| `https://dr.ntu.edu.sg/server/api/discover/search/objects` | Paginated publication/profile search, scopes, and facet filters |
| `https://dr.ntu.edu.sg/server/api/core/items/{uuid}` | Published item metadata, abstracts, and rights |
| `https://dr.ntu.edu.sg/server/api/core/communities` | Community browsing |
| `https://dr.ntu.edu.sg/server/api/core/collections` | Collection browsing |
| `https://dr.ntu.edu.sg/server/api/core/communities/{uuid}/subcommunities` | Community hierarchy |
| `https://dr.ntu.edu.sg/server/api/core/communities/{uuid}/collections` | Collections within a community |
| `https://dr.ntu.edu.sg/server/api/discover/facets` | Filter definitions |
| `https://dr.ntu.edu.sg/server/api/discover/facets/{name}` | Filter values, counts, and exact query filters |
| `https://dr.ntu.edu.sg/server/api/core/items/{uuid}/bundles` | Item file-group discovery |
| `https://dr.ntu.edu.sg/server/api/core/bundles/{uuid}/bitstreams` | File metadata and content links |
| `https://researchdata.ntu.edu.sg/api/datasets/:persistentId` | Latest dataset metadata with `persistentId=doi:...` |
| `https://researchdata.ntu.edu.sg/api/datasets/:persistentId/versions/{version}` | Explicit published dataset release |
| `https://dr.ntu.edu.sg/server/oai/request` | OAI-PMH Identify, ListMetadataFormats, ListSets, ListRecords, ListIdentifiers, and GetRecord |

The API root was checked to identify the repository's DSpace/CRIS format. Bundle details and individual bitstream metadata repeat fields already included in listings; separate format lookups were inspected but are omitted to avoid a request for every file. OAI-PMH supports incremental metadata retrieval, while the REST search tools provide keyword and facet searches.

Primary references: [DSpace REST contract](https://github.com/DSpace/RestContract), [search contract](https://github.com/DSpace/RestContract/blob/main/search-endpoint.md), [Dataverse Native API](https://guides.dataverse.org/en/6.6/api/native-api.html), and [OAI-PMH 2.0](https://www.openarchives.org/OAI/openarchivesprotocol.html). Current NTU response shapes were also checked directly over HTTPS.

## Tests

Offline parsers, pagination, filters, caching, network failures, CAPTCHA/error handling, and MCP schemas use synthetic records:

```sh
uv run python -m unittest discover -s tests/repository -t . -v
```

Opt-in live stdio checks search pages, publication filtering, item abstracts, browsing, facets and their filters, file discovery, and both dataset version endpoints. Prints statuses and never downloads research file bodies:

```sh
uv run python -m tests.repository.live_smoke
```

OAI-only live stdio checks exercise all six protocol verbs, provider continuation, date filters, alternate-format XML, empty results, and expired/invalid token errors. Prints statuses and counts without saving or printing research metadata:

```sh
uv run python -m tests.repository.live_oai_smoke
```

## Limitation

Only publicly exposed metadata is supported. No file downloads, full-text extraction, authenticated repository access, dataset search, or automatic repository-wide OAI harvesting is implemented. OAI timestamps describe repository changes, not publication dates. Continuation tokens can expire and NTU controls source-page sizes. Metadata may describe restricted or embargoed content. Dataset access can be interrupted by CAPTCHA; availability during one smoke test is not a guarantee of continued automated access.
