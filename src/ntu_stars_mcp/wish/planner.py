from __future__ import annotations

from email.message import Message
import re
from urllib.parse import urlencode, urljoin, urlsplit

from ..ntu_client.http import MAX_RESPONSE_BYTES, NTURequestError, REQUEST_TIMEOUT_SECONDS, _wait_for_request_slot
from ..parser import NTUPageError, parse_stars_planner_page
from ..parser.planner import parse_saved_plan_timetable
from .forms import _CHALLENGE_MESSAGE, _Forms, _is_challenge, _is_login_page
from .models import NTUAuthError, NTUPersonalDataError

PLANNER_VIEW_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.planner"
_SELECTION_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.time_table"
_LOAD_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_PLANNER.load_time_table"


def _same_endpoint(url: str, expected: str) -> bool:
    return urlsplit(url)._replace(query="", fragment="").geturl().casefold() == expected.casefold()


def _expired(html: str) -> bool:
    return _is_login_page(html) or bool(re.search(r"session (?:has )?(?:expired|time[ -]?out)", html, re.I))


def _post(page, url: str, fields: list[tuple[str, str]]) -> str | None:
    if url not in {_LOAD_URL, PLANNER_VIEW_URL}:
        raise NTUPersonalDataError("Refused a Planner request outside the two read-only display endpoints.")
    _wait_for_request_slot()
    response = page.context.request.post(
        url, data=urlencode(fields), headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=REQUEST_TIMEOUT_SECONDS * 1000, max_redirects=0,
    )
    try:
        if response.status == 401:
            return None
        if 300 <= response.status < 400:
            target = urlsplit(urljoin(url, response.headers.get("location", "")))
            if target.scheme == "https" and target.hostname == "wish.wis.ntu.edu.sg" and target.path.casefold().endswith("/ldap_login.login"):
                return None
            raise NTUPersonalDataError("NTU redirected the Planner display unexpectedly; no redirect was followed.")
        if response.status != 200:
            raise NTURequestError(f"NTU returned HTTP {response.status} for the read-only Planner display.")
        content_type = Message()
        content_type["content-type"] = response.headers.get("content-type", "")
        if content_type.get_content_type() != "text/html":
            raise NTUPersonalDataError("NTU's Planner display did not return HTML.")
        body = response.body()
        if len(body) > MAX_RESPONSE_BYTES:
            raise NTUPersonalDataError("NTU's Planner display exceeded the 5 MB safety limit.")
        try:
            html = body.decode(content_type.get_content_charset() or "windows-1252", errors="replace")
        except LookupError:
            html = body.decode("windows-1252", errors="replace")
        if _is_challenge(html):
            raise NTUAuthError(_CHALLENGE_MESSAGE)
        return None if _expired(html) else html
    finally:
        response.dispose()


def _load_plan(page, fields: list[tuple[str, str]], number: int) -> dict[str, object] | None:
    fields = [(key, value) for key, value in fields if key != "plan_no"] + [("plan_no", str(number))]
    html = _post(page, _LOAD_URL, fields)
    if html is None:
        return None
    forms = _Forms()
    forms.feed(html)
    form = next((form for form in forms.forms if _same_endpoint(urljoin(_LOAD_URL, form.action), PLANNER_VIEW_URL)), None)
    if form is None:
        raise NTUPageError("NTU's saved-plan Load response no longer contains its read-only display form.")
    expected = dict(fields)
    for name in ("plan_no", "acad", "semester"):
        actual = [item.value for item in form.inputs if item.name == name]
        if name not in expected or actual != [expected[name]]:
            raise NTUPageError("NTU's saved-plan response identified a different plan or academic term.")
    values = {name: [item.value for item in form.inputs if item.name == name] for name in ("subj_code", "index_nmbr", "subj_type")}
    if not values["subj_code"] or len({len(items) for items in values.values()}) != 1:
        raise NTUPageError("NTU's saved-plan course/index fields were missing or inconsistent.")
    courses: list[dict[str, object]] = []
    for code, index, kind in zip(values["subj_code"], values["index_nmbr"], values["subj_type"]):
        if not code.strip():
            continue
        code, index = code.strip().upper(), index.strip()
        if not re.fullmatch(r"[A-Z]{2,4}\d{4}[A-Z]?", code) or (index and not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", index)):
            raise NTUPageError("NTU's saved plan contained an unfamiliar course or index format.")
        courses.append({"course_code": code, "index": index if index and index != "0" else None, "course_type": kind or None})
    if len({course["course_code"] for course in courses}) != len(courses):
        raise NTUPageError("NTU's saved plan contained duplicate courses with ambiguous index assignments.")
    display = _post(page, PLANNER_VIEW_URL, [(item.name, item.value) for item in form.inputs if item.kind == "hidden"])
    if display is None:
        return None
    return {"plan_number": number, "status": "loaded", "courses": courses, **parse_saved_plan_timetable(display, courses)}


def read_stars_planner(page) -> dict[str, object] | None:
    """Read the registered-course view and saved plans. None means the session expired."""
    if not _same_endpoint(page.url, PLANNER_VIEW_URL):
        if not _same_endpoint(page.url, _SELECTION_URL):
            raise NTUPageError("NTU's Planner opened an unexpected page.")
        form = page.locator('input[type="button"][value="Plan/ Registration"]').locator("xpath=ancestor::form")
        if (not _same_endpoint(urljoin(page.url, form.get_attribute("action") or ""), _SELECTION_URL)
                or (form.get_attribute("method") or "get").casefold() != "post"):
            raise NTUPageError("NTU's Planner selection form changed; no form was submitted.")
        _wait_for_request_slot()
        with page.expect_navigation(wait_until="load", timeout=REQUEST_TIMEOUT_SECONDS * 1000) as navigation:
            form.evaluate("(f, url) => {f.action=url; f.target='_self'; HTMLFormElement.prototype.submit.call(f)}", PLANNER_VIEW_URL)
        if navigation.value is not None and navigation.value.status >= 400:
            raise NTURequestError(f"NTU returned HTTP {navigation.value.status} for the Planner display.")
    html = page.content()
    if _expired(html):
        return None
    if not _same_endpoint(page.url, PLANNER_VIEW_URL):
        raise NTUPageError("NTU's Planner display navigation changed.")
    result = parse_stars_planner_page(html)
    state = page.evaluate("""() => {
        const button = [...document.querySelectorAll('input[type=button]')].find(e => e.value === 'Load');
        return {flags: Object.fromEntries([...document.querySelectorAll('input')]
          .filter(e => /^plan[123]_exists$/.test(e.name)).map(e => [e.name, e.value])),
          action: button?.form?.action, fields: button?.form ? [...new FormData(button.form).entries()] : null};
    }""")
    plans: list[dict[str, object]] = []
    for number in (1, 2, 3):
        flag = state["flags"].get(f"plan{number}_exists")
        if flag == "Y":
            if not state.get("action") or not _same_endpoint(state["action"], PLANNER_VIEW_URL) or state["fields"] is None:
                raise NTUPageError("NTU's saved-plan Load form changed; no request was submitted.")
            plan = _load_plan(page, [tuple(field) for field in state["fields"]], number)
            if plan is None:
                return None
        else:
            plan = {"plan_number": number, "status": "not_saved" if flag == "N" else "unknown", "courses": [],
                    "sessions": [], "unparsed_sessions": [], "timetable_status": "not_present"}
        plans.append(plan)
    result["saved_plans"] = plans
    return result
