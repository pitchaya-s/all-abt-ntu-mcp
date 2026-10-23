"""Synthetic directory responses; no real faculty records are stored."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlsplit

from faculty.client import DIRECTORY


INTEREST_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
OPTIONS = f"""<html><body>
<input name="interests" id="all" value="all"><label for="all">All</label>
<input name="interests" id="ai" value="{INTEREST_ID}">
<label for="ai"><span>Artificial &amp; Augmented Intelligence</span></label>
<input name="interests" id="energy" value="{OTHER_ID}"><label for="energy">Energy</label>
<input name="interests" id="mobile" value="{INTEREST_ID}">
<label for="mobile">Artificial &amp; Augmented Intelligence</label>
</body></html>""".encode()
PROFILE = {
    "title": "Assoc Prof Example Éclair", "url": "https://dr.ntu.edu.sg/entities/person/Example-Faculty",
    "tag": "School of Example &amp; Testing", "email": "faculty@example.org",
    "appointments": "Associate Professor, Example School<br/>Director, <em>Example Centre</em>",
    "interests": "Artificial &amp; Augmented Intelligence | Testing",
    "description": "<p>A fictional profile &amp; biography ...</p>",
    "image": None, "unusedProviderField": "not needed",
}


def fake_get(url, refresh=False):
    snapshot = dict(retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_url=url, cached=False)
    if url == DIRECTORY:
        return OPTIONS, snapshot
    parsed = urlsplit(url)
    if parsed.path != "/research/faculty-directory/GetAcademicProfiles/":
        raise AssertionError("Unexpected offline faculty request")
    params = parse_qs(parsed.query, keep_blank_values=True)
    query, page = params["searchFaculty"][0], int(params["page"][0])
    values = [dict(deepcopy(PROFILE), url=PROFILE["url"] + str(i)) for i in range(11)]
    if query == "no matches":
        values = []
    elif params["interests"][0] != "all":
        values = values[:1]
    total = len(values)
    data = {"totalItems": total, "totalPages": (total + 9) // 10,
            "items": values[(page - 1) * 10:page * 10]}
    return json.dumps(data).encode(), snapshot
