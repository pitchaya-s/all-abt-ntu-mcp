# NTU MazeMap tools

Public campus lookups in the shared `all-abt-ntu-mcp` server. No credentials, keyring, Chromium, or additional dependencies are needed. See the [main README](../../README.md) for installation and MCP client configuration.

## Tools

All tools return typed structured results with `retrieved_at`, `source_url`, and `cached`. Responses use the shared in-memory cache, bounded to 64 entries for five minutes. Set `refresh: true` to refetch the requested data. Pooled HTTPS connections support up to two in-flight reads per client, with request starts paced at 250 ms by default and one retry for transient failures. Public HTTP settings are documented in the [shared runtime guide](../shared/README.md#public-http-reads). There is no background map download.

### `mazemap_list_campuses`

List NTU collection campuses with `campus_id`, name, and center coordinates. Accepts optional `refresh`. Main Campus is `2123`; other campus IDs are discovered from the collection rather than hardcoded.

### `mazemap_list_buildings`

Inputs: optional `campus_id`, default `2123`; optional `query` to filter building names by a case-insensitive substring; optional `refresh`.

Returns buildings with their floor IDs, printed names, and numeric levels. Floor names and levels can differ. A building with no published floors returns an empty floor list. Large polygon coordinates are omitted.

```json
{"campus_id": 2123, "query": "North Spine"}
```

### `mazemap_search_places`

Inputs: `query`, optional `campus_id`, `limit` from 1–50, default 10; `offset` from 0–10000, default 0; optional `refresh`.

Searches rooms, venues, and amenities using MazeMap's ranked search, including room aliases. Without a campus ID it searches the `ntu-sg` collection. Results include POI and campus IDs, name, identifier, aliases, building, floor, categories, coordinates, and a map link. Missing descriptions or capacities remain `null`.

Follow `next_offset` until it is `null`. The client requests one extra match to determine whether another page exists. Results are search matches, not a complete campus room inventory. Multiple buildings may use the same tutorial-room number; select the appropriate result before routing.

```json
{"query": "TR+7", "campus_id": 2123, "limit": 5}
```

### `mazemap_get_place`

Inputs: `poi_id`, optional `refresh`.

Returns one place's published details, including description and capacity where supplied. Deleted places, mismatched IDs, and places outside NTU are rejected.

```json
{"poi_id": 1002362545}
```

### `mazemap_get_directions`

Inputs: `from_poi_id`, `to_poi_id`; optional `constraint`, one of `NO_CONSTRAINT`, `PREFER_ACCESSIBLE`, or `REQUIRE_ACCESSIBLE`; optional `refresh`.

Both POIs must belong to NTU. Returns route alternatives, distance in metres, estimated duration in seconds, English directions when available, and referenced building/floor information. Distance is summed from the published basic path steps; duration comes from MazeMap's route estimate. Accessibility and uncertain-segment flags remain unknown when the source omits them. Missing directions for any leg are reported in `issues`, and `instructions` is `null` rather than presenting an incomplete instruction list as the whole route.

```json
{"from_poi_id": 1002362545, "to_poi_id": 1002362569, "constraint": "REQUIRE_ACCESSIBLE"}
```

## Sources

| Endpoint | Used for |
| --- | --- |
| `https://api.mazemap.com/api/campuscollection/ntu-sg/?withcampuses=true` | NTU campus discovery and scope validation |
| `https://api.mazemap.com/api/buildings/?campusid=2123&srid=4326` | Building names and floor metadata |
| `https://search.mazemap.com/search/equery/` | Ranked, paginated place search scoped with `campuscollectiontag=ntu-sg` |
| `https://api.mazemap.com/api/pois/{poi_id}/?srid=4326` | Place details and routing endpoint validation |
| `https://routing.mazemap.com/routing/v2/a-to-b/` | Walking routes with `campusCollectionTag=ntu-sg`, English text, and metric units |

The supplied campus information, single-building, POI-type, floor-outline, and web configuration endpoints were also inspected. Their useful metadata is already supplied by collection/building/place responses, while polygon data and web application settings are unnecessary for these tools.

The bulk campus POI endpoint returned 2,000 entries and a limit of 2,000. Its `zlevel=1` response included rooms on other levels. The integration uses the dedicated search service instead of treating that bulk response as complete or correctly floor-filtered.

Provider documentation: [search](https://mazemap.atlassian.net/wiki/spaces/MCSH/pages/3761668097/Developers+Guide+Search+-+JS+SDK), [v2 routing](https://mazemap.atlassian.net/wiki/spaces/MCSH/pages/3304685834/Supplementary+Guide+for+Version+2+Routing+in+MazeMap+JS+API). The [older Data API reference](https://github.com/MazeMap/Data-API) is marked deprecated; current response shapes were checked directly over HTTPS.

## Tests

Offline parser, request, cache, failure, and stdio schema tests use synthetic map fixtures:

```sh
uv run python -m unittest discover -s tests/mazemap -t . -v
```

Opt-in live smoke test makes public HTTP requests through the stdio MCP server and prints only statuses:

```sh
uv run python -m tests.mazemap.live_smoke
```

## Limitation

Search is ranked and bounded; no exhaustive room inventory or free-room search is provided. Directions and accessibility depend on published map data and may differ from current access, closures, or lift operation. Maps do not indicate actual occupancy. These tools do not join maps with STARS class schedules.
