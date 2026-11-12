"""Kaltura-specific streaming kept separate from NTULearn HTTP handling."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import anyio

from ...models import LearnError

if TYPE_CHECKING:
    from ..http import LearnHTTP

_REDIRECTS = {301, 302, 303, 307, 308}


async def download_kaltura_file(
    http: LearnHTTP,
    url: str,
    destination: Path,
    max_bytes: int,
    referer: str,
) -> int:
    """Stream a Kaltura download through validated Kaltura-only redirects."""
    try:
        player = urlsplit(referer)
        player_host = (player.hostname or "").lower()
        player_port = player.port
    except ValueError:
        raise LearnError(
            "Kaltura returned an unsupported player page; no video was saved."
        ) from None
    if (
        player.scheme != "https"
        or player_host != "api.sg.kaltura.com"
        or player_port not in (None, 443)
        or player.netloc.lower() not in {player_host, f"{player_host}:443"}
        or player.username is not None
        or player.password is not None
        or player.fragment
        or re.fullmatch(r"/p/\d+/embedPlaykitJs(?:/.*)?", player.path) is None
    ):
        raise LearnError(
            "Kaltura returned an unsupported player page; no video was saved."
        )
    request_headers = {
        "Referer": referer,
        "Origin": f"{player.scheme}://{player.netloc}",
    }
    current = url
    created = False
    total = 0
    try:
        for _ in range(4):
            try:
                parsed = urlsplit(current)
                host = (parsed.hostname or "").lower()
                port = parsed.port
            except ValueError:
                raise LearnError(
                    "Kaltura returned an unsupported or insecure video URL; no video was saved."
                ) from None
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.fragment
                or port not in (None, 443)
                or parsed.netloc.lower() not in {host, f"{host}:443"}
                or not (host == "kaltura.com" or host.endswith(".kaltura.com"))
            ):
                raise LearnError(
                    "Kaltura returned an unsupported or insecure video URL; no video was saved."
                )

            redirect = None
            async with http.stream(
                http.external_client, current, headers=request_headers
            ) as response:
                status = response.status_code
                if status in _REDIRECTS:
                    location = response.headers.get("location", "")
                    redirect = urljoin(current, location) if location else None
                elif status == 404:
                    raise LearnError(
                        "Kaltura did not expose a downloadable source for this video (HTTP 404); the entry may restrict raw downloads. No alternate access was attempted."
                    )
                elif status != 200:
                    raise LearnError(
                        f"Kaltura could not download this video (HTTP {status}); no video was saved."
                    )
                else:
                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                    )
                    if not (
                        content_type.startswith("video/")
                        or content_type
                        in {"application/octet-stream", "application/mp4"}
                    ):
                        raise LearnError(
                            "Kaltura returned a playlist or error page instead of a video file; no video was saved."
                        )
                    length = response.headers.get("content-length")
                    if length and length.isdigit() and int(length) > max_bytes:
                        raise LearnError(
                            "This video exceeds the requested size limit; no video was saved."
                        )
                    async with await anyio.open_file(destination, "xb") as output:
                        created = True
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > max_bytes:
                                raise LearnError(
                                    "This video exceeds the requested size limit; the partial file was removed."
                                )
                            await output.write(chunk)
                    if total == 0:
                        raise LearnError(
                            "Kaltura returned an empty video file; no video was saved."
                        )
                    return total

            if redirect is None:
                raise LearnError(
                    "Kaltura returned an incomplete or excessive redirect chain; no video was saved."
                )
            current = redirect

        raise LearnError(
            "Kaltura returned too many video redirects; no video was saved."
        )
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
