from .common import Freshness, Model


class Person(Model):
    id: str
    name: str | None = None
    role: str | None = None


class CourseUsers(Freshness):
    course_id: str
    group_id: str | None = None
    users: list[Person]
    offset: int
    next_offset: int | None


class Group(Model):
    id: str
    name: str
    description: str | None = None
    available: str | None = None
    parent_id: str | None = None
    is_group_set: bool | None = None


class CourseGroups(Freshness):
    course_id: str
    groups: list[Group]
    offset: int
    next_offset: int | None
