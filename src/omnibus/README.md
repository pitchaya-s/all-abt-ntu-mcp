# NTU Omnibus

Read-only public access to NTU shuttle routes, stop associations, live vehicle positions, arrival estimates, schedules, and service notices. No NTU credentials or extra dependencies are needed.

The client reads NTU Omnibus' current module manifest and JavaScript bundles to discover screen-service paths and version hashes. It caches that endpoint metadata and route-stop associations for five minutes and uses a small cookie jar for the app's anonymous CSRF handshake. The stop cache holds at most eight routes per client and is shared by stop searches and arrival lookups. Live bus positions, arrival estimates, and status responses are not cached. Requests are serialized and paced at least 250 ms apart, with a 20-second timeout and an 8 MB response limit.

## Tools

### `omnibus_get_live_buses`

Input: `route_code` (`Blue`, `Brown`, `Green`, `Grey`, or `Red`), default `Blue`.

Returns bus positions, speed/direction and available crowd data for one selected route. `reported_bus_count` and `buses` can be empty. `source_timestamp` may be `null` when NTU publishes its placeholder timestamp; `retrieved_at` is when this MCP fetched the snapshot.

### `omnibus_list_routes`

Returns the app's campus shuttle routes and published route colors. The route-list action currently lists Blue, Brown, Green, Grey, and Red. It does not supply route path geometry.

### `omnibus_list_stops`

Inputs: optional `query` (stop name or code), `route_code` (campus route or `179`, `179A`, `199`), `limit` (1–100, default 20), and `offset` (default 0).

Returns matching route-stop associations, with `total_count` and `next_offset`. A stop associated with more than one route can appear more than once. `cached` is true when every requested route came from the stop cache; `retrieved_at` is the oldest contributing route snapshot, including when fresh and cached routes are combined.

### `omnibus_get_arrivals`

Inputs: optional `route_filter` (campus route or `179`, `179A`, `199`), `stop_query`, and `source` (`all`, `shuttle`, or `lta`; default `all`).

Returns `shuttle_arrivals` and `lta_arrivals` separately. LTA minute estimates are retained; seconds/load are null when the public per-stop action does not publish them. `IsETA_NotFound` becomes null estimates rather than a zero-minute arrival. A call fetches at most 20 matching route-stop pairs; broader matches return an explicit error asking for a narrower stop/route filter. Services 179, 179A and 199 are exposed by the arrival and stop tools, not the campus shuttle vehicle-position endpoint. Estimates may be unavailable.

### `omnibus_get_service_status`

Input: `route_code` (campus route), default `Blue`.

Returns published first/last bus schedule rows, whether the app used its local schedule table, public-holiday and special-day flags, and temporary service messages. Schedules and notices are source data, not a live guarantee of operation.

## Sources and coverage

The app is hosted at [apps.ntu.edu.sg/NTUOmnibus](https://apps.ntu.edu.sg/NTUOmnibus/). Its current module manifest and public bundles are used to discover endpoint paths and API hashes at runtime. Reads use the same public map actions as the deployed Shuttle page; unused BusStop component endpoints reject requests and are not used. The client reads these screen services:

- `DataActionGetActiveBusServicesData` for live shuttle positions.
- `DataActionGetRoutesList` and `ActionGetRoutesCodejson` for route names and colors.
- `DataActionGetPickupCheckPoints` with the selected route and shuttle/LTA flag for route-stop associations.
- `ActionGetETAAndNextETA_FMS` and `ActionGetETAAndNextETA_LTA` for live estimates at each matching stop.
- `ActionGetRoutesMinMax`, `ActionCheckPHSpecialDay`, and `ActionGetTempMessages` for schedules and status.

Route path geometry is outside the current tool outputs. A missing vehicle or arrival in a snapshot does not establish that a route is not operating.

## Checks

Synthetic tests cover native route IDs and input flags, stop-cache reuse and expiry, cache isolation and concurrent reads, fresh arrival estimates, per-source arrival lookups, missing estimates, result limits, endpoint discovery, CSRF recovery, bounded HTTP reads, schemas and public HTTP integration. Live reads verified all five tools, including shuttle and LTA estimates.
