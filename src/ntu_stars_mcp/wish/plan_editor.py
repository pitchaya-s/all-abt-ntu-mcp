from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from ..ntu_client.validation import _academic_term, validate_course_code
from ..parser import NTUPageError
from .models import NTUAuthError, NTUPersonalDataError
from .planner import PLANNER_VIEW_URL, SAVE_PLAN_URL, _post, _same_endpoint


def validate_plan_request(
    plan_number: int, courses: list[dict[str, str]], academic_year: int, semester: int
) -> list[dict[str, str]]:
    if type(plan_number) is not int or plan_number not in {1, 2, 3}:
        raise ValueError("Choose Plan 1, 2, or 3.")
    _academic_term(academic_year, semester)
    if type(semester) is not int or semester not in {1, 2}:
        raise ValueError("Planner semester must be 1 or 2.")
    if not 1 <= len(courses) <= 13:
        raise ValueError("Provide the complete plan with 1–13 courses; clearing an entire plan is not supported.")
    normalized = []
    for course in courses:
        code = validate_course_code(course["course_code"])
        index = course["index"].strip()
        if not re.fullmatch(r"[0-9]{1,12}", index):
            raise ValueError("Every planned course needs a numeric index number, supplied as a string.")
        normalized.append({"course_code": code, "index": index})
    if len({course["course_code"] for course in normalized}) != len(normalized):
        raise ValueError("A plan cannot contain duplicate course codes.")
    return normalized


def course_assignments(courses: list[dict[str, Any]]) -> dict[str, str | None]:
    return {course["course_code"]: course["index"] for course in courses}


def _form(page, html: str | None, academic_year: int, semester: int) -> dict[str, Any]:
    # DOMParser reads detached HTML without executing NTU's scripts or submitting forms.
    state = page.evaluate("""html => {
        const d = html === null ? document : new DOMParser().parseFromString(html, 'text/html');
        const buttons = [...d.querySelectorAll('input[type=button]')].filter(e => e.value === 'Save');
        if (buttons.length !== 1 || !buttons[0].form) return null;
        const b = buttons[0], f = b.form;
        return {action:f.getAttribute('action'), method:f.method, handler:b.getAttribute('onclick'),
          fields:[...new FormData(f).entries()],
          indexes:[...f.elements].filter(e => e.name === 'index_nmbr').map(e => ({
            options:e.tagName === 'SELECT' ? [...e.options].map(o => o.value) : null
          }))};
    }""", html)
    if (not state or state["method"] != "post"
            or not _same_endpoint(urljoin(PLANNER_VIEW_URL, state["action"] or ""), PLANNER_VIEW_URL)
            or not re.search(r"this\.form\.action\s*=\s*['\"]AUS_STARS_PLANNER\.save_time_table['\"]", state["handler"] or "", re.I)):
        raise NTUPageError("NTU's Planner Save form changed; no plan was saved.")
    fields = [tuple(field) for field in state["fields"]]
    for name, expected in (("acad", str(academic_year)), ("semester", str(semester))):
        if [value for key, value in fields if key == name] != [expected]:
            raise NTUPageError("NTU's Planner form identified a different academic term; no plan was saved.")
    for name in ("p1", "p2"):
        values = [value for key, value in fields if key == name]
        if len(values) != 1 or not values[0]:
            raise NTUPageError("NTU's Planner session fields were missing; no plan was saved.")
    for name in ("plan_no", "boption", "r_subj"):
        if sum(key == name for key, _ in fields) != 1:
            raise NTUPageError("NTU's Planner update controls changed; no plan was saved.")
    groups = {name: [value for key, value in fields if key == name] for name in ("subj_code", "index_nmbr", "subj_type")}
    size = len(groups["subj_code"])
    if not 1 <= size <= 13 or any(len(values) != size for values in groups.values()) or len(state["indexes"]) != size:
        raise NTUPageError("NTU's Planner course/index fields changed; no plan was saved.")
    codes = [code for code in groups["subj_code"] if code]
    if len(set(codes)) != len(codes):
        raise NTUPageError("NTU's Planner returned duplicate course assignments; no plan was saved.")
    return {**state, "fields": fields, "groups": groups}


def _fields(state: dict[str, Any], **changes: str) -> list[tuple[str, str]]:
    return [(key, value) for key, value in state["fields"] if key not in changes] + list(changes.items())


def _display(page, fields: list[tuple[str, str]], academic_year: int, semester: int) -> dict[str, Any]:
    html = _post(page, PLANNER_VIEW_URL, fields)
    if html is None:
        raise NTUAuthError("NTU's session expired while preparing the plan; no save was submitted. Retry the tool.")
    return _form(page, html, academic_year, semester)


def prepare_stars_plan(
    page, courses: list[dict[str, str]], academic_year: int, semester: int
) -> list[tuple[str, str]]:
    """Build a scratch timetable through NTU's native Add/Update flow, without saving."""
    state = _form(page, None, academic_year, semester)
    fields = [(key, "" if key in {"subj_code", "index_nmbr", "subj_type"} else value) for key, value in state["fields"]]
    fields = [(key, value) for key, value in fields if key not in {"boption", "r_subj"}] + [("boption", "Update"), ("r_subj", "")]
    state = _display(page, fields, academic_year, semester)
    if any(state["groups"]["subj_code"]):
        raise NTUPageError("NTU did not clear the scratch timetable; no plan was saved.")
    requested: dict[str, str] = {}
    for course in courses:
        code, index = course["course_code"], course["index"]
        state = _display(page, _fields(state, boption="Update", r_subj=code), academic_year, semester)
        requested[code] = index
        if {code for code in state["groups"]["subj_code"] if code} != set(requested):
            raise NTUPersonalDataError("NTU did not accept a requested course in this term; no plan was saved.")
        values = []
        for code, options in zip(state["groups"]["subj_code"], state["indexes"]):
            if code:
                if requested[code] not in (options["options"] or []):
                    raise NTUPersonalDataError(f"Index {requested[code]} is not offered for {code} in this Planner term; no plan was saved.")
                values.append(requested[code])
            else:
                values.append("")
        iterator = iter(values)
        state["fields"] = [(key, next(iterator) if key == "index_nmbr" else value) for key, value in state["fields"]]
    state = _display(page, _fields(state, boption="Update", r_subj=""), academic_year, semester)
    actual = {code: index for code, index in zip(state["groups"]["subj_code"], state["groups"]["index_nmbr"]) if code}
    if actual != requested:
        raise NTUPersonalDataError("NTU did not retain the selected indexes in the scratch timetable; no plan was saved.")
    return _fields(state, boption="", r_subj="")


def submit_stars_plan(page, fields: list[tuple[str, str]], plan_number: int) -> None:
    fields = [(key, value) for key, value in fields if key != "plan_no"] + [("plan_no", str(plan_number))]
    try:
        html = _post(page, SAVE_PLAN_URL, fields, save=True)
    except Exception as error:
        raise NTUPersonalDataError(
            "NTU's plan-save response could not be verified. The plan may have changed; refresh the Planner before retrying. No automatic save retry was attempted."
        ) from error
    if html is None or not re.search(r"saved\s+successfully|successfully\s+saved", html, re.I):
        raise NTUPersonalDataError(
            "NTU did not confirm the plan save. Refresh the Planner to check its state before retrying; the save was not repeated."
        )
