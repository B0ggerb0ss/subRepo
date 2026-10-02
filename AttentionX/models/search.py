"""Search request/response contracts.

``SearchHit.score`` is a fused *ranking* score (reciprocal-rank fusion); it is
not P(relevance) and must never be displayed as a percentage. Channel scores
keep their own semantics (bm25, cosine, detector score, decision prob).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReasonCode = Literal[
    "OCR_PHRASE", "OCR_LEXICAL", "OCR_SEMANTIC", "VISUAL_SIMILARITY", "OBJECT_DETECTION",
    "SCENE_DECISION", "SOURCE_CONTEXT", "CONTEXT_DECISION", "USER_ANNOTATION", "COLLECTION",
    "FILTER",
]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filter(_M):
    key: str
    value: str


class ParsedQuery(_M):
    raw: str
    free_text: str
    text_phrases: list[str]
    filters: list[Filter]
    approximate_notes: list[str] = []


class SearchRequest(_M):
    query: str = ""
    library_id: str = "local"
    limit: int = Field(default=40, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    channels: list[Literal["lexical", "ocr_semantic", "visual"]] = ["lexical", "ocr_semantic", "visual"]
    similar_to: str | None = None                      # asset id for reference-image search
    crop: tuple[float, float, float, float] | None = None  # normalized display box on similar_to
    similar_frame: str | None = None                   # keyframe id when similar_to is a video
    collapse_duplicates: bool = True


class MatchEvidence(_M):
    reason: ReasonCode
    detail: str
    region_ids: list[str] = []
    polygons: list[list[tuple[float, float]]] = []   # normalized display coords
    box: tuple[float, float, float, float] | None = None
    score: float | None = None
    score_kind: str | None = None      # bm25 | cosine | raw_detector | decision_prob | ...
    excerpt: str | None = None         # verbatim OCR text (raw), never generated
    frame_id: str | None = None        # video: keyframe the evidence comes from (geometry is on that frame)
    t_s: float | None = None           # video: keyframe time in seconds


class SearchHit(_M):
    asset_id: str
    metadata_revision: int
    score: float
    channel_ranks: dict[str, int]
    channel_scores: dict[str, float]
    reasons: list[MatchEvidence]
    duplicate_count: int = 0
    duplicate_ids: list[str] = []


class SearchResponse(_M):
    query: ParsedQuery | None
    hits: list[SearchHit]
    total_candidates: int
    channels_used: list[str]
    degraded: list[str]            # human-readable notices for unavailable channels
    index_revision: dict[str, int]
    elapsed_ms: float
