from urllib.parse import urlencode
from uuid import UUID

from shared.public_http import PublicHTTPClient
from shared.sitefinity import form_options, query_text
from .models import Filters, SearchResults, ServiceError
from . import parser


DIRECTORY = "https://www.ntu.edu.sg/life-at-ntu/leisure-and-dining/general-directory/"
API = DIRECTORY + "GetLocations/"


class ServiceClient:
    def __init__(self):
        self.http = PublicHTTPClient("NTU campus service directory", ["www.ntu.edu.sg"], {"application/json", "text/html"})

    def list_filters(self, refresh=False):
        body, snapshot = self.http.get(DIRECTORY, refresh)
        return Filters(types=form_options(body, "locationTypes"), categories=form_options(body, "locationCategories"), **snapshot)

    def _page(self, type_id, category_id, page, refresh):
        params = {"locationTypes": type_id or "all", "locationCategories": category_id or "all", "page": page}
        body, snapshot = self.http.get(API + "?" + urlencode(params), refresh)
        return (*parser.locations(body, page), snapshot)

    def search(self, query="", type_id=None, category_id=None, location_contains="", limit=20, offset=0, refresh=False):
        query, location_contains = query_text(query).casefold(), query_text(location_contains).casefold()
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ServiceError("Use limit 1–100 and a non-negative offset.")
        if type_id is not None or category_id is not None:
            filters = self.list_filters(refresh)
            if type_id is not None:
                type_id = str(UUID(type_id))
                if type_id not in {item.id for item in filters.types}:
                    raise ServiceError("Unknown type_id; use service_list_filters for current IDs.")
            if category_id is not None:
                category_id = str(UUID(category_id))
                if category_id not in {item.id for item in filters.categories}:
                    raise ServiceError("Unknown category_id; use service_list_filters for current IDs.")
        rows, total, pages, snapshot = self._page(type_id, category_id, 1, refresh)
        if pages > 50:
            raise ServiceError("The directory exceeds the 50-page retrieval limit; select a type/category filter.")
        for page in range(2, pages + 1):
            items, count, page_count, current = self._page(type_id, category_id, page, refresh)
            if count != total or page_count != pages:
                raise ServiceError("The directory changed during retrieval; retry with refresh=true.")
            rows.extend(items)
            snapshot["retrieved_at"] = min(snapshot["retrieved_at"], current["retrieved_at"])
            snapshot["cached"] = snapshot["cached"] and current["cached"]
        if len(rows) != total or len({(item.name, item.address) for item in rows}) != total:
            raise ServiceError("NTU returned missing or duplicate directory entries; retry with refresh=true.")
        matches = [item for item in rows if query in " ".join([item.name, item.address or ""]).casefold()
                   and location_contains in (item.address or "").casefold()]
        end = offset + limit
        return SearchResults(locations=matches[offset:end], total_count=len(matches), directory_count=total,
                             pages_checked=max(1, pages), next_offset=end if end < len(matches) else None, **snapshot)
