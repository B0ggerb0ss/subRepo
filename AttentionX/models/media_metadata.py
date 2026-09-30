"""MediaMetadata/1.1 — the image/search extension of the audit's 1.0 contract.

1.1 is a new schema version, not a loosened 1.0: the strict 1.0 model
(``models/media_metadata_v1.py``) still rejects 1.1 fields. Use
``load_metadata`` to read either version and ``project_to_v1`` for the
documented 1.0 export projection.

Score semantics are never interchangeable: OCR ``recognizer_score`` is a raw
recognizer score, object ``detector_score`` a raw detector score, decision
``probs`` a (possibly uncalibrated) model distribution, and embeddings are
representations with no confidence at all.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "MediaMetadata/1.1"

StageStatus = Literal[
    "complete", "cached", "skipped", "disabled", "missing", "partial", "error",
    "not_applicable", "cancelled",
]
FAILED_STATUSES = {"missing", "partial", "error", "cancelled"}
ConfidenceKind = Literal[
    "deterministic_parse", "raw_recognizer", "raw_detector", "heuristic",
    "model_probability", "zero_shot_softmax_uncalibrated", "vendor_statistic",
    "derived_margin", "cosine_similarity", "unavailable",
]
CostClass = Literal[
    "cached", "cpu_probe", "cpu_pixels", "cpu_ocr", "cpu_embed", "cpu_detect",
    "cpu_decide", "cpu_asr", "local_vision", "cloud_decision", "control",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Provenance(StrictModel):
    producer: str                      # module that produced the field
    source_modality: Literal["bytes", "image", "text", "video", "mixed"]
    source_refs: list[str]
    extractor: str
    extractor_version: str
    model_digest: str | None = None
    confidence_kind: ConfidenceKind
    calibration_version: str | None = None
    cost_class: CostClass
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    failure_modes: list[str] = Field(min_length=1)
    status: StageStatus


def _normalized(points: list[tuple[float, float]] | list[float]) -> bool:
    flat = [v for p in points for v in (p if isinstance(p, (tuple, list)) else [p])]
    return all(math.isfinite(v) and -1e-6 <= v <= 1 + 1e-6 for v in flat)


class ImageObservation(StrictModel):
    format: str
    mime: str
    stored_width: int = Field(gt=0)     # pixel grid as encoded
    stored_height: int = Field(gt=0)
    exif_orientation: int = Field(ge=1, le=8)
    display_width: int = Field(gt=0)    # after applying EXIF orientation
    display_height: int = Field(gt=0)
    color_mode: str
    icc_profile: bool
    animated: bool
    frame_count: int = Field(ge=1)
    frames_analyzed: list[int]          # representative frame indices
    camera_exif: bool                   # Make/Model present (metadata, not proof)
    metrics: dict[str, float]
    palette: list[dict[str, Any]]
    hashes: dict[str, str]              # sha256 (bytes), dhash64/phash64 (pixels)
    provenance: Provenance


class OCRTile(StrictModel):
    tile_id: str
    box_px: tuple[int, int, int, int]   # display-space x0,y0,x1,y1 (pre-scaling)
    scale: float = Field(gt=0)
    status: Literal["complete", "error", "skipped"]


class OCRRegion(StrictModel):
    region_id: str
    raw_text: str                       # verbatim recognizer output
    norm_text: str                      # search view (NFKC + casefold + ws)
    polygon: list[tuple[float, float]] = Field(min_length=4, max_length=4)
    reading_order: int = Field(ge=0)
    line_group: int = Field(ge=0)
    language: str | None = None
    granularity: Literal["line", "word"] = "line"
    recognizer_score: float | None = Field(default=None, ge=0, le=1)
    tile_ids: list[str]

    @model_validator(mode="after")
    def _geometry(self):
        if not _normalized(self.polygon):
            raise ValueError("OCR polygon must be normalized display coordinates")
        return self


class OCRResult(StrictModel):
    engine: str
    engine_version: str
    model_ids: list[str]
    languages: list[str]
    script_scope: str
    tiles: list[OCRTile]
    regions: list[OCRRegion]
    coverage_fraction: float = Field(ge=0, le=1)
    complete: bool
    incomplete_reason: str | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _order(self):
        orders = [r.reading_order for r in self.regions]
        if sorted(orders) != list(range(len(orders))):
            raise ValueError("reading_order must be a permutation of 0..n-1")
        if len({r.region_id for r in self.regions}) != len(self.regions):
            raise ValueError("duplicate OCR region ids")
        if not self.complete and not self.incomplete_reason:
            raise ValueError("incomplete OCR coverage needs a reason")
        return self


class ObjectObservation(StrictModel):
    obs_id: str
    label: str
    class_id: int | None
    box: tuple[float, float, float, float]   # normalized display x0,y0,x1,y1
    detector_score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _box(self):
        x0, y0, x1, y1 = self.box
        if not _normalized(list(self.box)) or x1 <= x0 or y1 <= y0:
            raise ValueError("object box must be a normalized positive-area box")
        return self


class ObjectResult(StrictModel):
    model: str
    ontology_version: str
    score_threshold: float
    observations: list[ObjectObservation]
    provenance: Provenance


class Decision(StrictModel):
    question_id: str
    dtype: Literal["noul", "choice", "multilabel"]
    value: str | float | None                  # None when abstained/unavailable
    probs: dict[str, float]
    probability_kind: ConfidenceKind
    status: Literal["complete", "abstained", "unavailable", "not_applicable"]
    abstain_reason: str | None = None
    evidence_refs: list[str]
    missing_evidence: list[str] = Field(default_factory=list)
    gates: dict[str, Any] = Field(default_factory=dict)
    model: str
    catalog_version: str
    calibration_version: str | None = None

    @model_validator(mode="after")
    def _distribution(self):
        if any(not math.isfinite(p) or not 0 <= p <= 1 for p in self.probs.values()):
            raise ValueError("probabilities must be finite and within [0, 1]")
        needs_dist = self.status == "complete" or (self.status == "abstained" and self.probs)
        if needs_dist and self.dtype != "multilabel":
            if not self.probs or abs(sum(self.probs.values()) - 1) > 1e-4:
                raise ValueError("probabilities must sum to one")
        if self.status != "complete":
            if self.value is not None:
                raise ValueError("non-complete decisions carry no value")
            if self.status == "abstained" and not self.abstain_reason:
                raise ValueError("abstention needs a reason")
            return self
        if self.dtype == "noul":
            if set(self.probs) != {"yes", "no"} or not isinstance(self.value, float):
                raise ValueError("noul stores P(yes) with a yes/no distribution")
            if abs(self.value - self.probs["yes"]) > 1e-6:
                raise ValueError("noul value must equal P(yes)")
        if self.dtype == "choice":
            if self.value not in self.probs:
                raise ValueError("choice value must be a declared option")
            if self.probs[self.value] < max(self.probs.values()) - 1e-6:
                raise ValueError("choice value must be a maximum-probability option")
        return self


class EmbeddingRecord(StrictModel):
    embedding_id: str
    namespace: str
    space: str
    model: str
    model_digest: str
    dim: int = Field(gt=0)
    normalization: Literal["l2"]
    preprocess_version: str
    view_kind: Literal["global_letterbox", "region", "ocr_chunk", "ocr_body"]
    view_id: str
    region: tuple[float, float, float, float] | None = None
    source_refs: list[str] = Field(default_factory=list)
    storage_ref: str


class StageError(StrictModel):
    stage: str
    code: str
    message: str        # sanitized: no host paths, keys or raw OCR text
    retryable: bool


class MediaMetadata(StrictModel):
    schema_version: Literal["MediaMetadata/1.1"] = SCHEMA_VERSION
    asset_id: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    asset_kind: Literal["image", "video"]
    analyzer_version: str
    analyzed_at: datetime
    illustrative: bool = False
    image: ImageObservation | None = None
    ocr: OCRResult | None = None
    objects: ObjectResult | None = None
    decisions: dict[str, Decision] = Field(default_factory=dict)
    embeddings: list[EmbeddingRecord] = Field(default_factory=list)
    stage_status: dict[str, StageStatus]
    stage_provenance: dict[str, Provenance] = Field(default_factory=dict)
    errors: list[StageError] = Field(default_factory=list)
    partial: bool

    @model_validator(mode="after")
    def _consistency(self):
        if self.analyzed_at.tzinfo is None:
            raise ValueError("analyzed_at must be timezone-aware")
        failed = self.errors or any(s in FAILED_STATUSES for s in self.stage_status.values())
        if failed and not self.partial:
            raise ValueError("a failed/missing/partial stage requires partial=true")
        if not failed and self.partial:
            raise ValueError("partial=true requires a failed/missing/partial stage")
        for qid, d in self.decisions.items():
            if d.question_id != qid:
                raise ValueError(f"decision key {qid} != question_id {d.question_id}")
        if self.ocr and self.stage_status.get("ocr") not in {"complete", "cached", "partial"}:
            raise ValueError("OCR payload present but ocr stage not complete/partial")
        return self


# ---------------------------------------------------------------------------
# Version-aware loading and the documented 1.0 projection
# ---------------------------------------------------------------------------

def load_metadata(payload: dict | str) -> MediaMetadata:
    """Load 1.1 directly, or migrate a 1.0 document (see docs/metadata.md)."""
    import json

    data = json.loads(payload) if isinstance(payload, str) else payload
    version = data.get("schema_version")
    if version == SCHEMA_VERSION:
        return MediaMetadata.model_validate(data)
    if version == "MediaMetadata/1.0":
        return _migrate_v10(data)
    raise ValueError(f"unsupported metadata schema_version {version!r}")


def _migrate_v10(data: dict) -> MediaMetadata:
    from models.media_metadata_v1 import MediaMetadata as V10

    v1 = V10.model_validate(data)  # strict 1.0 validation first
    status: dict[str, str] = {}
    for stage, s in v1.stage_status.items():
        status[stage] = s
    # 1.0 image OCR carries no region geometry: it cannot become 1.1 regions.
    status["ocr"] = "missing"
    errors = [StageError(stage=e.stage, code=e.code, message=e.message, retryable=e.retryable)
              for e in v1.errors]
    errors.append(StageError(stage="ocr", code="migrated_without_geometry",
                             message="1.0 text layers have no polygons; re-run OCR", retryable=True))
    return MediaMetadata(
        asset_id=v1.asset_id,
        content_hash=v1.content_hash,
        asset_kind="image" if v1.asset_kind == "image" else "video",
        analyzer_version=f"migrated-from-1.0:{v1.analyzer_version}",
        analyzed_at=v1.analyzed_at,
        illustrative=v1.illustrative,
        stage_status=status,
        errors=errors,
        partial=True,
    )


def project_to_v1(meta: MediaMetadata) -> dict:
    """Documented lossy projection of a 1.1 image document to MediaMetadata/1.0.

    Kept: identity, technical/image facts, OCR as untimed text layers, choice
    and noul decisions (noul confidence = derived margin), stage status.
    Dropped: polygons, tiles, objects, embeddings, multilabel decisions.
    The result validates against the strict vendored 1.0 model.
    """
    def prov(stage: str, kind: str = "deterministic_parse") -> dict:
        p = meta.stage_provenance.get(stage)
        return {
            "source_modality": "image",
            "source_refs": [f"asset:{meta.asset_id}"],
            "extractor": p.extractor if p else stage,
            "extractor_version": p.extractor_version if p else "unknown",
            "decision_model": None,
            "confidence": None,
            "confidence_kind": kind,
            "calibration_version": None,
            "cost_class": "cpu_probe",
            "cache_key": p.cache_key if p else "0" * 64,
            "failure_modes": p.failure_modes if p else ["unknown"],
            "status": _v1_status(meta.stage_status.get(stage, "missing")),
        }

    img = meta.image
    technical = {
        "format": img.format if img else None,
        "width": img.display_width if img else None,
        "height": img.display_height if img else None,
    }
    text_layers = []
    if meta.ocr:
        for r in sorted(meta.ocr.regions, key=lambda r: r.reading_order):
            text_layers.append({
                "layer_id": r.region_id, "t_start": None, "t_end": None,
                "text": r.raw_text, "source": "ocr", "conf": r.recognizer_score,
                "source_ref": f"asset:{meta.asset_id}#ocr/{r.region_id}",
                "provenance": prov("ocr", "raw_recognizer"),
            })
    decisions = {}
    for qid, d in meta.decisions.items():
        if d.status != "complete" or d.dtype == "multilabel":
            continue
        entry = {
            "type": d.dtype, "value": d.value, "probs": d.probs, "model": d.model,
            "confidence_kind": "derived_margin", "raw_model_score": None, "legend": None,
            "latency_ms": 0.0, "request_id": f"local:{meta.asset_id}:{qid}",
            "question_catalog_version": d.catalog_version,
            "evidence_refs": d.evidence_refs, "status": "complete",
            "provenance": prov("context", "model_probability"),
        }
        if d.dtype == "noul":
            entry["confidence"] = abs(2 * float(d.value) - 1)
        else:
            entry["confidence"] = None
        decisions[qid] = entry
    stage_status = {k: _v1_status(v) for k, v in meta.stage_status.items()}
    partial = any(v in {"missing", "error", "partial"} for v in stage_status.values()) or bool(meta.errors)
    return {
        "schema_version": "MediaMetadata/1.0",
        "asset_id": meta.asset_id,
        "content_hash": meta.content_hash,
        "analyzer_version": meta.analyzer_version,
        "analyzed_at": meta.analyzed_at.isoformat(),
        "asset_kind": meta.asset_kind,
        "illustrative": meta.illustrative,
        "technical": {"value": technical, "provenance": prov("pixels")},
        "timeline": [],
        "video_scenes": [],
        "audio": None,
        "image": {"value": img.model_dump(mode="json", exclude={"provenance"}) if img else {},
                  "provenance": prov("pixels")} if img else None,
        "text_layers": text_layers,
        "decisions": decisions,
        "search_tags": [],
        "coverage": {"value": {"ocr_fraction": meta.ocr.coverage_fraction if meta.ocr else 0.0},
                     "provenance": prov("ocr", "deterministic_parse")},
        "stage_status": stage_status,
        "errors": [e.model_dump() | {"source_ref": f"asset:{meta.asset_id}"} for e in meta.errors],
        "partial": partial,
    }


def _v1_status(s: str) -> str:
    return {
        "cached": "complete", "disabled": "skipped", "cancelled": "error",
    }.get(s, s)
