from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

_CHALLENGE_MESSAGE = (
    "NTU requested MFA or a CAPTCHA. Automatic login stopped; "
    "interactive verification is not supported by this headless session."
)

_MFA_MARKERS = re.compile(
    r"\b(captcha|multi[- ]factor|two[- ]factor|mfa|one[- ]time (password|passcode)|verification code|authenticator|security code)\b",
    re.I,
)

_LOGIN_MARKERS = re.compile(
    r"session (has )?expired|session timeout|not logged in|please log ?in|login required|"
    r"authentication required|not authorized|unauthorized|sign in to continue",
    re.I,
)

@dataclass
class _Input:
    name: str
    field_id: str
    value: str
    kind: str
    checked: bool

@dataclass
class _Form:
    action: str
    inputs: list[_Input] = field(default_factory=list)
    method: str = "get"

class _Forms(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_Form] = []
        self.current: _Form | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "form":
            self.current = _Form(attrs_map.get("action", ""), method=attrs_map.get("method", "get").lower())
        elif tag.lower() == "input" and self.current is not None:
            kind = attrs_map.get("type", "text").lower()
            if kind in {"checkbox", "radio"} and "checked" not in attrs_map:
                return
            name = attrs_map.get("name") or attrs_map.get("id", "")
            if name:
                self.current.inputs.append(
                    _Input(name, attrs_map.get("id", ""), attrs_map.get("value", ""), kind, "checked" in attrs_map)
                )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None

def _normal_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())

def _username_input(form: _Form) -> _Input | None:
    names = {"uid", "username", "userid", "user", "useridnumber", "networkusername", "account"}
    return next(
        (item for item in form.inputs if _normal_name(item.name) in names or _normal_name(item.field_id) in names),
        None,
    )

def _password_input(form: _Form) -> _Input | None:
    return next(
        (
            item for item in form.inputs
            if item.kind == "password" or _normal_name(item.name) in {"pw", "password", "userpassword"}
            or _normal_name(item.field_id) in {"pw", "password", "userpassword"}
        ),
        None,
    )

def _is_challenge(html: str) -> bool:
    return bool(_MFA_MARKERS.search(re.sub(r"<[^>]+>", " ", html)))

def _is_login_page(html: str) -> bool:
    forms = _Forms()
    forms.feed(html)
    if any(_username_input(form) or _password_input(form) for form in forms.forms):
        return True
    visible = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<[^>]+>", " ", html, flags=re.I | re.S)
    return bool(_LOGIN_MARKERS.search(" ".join(visible.split())))

def _allowed_form_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname) and (
        parsed.hostname == "ntu.edu.sg" or parsed.hostname.endswith(".ntu.edu.sg")
    )
