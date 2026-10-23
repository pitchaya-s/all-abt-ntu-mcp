from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

@dataclass(frozen=True)
class Session:
    course_code: str
    index: str
    lesson_type: str | None
    group: str | None
    day: str | None
    start_time: str | None
    end_time: str | None
    venue: str | None
    teaching_weeks: tuple[int, ...] | None
    remarks: str | None
    raw_time: str | None = None
    raw_day: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_code": self.course_code,
            "index": self.index,
            "lesson_type": self.lesson_type,
            "group": self.group,
            "day": self.day,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "venue": self.venue,
            "teaching_weeks": list(self.teaching_weeks) if self.teaching_weeks is not None else None,
            "remarks": self.remarks,
            "raw_time": self.raw_time,
            "raw_day": self.raw_day,
        }

@dataclass(frozen=True)
class Course:
    course_code: str
    course_name: str
    au: float | None
    details: dict[str, str]
    indexes: dict[str, tuple[Session, ...]]
    academic_year: int | None = None
    semester: str | None = None
    retrieved_at: str | None = None
    source_url: str | None = None
    course_description: str | None = None
    course_description_status: Literal["available", "not_listed", "unavailable"] = "unavailable"
    course_description_source: str | None = None

    def with_request_metadata(
        self, *, academic_year: int, semester: str, retrieved_at: str, source_url: str
    ) -> Course:
        return replace(
            self,
            academic_year=academic_year,
            semester=semester,
            retrieved_at=retrieved_at,
            source_url=source_url,
        )

    def with_course_description(
        self,
        *,
        description: str | None,
        status: Literal["available", "not_listed", "unavailable"],
        source_url: str,
    ) -> Course:
        return replace(
            self,
            course_description=description,
            course_description_status=status,
            course_description_source=source_url,
        )

def course_metadata(course: Course) -> dict[str, Any]:
    return {
        "course_code": course.course_code,
        "course_name": course.course_name,
        "au": course.au,
        "course_description": course.course_description,
        "course_description_status": course.course_description_status,
        "course_description_source": course.course_description_source,
        "prerequisites": course.details.get("prerequisite"),
        "course_notes": [
            {"label": label, "text": text}
            for label, text in course.details.items()
            if label != "prerequisite"
        ],
        "academic_year": course.academic_year,
        "semester": course.semester,
        "retrieved_at": course.retrieved_at,
        "official_source": course.source_url,
    }

def session_signature(session: Session) -> tuple[Any, ...]:
    return (
        session.lesson_type,
        session.group,
        session.day,
        session.start_time,
        session.end_time,
        session.venue,
        session.teaching_weeks,
        session.remarks,
        session.raw_time,
        session.raw_day,
    )
