from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RepositoryError(RuntimeError):
    pass


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Snapshot(Model):
    retrieved_at: datetime
    source_url: str
    cached: bool


class MetadataValue(Model):
    value: str
    language: str | None
