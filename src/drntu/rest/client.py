"""Public DSpace and Dataverse reads using the shared bounded HTTP client."""

import json
from contextlib import contextmanager
from urllib.parse import urlencode

from public_http_client import PublicHTTPClient, PublicRequestError

from ..models import RepositoryError

API = "https://dr.ntu.edu.sg/server/api"
DATA = "https://researchdata.ntu.edu.sg"


class RepositoryClient:
    def __init__(self, *, transport=None):
        self.http = PublicHTTPClient(
            "DR-NTU",
            ["dr.ntu.edu.sg", "researchdata.ntu.edu.sg"],
            {"application/json", "application/hal+json"},
            transport=transport,
        )

    def get(self, path, parameters=None, *, dataset=False, refresh=False):
        url = (DATA if dataset else API) + path
        if parameters:
            url += "?" + urlencode(parameters, doseq=True)
        service = "DR-NTU (Data)" if dataset else "DR-NTU"
        try:
            body, snapshot = self.http.get(url, refresh)
        except PublicRequestError as error:
            if error.status in (401, 403):
                raise RepositoryError(
                    f"{service} denied public access (HTTP {error.status}); access restrictions or a CAPTCHA may apply. No login or bypass is attempted."
                ) from None
            if error.status == 404:
                raise RepositoryError(
                    f"{service} could not find this record, file bundle, or dataset version (HTTP 404)."
                ) from None
            if (
                dataset
                and error.content_type
                and error.content_type
                not in {"application/json", "application/hal+json"}
            ):
                raise RepositoryError(
                    "DR-NTU (Data) returned a non-JSON page, possibly a CAPTCHA. Open the dataset site manually; automated retrieval cannot continue."
                ) from None
            if error.response_too_large:
                raise RepositoryError(
                    f"{service} response exceeded the 8 MB safety limit; reduce the page size if available."
                ) from None
            raise RepositoryError(str(error)) from None
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            self.http.invalidate(url, retrieved_at=snapshot.get("retrieved_at"))
            raise RepositoryError(
                f"{service} returned invalid JSON; no repository data was inferred."
            ) from None
        if not isinstance(data, dict):
            self.http.invalidate(url, retrieved_at=snapshot.get("retrieved_at"))
            raise RepositoryError(f"{service} returned an unexpected response format.")
        return data, snapshot

    @contextmanager
    def validated(self, *args, **kwargs):
        data, snapshot = self.get(*args, **kwargs)
        try:
            yield data, snapshot
        except Exception:
            url = snapshot.get("source_url")
            if url:
                self.http.invalidate(url, retrieved_at=snapshot.get("retrieved_at"))
            raise
