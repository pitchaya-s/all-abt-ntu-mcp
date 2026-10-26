"""Optional, transient discovery of authenticated NTULearn browser cookies."""

import http.cookiejar
import re
import time
from dataclasses import dataclass, field
from typing import Any

BASE_URL = "https://ntulearn.ntu.edu.sg"
NTULEARN_HOST = "ntulearn.ntu.edu.sg"
_ALLOWED_DOMAINS = {"ntu.edu.sg", NTULEARN_HOST}
_COOKIE_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_BROWSERS = ("edge", "chrome", "firefox", "brave", "safari")


@dataclass(frozen=True, slots=True)
class SessionCookie:
    name: str
    value: str = field(repr=False)
    domain: str
    path: str = "/"
    expires: int | None = None
    secure: bool = True
    http_only: bool = False
    domain_specified: bool = False


def _is_safe(cookie: SessionCookie) -> bool:
    if not all(
        isinstance(value, str)
        for value in (cookie.name, cookie.value, cookie.domain, cookie.path)
    ):
        return False
    raw_domain = cookie.domain.lower()
    domain = raw_domain[1:] if raw_domain.startswith(".") else raw_domain
    return (
        cookie.name != ""
        and _COOKIE_NAME.fullmatch(cookie.name) is not None
        and bool(cookie.value)
        and not any(ord(char) < 32 or ord(char) == 127 for char in cookie.value)
        and domain in _ALLOWED_DOMAINS
        and raw_domain in {domain, f".{domain}"}
        and cookie.path.startswith("/")
        and not any(char in cookie.path for char in "\r\n\0")
        and (cookie.expires is None or cookie.expires > time.time())
    )


def _from_browser_cookie(cookie: Any) -> SessionCookie | None:
    try:
        expires = getattr(cookie, "expires", None)
        expires = int(expires) if expires and expires > 0 else None
        rest = getattr(cookie, "_rest", {}) or {}
        value = SessionCookie(
            name=cookie.name,
            value=cookie.value,
            domain=cookie.domain,
            path=cookie.path or "/",
            expires=expires,
            secure=bool(cookie.secure),
            http_only="HttpOnly" in rest,
            domain_specified=bool(getattr(cookie, "domain_specified", False)),
        )
    except (AttributeError, TypeError, ValueError):
        return None
    return value if _is_safe(value) else None


def _from_playwright_cookie(cookie: dict[str, Any]) -> SessionCookie | None:
    try:
        raw_expiry = cookie.get("expires")
        expires = int(raw_expiry) if isinstance(raw_expiry, (int, float)) and raw_expiry > 0 else None
        value = SessionCookie(
            name=cookie["name"],
            value=cookie["value"],
            domain=cookie["domain"],
            path=cookie.get("path") or "/",
            expires=expires,
            secure=bool(cookie.get("secure", True)),
            http_only=bool(cookie.get("httpOnly", False)),
            domain_specified=str(cookie["domain"]).startswith("."),
        )
    except (KeyError, TypeError, ValueError):
        return None
    return value if _is_safe(value) else None


def _read_from_module(module: Any, browsers: tuple[str, ...]) -> list[tuple[SessionCookie, ...]]:
    candidates = []
    for browser in browsers:
        getter = getattr(module, browser, None)
        if getter is None:
            continue
        try:
            jar = getter(domain_name="ntu.edu.sg")
            cookies = tuple(
                candidate
                for item in jar
                if (candidate := _from_browser_cookie(item)) is not None
            )
        except Exception:  # noqa: BLE001,S112  # nosec B112
            # Browser locks, encryption, permissions, and platform failures are
            # expected. Never put exception text or cookie data in logs.
            continue
        if any(cookie.name == "BbRouter" and cookie.value.startswith("expires:") for cookie in cookies):
            candidates.append(cookies)
    return candidates


def read_browser_cookie_sets(
    *, module: Any | None = None, browsers: tuple[str, ...] = _BROWSERS
) -> list[tuple[SessionCookie, ...]]:
    """Return isolated cookie sets, one per browser, without persisting values."""
    if module is None:
        try:
            import browser_cookie3
        except ImportError:
            return []
        module = browser_cookie3
    return _read_from_module(module, browsers)


def playwright_cookies(cookies: list[dict[str, Any]]) -> tuple[SessionCookie, ...]:
    """Keep all valid cookies applicable to NTULearn, not only BbRouter."""
    result = tuple(
        value
        for cookie in cookies
        if (value := _from_playwright_cookie(cookie)) is not None
    )
    if not any(cookie.name == "BbRouter" for cookie in result):
        return ()
    return result


def install_cookies(jar: http.cookiejar.CookieJar, cookies: tuple[SessionCookie, ...]) -> None:
    """Install cookies while retaining their original domain/path/expiry scope."""
    jar.clear()
    for cookie in cookies:
        domain = cookie.domain.lower()
        initial_dot = domain.startswith(".")
        expires = cookie.expires
        jar.set_cookie(
            http.cookiejar.Cookie(
                version=0,
                name=cookie.name,
                value=cookie.value,
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=cookie.domain_specified or initial_dot,
                domain_initial_dot=initial_dot,
                path=cookie.path,
                path_specified=True,
                secure=cookie.secure,
                expires=expires,
                discard=expires is None,
                comment=None,
                comment_url=None,
                rest={"HttpOnly": ""} if cookie.http_only else {},
                rfc2109=False,
            )
        )
