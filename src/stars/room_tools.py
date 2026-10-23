"""Read-only MCP tools over the shared term-wide teaching snapshot."""

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .domain.rooms import build_catalogue, available_rooms, room_schedule
from .client.http import NTURequestError
from .client.teaching import get_teaching_snapshot
from .room_schemas import (
    AvailableRoomsResult,
    RoomScheduleResult,
    RoomWindow,
    RoomFilters,
    Day,
    Semester,
    Year,
    Weeks,
    TimeText,
    Label,
    Limit,
    Offset,
    minutes,
)

INSTRUCTIONS = (
    "stars_find_available_rooms and stars_get_room_schedule share a term-wide snapshot of all published "
    "full-time and part-time undergraduate indexes. Only recognizable room labels observed in teaching "
    "are candidates. Room types and venue-code prefixes are inferred from labels, not an official room inventory. "
    "Availability means no known scheduled undergraduate teaching, not occupancy, permission to enter, opening hours, "
    "or a guarantee against graduate classes, exams, events or other bookings. Unplaced lessons and excluded "
    "venue labels are counted in coverage. Unknown timings or potentially overlapping unknown teaching weeks "
    "exclude a candidate from availability; room schedule queries retain uncertain lessons. Multiple requested "
    "teaching weeks require the same room to be free in all of them. Omit weeks to consider every published "
    "meeting, not the current calendar week. free_from/free_until are teaching-free bounds on that day, "
    "not building access hours. No capacity, facilities, accessibility or geographic location is inferred. "
    "Use stars_get_room_schedule to inspect course/index use, with shared lessons grouped by their index lists. "
)


def _source(snapshot, catalogue):
    return dict(
        academic_year=snapshot.academic_year,
        semester=snapshot.semester,
        source_url=snapshot.source_url,
        retrieved_at=snapshot.retrieved_at,
        cached=snapshot.cached,
        coverage=catalogue.coverage,
    )


def find_available_rooms(
    academic_year: Year,
    semester: Semester,
    window: RoomWindow,
    filters: RoomFilters | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
    refresh: bool = False,
) -> AvailableRoomsResult:
    """Find rooms with no known published undergraduate teaching throughout a day/time interval and every requested teaching week. Covers all indexes from both full-time and part-time schedules, including all lesson types. Filters select room type inferred from venue code, venue text/prefix, excluded rooms or observed lesson types. Unknown conflicting schedules are excluded. Only teaching-observed rooms are returned; this does not establish occupancy, access, capacity or availability against graduate classes, exams or other bookings. Times are Singapore time and weeks are semester teaching weeks. Omit weeks for a conservative whole-term check. Follow has_more with offset."""
    try:
        snapshot = get_teaching_snapshot(academic_year, semester, refresh)
        catalogue = build_catalogue(snapshot.courses)
        return AvailableRoomsResult(
            window=window,
            **_source(snapshot, catalogue),
            **available_rooms(catalogue, window, filters or RoomFilters(), limit, offset),
        )
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from None


def get_room_schedule(
    venue: Label,
    academic_year: Year,
    semester: Semester,
    day: Day | None = None,
    teaching_weeks: Weeks | None = None,
    start_time: TimeText | None = None,
    end_time: TimeText | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
    refresh: bool = False,
) -> RoomScheduleResult:
    """Get all published undergraduate course/index lessons using one observed room, including full-time and part-time offerings. Accepts a venue code or returned alias. Shared lessons carry all associated index numbers. Optional day, teaching weeks and overlapping time interval filter the result; uncertain lessons remain included. Missing weeks/times are unknown. Paginate with offset/limit and has_more. This is teaching data, not room bookings or actual occupancy."""
    try:
        if not venue.strip() or any(ord(c) < 32 for c in venue):
            raise ValueError("venue must be a nonblank venue code without control characters.")
        if (start_time is None) != (end_time is None) or (
            start_time and minutes(start_time) >= minutes(end_time)
        ):
            raise ValueError("Supply both start_time and end_time, with end_time later on the same day.")
        snapshot = get_teaching_snapshot(academic_year, semester, refresh)
        catalogue = build_catalogue(snapshot.courses)
        return RoomScheduleResult(
            **_source(snapshot, catalogue),
            **room_schedule(catalogue, venue, day, teaching_weeks, start_time, end_time, limit, offset),
        )
    except (NTURequestError, ValueError) as error:
        raise ToolError(str(error)) from None


def register_tools(mcp):
    read = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
    for function in (find_available_rooms, get_room_schedule):
        mcp.tool(name="stars_" + function.__name__, annotations=read)(function)
