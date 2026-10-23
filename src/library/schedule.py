"""Validated facility selections and lossless daily time-grid normalization."""

from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from .facilities import SGT
from .models import LibraryError, SpaceSchedule, TimeSlot


def schedule_path(space_id, location_id, group_id):
    if any(
        value is not None and (type(value) is not int or not 1 <= value <= 9_999_999_999)
        for value in (space_id, location_id, group_id)
    ):
        raise LibraryError("Facility IDs must be positive integers, copied from facility results.")
    if space_id is not None and location_id is None and group_id is None:
        return "/space/" + str(space_id)
    if space_id is None and location_id is not None and group_id is not None:
        return "/spaces?" + urlencode({"lid": location_id, "gid": group_id})
    raise LibraryError("Supply space_id, or both location_id and group_id, not both forms.")


def parse_slots(data, names, day):
    if not isinstance(data, dict) or not isinstance(data.get("slots"), list) or len(data["slots"]) > 20000:
        raise LibraryError("LibFacilities returned an unexpected time grid.")
    if data.get("isPreCreatedBooking") is not False:
        raise LibraryError(
            "LibFacilities returned an unexpected booking state; no booking operation was requested."
        )
    spaces = {str(key): SpaceSchedule(item_id=str(key), name=value, slots=[]) for key, value in names.items()}
    start_of_day = datetime.combine(date.fromisoformat(day), datetime.min.time(), SGT)
    for row in data["slots"]:
        item_id = row["itemId"]
        if type(item_id) is not int or item_id <= 0:
            raise LibraryError("LibFacilities returned an invalid resource ID.")
        start, end = (
            datetime.strptime(row[key], "%Y-%m-%d %H:%M:%S").replace(tzinfo=SGT) for key in ("start", "end")
        )
        if not start_of_day <= start < end <= start_of_day + timedelta(days=1):
            raise LibraryError("LibFacilities returned time slots outside the requested day.")
        item = spaces.setdefault(str(item_id), SpaceSchedule(item_id=str(item_id), name=None, slots=[]))
        source_classes = row.get("className")
        # Match LibFacilities' formatEventsForFullCalendar; omitted className means available.
        item.slots.append(
            TimeSlot(
                start=start,
                end=end,
                status="unavailable" if source_classes else "available",
                source_classes=source_classes,
            )
        )
    for item in spaces.values():
        merged = []
        for slot in sorted(item.slots, key=lambda s: s.start):
            if merged and slot.start < merged[-1].end:
                raise LibraryError("LibFacilities returned overlapping time slots for one resource.")
            if merged and merged[-1].end == slot.start and merged[-1].source_classes == slot.source_classes:
                merged[-1].end = slot.end
            else:
                merged.append(slot)
        item.slots = merged
    return list(spaces.values())
