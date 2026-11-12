"""Discover and call the public Omnibus module endpoints."""

import json
import re
import time
from urllib.parse import unquote

from ..models import OmnibusError
from .constants import _ASSETS, _BASE, _CALL_PATTERN, _ORIGIN


class MetadataMethods:
    def _bootstrap(self):
        if self._bootstrapped:
            return
        self._get_bytes(_BASE)
        self._bootstrapped = True

    def _metadata(self):
        if (
            self._metadata_cache is not None
            and time.monotonic() - self._metadata_cached_at < 300
        ):
            return self._metadata_cache
        self._bootstrap()
        raw = self._get_bytes(_BASE + "moduleservices/moduleinfo?latest")
        try:
            manifest = json.loads(raw)["manifest"]
            module_version = manifest["versionToken"]
            versions = manifest["urlVersions"]
            if not isinstance(versions, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise OmnibusError(
                "NTU Omnibus returned an unexpected public app manifest."
            ) from None

        endpoints = {}
        for asset in _ASSETS:
            version = versions.get(asset)
            if not isinstance(version, str):
                continue
            script = self._get_bytes(_ORIGIN + asset + version).decode(
                "utf-8", "replace"
            )
            for call_type, name, path, api_version in _CALL_PATTERN.findall(script):
                candidate = {
                    "type": call_type,
                    "path": path,
                    "api_version": api_version,
                }
                previous = endpoints.get(name)
                if previous is None:
                    endpoints[name] = candidate

        required = {
            "DataActionGetRoutesList",
            "DataActionGetActiveBusServicesData",
            "DataActionGetPickupCheckPoints",
            "GetETAAndNextETA_FMS",
            "GetETAAndNextETA_LTA",
            "GetRoutesCodejson",
            "GetRoutesMinMax",
            "CheckPHSpecialDay",
            "GetTempMessages",
        }
        if not required.issubset(endpoints):
            raise OmnibusError(
                "NTU Omnibus changed its public app API; endpoint discovery could not complete."
            )
        self._metadata_cache = {
            "module_version": module_version,
            "endpoints": endpoints,
        }
        self._metadata_cached_at = time.monotonic()
        return self._metadata_cache

    def _csrf_token(self):
        for cookie in self._cookies:
            if cookie.name != "nr2Users":
                continue
            decoded = unquote(cookie.value)
            match = re.search(r"(?:^|[;%])crf=([^;%]+)", decoded)
            if match:
                return match.group(1)
        return None

    def _post(
        self,
        name,
        view_name,
        *,
        screen_variables=None,
        client_variables=None,
        inputs=None,
        aggregate=False,
    ):
        with self._lock:
            metadata = self._metadata()
            try:
                endpoint = metadata["endpoints"][name]
            except KeyError:
                raise OmnibusError(
                    f"NTU Omnibus does not expose the {name} endpoint."
                ) from None
            payload = {
                "versionInfo": {
                    "moduleVersion": metadata["module_version"],
                    "apiVersion": endpoint["api_version"],
                },
                "viewName": view_name,
            }
            if screen_variables is not None:
                payload["screenData"] = {"variables": screen_variables}
                payload["clientVariables"] = client_variables or {}
            if inputs is not None or endpoint["type"] == "callServerAction":
                payload["inputParameters"] = inputs or {}
            if aggregate:
                payload["inputParameters"] = {"StartIndex": 0, "MaxRecords": 1000}

            request_headers = {
                "Content-Type": "application/json",
                "Origin": _ORIGIN,
                "Referer": _BASE,
                "X-Requested-With": "XMLHttpRequest",
            }
            token = self._csrf_token()
            if token:
                request_headers["X-CSRFToken"] = token
            url = _BASE + endpoint["path"]
            for attempt in range(2):
                response = self._read(
                    url,
                    body=json.dumps(payload, separators=(",", ":")).encode(),
                    headers=request_headers,
                )
                if isinstance(response, tuple):
                    code, raw = response
                    if code == 403 and attempt == 0 and self._is_invalid_login(raw):
                        token = self._csrf_token()
                        if token:
                            request_headers["X-CSRFToken"] = token
                            continue
                    raise OmnibusError(f"NTU Omnibus returned HTTP {code} for {name}.")
                try:
                    envelope = json.loads(response)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise OmnibusError(
                        f"NTU Omnibus returned invalid JSON for {name}."
                    ) from None
                exception = envelope.get("exception")
                if exception:
                    message = (
                        exception.get("message")
                        if isinstance(exception, dict)
                        else None
                    )
                    if message == "Invalid Login" and attempt == 0:
                        token = self._csrf_token()
                        if token:
                            request_headers["X-CSRFToken"] = token
                            continue
                    raise OmnibusError(
                        f"NTU Omnibus could not complete {name}; the app rejected the public request."
                    )
                result = envelope.get("data")
                if not isinstance(result, dict):
                    raise OmnibusError(
                        f"NTU Omnibus returned an unexpected response for {name}."
                    )
                return result, url
        raise OmnibusError(f"NTU Omnibus could not complete {name}.")

    @staticmethod
    def _is_invalid_login(raw):
        try:
            return (
                json.loads(raw).get("exception", {}).get("message") == "Invalid Login"
            )
        except (ValueError, AttributeError, TypeError):
            return False
