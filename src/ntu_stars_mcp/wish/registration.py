from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urljoin

from ..ntu_client.http import REQUEST_TIMEOUT_SECONDS, _wait_for_request_slot
from .models import NTUPersonalDataError, RegistrationResult
from .plan_editor import course_assignments, prepare_stars_plan
from .planner import PLANNER_VIEW_URL, _post, _response_html, _same_endpoint

if TYPE_CHECKING:
    from .session import WishSessionManager

REGISTRATION_URL = "https://wish.wis.ntu.edu.sg/pls/webexe/AUS_STARS_REG.reg_sub"
CONFIRMATION_TTL_SECONDS = 300
DANGER_WARNING = (
    "VERY DANGEROUS: this submits a real NTU course-registration request and can change official enrolment. "
    "NTU may reject, wait-list, or allocate courses according to its rules. This is not a saved-plan edit."
)


@dataclass(frozen=True)
class PendingRegistration:
    token: str
    courses: tuple[tuple[str, str], ...]
    academic_year: int
    semester: int
    baseline: str
    expires_at: str
    deadline: float


def _baseline(snapshot: dict[str, Any]) -> str:
    if snapshot["registered_courses_status"] not in {"empty", "parsed"}:
        raise NTUPersonalDataError("Existing registered courses could not be verified; no registration was submitted.")
    records = sorted(json.dumps(record, sort_keys=True) for record in snapshot["registered_courses"])
    return hashlib.sha256(json.dumps(records).encode()).hexdigest()


def _registration_form(page, html: str, courses: list[dict[str, str]]) -> list[tuple[str, str]]:
    state = page.evaluate("""html => {
        const d = new DOMParser().parseFromString(html, 'text/html');
        const buttons = [...d.querySelectorAll('input[type=submit]')]
          .filter(e => e.value === 'Add (Register) Selected Course(s)');
        if (buttons.length !== 1 || !buttons[0].form) return null;
        const b = buttons[0], f = b.form;
        return {action:f.getAttribute('action'), method:f.method, disabled:b.disabled,
          fields:[...new FormData(f).entries()]};
    }""", html)
    if (not state or state["disabled"] or state["method"] != "post"
            or not _same_endpoint(urljoin(PLANNER_VIEW_URL, state["action"] or ""), REGISTRATION_URL)):
        raise NTUPersonalDataError("NTU's registration form changed or is disabled; no registration was submitted.")
    fields = [tuple(field) for field in state["fields"]]
    if any(key not in {"p1", "p2", "subj_code", "index_nmbr", "tchar2", "boption"} for key, _ in fields):
        raise NTUPersonalDataError("NTU's registration form requires unfamiliar fields; complete it manually. No registration was submitted.")
    for name in ("p1", "p2", "tchar2", "boption"):
        values = [value for key, value in fields if key == name]
        if len(values) != 1 or (name in {"p1", "p2"} and not values[0]):
            raise NTUPersonalDataError("NTU's registration session fields changed; no registration was submitted.")
    codes = [value.strip().upper() for key, value in fields if key == "subj_code"]
    indexes = [value.strip() for key, value in fields if key == "index_nmbr"]
    if not 1 <= len(codes) <= 13 or len(codes) != len(indexes):
        raise NTUPersonalDataError("NTU's registration course/index fields are inconsistent; no registration was submitted.")
    selected = [(code, index) for code, index in zip(codes, indexes) if code]
    if (len(dict(selected)) != len(selected) or dict(selected) != course_assignments(courses)
            or any(index not in {"", "0", "null"} for code, index in zip(codes, indexes) if not code)):
        raise NTUPersonalDataError("NTU's registration form does not match the exact requested courses/indexes; no registration was submitted.")
    return fields


def _prepare_registration(page, courses: list[dict[str, str]], academic_year: int, semester: int) -> list[tuple[str, str]]:
    fields = prepare_stars_plan(page, courses, academic_year, semester)
    html = _post(page, PLANNER_VIEW_URL, fields)
    if html is None:
        raise NTUPersonalDataError("The NTU session expired during preview; no registration was submitted. Generate a fresh preview.")
    return _registration_form(page, html, courses)


def _submit_registration(page, fields: list[tuple[str, str]]) -> None:
    # One fixed registration request; never follow further forms, declarations, or redirects.
    _wait_for_request_slot()
    response = page.context.request.post(
        REGISTRATION_URL, data=urlencode(fields), headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=REQUEST_TIMEOUT_SECONDS * 1000, max_redirects=0,
    )
    _response_html(response, REGISTRATION_URL)


def _registered_as_requested(records: list[dict[str, str]], courses: list[dict[str, str]]) -> bool:
    found = {}
    for record in records:
        if any(re.search(r"wait.?list|pending|unsuccessful|rejected", value, re.I) for key, value in record.items() if "status" in key.casefold()):
            continue
        indexes = [value.strip() for key, value in record.items() if re.sub(r"[^a-z]", "", key.casefold()) in {"index", "indexno", "indexnumber", "indexnmbr"}]
        if len(indexes) == 1:
            found[record.get("course_code")] = indexes[0]
    return all(found.get(course["course_code"]) == course["index"] for course in courses)


def register_courses(
    session: WishSessionManager, courses: list[dict[str, str]], academic_year: int, semester: int,
    confirmation_token: str | None, user_confirmed: bool,
) -> RegistrationResult:
    """Run on the shared browser thread; a consumed confirmation can never resubmit."""
    from .session import PLANNER_URL

    with session._lock:
        selection = tuple((course["course_code"], course["index"]) for course in courses)
        pending = session._pending_registration
        if user_confirmed:
            if (pending is None or not confirmation_token or not hmac.compare_digest(confirmation_token, pending.token)
                    or time.monotonic() >= pending.deadline
                    or (selection, academic_year, semester) != (pending.courses, pending.academic_year, pending.semester)):
                raise NTUPersonalDataError("Missing, expired, consumed, or mismatched confirmation. Generate a new preview and ask the user 'Are you sure?' again.")
            session._pending_registration = None
        else:
            if confirmation_token is not None:
                raise NTUPersonalDataError("Ask the user 'Are you sure?' about this preview, then submit its token with user_confirmed=true only after a fresh affirmative reply.")
            session._pending_registration = None
        before = session._get_personal_data("stars_planner", PLANNER_URL, refresh=True)
        if (before["academic_year"], before["semester"]) != (academic_year, semester):
            raise NTUPersonalDataError("The requested term differs from NTU's current Planner term; no registration was submitted.")
        baseline = _baseline(before)
        if user_confirmed and baseline != pending.baseline:
            raise NTUPersonalDataError("Registered courses changed after the preview. Generate a new preview and obtain fresh user confirmation; no registration was submitted.")
        existing = {course["course_code"] for course in before["registered_courses"]}
        if any(course["course_code"] in existing for course in courses):
            raise NTUPersonalDataError("A requested course is already registered. This tool only adds new courses; remove existing courses from the request. No registration was submitted.")
        fields = _prepare_registration(session._page, courses, academic_year, semester)
        result: RegistrationResult = {
            "status": "confirmation_required", "academic_year": academic_year, "semester": semester,
            "courses": courses, "warning": DANGER_WARNING, "confirmation_question": None,
            "confirmation_token": None, "confirmation_expires_at": None,
            "registered_courses": before["registered_courses"], "message": "", "verified_at": None,
            "registered_courses_status": before["registered_courses_status"],
            "source_url": REGISTRATION_URL,
        }
        if not user_confirmed:
            token = secrets.token_urlsafe(32)
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONFIRMATION_TTL_SECONDS)).isoformat(timespec="seconds")
            session._pending_registration = PendingRegistration(token, selection, academic_year, semester, baseline, expires_at, time.monotonic() + CONFIRMATION_TTL_SECONDS)
            choices = ", ".join(f"{code} index {index}" for code, index in selection)
            result.update(
                confirmation_token=token, confirmation_expires_at=expires_at,
                confirmation_question=f"This changes your official NTU enrolment: register {choices} for AY{academic_year}/{str(academic_year + 1)[-2:]} semester {semester}. Are you sure?",
                message="Preview only; no registration submitted. Show the warning and exact courses/indexes, ask the confirmation question, and wait for a new explicit affirmative user reply before submitting.",
            )
            return result
        if time.monotonic() >= pending.deadline:
            raise NTUPersonalDataError("Confirmation expired during preparation. Generate a new preview and obtain fresh user confirmation; no registration was submitted.")
        session._cache.pop("stars_planner", None)
        session._cache.pop("degree_audit", None)
        result.update(status="unverified", message="Registration was attempted once. NTU may have registered, rejected, or wait-listed courses, or require additional choices. Check NTU before another attempt; no automatic retry or follow-up submission was performed.")
        result.update(registered_courses=[], registered_courses_status="unavailable")
        try:
            _submit_registration(session._page, fields)
        except Exception:
            # Even a timeout may follow a completed write; verify without repeating it.
            pass
        try:
            after = session._get_personal_data("stars_planner", PLANNER_URL, refresh=True)
            if (after["academic_year"], after["semester"]) == (academic_year, semester):
                _baseline(after)
                result["registered_courses"] = after["registered_courses"]
                result["registered_courses_status"] = after["registered_courses_status"]
                result["verified_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if _registered_as_requested(after["registered_courses"], courses):
                    result.update(status="registered", message="All requested course/index assignments appear in NTU's refreshed registered-course view.")
        except Exception:
            session._cache.pop("stars_planner", None)
            result["message"] = "Registration was attempted once, but its outcome could not be verified. Check NTU manually before another attempt; no automatic retry was performed."
        return result
