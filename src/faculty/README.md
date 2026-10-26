# Faculty

Public, read-only access to NTU's faculty directory. No credentials or Chromium are needed.

## Tools

### `faculty_search`

Optional inputs: `query`, `interest_id`, `page`, and `refresh`.

`query` searches faculty names, up to 200 characters. Omit it to browse. `interest_id` selects one research interest; obtain its ID with `faculty_list_interests`. Search pages start at 1 and contain up to ten profiles. Follow `next_page` until it is `null`.

```json
{"query": "faculty member name", "page": 1}
```

Returns `profiles`, `page`, `total_pages`, `total_count`, and `next_page`. Each profile contains its published name, school, email, appointments, research interests, biography summary, and profile URL. Missing information stays `null`; summaries may be abbreviated by NTU. Profile URLs often point to DR-NTU person pages; their readable slugs are not item UUIDs accepted by `drntu_get_item`.

For pages after the first, the client checks the first page's totals, using the cache when available. NTU otherwise reports zero totals for out-of-range pages, which could be mistaken for a search with no matches. Out-of-range requests return an error.

### `faculty_list_interests`

Optional inputs: `query`, `limit`, `offset`, and `refresh`.

Lists research-interest labels and IDs from the official directory form. `query` filters labels by case-insensitive substring. `limit` defaults to 50, maximum 100. Follow `next_offset` for additional results, then pass a returned `interest_id` to `faculty_search`.

```json
{"query": "intelligence"}
```

Labels are not API filter values. Unknown IDs are rejected rather than silently returning an unfiltered directory.

## Requests and caching

Both tools include `retrieved_at`, `source_url`, and `cached`. Responses stay in memory for five minutes; `refresh: true` fetches them again. Requests use the shared pooled HTTP client with an 8 MB response bound, a 20-second timeout, up to two in-flight reads per client, and 250 ms default pacing. Public HTTP settings are documented in the [shared runtime guide](../shared/README.md#public-http-reads). Unexpected JSON, changed form structure, inconsistent pagination, and access denials return errors.

The directory covers profiles NTU publishes here; it does not establish a complete employee list, current employment, supervision availability, or contact responsiveness. No full profile pages are fetched.

## Sources

- [Faculty directory](https://www.ntu.edu.sg/research/faculty-directory/) supplies current research-interest IDs and labels.
- [GetAcademicProfiles](https://www.ntu.edu.sg/research/faculty-directory/GetAcademicProfiles/?interests=all&page=1&searchFaculty=) supplies JSON profile cards and pagination. Parameters: `searchFaculty`, `interests` set to `all` or one returned interest ID, and `page` starting at 1.

## Tests

Run from the repository root:

```sh
uv run python -m unittest discover -s tests/faculty -t . -v
uv run python -m tests.faculty.live_smoke
```

Offline tests use synthetic profiles and form options. The opt-in live stdio smoke checks name search, pagination, no matches, interest filtering, and cache reuse. It prints statuses and saves no profiles.
