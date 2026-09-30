"""Collection / group / correction contracts."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Membership(_M):
    asset_id: str
    method: str                 # decision | user_override | cluster | incremental | near_duplicate | representative | user
    affinity: float | None
    affinity_kind: str          # zero_shot_softmax_uncalibrated | cosine_to_medoid | cosine | rule | user
    state: Literal["suggested", "confirmed", "excluded"]
    evidence: dict


class Collection(_M):
    id: str
    ctype: Literal["smart", "similarity", "duplicate", "user"]
    key: str | None
    parent_id: str | None
    label: str                  # user label if set, else suggested
    suggested_label: str
    user_label: str | None
    pinned: bool
    hidden: bool
    representative_asset: str | None
    revision: int
    member_count: int
    members: list[Membership] = []


Op = Literal["rename", "pin", "hide", "confirm", "exclude", "move", "merge", "split", "create",
             "set_decision", "clear_decision"]


class CorrectionCommand(_M):
    op: Op
    collection_id: str | None = None
    collection_ids: list[str] = []
    into: str | None = None
    to: str | None = None
    asset_ids: list[str] = []
    label: str | None = None
    value: str | bool | None = None
    asset_id: str | None = None
    question_id: str | None = None
    reason: str = ""


class CorrectionResult(_M):
    ok: bool
    correction_ids: list[str]
    collection_id: str | None = None
    new_revision: int | None = None
    message: str = ""
    affected_assets: list[str] = Field(default_factory=list)
