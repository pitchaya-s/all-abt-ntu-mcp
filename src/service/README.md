# Campus services

Read-only access to NTU's published food, retail, clinic, and service directory. No credentials or Chromium required.

## Tools

### `service_search`

Optional inputs: `query`, `type_id`, `category_id`, `location_contains`, `limit`, `offset`, and `refresh`.

`query` matches a case-insensitive substring of a location's name or address. `location_contains` additionally filters its address. Each accepts up to 200 characters. Omit both to browse. `type_id` and `category_id` must be current IDs from `service_list_filters`.

```json
{"query": "clinic"}
```

```json
{"query": "coffee", "location_contains": "North Spine", "limit": 10}
```

The API ignores keyword parameters, so the client collects every page within the selected type/category before applying these substring filters locally. `limit` defaults to 20, maximum 100. Follow `next_offset` for remaining matches.

Each location includes its name, address, published operating hours, phone, fax, email, and map URL where supplied. Missing or blank values become `null`. Hours retain published wording, including holiday exceptions; they are not converted into an open-now guarantee.

Results include `total_count` after local matching, `directory_count` before local matching, and `pages_checked`. The latter covers all pages for the selected source filters. Collection stops with an error if pages are missing, inconsistent, duplicated, or exceed the 50-page safety limit; no partial directory is presented as complete.

### `service_list_filters`

Optional input: `refresh`.

Returns `types` and `categories`, each containing labels and IDs extracted from the official form. Types include food and beverages, retail, clinics, and services. Categories include the site's published dietary/general labels. Pass a returned `id` to the corresponding search argument.

**NTU's taxonomy assignments are incomplete.** During testing, the clinic and halal category filters returned no entries, even though the unfiltered directory contained a clinic and locations whose names mentioned halal certification. A zero-result source filter does not establish that no relevant services exist. Prefer an unfiltered keyword search when coverage matters. Published dietary labels are not independent verification of current certification.

## Requests and limitations

Results include `retrieved_at`, `source_url`, and `cached`. Pages are cached in memory for five minutes. For a collected directory, `retrieved_at` is the oldest page timestamp, `cached` is true only when every result page came from cache, and `source_url` identifies the first page. `refresh: true` fetches every page again.

The shared public HTTP client pools connections, bounds responses to 8 MB, uses a 20-second timeout, and permits up to two in-flight requests per client with 250 ms default pacing. Later directory pages are fetched with bounded concurrency, and results remain in source page order. Subsequent searches reuse cached pages. Public HTTP settings are documented in the [shared runtime guide](../shared/README.md#public-http-reads). Published hours, contact information, and map links can become outdated; the directory does not establish live opening, occupancy, accessibility, or booking availability.

## Sources

- [NTU general directory](https://www.ntu.edu.sg/life-at-ntu/leisure-and-dining/general-directory/) supplies filter labels and IDs.
- [GetLocations](https://www.ntu.edu.sg/life-at-ntu/leisure-and-dining/general-directory/GetLocations/) returns location cards, twelve per page. Verified parameters: `page`, `locationTypes`, and `locationCategories`. The tested `listingKeyword` parameter was ignored; keyword and address matching are therefore local.

## Tests

Run from the repository root:

```sh
uv run python -m unittest discover -s tests/service -t . -v
uv run python -m tests.service.live_smoke
```

Synthetic offline fixtures cover later-page keyword matches, source taxonomy gaps, address filtering, result pagination, missing contact fields, changing/malformed responses, and MCP schemas and errors. The opt-in live stdio smoke checks complete directory retrieval, keyword and location searches, a working source filter, pagination, and caching. It prints statuses without saving directory records.
