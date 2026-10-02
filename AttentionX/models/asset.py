"""Asset, import and job records (typed views over repository rows)."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

JobStatus = Literal["queued", "running", "complete", "partial", "error", "cancelled", "superseded"]


class _Rec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Asset(_Rec):
    id: str
    library_id: str
    content_hash: str
    kind: Literal["image", "video"]
    mime: str
    byte_size: int
    width: int | None
    height: int | None
    original_ref: str          # managed relative ref, never a host path
    thumb_ref: str | None
    created_at: float
    deleted_at: float | None
    metadata_revision: int
    analysis_generation: int
    duration_s: float | None = None    # videos only

    @classmethod
    def from_row(cls, row) -> "Asset":
        keys = row.keys()
        return cls(**{k: row[k] for k in cls.model_fields if k in keys})


class ImportInstance(_Rec):
    id: str
    asset_id: str
    batch_id: str
    library_id: str
    original_filename: str
    path_hint: str | None
    source_note: str | None
    imported_at: float

    @classmethod
    def from_row(cls, row) -> "ImportInstance":
        return cls(**{k: row[k] for k in cls.model_fields})


class Rejection(_Rec):
    filename: str
    code: str
    message: str


class ImportBatch(_Rec):
    id: str
    library_id: str
    source_kind: Literal["files", "folder"]
    total: int
    admitted: int          # new assets
    reused: int            # identical bytes already in the library
    rejected: int
    status: Literal["complete", "partial", "failed"]
    asset_ids: list[str]
    job_ids: list[str]
    rejections: list[Rejection]


class JobStage(_Rec):
    stage: str
    seq: int
    status: str
    cache_key: str | None
    detail: str | None
    started_at: float | None
    finished_at: float | None


class Job(_Rec):
    id: str
    library_id: str
    asset_id: str | None
    kind: str
    status: JobStatus
    generation: int
    params: dict
    attempts: int
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    created_at: float
    updated_at: float
    stages: list[JobStage] = []

    @classmethod
    def from_row(cls, row, stages=()) -> "Job":
        d = {k: row[k] for k in cls.model_fields if k not in {"stages", "params", "cancel_requested"}}
        d["params"] = json.loads(row["params"] or "{}")
        d["cancel_requested"] = bool(row["cancel_requested"])
        d["stages"] = [JobStage(**{k: s[k] for k in JobStage.model_fields}) for s in stages]
        return cls(**d)
