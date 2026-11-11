"""Kaltura embed parsing and viewer playback capture."""

import asyncio
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from ...client.browser_cookies import BASE_URL
from ...models import LearnError

_KALTURA_HOST = "api.sg.kaltura.com"
_KALTURA_PLAYER_PATH = re.compile(r"/p/\d+/embedPlaykitJs(?:/|$)")
_ENTRY_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_BROWSE_ENTRY_PATH = re.compile(r"^/browseandembed/index/media/entryid/(?P<entry>[A-Za-z0-9_-]{1,80})(?:/|$)", re.I)
_KALTURA_UICONF = re.compile(r"api\.sg\.kaltura\.com/p/(\d+)/embedPlaykitJs/uiconf_id/(\d+)", re.I)
_KALTURA_OVP_HOST = re.compile(r"api\.[A-Za-z0-9-]+\.ovp\.kaltura\.com\Z")
_MANIFEST_PATH = re.compile(
    r"/playManifest/entryId/(?P<entry>[A-Za-z0-9_-]{1,80})(?:/|$)"
)
_MANIFEST_ROOT = re.compile(
    r"^/p/(?P<partner>\d+)/sp/(?P<subpartner>\d+)/playManifest/entryId/"
    r"(?P<entry>[A-Za-z0-9_-]{1,80})(?:/|$)"
)
_MEDIA_SUFFIXES = (".aac", ".m3u8", ".m4s", ".mp4", ".m4v", ".ts", ".webm")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src", "data-src", "srcdoc"} and isinstance(value, str):
                self.values.append(value)

    def handle_data(self, data):
        self.values.extend(re.findall(r"https?://[^\s\"'<>]+", data))


def _values(html: str, depth: int = 0) -> list[str]:
    parser = _Links()
    parser.feed(html)
    result = list(parser.values)
    if depth < 2:
        for value in parser.values:
            if "<" in value and ">" in value:
                result.extend(_values(value, depth + 1))
    return [value.replace("\\/", "/").replace("\\u0026", "&") for value in result]


def _player(html: str) -> tuple[str, str] | None:
    for candidate in _values(html):
        try:
            parsed = urlsplit(candidate)
            host = (parsed.hostname or "").lower()
            entry_id = parse_qs(parsed.query).get("entry_id", [""])[0]
            if (
                parsed.scheme == "https"
                and host == _KALTURA_HOST
                and parsed.port in (None, 443)
                and parsed.netloc.lower() in {host, f"{host}:443"}
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
                and _KALTURA_PLAYER_PATH.search(parsed.path)
                and _ENTRY_ID.fullmatch(entry_id)
            ):
                return candidate, entry_id
        except ValueError:
            continue
    return None


def _webdav_link(html: str) -> str | None:
    for candidate in _values(html):
        try:
            absolute = urljoin(BASE_URL + "/", candidate)
            parsed = urlsplit(absolute)
            host = (parsed.hostname or "").lower()
            if (
                parsed.scheme == "https"
                and host == "ntulearn.ntu.edu.sg"
                and parsed.port in (None, 443)
                and parsed.netloc.lower() in {host, f"{host}:443"}
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
                and parsed.path.startswith("/bbcswebdav/")
            ):
                return absolute
        except ValueError:
            continue
    return None


def _browseandembed_link(html: str) -> tuple[str, str] | None:
    candidates = [*_values(html), *re.findall(r"https?://[^\s\"'<>]+", html, re.I)]
    for candidate in candidates:
        candidate = candidate.strip().replace("\\/", "/")
        candidate = re.split(r"&quot;|&#34;|[\"']", candidate, maxsplit=1)[0].rstrip(",; ")
        try:
            absolute = urljoin(BASE_URL + "/", candidate)
            parsed = urlsplit(absolute)
            host = (parsed.hostname or "").lower()
            path = _BROWSE_ENTRY_PATH.match(parsed.path)
            if (
                parsed.scheme == "https"
                and host == "ntulearnv1.ntu.edu.sg"
                and parsed.port in (None, 443)
                and parsed.netloc.lower() in {host, f"{host}:443"}
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
                and path is not None
            ):
                return absolute, path.group("entry")
        except ValueError:
            continue
    return None


def _player_from_browseandembed(html: str, entry_id: str) -> tuple[str, str] | None:
    for partner, uiconf in _KALTURA_UICONF.findall(html):
        query = urlencode({"entry_id": entry_id, "iframeembed": "true"})
        return (
            f"https://{_KALTURA_HOST}/p/{partner}/embedPlaykitJs/uiconf_id/{uiconf}?{query}",
            entry_id,
        )
    return None


def _download_manifest_url(manifest_url: str, expected_entry: str) -> str:
    try:
        parsed = urlsplit(manifest_url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
        match = _MANIFEST_PATH.search(parsed.path)
        root = _MANIFEST_ROOT.match(parsed.path)
        playback_format = re.search(r"/format/applehttp(?:/|$)", parsed.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
    except (ValueError, TypeError):
        match = None
        root = None
        playback_format = None
        port = None
        query = {}
        parsed = None
        host = ""
    if (
        parsed is None
        or parsed.scheme != "https"
        or not (host == _KALTURA_HOST or _KALTURA_OVP_HOST.fullmatch(host))
        or port not in (None, 443)
        or parsed.netloc.lower() not in {host, f"{host}:443"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or match is None
        or match.group("entry") != expected_entry
        or root is None
        or root.group("entry") != expected_entry
        or playback_format is None
    ):
        raise LearnError("Kaltura did not provide a supported viewer playback session for this entry.")
    path_sessions = re.findall(r"/ks/([^/]+)(?=/|$)", parsed.path)
    query_sessions = query.get("ks", [])
    sessions = path_sessions + query_sessions
    if len(sessions) > 1 or (sessions and (not sessions[0] or len(sessions[0]) > 8192)):
        raise LearnError("Kaltura returned an invalid viewer session for this entry.")
    if sessions and any(ord(char) < 32 or ord(char) == 127 for char in sessions[0]):
        raise LearnError("Kaltura returned an invalid viewer session.")
    query_pairs = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "ks"]
    path = (
        f"/p/{root.group('partner')}/sp/{root.group('subpartner')}"
        f"/playManifest/entryId/{expected_entry}/format/download/protocol/https"
        f"/flavorParamIds/0"
    )
    if sessions:
        path += f"/ks/{quote(unquote(sessions[0]), safe='')}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query_pairs), ""))


async def _capture_viewer_manifest(player_url: str, entry_id: str) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise LearnError(
            "Kaltura video downloads need the optional personal dependencies and Chromium. Install them with `uv sync --extra personal` and `uv run playwright install chromium`."
        ) from None

    loop = asyncio.get_running_loop()
    captured: asyncio.Future[str] = loop.create_future()
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(service_workers="block", locale="en-US")
                page = await context.new_page()

                async def inspect_request(route):
                    request = route.request
                    try:
                        parsed = urlsplit(request.url)
                    except ValueError:
                        await route.abort()
                        return
                    host = (parsed.hostname or "").lower()
                    if not (host == "kaltura.com" or host.endswith(".kaltura.com")):
                        await route.abort()
                        return
                    path = parsed.path.lower()
                    if "/playmanifest/" in path:
                        host = (parsed.hostname or "").lower()
                        if (host == _KALTURA_HOST or _KALTURA_OVP_HOST.fullmatch(host)) and not captured.done():
                            try:
                                _download_manifest_url(request.url, entry_id)
                            except LearnError:
                                pass
                            else:
                                captured.set_result(request.url)
                        await route.abort()
                        return
                    if request.resource_type == "media" or path.endswith(_MEDIA_SUFFIXES):
                        await route.abort()
                        return
                    await route.continue_()

                await page.route("**/*", inspect_request)
                try:
                    await page.goto(player_url, wait_until="domcontentloaded", timeout=30_000)
                except Exception:
                    if not captured.done():
                        raise
                if not captured.done():
                    for selector in (
                        ".playkit-pre-playback-play-button",
                        'button[aria-label*="Play" i]',
                        '[role="button"][aria-label*="Play" i]',
                    ):
                        try:
                            control = page.locator(selector).first
                            if await control.count():
                                await control.click(timeout=2_000)
                                break
                        except Exception:
                            continue
                if not captured.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(captured), timeout=25)
                    except asyncio.TimeoutError:
                        raise LearnError("Kaltura did not start playback for this video; no download was made.") from None
                return captured.result()
            finally:
                await browser.close()
    except LearnError:
        raise
    except Exception:
        raise LearnError("Could not open the Kaltura player or obtain its short-lived viewer session.") from None
