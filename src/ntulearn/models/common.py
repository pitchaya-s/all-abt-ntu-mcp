from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LearnError(RuntimeError):
    """A sanitized NTULearn authentication, network, or response error."""


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AuthStatus(Model):
    credentials_configured: bool | None
    credential_storage: Literal["os_keyring"] = "os_keyring"
    credential_error: str | None = None
    session_verified: bool
    last_verified_at: datetime | None
    session_storage: Literal["in_memory_only"] = "in_memory_only"
    cache_ttl_seconds: int


class Freshness(Model):
    retrieved_at: datetime
    from_cache: bool
    cache_age_seconds: int


class Issue(Model):
    service: str
    course_id: str | None = None
    content_id: str | None = None
    message: str


class ScanResult(Freshness):
    complete: bool
    requests_used: int
    issues: list[Issue]
