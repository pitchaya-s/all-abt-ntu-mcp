import json
from urllib.parse import quote, urlencode, urljoin, urlsplit

from shared.public_http import PublicHTTPClient

from . import parser
from .models import Availability, ElectronicService, Holding, LibraryError, RecordDetails, SearchResults


BASE = "https://ntu-sp.primo.exlibrisgroup.com/primaws/rest/pub/pnxs"
VIEW = "65NTU_INST:65NTU_INST"


class LibraryClient:
    def __init__(self):
        self.http = PublicHTTPClient(
            "NTU Library OneSearch", ["ntu-sp.primo.exlibrisgroup.com"], {"application/json"}
        )

    def get(self, path, parameters, refresh=False):
        url = BASE + path + "?" + urlencode({"vid": VIEW, **parameters})
        body, snapshot = self.http.get(url, refresh)
        data = json.loads(body)
        if not isinstance(data, dict):
            raise LibraryError("OneSearch returned an unexpected JSON response.")
        return data, snapshot

    def search(
        self, query, field="any", match="contains", resource_type=None, limit=10, offset=0, refresh=False
    ):
        query = query.strip()
        if not query or any(c == ";" or ord(c) < 32 or ord(c) == 127 for c in query):
            raise LibraryError("query must contain search text without semicolons or control characters.")
        parameters = dict(
            tab="Everything",
            scope="MyInst_and_CI",
            q=f"{field},{match},{query}",
            limit=limit,
            offset=offset,
            lang="en",
        )
        if resource_type:
            parameters["qInclude"] = "facet_rtype,exact," + resource_type
        data, snapshot = self.get("", parameters, refresh)
        info, docs = data["info"], data["docs"]
        if not isinstance(docs, list) or any(not isinstance(v, dict) for v in docs) or len(docs) > limit:
            raise LibraryError("OneSearch returned an unexpected result page.")
        total = info["total"]
        if type(total) is not int or total < 0:
            raise LibraryError("OneSearch returned an invalid result count.")
        if docs and (info["first"] != offset + 1 or info["last"] != offset + len(docs)):
            raise LibraryError("OneSearch returned mismatched pagination; no complete page was inferred.")
        if not docs and offset < total:
            raise LibraryError(
                "OneSearch returned an empty page inside its result range; refine the query or try again."
            )
        records = [parser.summary(doc) for doc in docs]
        return SearchResults(
            query=query,
            records=records,
            offset=offset,
            total_count=total,
            local_count=info.get("totalResultsLocal"),
            central_index_count=info.get("totalResultsPC"),
            next_offset=offset + len(docs) if docs and offset + len(docs) < total else None,
            **snapshot,
        )

    def get_record(self, record_id, context="L", refresh=False):
        parameters = {"lang": "en"}
        if context == "PC":
            parameters["adaptor"] = "Primo Central"
        data, snapshot = self.get("/" + context + "/" + quote(record_id, safe=""), parameters, refresh)
        if data.get("docs") == [] and data.get("info", {}).get("total") == 0:
            raise LibraryError(
                "OneSearch could not find this record. Use record_id and context exactly as returned by library_search."
            )
        record = parser.record(data)
        if record.record_id != record_id or record.context != context:
            raise LibraryError("OneSearch returned a different record or search context.")
        return RecordDetails(record=record, **snapshot)

    def get_availability(self, record_id, context="L", refresh=False):
        parameters = {"lang": "en"}
        if context == "PC":
            parameters["adaptor"] = "Primo Central"
        data, snapshot = self.get("/" + context + "/" + quote(record_id, safe=""), parameters, refresh)
        brief = parser.summary(data)
        if brief.record_id != record_id or brief.context != context:
            raise LibraryError("OneSearch returned a different record or search context.")
        delivery = data.get("delivery") or {}
        raw_holdings = delivery.get("holding") or []
        if not isinstance(raw_holdings, list):
            raise LibraryError("OneSearch returned unexpected holdings.")
        holdings = [
            Holding(
                library=v.get("mainLocation"),
                location=v.get("subLocation"),
                call_number=v.get("callNumber"),
                availability=v.get("availabilityStatus"),
            )
            for v in raw_holdings
        ]
        services_url = None
        if context == "L" and (
            delivery.get("electronicContextObjectId") or "Alma-E" in (delivery.get("deliveryCategory") or [])
        ):
            services_url = (
                BASE.rsplit("/", 1)[0]
                + "/edelivery/"
                + quote(record_id, safe="")
                + "?"
                + urlencode({"vid": VIEW, "lang": "en"})
            )
            body, service_snapshot = self.http.get(services_url, refresh)
            delivery = json.loads(body)
            snapshot["retrieved_at"] = min(snapshot["retrieved_at"], service_snapshot["retrieved_at"])
            snapshot["cached"] = snapshot["cached"] and service_snapshot["cached"]
        raw_services = delivery.get("electronicServices") or []
        if not isinstance(raw_services, list):
            raise LibraryError("OneSearch returned unexpected electronic services.")
        services = []
        for value in raw_services:
            url = value.get("serviceUrl")
            if url:
                url = urljoin(BASE, url)
                parsed = urlsplit(url)
                if parsed.scheme != "https" or not parsed.netloc or parsed.username:
                    raise LibraryError("OneSearch returned an unsupported service link.")
            services.append(
                ElectronicService(
                    name=value.get("packageName"),
                    url=url,
                    notes=parser.clean(value["publicNote"]) if value.get("publicNote") else None,
                )
            )
        return Availability(
            record_id=record_id,
            context=context,
            holdings=holdings,
            electronic_services=services,
            availability_codes=brief.availability_codes,
            services_source_url=services_url,
            **snapshot,
        )
