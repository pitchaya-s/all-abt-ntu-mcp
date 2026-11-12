"""Stop lookup, caching, and search validation."""

import time

from .. import parser
from ..models import OmnibusError, Stops
from .constants import _ROUTE_CODES, _STOP_CACHE_TTL_SECONDS


class StopMethods:
    def _stop_records(self, route_codes=None):
        codes = route_codes or _ROUTE_CODES
        if any(code not in _ROUTE_CODES for code in codes):
            raise OmnibusError(
                "Choose a campus shuttle route or service 179, 179A, or 199."
            )
        records, urls, retrieved_times = [], [], []
        all_cached = True
        for code in codes:
            # Share stop metadata across lookups without caching live estimates.
            # The fixed route keys bound this cache to eight entries per client.
            with self._lock:
                entry = self._stop_cache.get(code)
                if (
                    entry is None
                    or time.monotonic() - entry[0] >= _STOP_CACHE_TTL_SECONDS
                ):
                    is_lta = code in {"179", "179A", "199"}
                    data, url = self._post(
                        "DataActionGetPickupCheckPoints",
                        "MainFlow.Shuttle",
                        screen_variables=dict(
                            self._empty_map_variables(),
                            RouteId=code,
                            IsSBS_Route=is_lta,
                        ),
                        client_variables=self._client_variables(code),
                    )
                    stops = parser.pickup_stops(data, code, is_lta)
                    entry = (time.monotonic(), self._now(), stops, url)
                    self._stop_cache[code] = entry
                    all_cached = False
                _, retrieved_at, stops, url = entry
                records.extend(stop.model_copy(deep=True) for stop in stops)
                urls.append(url)
                retrieved_times.append(retrieved_at)
        return records, list(dict.fromkeys(urls)), min(retrieved_times), all_cached

    def list_stops(self, query, route_code, limit, offset):
        self._query(query)
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or offset < 0
        ):
            raise OmnibusError("Use a limit from 1 to 100 and a nonnegative offset.")
        records, urls, retrieved_at, cached = self._stop_records(
            [route_code] if route_code else None
        )
        folded_query = query.casefold().strip()
        filtered = [
            stop
            for stop in records
            if not folded_query
            or folded_query in stop.name.casefold()
            or folded_query in stop.stop_code.casefold()
        ]
        page = filtered[offset : offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(filtered) else None
        return Stops(
            retrieved_at=retrieved_at,
            source_urls=urls,
            cached=cached,
            stops=page,
            total_count=len(filtered),
            next_offset=next_offset,
        )

    @staticmethod
    def _query(query):
        if (
            not isinstance(query, str)
            or len(query) > 120
            or any(ord(c) < 32 or ord(c) == 127 for c in query)
        ):
            raise OmnibusError(
                "Use at most 120 search characters without control characters."
            )
