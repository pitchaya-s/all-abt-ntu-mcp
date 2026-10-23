"""Normalize the directory's JSON cards and research-interest form options."""

import json
from urllib.parse import urlsplit

from shared.sitefinity import form_options, lines, text

from .models import FacultyError, Interest, Profile, SearchResults


def profile(value):
    url = value["url"]
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not (host == "ntu.edu.sg" or host.endswith(".ntu.edu.sg"))):
        raise FacultyError("NTU returned an unsupported faculty profile link.")
    interests = text(value.get("interests"))
    return Profile(
        name=text(value["title"]), school=text(value.get("tag")), email=text(value.get("email")),
        appointments=lines(value.get("appointments")),
        interests=[part.strip() for part in interests.split("|") if part.strip()] if interests else (
            [] if value.get("interests") == "" else None
        ),
        summary=text(value.get("description")), profile_url=url,
    )


def search_results(body, snapshot, page):
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise FacultyError("NTU returned an unexpected faculty result list.")
    result = SearchResults(
        profiles=[profile(value) for value in data["items"]], page=page,
        total_pages=data["totalPages"], total_count=data["totalItems"],
        next_page=page + 1 if page < data["totalPages"] else None, **snapshot,
    )
    if (result.total_pages != (result.total_count + 9) // 10
            or len(result.profiles) != min(10, max(0, result.total_count - (page - 1) * 10))
            or len({p.profile_url for p in result.profiles}) != len(result.profiles)):
        raise FacultyError("NTU changed its faculty pagination format; no complete result page was inferred.")
    return result


def interest_options(body):
    try:
        return [Interest(interest_id=item.id, name=item.name) for item in form_options(body, "interests")]
    except ValueError:
        raise FacultyError("NTU changed its faculty interest form; no filter IDs were inferred.") from None
