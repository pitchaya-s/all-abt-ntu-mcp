"""Bounded public HTTP transport for Omnibus."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
from urllib.parse import urljoin, urlsplit

import httpx

from public_http_client import defer_host_requests, host_request_slot
from ..models import OmnibusError
from .constants import (
    _ALLOWED_HOSTS,
    _MAX_ATTEMPTS,
    _MAX_REDIRECTS,
    _MAX_RESPONSE_BYTES,
    _MAX_RETRY_DELAY_SECONDS,
    _REDIRECTS,
    _RETRYABLE,
)


class HTTPMethods:
    def _read(self, url, *, body=None, headers=None):
        self._validate_url(url, redirect=False)
        if self._closed:
            raise OmnibusError(
                "The NTU Omnibus HTTP client is closed; restart the MCP server."
            )
        request_headers = {
            "OutSystems-client-env": "browser",
        }
        if headers:
            request_headers.update(headers)
        method = "POST" if body is not None else "GET"
        for attempt in range(_MAX_ATTEMPTS):
            try:
                status, payload, response_headers, response_url = self._request_chain(
                    url, method, body, request_headers
                )
            except httpx.RequestError:
                if attempt + 1 < _MAX_ATTEMPTS:
                    defer_host_requests(url, min(4.0, 2.0**attempt))
                    continue
                raise OmnibusError(
                    "Could not reach NTU Omnibus; try again later."
                ) from None
            except httpx.HTTPError:
                raise OmnibusError(
                    "NTU Omnibus returned an invalid HTTP response; retrieval stopped."
                ) from None

            if status == 429:
                logging.getLogger(__name__).warning(
                    "NTU Omnibus upstream returned HTTP 429"
                )
            if status in _RETRYABLE and attempt + 1 < _MAX_ATTEMPTS:
                delay = self._retry_delay(response_headers.get("retry-after"), attempt)
                if delay <= _MAX_RETRY_DELAY_SECONDS:
                    defer_host_requests(response_url, delay)
                    continue
            if status >= 400:
                return status, payload
            return payload
        raise OmnibusError(
            "Could not reach NTU Omnibus after two attempts; try again later."
        )

    @staticmethod
    def _validate_url(url, *, redirect=True):
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme == "https"
                and parsed.hostname is not None
                and parsed.hostname.lower() in _ALLOWED_HOSTS
                and parsed.port in (None, 443)
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            message = (
                "NTU Omnibus returned an unexpected redirect; retrieval stopped."
                if redirect
                else ("NTU Omnibus returned an unexpected URL; retrieval stopped.")
            )
            raise OmnibusError(message)

    def _request_chain(self, url, method, body, headers):
        current_url = url
        for _ in range(_MAX_REDIRECTS + 1):
            self._validate_url(current_url)
            with (
                host_request_slot(current_url),
                self._http.stream(
                    method, current_url, content=body, headers=headers
                ) as response,
            ):
                response_url = str(response.url)
                self._validate_url(response_url)
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise OmnibusError(
                            "NTU Omnibus returned an incomplete redirect; retrieval stopped."
                        )
                    current_url = urljoin(current_url, location)
                    self._validate_url(current_url)
                    if response.status_code in {301, 302, 303} and method not in {
                        "GET",
                        "HEAD",
                    }:
                        method, body = "GET", None
                        headers = {
                            name: value
                            for name, value in headers.items()
                            if name.casefold() not in {"content-length", "content-type"}
                        }
                    continue

                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > _MAX_RESPONSE_BYTES:
                        raise OmnibusError(
                            "NTU Omnibus response exceeded the 8 MB limit."
                        )
                return (
                    response.status_code,
                    bytes(payload),
                    response.headers,
                    response_url,
                )
        raise OmnibusError(
            "NTU Omnibus returned too many redirects; retrieval stopped."
        )

    @staticmethod
    def _retry_delay(value, attempt):
        if value:
            try:
                delay = max(0.0, float(value))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(value)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    delay = max(
                        0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()
                    )
                except (TypeError, ValueError, OverflowError):
                    delay = min(4.0, 2.0**attempt)
        else:
            delay = min(4.0, 2.0**attempt)
        return delay

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._http.close()
            self._finalizer.detach()

    def _get_bytes(self, url):
        response = self._read(url)
        if isinstance(response, tuple):
            code, _ = response
            raise OmnibusError(
                f"NTU Omnibus returned HTTP {code} while loading public app data."
            )
        return response
