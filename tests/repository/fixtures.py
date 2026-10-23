"""Synthetic DSpace and Dataverse records; no actual research records are stored."""

from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urlencode

from drntu.client import API


ITEM_ID = "11111111-1111-4111-8111-111111111111"
BUNDLE_ID = "22222222-2222-4222-8222-222222222222"
FILE_ID = "33333333-3333-4333-8333-333333333333"
CONTAINER_ID = "44444444-4444-4444-8444-444444444444"
DOI = "doi:10.21979/EXAMPLE/DATA"
META = {
    "dc.title": [{"value": "Synthetic publication", "language": None}],
    "dc.contributor.author": [{"value": "Example, Author", "language": None}],
    "dc.description.abstract": [{"value": "A fictional abstract for parser tests.", "language": "en"}],
    "dc.date.issued": [{"value": "2026", "language": None}],
    "datacite.rights": [{"value": "restricted", "language": None}],
}
ITEM = {"uuid": ITEM_ID, "name": "Synthetic publication", "entityType": "Publication", "type": "item",
        "metadata": META, "withdrawn": False, "lastModified": "2026-01-01T00:00:00Z"}
CONTAINER = {"uuid": CONTAINER_ID, "name": "Example collection", "type": "collection", "metadata": META, "archivedItemsCount": -1}
BUNDLE = {"uuid": BUNDLE_ID, "name": "ORIGINAL", "type": "bundle"}
FILE = {"uuid": FILE_ID, "name": "example.pdf", "type": "bitstream", "bundleName": "ORIGINAL", "sizeBytes": 123,
        "metadata": {"datacite.rights": [{"value": "restricted", "language": None}]},
        "checkSum": {"checkSumAlgorithm": "MD5", "value": "synthetic-checksum"},
        "_links": {"content": {"href": f"{API}/core/bitstreams/{FILE_ID}/content"}}}
VERSION = {
    "datasetId": 123, "datasetPersistentId": DOI, "versionNumber": 1, "versionMinorNumber": 0,
    "versionState": "RELEASED", "publicationDate": "2026-01-01", "license": {"name": "CC0", "uri": "https://example.org/license"},
    "metadataBlocks": {"citation": {"fields": [
        {"typeName": "title", "typeClass": "primitive", "value": "Synthetic dataset"},
        {"typeName": "author", "typeClass": "compound", "value": [{"authorName": {"value": "Example, Author"}}]},
        {"typeName": "dsDescription", "typeClass": "compound", "value": [{"dsDescriptionValue": {"value": "Fictional data."}}]},
        {"typeName": "subject", "typeClass": "controlledVocabulary", "value": ["Computer Science"]},
    ]}},
    "files": [{"restricted": True, "directoryLabel": "example", "dataFile": {"id": 101, "filename": "one.csv", "contentType": "text/csv", "filesize": 10}},
              {"dataFile": {"id": 102, "filename": "two.csv", "filesize": 20}}],
}


def hal(key, items, page=0, size=20):
    start = page * size
    return {"_embedded": {key: items[start:start + size]}, "page": {
        "number": page, "size": size, "totalElements": len(items), "totalPages": (len(items) + size - 1) // size,
    }}


def fake_get(path, parameters=None, *, dataset=False, refresh=False):
    parameters = parameters or {}
    page, size = parameters.get("page", 0), parameters.get("size", 20)
    snapshot = dict(retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_url=API + path, cached=False)
    if dataset:
        value = VERSION if "/versions/" in path else {"id": 123, "latestVersion": VERSION}
        data = {"status": "OK", "data": value}
    elif path == "/discover/search/objects":
        values = [] if parameters["query"] == "no matches" else [
            {"_embedded": {"indexableObject": ITEM}},
            {"_embedded": {"indexableObject": {**ITEM, "uuid": CONTAINER_ID}}},
        ]
        data = {"_embedded": {"searchResult": hal("objects", values, page, size)}}
    elif path == "/discover/facets":
        data = {"_embedded": {"facets": [{"name": "dateIssued", "facetType": "date"}]}}
    elif path.startswith("/discover/facets/"):
        facet = path.split("/")[-1]
        search_url = API + "/discover/search/objects?" + urlencode({"f." + facet: "[2020 TO 2026],equals"})
        data = {"name": facet, "page": {"number": page, "size": size}, "_links": {}, "_embedded": {"values": [
            {"label": "2020 - 2026", "count": 2, "authorityKey": None, "_links": {"search": {"href": search_url}}},
        ]}}
    elif path == f"/core/items/{ITEM_ID}":
        data = ITEM
    elif path.endswith("/bundles"):
        data = hal("bundles", [BUNDLE], page, size)
    elif path.endswith("/bitstreams"):
        data = hal("bitstreams", [FILE], page, size)
    elif path.startswith("/core/communities") or path == "/core/collections":
        kind = "communities" if path.endswith("communities") else "collections"
        value = {**CONTAINER, "type": "community" if kind == "communities" else "collection"}
        key = "subcommunities" if path.endswith("/subcommunities") else kind
        data = hal(key, [value], page, size)
    else:
        raise AssertionError("Unexpected offline repository request")
    return deepcopy(data), snapshot
