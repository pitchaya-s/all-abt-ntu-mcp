"""Conservative room lookups from published teaching sessions only."""

from dataclasses import dataclass, field
import re

from ..room_schemas import AvailableRoom, RoomCoverage, RoomIdentity, RoomLesson, minutes


class RoomQueryError(ValueError):
    pass


def normalize_venue(value):
    value = " ".join(value.strip().strip("\"'").lstrip("/").upper().split())
    value = re.sub(r"[\s_]+", "-", value)
    value = re.sub(r"TR-(?=\d)", "TR+", value)
    return re.sub(r"(TR\+)0+(?=\d)", r"\1", value)


def room_type(venue):
    if not re.fullmatch(r"[A-Z0-9.+-]+", venue):
        return None
    if venue.startswith(("SEE-", "PAP-YR")):
        return None
    if re.search(r"(?:^|-)TR\+?\d+[A-Z]?$", venue):
        return "tutorial_room"
    if re.search(r"(?:^|-)SR\d+[A-Z]?$|SEMRM\d+$", venue):
        return "seminar_room"
    if re.search(r"(?:^|-)LT(?:\d+[A-Z]?)?$", venue):
        return "lecture_theatre"
    if re.search(r"(?:^|-)CL\d+$|[A-Z]*LAB\d+$|(?:^|-)LAB-\d+$", venue):
        return "laboratory"
    if re.fullmatch(r"(?:[A-Z][A-Z0-9.]*-)+[A-Z0-9]+(?:-[A-Z0-9]+)*", venue) and re.search(r"\d", venue):
        return "other"
    if re.fullmatch(r"(?:CR|FTR|ESR|CSKL|TRX)\d+[A-Z]?", venue):
        return "other"
    return None


@dataclass
class Room:
    venue: str
    kind: str
    aliases: set[str] = field(default_factory=set)
    lessons: dict = field(default_factory=dict)

    def identity(self):
        return RoomIdentity(
            venue=self.venue,
            room_type=self.kind,
            aliases=sorted(self.aliases - {self.venue}),
            observed_lesson_types=sorted({s.lesson_type for s in self.lessons.values() if s.lesson_type}),
        )


@dataclass
class RoomCatalogue:
    rooms: dict[str, Room]
    coverage: RoomCoverage


def lesson_key(session):
    return (
        session.course_code,
        session.lesson_type,
        session.group,
        session.day,
        session.start_time,
        session.end_time,
        session.teaching_weeks,
        session.remarks,
        session.raw_day,
        session.raw_time,
    )


def build_catalogue(courses):
    rooms = {}
    sessions = []
    course_codes = set()
    indexes = set()
    for course in courses:
        course_codes.add(course.course_code)
        for index, lessons in course.indexes.items():
            indexes.add((course.course_code, index))
            for session in lessons:
                sessions.append(session)
                if session.venue:
                    key = normalize_venue(session.venue)
                    kind = room_type(key)
                    if kind:
                        room = rooms.setdefault(key, Room(key, kind))
                        room.aliases.add(session.venue)
    all_lessons = set()
    unplaced = set()
    excluded = set()
    for session in sessions:
        key = normalize_venue(session.venue or "")
        identity = lesson_key(session)
        all_lessons.add((key, identity))
        targets = [key] if key in rooms else []
        if not targets and session.venue:
            # Multi-venue cells block each independently observed component; they never create candidate rooms.
            targets = list(
                dict.fromkeys(
                    normalize_venue(v)
                    for v in re.split(r"[/,;&]", session.venue)
                    if normalize_venue(v) in rooms
                )
            )
        if not targets:
            unplaced.add((key, identity))
            if session.venue:
                excluded.add(session.venue)
        for venue in targets:
            room = rooms[venue]
            if identity in room.lessons:
                lesson = room.lessons[identity]
                if session.index not in lesson.indexes:
                    lesson.indexes.append(session.index)
            else:
                room.lessons[identity] = RoomLesson(
                    course_code=session.course_code,
                    indexes=[session.index],
                    lesson_type=session.lesson_type,
                    group=session.group,
                    day=session.day,
                    start_time=session.start_time,
                    end_time=session.end_time,
                    teaching_weeks=list(session.teaching_weeks)
                    if session.teaching_weeks is not None
                    else None,
                    remarks=session.remarks,
                    raw_day=session.raw_day,
                    raw_time=session.raw_time,
                )
                lesson = room.lessons[identity]
            if session.venue and session.venue != venue and session.venue not in lesson.source_venue_labels:
                lesson.source_venue_labels.append(session.venue)
    for room in rooms.values():
        for lesson in room.lessons.values():
            lesson.indexes.sort()
    return RoomCatalogue(
        rooms,
        RoomCoverage(
            course_count=len(course_codes),
            courses_without_published_indexes=len(course_codes - {code for code, _ in indexes}),
            index_count=len(indexes),
            lesson_count=len(all_lessons),
            observed_room_count=len(rooms),
            excluded_venue_label_count=len(excluded),
            unplaced_lesson_count=len(unplaced),
        ),
    )


def relevant(lesson, day, weeks):
    if day is not None and lesson.day is not None and lesson.day != day:
        return False
    return not (
        weeks is not None
        and lesson.teaching_weeks is not None
        and not set(weeks).intersection(lesson.teaching_weeks)
    )


def candidate(room, filters):
    identity = room.identity()
    if filters.room_types and room.kind not in filters.room_types:
        return False
    if filters.venue_contains and normalize_venue(filters.venue_contains) not in room.venue:
        return False
    if filters.venue_prefixes and not any(
        room.venue.startswith(normalize_venue(prefix)) for prefix in filters.venue_prefixes
    ):
        return False
    if room.venue in {normalize_venue(v) for v in filters.exclude_venues}:
        return False
    return not filters.used_for_lesson_types or bool(
        set(identity.observed_lesson_types).intersection(
            v.strip().upper() for v in filters.used_for_lesson_types
        )
    )


def clock(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def available_rooms(catalogue, window, filters, limit, offset):
    start = minutes(window.start_time) - window.buffer_minutes
    end = minutes(window.end_time) + window.buffer_minutes
    matches = []
    busy_count = uncertain_count = 0
    for venue in sorted(catalogue.rooms):
        room = catalogue.rooms[venue]
        if not candidate(room, filters):
            continue
        busy = uncertain = False
        before, after = 0, 1440
        for lesson in room.lessons.values():
            if not relevant(lesson, window.day, window.teaching_weeks):
                continue
            if lesson.day is None or lesson.start_time is None or lesson.end_time is None:
                uncertain = True
                continue
            a, b = minutes(lesson.start_time), minutes(lesson.end_time)
            if a < end and start < b:
                if window.teaching_weeks is not None and lesson.teaching_weeks is None:
                    uncertain = True
                else:
                    busy = True
            elif b <= start:
                before = max(before, b)
            elif a >= end:
                after = min(after, a)
        if busy:
            busy_count += 1
        elif uncertain:
            uncertain_count += 1
        else:
            matches.append(
                AvailableRoom(
                    **room.identity().model_dump(), free_from=clock(before), free_until=clock(after)
                )
            )
    return dict(
        match_count=len(matches),
        offset=offset,
        has_more=offset + limit < len(matches),
        rooms=matches[offset : offset + limit],
        excluded_busy_count=busy_count,
        excluded_uncertain_count=uncertain_count,
    )


def room_schedule(catalogue, venue, day, weeks, start_time, end_time, limit, offset):
    key = normalize_venue(venue)
    if key not in catalogue.rooms:
        raise RoomQueryError(
            "This venue was not identified as a room in the published teaching schedules. Use a venue code returned by stars_find_available_rooms."
        )
    if (start_time is None) != (end_time is None) or (
        start_time and minutes(start_time) >= minutes(end_time)
    ):
        raise RoomQueryError("Supply both start_time and end_time, with end_time later on the same day.")
    room = catalogue.rooms[key]
    lessons = []
    for lesson in room.lessons.values():
        if not relevant(lesson, day, weeks):
            continue
        if (
            start_time
            and lesson.start_time
            and lesson.end_time
            and not (
                minutes(lesson.start_time) < minutes(end_time)
                and minutes(start_time) < minutes(lesson.end_time)
            )
        ):
            continue
        lessons.append(lesson)
    lessons.sort(key=lambda s: (s.day or "", s.start_time or "", s.course_code, s.group or ""))
    return dict(
        room=room.identity(),
        session_count=len(lessons),
        offset=offset,
        has_more=offset + limit < len(lessons),
        sessions=lessons[offset : offset + limit],
    )
