"""Synthetic campus service records; no real business/contact data stored."""

from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit

from service.client import DIRECTORY


TYPE_ID = "11111111-1111-4111-8111-111111111111"
CATEGORY_ID = "22222222-2222-4222-8222-222222222222"
FORM = f'''<html><input name="locationTypes" id="type-all" value="all"><label for="type-all">All</label>
<input name="locationTypes" id="food" value="{TYPE_ID}"><label for="food">Food &amp; Beverage</label>
<input name="locationCategories" id="category-all" value="all"><label for="category-all">All</label>
<input name="locationCategories" id="general" value="{CATEGORY_ID}"><label for="general">General</label></html>'''.encode()
ROWS = [{"title": f"Example shop {i}", "location": "North Spine, Example Unit " + str(i),
         "phone": "", "fax": None, "email": "", "operatingHours": "Mon–Fri: 9am to 5pm<br/>Closed on holidays",
         "mapUrl": "https://maps.ntu.edu.sg/?example=" + str(i)} for i in range(13)]
ROWS[-1] = {**ROWS[-1], "title": "Synthetic Café Clinic", "location": "South Spine, Example Unit 13",
            "phone": "0000 0000", "email": "clinic@example.org"}


def fake_get(url, refresh=False):
    snapshot = dict(retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_url=url, cached=True)
    if url == DIRECTORY:
        return FORM, snapshot
    if urlsplit(url).path != "/life-at-ntu/leisure-and-dining/general-directory/GetLocations/":
        raise AssertionError("Unexpected offline service request")
    params = parse_qs(urlsplit(url).query)
    page = int(params["page"][0])
    if page > 1:
        snapshot["retrieved_at"] -= timedelta(seconds=30)
        snapshot["cached"] = False
    rows = ROWS
    if params["locationTypes"][0] != "all":
        rows = ROWS[:2]
    if params["locationCategories"][0] != "all":
        rows = []
    return json.dumps({"items": rows[(page - 1) * 12:page * 12], "totalItems": len(rows),
                       "totalPages": (len(rows) + 11) // 12}).encode(), snapshot
