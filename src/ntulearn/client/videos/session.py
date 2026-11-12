"""Authenticated access to NTULearn video wrappers and Kaltura downloads."""

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ...models import Download, LearnError
from ..http import AuthGenerationChanged

MAX_WRAPPER_BYTES = 2_000_000
_REDIRECTS = {301, 302, 303, 307, 308}


def _is_blackboard_host(host: str | None) -> bool:
    return bool(
        host
        and (
            host == "blackboard.com"
            or host.endswith((".blackboard.com", ".blackboardcdn.com"))
        )
    )


def _safe_webdav_url(value: str) -> bool:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and host == "ntulearn.ntu.edu.sg"
        and parsed.port in (None, 443)
        and parsed.netloc.lower() in {host, f"{host}:443"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and parsed.path.startswith("/bbcswebdav/")
    )


def _safe_browseandembed_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and host == "ntulearnv1.ntu.edu.sg"
        and port in (None, 443)
        and parsed.netloc.lower() in {host, f"{host}:443"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and parsed.path.startswith("/browseandembed/index/media/entryid/")
    )


def _safe_blackboard_url(value: str) -> bool:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and _is_blackboard_host(host)
        and parsed.port in (None, 443)
        and parsed.netloc.lower() in {host, f"{host}:443"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


class VideoSession:
    """Video operations that share authentication and HTTP resources with Session."""

    def __init__(self, session):
        self._session = session

    async def get_webdav_wrapper(self, url: str) -> str:
        """Fetch one Blackboard HTML wrapper, using NTU cookies only on NTU."""
        session = self._session
        if not _safe_webdav_url(url):
            raise LearnError(
                "This course item does not contain a supported NTULearn WebDAV link."
            )
        await session._begin_operation()
        try:
            state = await session._ensure_authenticated()
            current = url
            authenticated = True
            redirects = 0
            auth_retries = 0
            generation_retries = 0
            while True:
                request_client = (
                    session.http.client
                    if authenticated
                    else session.http.external_client
                )
                try:
                    async with session.http.stream(
                        request_client,
                        current,
                        expected_generation=state.generation if authenticated else None,
                    ) as response:
                        status = response.status_code
                        location = response.headers.get("location", "")
                        redirected_to = urljoin(current, location) if location else ""
                        login_redirect = bool(
                            authenticated
                            and status in _REDIRECTS
                            and urlsplit(redirected_to).hostname
                            in {"ntulearn.ntu.edu.sg", "login.microsoftonline.com"}
                            and (
                                "login" in urlsplit(redirected_to).path.lower()
                                or "signin" in urlsplit(redirected_to).path.lower()
                            )
                        )
                        if authenticated and (status == 401 or login_redirect):
                            expired = True
                        else:
                            expired = False
                            if status in _REDIRECTS:
                                if not location or redirects >= 3:
                                    raise LearnError(
                                        "NTULearn returned an incomplete or excessive WebDAV redirect chain."
                                    )
                                if not _safe_blackboard_url(redirected_to):
                                    if authenticated:
                                        raise LearnError(
                                            "The WebDAV link redirected outside Blackboard; no request was sent there."
                                        )
                                    raise LearnError(
                                        "The Blackboard wrapper redirected to an unsupported host."
                                    )
                                authenticated = False
                                current = redirected_to
                                redirects += 1
                                continue
                            if status == 403:
                                raise LearnError(
                                    "NTULearn denied access to this video wrapper (HTTP 403); no alternate access was attempted."
                                )
                            if status == 404:
                                raise LearnError(
                                    "NTULearn could not find this video wrapper (HTTP 404)."
                                )
                            if status != 200:
                                raise LearnError(
                                    f"NTULearn could not read the video wrapper (HTTP {status})."
                                )
                            if (
                                "text/html"
                                not in response.headers.get("content-type", "").lower()
                            ):
                                raise LearnError(
                                    "The Blackboard WebDAV item was not an HTML video wrapper."
                                )
                            body = await self._read_wrapper(
                                response, "The Blackboard video wrapper"
                            )
                            return body
                    if expired:
                        if auth_retries:
                            raise LearnError(
                                "NTULearn's session expired while reading the video wrapper; retry later."
                            )
                        state = await session.auth.recover(state.generation)
                        session._sync_cache_generation()
                        current = url
                        authenticated = True
                        redirects = 0
                        auth_retries += 1
                        continue
                except AuthGenerationChanged:
                    generation_retries += 1
                    if generation_retries > 2:
                        raise LearnError(
                            "NTULearn authentication changed repeatedly while reading the video wrapper; retry the request."
                        ) from None
                    state = await session._ensure_authenticated()
                    current = url
                    authenticated = True
                    redirects = 0
        finally:
            await session._end_operation()

    async def get_browseandembed_page(self, url: str) -> str:
        """Read the NTU-hosted Kaltura browse-and-embed configuration page."""
        session = self._session
        if not _safe_browseandembed_url(url):
            raise LearnError(
                "This course item does not contain a supported NTULearn video wrapper."
            )
        await session._begin_operation()
        try:
            state = await session._ensure_authenticated()
            auth_retries = 0
            generation_retries = 0
            while True:
                try:
                    async with session.http.stream(
                        session.http.client,
                        url,
                        expected_generation=state.generation,
                    ) as response:
                        status = response.status_code
                        if status == 401:
                            expired = True
                        elif status in _REDIRECTS:
                            location = response.headers.get("location", "")
                            target = urljoin(url, location) if location else ""
                            parsed_target = urlsplit(target)
                            if (
                                parsed_target.hostname == "login.microsoftonline.com"
                                or (
                                    parsed_target.hostname == "ntulearnv1.ntu.edu.sg"
                                    and (
                                        "login" in parsed_target.path.lower()
                                        or "signin" in parsed_target.path.lower()
                                    )
                                )
                            ):
                                expired = True
                            else:
                                raise LearnError(
                                    "The NTULearn video wrapper redirected to an unsupported destination."
                                )
                        else:
                            expired = False
                            if status == 403:
                                raise LearnError(
                                    "NTULearn denied access to this video wrapper (HTTP 403)."
                                )
                            if status == 404:
                                raise LearnError(
                                    "NTULearn could not find this video wrapper (HTTP 404)."
                                )
                            if status != 200:
                                raise LearnError(
                                    f"NTULearn could not read the video wrapper (HTTP {status})."
                                )
                            if (
                                "text/html"
                                not in response.headers.get("content-type", "").lower()
                            ):
                                raise LearnError(
                                    "The NTULearn video wrapper was not an HTML page."
                                )
                            return await self._read_wrapper(
                                response, "The NTULearn video wrapper"
                            )
                    if expired:
                        if auth_retries:
                            raise LearnError(
                                "NTULearn's session expired while reading the video wrapper; retry later."
                            )
                        state = await session.auth.recover(state.generation)
                        session._sync_cache_generation()
                        auth_retries += 1
                        continue
                except AuthGenerationChanged:
                    generation_retries += 1
                    if generation_retries > 2:
                        raise LearnError(
                            "NTULearn authentication changed repeatedly while reading the video wrapper; retry the request."
                        ) from None
                    state = await session._ensure_authenticated()
        finally:
            await session._end_operation()

    async def download_kaltura_video(
        self, url: str, destination: str, max_bytes: int, referer: str
    ) -> Download:
        session = self._session
        if type(max_bytes) is not int or not 1 <= max_bytes <= 2_000_000_000:
            raise LearnError(
                "The video size limit must be between 1 byte and 2000000000 bytes."
            )
        target = Path(destination).expanduser().absolute()
        if any(part.is_symlink() for part in (target.parent, *target.parent.parents)):
            raise LearnError(
                "Video download directories must not contain symbolic links."
            )
        if target.exists() or not target.parent.is_dir():
            raise LearnError(
                "Choose a new video file path in an existing directory; existing files are never overwritten."
            )
        await session._begin_operation()
        try:
            size = await session.http.download_kaltura_file(
                url, target, max_bytes, referer
            )
            return Download(
                path=str(target),
                bytes_written=size,
                downloaded_at=datetime.now(timezone.utc),
            )
        except OSError:
            raise LearnError(
                "Could not save the video. Check the destination and available space; no partial file was kept."
            ) from None
        finally:
            await session._end_operation()

    @staticmethod
    async def _read_wrapper(response, description: str) -> str:
        if (
            (length := response.headers.get("content-length"))
            and length.isdigit()
            and int(length) > MAX_WRAPPER_BYTES
        ):
            raise LearnError(f"{description} exceeded the 2 MB read limit.")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_WRAPPER_BYTES:
                raise LearnError(f"{description} exceeded the 2 MB read limit.")
        return body.decode("utf-8", errors="replace")
