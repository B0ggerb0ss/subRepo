"""Staged, incremental image analysis.

Each stage declares its version, upstream stages and (via ``prepare``) the
exact parameters and model digest that determine its output. Its cache key is
derived from those plus the upstream stage keys, so:

- unchanged pixels + unchanged provider => cache hit, no re-inference;
- a user tag/title edit touches no stage input => nothing re-runs;
- changing OCR languages changes the OCR key and its dependents only.

Statuses are explicit and distinct: complete, cached, disabled (flag off),
missing (provider/model unavailable), not_applicable, partial, error,
cancelled. A missing provider never produces an empty "successful" result.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from models.asset import Asset, Job
from models.media_metadata import (
    SCHEMA_VERSION,
    VIDEO_SCHEMA_VERSION,
    ImageObservation,
    Keyframe,
    MediaMetadata,
    OCRRegion,
    OCRResult,
    OCRTile,
    Provenance,
    SpeechResult,
    SpeechSegment,
    StageError,
    VideoObservation,
)
from services.analyze import pixels as px
from services.analyze.cache import StageCache, stage_key
from services.analyze.ocr import (
    NORMALIZATION_VERSION,
    OCR_VERSION,
    normalize_for_search,
    reading_order,
    run_ocr,
)
from services.analyze.providers import Providers, ProviderUnavailable
from services.library.config import LibraryConfig
from services.library.jobs import JobCancelled, JobQueue
from services.library.repository import Repository

log = logging.getLogger(__name__)
ANALYZER_VERSION = "attentionx-image/1.0"


@dataclass
class StageResult:
    status: str
    payload: dict = field(default_factory=dict)
    detail: str | None = None
    error: StageError | None = None


@dataclass
class Prepared:
    params: dict
    model_digest: str | None
    provider: object | None = None


@dataclass
class Stage:
    name: str
    version: str
    upstream: tuple[str, ...]
    prepare: Callable[["Ctx"], Prepared]
    run: Callable[["Ctx", Prepared], StageResult]
    cost_class: str
    # Upstream stages whose *success* is required (others are optional inputs).
    requires: tuple[str, ...] = ()


@dataclass
class Ctx:
    cfg: LibraryConfig
    repo: Repository
    providers: Providers
    asset: Asset
    job: Job | None
    queue: JobQueue | None
    results: dict[str, StageResult] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)
    _decoded: px.DecodedImage | None = None

    def original_path(self) -> Path:
        return self.cfg.library_root / self.asset.original_ref

    def decoded(self) -> px.DecodedImage:
        if self._decoded is None:
            self._decoded = px.decode_image(self.original_path(), self.cfg.limits.max_image_pixels)
        return self._decoded

    def check_cancel(self) -> None:
        if self.job is not None and self.queue is not None:
            self.queue.heartbeat(self.job.id)


# ---------------------------------------------------------------------------
# Stage: pixels
# ---------------------------------------------------------------------------

def _prep_pixels(ctx: Ctx) -> Prepared:
    return Prepared(params={"metric_long_edge": px.METRIC_LONG_EDGE,
                            "thumb_long_edge": ctx.cfg.limits.thumb_long_edge}, model_digest=None)


def _run_pixels(ctx: Ctx, prep: Prepared) -> StageResult:
    try:
        d = ctx.decoded()
    except px.ImageAdmissionError as e:
        return StageResult("error", error=StageError(stage="pixels", code=e.code, message=str(e), retryable=False))
    metrics, palette = px.measure(d.rgb)
    thumb_rel = f"derived/thumbs/{ctx.asset.content_hash[:2]}/{ctx.asset.content_hash}_{prep.params['thumb_long_edge']}.webp"
    thumb_path = ctx.cfg.library_root / thumb_rel
    if not thumb_path.exists():
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = thumb_path.with_suffix(".part")
        tmp.write_bytes(px.make_thumbnail(d.rgb, prep.params["thumb_long_edge"]))
        tmp.replace(thumb_path)
    return StageResult("complete", payload={
        "format": d.format, "mime": d.mime,
        "stored_width": d.stored_size[0], "stored_height": d.stored_size[1],
        "exif_orientation": d.exif_orientation,
        "display_width": d.display_size[0], "display_height": d.display_size[1],
        "color_mode": d.color_mode, "icc_profile": d.icc_profile,
        "animated": d.animated, "frame_count": d.frame_count, "frames_analyzed": [0],
        "camera_exif": d.camera_exif, "metrics": metrics, "palette": palette,
        "hashes": {"sha256": ctx.asset.content_hash, "dhash64": px.dhash64(d.rgb), "phash64": px.phash64(d.rgb)},
        "thumb_ref": thumb_rel,
    })


# ---------------------------------------------------------------------------
# Stage: OCR
# ---------------------------------------------------------------------------

def _prep_ocr(ctx: Ctx) -> Prepared:
    engine = ctx.providers.ocr_engine()
    lim = ctx.cfg.limits
    return Prepared(
        params={
            "engine": engine.name, "languages": list(ctx.cfg.ocr_languages),
            "tile": lim.ocr_tile_edge, "overlap": lim.ocr_tile_overlap,
            "max_tiles": lim.ocr_max_tiles, "normalization": NORMALIZATION_VERSION,
        },
        model_digest=engine.digest,
        provider=engine,
    )


def _run_ocr(ctx: Ctx, prep: Prepared) -> StageResult:
    engine = prep.provider
    d = ctx.decoded()
    lim = ctx.cfg.limits
    run = run_ocr(d.rgb, engine, lim.ocr_tile_edge, lim.ocr_tile_overlap, lim.ocr_max_tiles,
                  lim.ocr_max_seconds, cancel_check=ctx.check_cancel)
    W, H = d.display_size
    regions = []
    for line, order, group in reading_order(run.lines):
        poly = [(min(max(x / W, 0.0), 1.0), min(max(y / H, 0.0), 1.0)) for x, y in line.polygon_px]
        regions.append({
            "region_id": f"r{order:04d}", "raw_text": line.text,
            "norm_text": normalize_for_search(line.text), "polygon": poly,
            "reading_order": order, "line_group": group,
            "language": None, "granularity": "line",
            "recognizer_score": None if line.score is None else round(min(max(line.score, 0.0), 1.0), 5),
            "tile_ids": [line.tile_id],
        })
    complete = run.complete
    reason = run.incomplete_reason
    if d.animated:
        complete = False
        reason = f"animated image: only representative frame 0 of {d.frame_count} analyzed"
    done = sum(1 for t in run.tiles if t.status == "complete")
    payload = {
        "engine": run.engine, "engine_version": run.engine_version, "model_ids": run.model_ids,
        "languages": list(ctx.cfg.ocr_languages), "script_scope": run.script_scope,
        "tiles": [{"tile_id": t.tile_id, "box_px": [t.x0, t.y0, t.x1, t.y1], "scale": t.scale,
                   "status": t.status} for t in run.tiles],
        "regions": regions,
        "coverage_fraction": round(done / len(run.tiles), 4) if run.tiles else 1.0,
        "complete": complete, "incomplete_reason": reason,
        "elapsed_s": round(run.elapsed_s, 3),
        "fallback_note": getattr(engine, "fallback_note", None),
    }
    status = "complete" if complete else "partial"
    return StageResult(status, payload=payload, detail=(
        f"{len(regions)} lines, {done}/{len(run.tiles)} tiles" + ("" if complete else f"; {reason}")))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

STAGES: dict[str, Stage] = {
    "pixels": Stage("pixels", px.PIXELS_VERSION, (), _prep_pixels, _run_pixels, "cpu_pixels"),
    "ocr": Stage("ocr", OCR_VERSION, ("pixels",), _prep_ocr, _run_ocr, "cpu_ocr", requires=("pixels",)),
}
# Stages after "index" run once the metadata revision is active.
POST_COMMIT: dict[str, Callable[[Ctx], StageResult]] = {}


def register_stage(stage: Stage) -> None:
    STAGES[stage.name] = stage


def register_post_commit(name: str, fn: Callable[[Ctx], StageResult]) -> None:
    POST_COMMIT[name] = fn


def stages_for(kind: str) -> dict[str, Stage]:
    _load_optional_stages()
    if kind == "video":
        from services.analyze.video import VIDEO_STAGES

        return VIDEO_STAGES
    return STAGES


def planned_stages(kind: str = "image") -> list[str]:
    return list(stages_for(kind)) + ["index"] + list(POST_COMMIT)


_OPTIONAL_LOADED = False


def _load_optional_stages() -> None:
    """Import modules that register M3+ stages (embeddings, objects, context, organize)."""
    global _OPTIONAL_LOADED
    if _OPTIONAL_LOADED:
        return
    _OPTIONAL_LOADED = True
    import importlib

    for mod in ("services.analyze.stages_semantic", "services.organize.stage"):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if e.name != mod:
                raise


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _stage_error(stage: str, exc: Exception) -> StageError:
    # Sanitized: type name only, never paths/OCR text/keys.
    return StageError(stage=stage, code="exception", message=f"{type(exc).__name__} during {stage}",
                      retryable=True)


def run_stage(ctx: Ctx, cache: StageCache, stage: Stage) -> StageResult:
    for dep in stage.requires:
        dep_res = ctx.results.get(dep)
        if dep_res is None or dep_res.status not in {"complete", "cached", "partial"}:
            return StageResult("missing", detail=f"requires {dep}")
    try:
        prep = stage.prepare(ctx)
    except ProviderUnavailable as e:
        status = "disabled" if e.code == "disabled" else "missing"
        err = None if status == "disabled" else StageError(stage=stage.name, code=e.code, message=str(e), retryable=True)
        return StageResult(status, detail=str(e), error=err)
    upstream = [ctx.keys[u] for u in stage.upstream if u in ctx.keys]
    key = stage_key(ctx.asset.content_hash, stage.name, stage.version, prep.params, prep.model_digest, upstream)
    ctx.keys[stage.name] = key
    hit = cache.get(key)
    if hit is not None:
        status = hit.pop("_cache_status")
        res = StageResult("cached" if status == "complete" else status, payload=hit)
        res.payload["_cache_key"] = key
        res.payload["_prepared"] = {"params": prep.params, "model_digest": prep.model_digest}
        return res
    try:
        res = stage.run(ctx, prep)
    except JobCancelled:
        raise
    except Exception as e:  # stage failure is isolated; other stages continue
        log.exception("stage %s failed", stage.name)
        return StageResult("error", detail=f"{type(e).__name__}", error=_stage_error(stage.name, e))
    cache.put(key, stage.name, ctx.asset.content_hash, stage.version, res.status, res.payload)
    res.payload["_cache_key"] = key
    res.payload["_prepared"] = {"params": prep.params, "model_digest": prep.model_digest}
    return res


def _prov(ctx: Ctx, stage: str, kind: str, modality: str, extractor: str, version: str,
          failure_modes: list[str]) -> Provenance:
    r = ctx.results[stage]
    stages = stages_for(ctx.asset.kind)
    return Provenance(
        producer=f"services.analyze.{stage}",
        source_modality=modality,
        source_refs=[f"asset:{ctx.asset.id}"],
        extractor=extractor,
        extractor_version=version,
        model_digest=r.payload.get("_prepared", {}).get("model_digest"),
        confidence_kind=kind,
        cost_class="cached" if r.status == "cached" else stages[stage].cost_class,
        cache_key=r.payload["_cache_key"],
        failure_modes=failure_modes,
        status=r.status,
    )


def assemble_metadata(ctx: Ctx) -> MediaMetadata:
    status: dict[str, str] = {}
    errors: list[StageError] = []
    prov: dict[str, Provenance] = {}
    for name, r in ctx.results.items():
        status[name] = r.status
        if r.error is not None:
            errors.append(r.error)

    image = None
    pr = ctx.results.get("pixels")
    if pr and pr.status in {"complete", "cached"}:
        p = pr.payload
        prov["pixels"] = _prov(ctx, "pixels", "deterministic_parse", "image", "pillow+opencv", px.PIXELS_VERSION,
                               ["corrupt_or_truncated_data", "unsupported_color_profile_conversion"])
        image = ImageObservation(
            format=p["format"], mime=p["mime"], stored_width=p["stored_width"], stored_height=p["stored_height"],
            exif_orientation=p["exif_orientation"], display_width=p["display_width"],
            display_height=p["display_height"], color_mode=p["color_mode"], icc_profile=p["icc_profile"],
            animated=p["animated"], frame_count=p["frame_count"], frames_analyzed=p["frames_analyzed"],
            camera_exif=p["camera_exif"], metrics=p["metrics"], palette=p["palette"], hashes=p["hashes"],
            provenance=prov["pixels"],
        )

    ocr = None
    orr = ctx.results.get("ocr")
    if orr and orr.status in {"complete", "cached", "partial"}:
        p = orr.payload
        prov["ocr"] = _prov(ctx, "ocr", "raw_recognizer", "video" if ctx.asset.kind == "video" else "image",
                            p["engine"], p["engine_version"],
                            ["small_or_low_contrast_text_missed", "unsupported_script", "tile_cap_truncation",
                             "reading_order_multicolumn"])
        ocr = OCRResult(
            engine=p["engine"], engine_version=p["engine_version"], model_ids=p["model_ids"],
            languages=p["languages"], script_scope=p["script_scope"],
            tiles=[OCRTile(tile_id=t["tile_id"], box_px=tuple(t["box_px"]), scale=t["scale"], status=t["status"])
                   for t in p["tiles"]],
            regions=[OCRRegion(**{k: v for k, v in r.items()}) for r in p["regions"]],
            coverage_fraction=p["coverage_fraction"], complete=p["complete"],
            incomplete_reason=p["incomplete_reason"], provenance=prov["ocr"],
        )

    extra = {}
    for hook in _ASSEMBLE_HOOKS:
        extra.update(hook(ctx, prov))
    if ctx.asset.kind == "video":
        extra.update(_assemble_video(ctx, prov, status))

    status["index"] = "complete"
    partial = bool(errors) or any(s in {"missing", "partial", "error", "cancelled"} for s in status.values())
    return MediaMetadata(
        schema_version=VIDEO_SCHEMA_VERSION if ctx.asset.kind == "video" else SCHEMA_VERSION,
        asset_id=ctx.asset.id,
        content_hash=ctx.asset.content_hash,
        asset_kind=ctx.asset.kind,
        analyzer_version=ANALYZER_VERSION,
        analyzed_at=datetime.now(timezone.utc),
        image=image,
        ocr=ocr,
        stage_status=status,
        stage_provenance=prov,
        errors=errors,
        partial=partial,
        **extra,
    )


_ASSEMBLE_HOOKS: list[Callable[[Ctx, dict], dict]] = []


def _assemble_video(ctx: Ctx, prov: dict, status: dict) -> dict:
    from services.analyze.video import (
        KEYFRAME_POLICY,
        KEYFRAMES_VERSION,
        TRANSCRIPT_VERSION,
    )

    out: dict = {}
    # Typed context/source/scene decisions are image questions; not asked of videos (yet).
    status.setdefault("context", "not_applicable")
    kr = ctx.results.get("keyframes")
    if kr and kr.status in {"complete", "cached", "partial"}:
        p = kr.payload
        pr = p["probe"]
        prov["keyframes"] = _prov(ctx, "keyframes", "deterministic_parse", "video", "ffmpeg+opencv",
                                  KEYFRAMES_VERSION, ["text_shorter_than_sample_interval_missed",
                                                      "keyframe_cap_truncation", "gradual_change_undersampled"])
        out["video"] = VideoObservation(
            container=pr["container"], mime=pr["mime"], duration_s=pr["duration_s"], fps=pr["fps"],
            width=pr["width"], height=pr["height"], rotation=pr["rotation"], video_codec=pr["video_codec"],
            has_audio=pr["has_audio"], audio_codec=pr["audio_codec"],
            sample_fps=kr.payload["_prepared"]["params"]["sample_fps"], keyframe_policy=KEYFRAME_POLICY,
            min_gap_s=p.get("min_gap_s"), max_gap_s=p.get("max_gap_s"),
            keyframes=[Keyframe(frame_id=k["frame_id"], t_s=k["t_s"], t_end_s=k["t_end_s"], frame_ref=k["frame_ref"],
                                width=k["width"], height=k["height"], reason=k["reason"]) for k in p["keyframes"]],
            poster_ref=p["poster_ref"], coverage_complete=p["complete"], coverage_end_s=p["coverage_end_s"],
            incomplete_reason=p["incomplete_reason"], provenance=prov["keyframes"])
    tr = ctx.results.get("transcript")
    if tr and tr.status in {"complete", "cached"} and tr.payload.get("segments") is not None \
            and tr.payload.get("engine"):
        prov["transcript"] = _prov(ctx, "transcript", "raw_recognizer", "video", "faster-whisper",
                                   TRANSCRIPT_VERSION, ["background_noise", "non_english_speech", "hallucinated_text"])
        out["speech"] = SpeechResult(engine=tr.payload["engine"], model=tr.payload["model"],
                                     segments=[SpeechSegment(**s) for s in tr.payload["segments"]],
                                     provenance=prov["transcript"])
    return out


def register_assemble_hook(fn: Callable[[Ctx, dict], dict]) -> None:
    _ASSEMBLE_HOOKS.append(fn)


def analyze_asset(ctx: Ctx) -> tuple[str, MediaMetadata | None]:
    """Run all stages for one asset; commit if still current. Returns (job_status, metadata)."""
    from services.library.metadata import commit_metadata

    cache = StageCache(ctx.repo)
    q = ctx.queue
    job_id = ctx.job.id if ctx.job else None
    for name, stage in stages_for(ctx.asset.kind).items():
        ctx.check_cancel()
        if q and job_id:
            q.set_stage(job_id, name, "running")
        t0 = time.monotonic()
        res = run_stage(ctx, cache, stage)
        ctx.results[name] = res
        if q and job_id:
            detail = res.detail or ""
            q.set_stage(job_id, name, res.status,
                        detail=(detail + f" ({time.monotonic() - t0:.2f}s)").strip(),
                        cache_key=res.payload.get("_cache_key"))

    ctx.check_cancel()
    meta = assemble_metadata(ctx)
    if q and job_id:
        q.set_stage(job_id, "index", "running")
    committed = commit_metadata(ctx.repo, ctx.cfg, ctx.asset, meta, ctx.results, ctx.job)
    if not committed:
        if q and job_id:
            q.set_stage(job_id, "index", "cancelled", detail="superseded by newer analysis or asset deleted")
        return "superseded", meta
    if q and job_id:
        q.set_stage(job_id, "index", "complete", detail=f"revision {committed}")

    post_failed = False
    for name, fn in POST_COMMIT.items():
        if q and job_id:
            q.set_stage(job_id, name, "running")
        try:
            res = fn(ctx)
        except Exception as e:
            log.exception("post-commit stage %s failed", name)
            res = StageResult("error", detail=type(e).__name__)
        post_failed |= res.status in {"error", "missing"}
        if q and job_id:
            q.set_stage(job_id, name, res.status, detail=res.detail)

    first = ctx.results.get("pixels") or ctx.results.get("keyframes")
    if first and first.status == "error":
        return "error", meta
    return ("partial" if meta.partial or post_failed else "complete"), meta
