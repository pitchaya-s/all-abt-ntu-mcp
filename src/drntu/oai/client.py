"""Public XML requests with bounded caching and protocol validation."""

from urllib.parse import urlencode
from contextlib import contextmanager

from public_http_client import PublicHTTPClient, PublicRequestError

from ..models import RepositoryError
from .parser import envelope

BASE = "https://dr.ntu.edu.sg/server/oai/request"


class OAIClient(PublicHTTPClient):
    def __init__(self):
        super().__init__(
            "DR-NTU OAI-PMH", {"dr.ntu.edu.sg"}, {"application/xml", "text/xml"}
        )

    def request(self, verb, parameters=None, refresh=False):
        url = BASE + "?" + urlencode({"verb": verb, **(parameters or {})})
        try:
            body, snapshot = self.get(url, refresh=refresh)
            try:
                container, response_date = envelope(body, verb)
            except RepositoryError:
                self.invalidate(url, retrieved_at=snapshot.get("retrieved_at"))
                raise
            return container, response_date, snapshot
        except PublicRequestError as error:
            raise RepositoryError(str(error)) from None

    @contextmanager
    def validated(self, *args, **kwargs):
        data, response_date, snapshot = self.request(*args, **kwargs)
        try:
            yield data, response_date, snapshot
        except Exception:
            url = snapshot.get("source_url")
            if url:
                self.invalidate(url, retrieved_at=snapshot.get("retrieved_at"))
            raise
