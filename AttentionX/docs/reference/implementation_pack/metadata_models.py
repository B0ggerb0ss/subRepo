"""PROPOSED MediaMetadata v1 contract; not part of the uploaded AttentionX repo.

Requires Pydantic >=2,<3. All times are seconds on the original asset clock.
Probabilities are model estimates, not guarantees. This file does no inference.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import PurePosixPath
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

T = TypeVar("T")
Probability = float
Status = Literal["complete", "skipped", "missing", "error", "not_applicable", "partial"]
Modality = Literal["bytes", "video", "audio", "image", "text", "timeline", "mixed"]
CostClass = Literal["cached", "cpu_probe", "cpu_pixels", "cpu_decode", "cpu_ocr", "cpu_asr", "local_vision", "cloud_decision", "control"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Provenance(StrictModel):
    source_modality: Modality
    source_refs: list[str]
    extractor: str
    extractor_version: str
    decision_model: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_kind: Literal["deterministic_parse", "raw_recognizer", "heuristic", "model_probability", "vendor_statistic", "derived_margin", "unavailable"]
    calibration_version: str | None = None
    cost_class: CostClass
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    failure_modes: list[str] = Field(min_length=1)
    status: Status


class Observation(StrictModel, Generic[T]):
    value: T
    provenance: Provenance


class TimeRange(StrictModel):
    t0: float = Field(ge=0)
    t1: float = Field(ge=0)

    @model_validator(mode="after")
    def positive_range(self):
        if self.t1 <= self.t0:
            raise ValueError("t1 must exceed t0")
        return self


class ClipBinding(StrictModel):
    project_id: str
    clip_id: str
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    timeline_start: float = Field(ge=0)
    playback_rate: float = Field(default=1, gt=0)
    provenance: Provenance

    @model_validator(mode="after")
    def positive_range(self):
        if self.source_out <= self.source_in:
            raise ValueError("source_out must exceed source_in")
        return self


class FrameRef(StrictModel):
    frame_id: str
    scene_id: str
    t: float = Field(ge=0)
    path: str  # managed relative reference; never a cloud-fetchable URL
    why_sampled: list[str]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    provenance: Provenance

    @model_validator(mode="after")
    def managed_relative_path(self):
        p = PurePosixPath(self.path)
        if not self.path or p.is_absolute() or ".." in p.parts or "\\" in self.path or ":" in self.path:
            raise ValueError("frame path must be a managed relative reference")
        return self


class OCRRegion(StrictModel):
    region_id: str
    text: str
    polygon: list[tuple[float, float]] = Field(min_length=4, max_length=4)
    reading_order: int = Field(ge=0)
    language: str | None = None
    granularity: Literal["line", "word"] = "line"
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: Provenance

    @model_validator(mode="after")
    def normalized_coordinates(self):
        if any(not 0 <= v <= 1 for point in self.polygon for v in point):
            raise ValueError("polygon must use normalized, orientation-corrected coordinates")
        return self


class TextLayer(StrictModel):
    layer_id: str
    t_start: float | None = Field(default=None, ge=0)
    t_end: float | None = Field(default=None, ge=0)
    text: str
    source: Literal["ocr", "asr", "srt", "vtt", "project_title", "user_text"]
    conf: float | None = Field(default=None, ge=0, le=1)
    source_ref: str
    provenance: Provenance

    @model_validator(mode="after")
    def paired_timestamps(self):
        if (self.t_start is None) != (self.t_end is None):
            raise ValueError("both timestamps must be present or both absent")
        if self.t_start is not None and self.t_end <= self.t_start:
            raise ValueError("text range must have positive duration")
        return self


class Decision(StrictModel):
    type: Literal["noul", "choice", "score"]
    value: str | float
    probs: dict[str, float]
    model: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_kind: Literal["vendor_statistic", "derived_margin"]
    raw_model_score: float | None = None
    legend: dict[str, str] | None = None
    latency_ms: float = Field(ge=0)  # whole request; do not sum across questions
    request_id: str
    question_catalog_version: str
    evidence_refs: list[str]
    status: Status
    provenance: Provenance

    @model_validator(mode="after")
    def valid_distribution(self):
        if not self.probs or any(not math.isfinite(p) or not 0 <= p <= 1 for p in self.probs.values()):
            raise ValueError("invalid probability distribution")
        if abs(sum(self.probs.values()) - 1) > 1e-5:
            raise ValueError("probabilities must sum to one")
        if self.type == "noul":
            if set(self.probs) != {"yes", "no"} or not isinstance(self.value, (float, int)):
                raise ValueError("Noul stores P(yes) plus a yes/no distribution")
            if abs(float(self.value) - self.probs["yes"]) > 1e-5:
                raise ValueError("Noul value must equal P(yes)")
            if self.confidence_kind != "derived_margin" or (self.confidence is not None and abs(self.confidence - abs(2*float(self.value)-1)) > 1e-5):
                raise ValueError("Noul confidence is an explicitly derived margin, not vendor confidence")
        if self.type == "choice":
            if self.value not in self.probs or self.probs[self.value] < max(self.probs.values()) - 1e-5:
                raise ValueError("choice value must be a maximum-probability declared option")
        if self.type == "score":
            if not 2 <= len(self.probs) <= 10 or set(self.probs) != {str(i) for i in range(1, len(self.probs)+1)}:
                raise ValueError("score levels must be contiguous product levels 1 to N")
            expected = sum(float(k) * p for k, p in self.probs.items())
            if not isinstance(self.value, (float, int)) or abs(float(self.value) - expected) > 1e-4:
                raise ValueError("score value must equal expected product level (1 to N)")
            if self.raw_model_score is not None and abs(self.raw_model_score - (float(self.value)-1)) > 1e-4:
                raise ValueError("native score must equal product score minus one")
        return self


class Scene(TimeRange):
    scene_id: str
    keyframe: FrameRef | None
    additional_keyframes: list[FrameRef] = Field(default_factory=list)
    metrics: dict[str, Observation[JsonValue]]
    ocr: Observation[list[OCRRegion]]
    decisions: dict[str, Decision]
    provenance: Provenance

    @model_validator(mode="after")
    def frames_within_scene(self):
        frames = ([self.keyframe] if self.keyframe else []) + self.additional_keyframes
        if any(not self.t0 <= f.t < self.t1 for f in frames):
            raise ValueError("keyframes must lie inside [t0,t1)")
        if any(f.scene_id != self.scene_id for f in frames):
            raise ValueError("frame scene identity must match its owning scene")
        return self


class AudioMetadata(StrictModel):
    loudness: Observation[dict[str, float | None]]  # LUFS/dBTP; preserve original channel layout
    silence_ranges: Observation[list[TimeRange]]
    speech_prior: Observation[float | None]
    transcript_ref: str | None
    transcript: Observation[list[TextLayer]]

    @model_validator(mode="after")
    def bounded_prior(self):
        if self.speech_prior.value is not None and not 0 <= self.speech_prior.value <= 1:
            raise ValueError("speech routing prior must be between zero and one")
        return self


class SearchTag(StrictModel):
    tag: str
    probability: float = Field(ge=0, le=1)
    decision_ref: str
    provenance: Provenance


class StageError(StrictModel):
    stage: str
    code: str
    message: str  # sanitized; no keys, host paths, or raw uploaded text
    retryable: bool
    source_ref: str


class MediaMetadata(StrictModel):
    schema_version: Literal["MediaMetadata/1.0"] = "MediaMetadata/1.0"
    asset_id: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    analyzer_version: str
    analyzed_at: datetime
    asset_kind: Literal["video", "audio", "image", "text"]
    illustrative: bool = False
    technical: Observation[dict[str, JsonValue]]
    timeline: list[ClipBinding]
    video_scenes: list[Scene]
    audio: AudioMetadata | None
    image: Observation[dict[str, JsonValue]] | None
    text_layers: list[TextLayer]
    decisions: dict[str, Decision]
    search_tags: list[SearchTag]
    coverage: Observation[dict[str, JsonValue]]
    stage_status: dict[str, Status]
    errors: list[StageError]
    partial: bool

    @model_validator(mode="after")
    def valid_asset(self):
        if self.analyzed_at.tzinfo is None:
            raise ValueError("analyzed_at must contain a timezone")
        duration = self.technical.value.get("duration_s")
        if isinstance(duration, (float, int)):
            if isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
                raise ValueError("known original duration must be finite and positive")
            if any(s.t1 > duration + 1e-3 for s in self.video_scenes):
                raise ValueError("scene exceeds original asset duration")
            if any(c.source_out > duration + 1e-3 for c in self.timeline):
                raise ValueError("trim exceeds original asset duration")
            if any(t.t_end is not None and t.t_end > duration + 1e-3 for t in self.text_layers):
                raise ValueError("text exceeds original asset duration")
            if self.audio and (any(r.t1 > duration + 1e-3 for r in self.audio.silence_ranges.value) or any(t.t_end is not None and t.t_end > duration + 1e-3 for t in self.audio.transcript.value)):
                raise ValueError("audio range exceeds original asset duration")
        ordered = sorted(self.video_scenes, key=lambda s: s.t0)
        if [s.scene_id for s in ordered] != [s.scene_id for s in self.video_scenes] or len({s.scene_id for s in ordered}) != len(ordered):
            raise ValueError("source scenes must be uniquely identified and ordered")
        if any(a.t1 > b.t0 + 1e-5 for a, b in zip(ordered, ordered[1:])):
            raise ValueError("source scenes must not overlap")
        if (self.errors or any(status in {"missing", "error", "partial"} for status in self.stage_status.values())) and not self.partial:
            raise ValueError("a failed scheduled stage requires partial=true")
        return self
