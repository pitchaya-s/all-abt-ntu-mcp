"""Synthetic LibFacilities responses; no accounts, bookings, cookies or tokens."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from library.models import FacilitySchedule

DIRECTORY = b"""<h1>Example Library</h1><a href="/map/abcdef123456">Floor 1</a>
<a href="/space/100">Example Room</a><a href="/spaces?lid=10&amp;gid=20">Study Rooms</a>
<table><tr><td>Example closure notice.</td></tr></table>"""
MAP_PAGE = b"<script>var springyPage = {mapId: 42};</script>"
MAP = b"""<script>var springyAjax = {mapId: 42, linkModelsByShapeId: {
"a":{"type":2,"id":100,"title":"Example Room","status":10},
"b":{"type":2,"id":101,"title":"Example Seat","status":5},
"c":{"type":2,"id":102,"title":"Another Seat","status":1},
"d":{"type":2,"id":103,"title":"Unknown Seat","status":88},
"other":{"type":4,"id":0,"title":"Printer","status":0}}};</script>"""
GRID = {
    "slots": [
        {
            "start": "2026-10-24 10:00:00",
            "end": "2026-10-24 10:15:00",
            "itemId": 100,
            "className": "s-lc-eq-checkout",
            "checksum": "never-output",
        },
        {
            "start": "2026-10-24 10:15:00",
            "end": "2026-10-24 10:30:00",
            "itemId": 100,
            "className": "s-lc-eq-checkout",
            "checksum": "never-output",
        },
        {
            "start": "2026-10-24 10:30:00",
            "end": "2026-10-24 10:45:00",
            "itemId": 100,
            "className": "future-source-state",
        },
    ],
    "bookings": [{"private": "never-output"}],
    "isPreCreatedBooking": False,
    "windowEnd": False,
}


def snapshot(url):
    return dict(retrieved_at=datetime(2026, 10, 23, tzinfo=timezone.utc), source_url=url, cached=False)


def fake_facility_get(url, refresh=False):
    path = urlsplit(url).path
    body = MAP if path == "/maps/search/spaces" else MAP_PAGE if path.startswith("/map/") else DIRECTORY
    return body, snapshot(url)


def fake_schedule(day, space_id=None, location_id=None, group_id=None, refresh=False):
    from library.facilities import BASE
    from library.schedule import parse_slots, schedule_path

    path = schedule_path(space_id, location_id, group_id)
    return FacilitySchedule(
        date=day,
        title="Example Room",
        description="An example study room.",
        spaces=parse_slots(GRID, {100: "Example Room"}, day),
        window_end=False,
        **snapshot(BASE + path),
    )
