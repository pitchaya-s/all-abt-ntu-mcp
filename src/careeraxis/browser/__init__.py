"""Browser session and page projections used by CareerAxis workflows."""

from .session import CareerAxisSession
from .snapshots import (
    _DETAIL_READY_STATE,
    _DETAIL_SNAPSHOT,
    _JOB_STATE,
    _PORTAL_SNAPSHOT,
    _SEARCH_SNAPSHOT,
    _SECTION_PATHS,
)

__all__ = [
    "CareerAxisSession",
    "_DETAIL_READY_STATE",
    "_DETAIL_SNAPSHOT",
    "_JOB_STATE",
    "_PORTAL_SNAPSHOT",
    "_SEARCH_SNAPSHOT",
    "_SECTION_PATHS",
]
