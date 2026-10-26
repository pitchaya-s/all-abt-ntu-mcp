# News

Read-only tools for NTU's public news listing and article pages. No credentials or Chromium required.

## Tools

### `news_search`

Optional inputs: `query`, `category_id`, `sort`, `page`, and `refresh`.

Search by keyword, up to 200 characters, or omit `query` to browse. `sort` is `latest`, the default, or `oldest`. `category_id` must be an ID from `news_list_categories`. Pages start at 1 and contain up to ten stories. Follow `next_page` until it is `null`; out-of-range pages return an error because NTU otherwise reports misleading zero totals.

```json
{"query": "quantum", "sort": "latest", "page": 1}
```

Returns story titles, URLs, published dates, summaries where supplied, total counts, and pagination. Dates retain NTU's display format, such as `21 Oct 2026`. A missing summary remains `null`.

### `news_list_categories`

Optional input: `refresh`.

Lists current category labels and IDs from the official news page, including research, university, education, sustainability, and other published categories. Pass one returned `id` as `news_search.category_id`. Unknown IDs are rejected instead of returning an unfiltered listing.

### `news_get_article`

Required: `url` from a search result. Optional: `offset`, default 0; `max_chars`, default 12000 and maximum 50000; and `refresh`.

Reads one `https://www.ntu.edu.sg/news/detail/…` article and extracts its title, display date, and text. Navigation, related stories, scripts, and styling are excluded. Returns `total_characters` and `next_offset`; pass the latter as `offset` to continue reading. Text slices retain their original boundaries so consecutive slices reconstruct the extracted text.

Only supported NTU news URLs are fetched. External pages, linked PDFs, images, and video are not retrieved. Unexpected or incomplete article markup returns an error rather than unrelated page text.

## Requests and limitations

All results include `retrieved_at`, `source_url`, and `cached`. Responses are cached in memory for five minutes; `refresh: true` fetches them again. The shared public HTTP client pools connections, bounds responses to 8 MB, uses a 20-second timeout, and permits up to two in-flight requests per client with 250 ms default pacing. Public HTTP settings are documented in the [shared runtime guide](../shared/README.md#public-http-reads). Published news may be corrected or removed; cached results are snapshots.

## Sources

- [NTU news page](https://www.ntu.edu.sg/news/) supplies category labels and IDs, plus the supported sort values.
- [GetStories](https://www.ntu.edu.sg/news/GetStories/?categories=all&page=1&listingKeyword=&sort=latest) returns story cards and pagination. Verified parameters: `categories`, `page`, `listingKeyword`, and `sort`.
- Article URLs returned by the API supply the full published HTML text.

## Tests

Run from the repository root:

```sh
uv run python -m unittest discover -s tests/news -t . -v
uv run python -m tests.news.live_smoke
```

Offline tests use synthetic stories, category forms, and article markup. The opt-in live stdio smoke checks keyword search, categories, pagination, oldest-first ordering, empty results, current and older article text, chunking, and caching. It prints statuses without saving article bodies.
