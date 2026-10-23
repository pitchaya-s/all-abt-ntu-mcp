"""Bounded public HTTP reads shared by NTU services."""

from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class PublicRequestError(RuntimeError):
    pass


class _Redirects(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def validate(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in self.hosts or parsed.port not in (None, 443) or parsed.username:
            raise PublicRequestError("The public service returned an unexpected redirect; retrieval stopped.")

    def redirect_request(self, request, response, code, message, headers, new_url):
        self.validate(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


class PublicHTTPClient:
    def __init__(self, service, hosts, content_types):
        self.service = service
        self.content_types = content_types
        self.redirects = _Redirects(frozenset(hosts))
        self.opener = build_opener(self.redirects)
        self._lock = Lock()
        self._cache = OrderedDict()
        self._last_request = 0.0

    def get(self, url, refresh=False):
        self.redirects.validate(url)
        with self._lock:
            cached = self._cache.get(url)
            if not refresh and cached is not None and time.monotonic() - cached[0] < 300:
                self._cache.move_to_end(url)
                return cached[1], dict(retrieved_at=cached[2], source_url=url, cached=True)
            request = Request(url, headers={"User-Agent": "all-abt-ntu-mcp/0.1 (public NTU lookup)", "Accept": ", ".join(sorted(self.content_types))})
            for attempt in range(2):
                time.sleep(max(0, 0.5 - (time.monotonic() - self._last_request)))
                self._last_request = time.monotonic()
                try:
                    with self.opener.open(request, timeout=20) as response:
                        self.redirects.validate(response.geturl())
                        if response.headers.get_content_type() not in self.content_types:
                            raise PublicRequestError(f"{self.service} returned an unexpected content type; no data was inferred.")
                        body = response.read(8_000_001)
                        if len(body) > 8_000_000:
                            raise PublicRequestError(f"{self.service} response exceeded the 8 MB safety limit.")
                    retrieved = datetime.now(timezone.utc)
                    self._cache[url] = (time.monotonic(), body, retrieved)
                    self._cache.move_to_end(url)
                    while len(self._cache) > 64:
                        self._cache.popitem(last=False)
                    return body, dict(retrieved_at=retrieved, source_url=url, cached=False)
                except HTTPError as error:
                    code, retry_after = error.code, error.headers.get("Retry-After", "1")
                    error.close()
                    try:
                        delay = max(0, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(0, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            delay = 1
                    if not attempt and (code == 429 or 500 <= code <= 599) and delay <= 10:
                        time.sleep(delay)
                        continue
                    raise PublicRequestError(f"{self.service} returned HTTP {code}; check the request or try again later.") from None
                except (URLError, HTTPException, OSError):
                    if not attempt:
                        continue
                    raise PublicRequestError(f"Could not reach {self.service} after two attempts; try again later.") from None
