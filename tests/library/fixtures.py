"""Synthetic Primo records matching verified local and central-index shapes."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlsplit


LOCAL = {
    "context": "L",
    "pnx": {
        "control": {"recordid": ["almaExample001"]},
        "display": {
            "title": ["<em>Example</em> algorithms"],
            "type": ["books"],
            "creator": ["Example, Author$$QAuthor, Example"],
            "creationdate": ["2026"],
            "publisher": ["Example Publisher"],
            "subject": ["Algorithms$$QAlgorithms -- Examples"],
            "description": ["<p>First paragraph.</p><p>Second paragraph.</p>"],
        },
        "addata": {
            "au": ["Example, Author"],
            "isbn": ["9780000000001"],
            "openaccess": ["true"],
            "url": ["https://example.org/book"],
        },
    },
    "delivery": {
        "availability": ["not_restricted"],
        "displayedAvailability": "Not available",
        "link": [],
        "holding": [
            {
                "mainLocation": "Example Library",
                "subLocation": "Main Collection",
                "callNumber": "QA1.EX",
                "availabilityStatus": "available",
            }
        ],
    },
}
CENTRAL = deepcopy(LOCAL)
CENTRAL["context"] = "PC"
CENTRAL["pnx"]["control"]["recordid"] = ["cdi_example_article"]
CENTRAL["pnx"]["display"]["type"] = ["article"]


def fake_get(url, refresh=False):
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    if "/edelivery/" in parsed.path:
        data = {
            "electronicServices": [
                {
                    "packageName": "Example Online",
                    "serviceUrl": "/view/action/uresolver.do?operation=resolveService",
                    "publicNote": "<b>Current students only.</b>",
                }
            ]
        }
    elif parsed.path.endswith("/L/missing"):
        data = {"info": {"total": 0, "first": 0, "last": 0}, "docs": []}
    elif "/pnxs/L/" in parsed.path:
        data = LOCAL
    elif "/pnxs/PC/" in parsed.path:
        assert params.get("adaptor") == ["Primo Central"]
        data = CENTRAL
    else:
        offset, limit = int(params.get("offset", [0])[0]), int(params.get("limit", [10])[0])
        values = [] if "no matches" in params["q"][0] else [LOCAL, CENTRAL]
        docs = values[offset : offset + limit]
        data = {
            "info": {
                "total": len(values),
                "totalResultsLocal": 1 if values else 0,
                "totalResultsPC": 1 if values else 0,
                "first": offset + 1 if docs else 0,
                "last": offset + len(docs) if docs else 0,
            },
            "docs": docs,
        }
    return json.dumps(data).encode(), dict(
        retrieved_at=datetime(2026, 10, 23, tzinfo=timezone.utc), source_url=url, cached=False
    )
