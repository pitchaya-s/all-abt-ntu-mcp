"""Synthetic response shapes based on verified reads; no real NTU records or sessions."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from ntulearn_mcp.models import AuthStatus, Download

PREFIX = "/learn/api/public/v1"
COURSE = "_100_1"
CONTENT = "_200_1"
USER = "_900_1"
NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)
SECRET = "synthetic-secret-not-a-real-credential"
RESPONSES = {
    PREFIX + "/users/me": {"id": USER, "userName": "student@example.invalid", "password": SECRET},
    PREFIX + "/users/me/courses": {"results": [
        {"courseId": COURSE, "courseRoleId": "Student", "userId": USER,
         "course": {"id": COURSE, "courseId": "SC0001", "name": "Example Course", "organization": False,
                    "availability": {"available": "Yes"}}, "cookie": SECRET},
        {"courseId": "_101_1", "courseRoleId": "Student", "course": {
            "id": "_101_1", "name": "Example Organization", "organization": True, "availability": {"available": "No"}}},
    ]},
    f"{PREFIX}/courses/{COURSE}/contents": {"results": [
        {"id": CONTENT, "title": "Week 1", "hasChildren": True, "contentHandler": {"id": "resource/x-bb-folder"}},
        {"id": "_201_1", "title": "Briefing", "body": "<p>Hello &amp; welcome</p><script>hidden()</script>"},
    ]},
    f"{PREFIX}/courses/{COURSE}/contents/{CONTENT}/children": {"results": [
        {"id": "_202_1", "parentId": CONTENT, "title": "Example slides", "contentHandler": {"id": "resource/x-bb-file"}},
    ]},
    f"{PREFIX}/courses/{COURSE}/announcements": {"results": [
        {"id": "_300_1", "title": "Example announcement", "body": "<p>Bring your laptop.</p>", "created": NOW.isoformat()},
    ]},
    PREFIX + "/calendars/items": {"results": [
        {"id": "calendar-1", "title": "Example assignment", "type": "GradebookColumn", "start": NOW.isoformat(),
         "dynamicCalendarItemProps": {"courseId": COURSE}, "createdByUserId": USER},
    ]},
    f"{PREFIX}/courses/{COURSE}/gradebook/columns": {"results": [
        {"id": "_400_1", "name": "Example quiz", "score": {"possible": 10.0}, "grading": {"due": NOW.isoformat()}},
    ]},
    f"{PREFIX}/courses/{COURSE}/gradebook/users/{USER}": {"results": [
        {"columnId": "_400_1", "userId": USER, "exempt": False},
        {"columnId": "_401_1", "score": 0.0, "feedback": "<p>Example feedback</p>"},
    ]},
    f"{PREFIX}/courses/{COURSE}/contents/_202_1/attachments": {"results": [
        {"id": "_500_1", "fileName": "example.pdf", "mimeType": "application/pdf"},
    ]},
    f"{PREFIX}/courses/{COURSE}/contents/_201_1/attachments": {"results": []},
    f"{PREFIX}/courses/{COURSE}/users": {"results": [
        {"userId": USER, "courseRoleId": "Student", "user": {"id": USER, "name": {"given": "Example", "family": "Student"}, "password": SECRET}},
        {"userId": "_901_1", "courseRoleId": "Instructor", "user": {"id": "_901_1", "name": {"given": "Example", "family": "Teacher"}}},
    ]},
    f"{PREFIX}/courses/{COURSE}/groups": {"results": [
        {"id": "_600_1", "name": "Example group", "description": "<p>Example tutorial</p>"},
    ]},
    f"/learn/api/v1/courses/{COURSE}/memberships": {"results": [
        {"userId": USER, "courseRole": {"roleId": "Student"}, "user": {"id": USER, "givenName": "Example", "familyName": "Student"}},
    ]},
    '/learn/api/v1/messages/summary': {"results": [{"courseId": COURSE, "isCourseMessagesEnabled": True}]},
    f'/learn/api/v1/courses/{COURSE}/conversations': {"results": [{
        "id": "_800_1", "courseId": COURSE, "totalCount": 2,
        "participantIds": [USER, "_901_1"], "participantsNotInACategory": [], "recipientCategory": ["Instructor"],
        "includesAllMembers": False, "messages": [
            {"id": "_801_1", "senderId": "_901_1", "sender": {"id": "_901_1", "givenName": "Example", "familyName": "Teacher"},
             "isRead": False, "postDate": NOW.isoformat(), "body": {"rawText": "<p>Full example message</p>"}},
            {"id": "_802_1", "senderId": USER, "sender": {"id": USER}, "postDate": NOW.isoformat(), "body": {"rawText": "<p>Example reply</p>"}},
        ],
    }]},
}
RESPONSES[f'/learn/api/v1/courses/{COURSE}/conversations/_800_1'] = deepcopy(
    RESPONSES[f'/learn/api/v1/courses/{COURSE}/conversations']['results'][0])


class FixtureSession:
    def get(self, path, params=None, refresh=False):
        data = deepcopy(RESPONSES[path])
        params = params or {}
        if "results" in data:
            limit, offset = params.get("limit", 50), params.get("offset", 0)
            rows = data["results"]
            data["results"] = rows[offset:offset + limit]
            if offset + limit < len(rows):
                data["paging"] = {"nextPage": f"{path}?limit={limit}&offset={offset + limit}"}
        return data, {"retrieved_at": NOW, "from_cache": False, "cache_age_seconds": 0}

    def status(self):
        return AuthStatus(credentials_configured=True, session_verified=True, last_verified_at=NOW, cache_ttl_seconds=300)

    def download(self, path, destination, max_bytes=20_000_000):
        with Path(destination).open('xb') as output:
            output.write(b'Example attachment')
        return Download(path=destination, bytes_written=18, downloaded_at=NOW)

    def close(self):
        pass
