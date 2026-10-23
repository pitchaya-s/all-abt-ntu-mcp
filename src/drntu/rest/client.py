"""Public JSON requests with bounded memory, pacing, retries, and no cookies."""

from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
import json
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import RepositoryError


API = "https://dr.ntu.edu.sg/server/api"
DATA = "https://researchdata.ntu.edu.sg"


class RepositoryClient:
    def __init__(self):
        self._lock = Lock()
        self._cache = OrderedDict()
        self._last_request = 0.0

    def get(self, path, parameters=None, *, dataset=False, refresh=False):
        url = (DATA if dataset else API) + path
        if parameters:
            url += "?" + urlencode(parameters, doseq=True)
        service = "DR-NTU (Data)" if dataset else "DR-NTU"
        with self._lock:
            cached = self._cache.get(url)
            if not refresh and cached is not None and time.monotonic() - cached[0] < 300:
                self._cache.move_to_end(url)
                return cached[1], dict(retrieved_at=cached[2], source_url=url, cached=True)
            request = Request(url, headers={"User-Agent": "all-abt-ntu-mcp/0.1 (NTU repository lookup)", "Accept": "application/json"})
            for attempt in range(2):
                time.sleep(max(0, 0.5 - (time.monotonic() - self._last_request)))
                self._last_request = time.monotonic()
                try:
                    with urlopen(request, timeout=20) as response:
                        if response.headers.get_content_type() not in ("application/json", "application/hal+json"):
                            message = ("DR-NTU (Data) returned a non-JSON page, possibly a CAPTCHA. Open the dataset site manually; automated retrieval cannot continue."
                                       if dataset else "DR-NTU returned a non-JSON response; try again later.")
                            raise RepositoryError(message)
                        raw = response.read(8_000_001)
                        if len(raw) > 8_000_000:
                            raise RepositoryError(f"{service} response exceeded the 8 MB safety limit; reduce the page size if available.")
                        data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise RepositoryError(f"{service} returned an unexpected response format.")
                    retrieved = datetime.now(timezone.utc)
                    self._cache[url] = (time.monotonic(), data, retrieved)
                    self._cache.move_to_end(url)
                    while len(self._cache) > 64:
                        self._cache.popitem(last=False)
                    return data, dict(retrieved_at=retrieved, source_url=url, cached=False)
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
                    if code in (401, 403):
                        raise RepositoryError(f"{service} denied public access (HTTP {code}); access restrictions or a CAPTCHA may apply. No login or bypass is attempted.") from None
                    if code == 404:
                        raise RepositoryError(f"{service} could not find this record, file bundle, or dataset version (HTTP 404).") from None
                    raise RepositoryError(f"{service} request failed with HTTP {code}; check the query or try again later.") from None
                except (URLError, HTTPException, OSError):
                    if not attempt:
                        continue
                    raise RepositoryError(f"Could not reach {service} after two attempts; try again later.") from None
                except (ValueError, UnicodeError):
                    raise RepositoryError(f"{service} returned invalid JSON; no repository data was inferred.") from None
