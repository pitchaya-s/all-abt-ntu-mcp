from __future__ import annotations

from typing import Any

from .models import Course, Session, course_metadata, session_signature

def _value(session: Session | dict[str, Any], key: str) -> Any:
    return getattr(session, key) if isinstance(session, Session) else session.get(key)

def _minutes(value: str | None) -> int | None:
    if value is None or len(value) != 5 or value[2] != ":":
        return None
    try:
        hours, minutes = map(int, value.split(":"))
    except ValueError:
        return None
    return hours * 60 + minutes

def clash_status(first: Session | dict[str, Any], second: Session | dict[str, Any]) -> bool | None:
    """Return True for a clash, False for a known non-clash, or None if unknown."""
    first_weeks = _value(first, "teaching_weeks")
    second_weeks = _value(second, "teaching_weeks")
    if first_weeks is not None and second_weeks is not None and not set(first_weeks).intersection(second_weeks):
        return False

    first_day, second_day = _value(first, "day"), _value(second, "day")
    if first_day is None or second_day is None:
        return None
    if first_day != second_day:
        return False

    first_start = _minutes(_value(first, "start_time"))
    first_end = _minutes(_value(first, "end_time"))
    second_start = _minutes(_value(second, "start_time"))
    second_end = _minutes(_value(second, "end_time"))
    if None in (first_start, first_end, second_start, second_end):
        return None
    if not (first_start < second_end and second_start < first_end):
        return False
    return None if first_weeks is None or second_weeks is None else True

def compare_indexes(
    course: Course, indexes: list[str], against: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    if len(indexes) < 2:
        raise ValueError("Provide at least two index numbers to compare.")
    if len(set(indexes)) != len(indexes):
        raise ValueError("Index numbers must be unique.")
    missing = [index for index in indexes if index not in course.indexes]
    if missing:
        raise ValueError(f"Index(es) not found for {course.course_code}: {', '.join(missing)}.")

    signatures = {
        index: {session_signature(session) for session in course.indexes[index]}
        for index in indexes
    }
    common = set.intersection(*(signatures[index] for index in indexes))
    common_sessions = []
    seen_common: set[tuple[Any, ...]] = set()
    for session in course.indexes[indexes[0]]:
        signature = session_signature(session)
        if signature in common and signature not in seen_common:
            item = session.to_dict()
            item.pop("index")
            item["shared_by"] = indexes
            common_sessions.append(item)
            seen_common.add(signature)

    unique_sessions = {
        index: [
            session.to_dict()
            for session in course.indexes[index]
            if session_signature(session) not in common
        ]
        for index in indexes
    }
    result: dict[str, Any] = {
        **course_metadata(course),
        "indexes_compared": indexes,
        "common_sessions": common_sessions,
        "unique_sessions_by_index": unique_sessions,
    }

    if against is not None:
        clashes: dict[str, list[dict[str, Any]]] = {}
        uncertain: dict[str, int] = {}
        for index in indexes:
            pairs = []
            unknown = 0
            for session in course.indexes[index]:
                for other in against:
                    status = clash_status(session, other)
                    if status is True:
                        pairs.append(
                            {"course_session": session.to_dict(), "existing_session": other}
                        )
                    elif status is None:
                        unknown += 1
            clashes[index] = pairs
            uncertain[index] = unknown
        result["clash_check"] = {
            "against_session_count": len(against),
            "clashes_by_index": clashes,
            "uncertain_comparisons_by_index": uncertain,
        }
    else:
        result["clash_check"] = None
    return result

def find_matching_indexes(
    course: Course,
    constraints: dict[str, Any],
    against: list[dict[str, Any]],
) -> dict[str, Any]:
    requested_weeks = constraints.get("teaching_weeks")
    week_scope = set(requested_weeks) if requested_weeks is not None else None
    matches = []

    for index, sessions in course.indexes.items():
        active: list[Session] = []
        uncertain: set[str] = set()
        for session in sessions:
            if week_scope is None:
                active.append(session)
            elif session.teaching_weeks is None:
                active.append(session)
                uncertain.add("teaching weeks are unspecified for one or more sessions")
            elif week_scope.intersection(session.teaching_weeks):
                active.append(session)

        rejected = False
        avoid_days = set(constraints.get("avoid_days") or [])
        for session in active:
            if avoid_days:
                if session.day is None:
                    uncertain.add("one or more sessions have an unknown day")
                elif session.day in avoid_days:
                    rejected = True
                    break

            earliest = constraints.get("earliest_start")
            if earliest:
                if session.start_time is None:
                    uncertain.add("one or more session start times are unknown")
                elif session.start_time < earliest:
                    rejected = True
                    break

            latest = constraints.get("latest_end")
            if latest:
                if session.end_time is None:
                    uncertain.add("one or more session end times are unknown")
                elif session.end_time > latest:
                    rejected = True
                    break

            for window in constraints.get("avoid_windows") or []:
                if session.day is None or session.start_time is None or session.end_time is None:
                    uncertain.add("one or more sessions cannot be checked against time windows")
                elif session.day == window["day"] and session.start_time < window["end_time"] and window["start_time"] < session.end_time:
                    rejected = True
                    break
            if rejected:
                break

        if rejected:
            continue

        for requirement in constraints.get("require_sessions") or []:
            found = False
            for session in active:
                if requirement.get("lesson_type") and (
                    session.lesson_type is None
                    or session.lesson_type.casefold() != requirement["lesson_type"].casefold()
                ):
                    continue
                if requirement.get("day") and session.day != requirement["day"]:
                    continue
                after = requirement.get("starts_at_or_after")
                before = requirement.get("starts_at_or_before")
                if after and (session.start_time is None or session.start_time < after):
                    continue
                if before and (session.start_time is None or session.start_time > before):
                    continue
                found = True
                break
            if not found:
                if any(
                    session.day is None or session.start_time is None or session.lesson_type is None
                    for session in active
                ):
                    uncertain.add("a required session could not be confirmed from incomplete timetable data")
                else:
                    rejected = True
                    break

        if rejected:
            continue

        clash_pairs = []
        for session in active:
            for other in against:
                if week_scope is not None and other.get("teaching_weeks") is not None and not week_scope.intersection(other["teaching_weeks"]):
                    continue
                if (week_scope is not None and session.teaching_weeks is not None
                        and other.get("teaching_weeks") is not None
                        and not week_scope.intersection(session.teaching_weeks, other["teaching_weeks"])):
                    continue
                status = clash_status(session, other)
                if status is True:
                    clash_pairs.append(
                        {"course_session": session.to_dict(), "existing_session": other}
                    )
                elif status is None:
                    uncertain.add("one or more clash checks have incomplete schedule data")
        if clash_pairs:
            continue

        if any(
            session.lesson_type is None
            or session.day is None
            or session.start_time is None
            or session.end_time is None
            for session in active
        ):
            uncertain.add("one or more active sessions have an unknown lesson type, day, or time")

        matches.append(
            {
                "index": index,
                "status": "uncertain" if uncertain else "confirmed",
                "uncertainties": sorted(uncertain),
                "schedule_complete": all(
                    session.lesson_type is not None
                    and session.day is not None
                    and session.start_time is not None
                    and session.end_time is not None
                    for session in sessions
                ),
                "sessions": [session.to_dict() for session in sessions],
            }
        )

    return {
        **course_metadata(course),
        "constraints": constraints,
        "against_session_count": len(against),
        "match_count": len(matches),
        "matches": matches,
    }
