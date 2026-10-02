"""Video assets in the shared library (M8).

A video stays one library asset. Analysis samples it once, bounded:

1. ``keyframes``: one streaming FFmpeg decode at ``video_sample_fps`` (scaled to
   ``video_frame_long_edge``, rotation applied). A frame becomes a keyframe when
   it is the first, when its content changed (fraction of changed pixels on a
   64x36 grayscale view), or when ``video_max_gap_s`` passed without one. Only the
   last kept frame is held in memory; keyframes are written to ``derived/`` as
   JPEG. A cap (``video_max_keyframes``) stops sampling and the coverage is
   reported as incomplete — never silently truncated.
2. ``ocr`` / ``image_embed`` / ``ocr_text_embed`` / ``objects``: the existing
   image providers run on each keyframe. Every OCR line, vector and detection
   carries its ``frame_id`` and ``t_s``; polygons/boxes are normalized to the
   keyframe. Frame vectors use the same CLIP preprocessing (letterboxed global
   view) as images, so they live in the same namespace and are comparable.
3. ``transcript``: local faster-whisper only, and only when ASR is enabled and
   its weights are provisioned; otherwise ``disabled``/``missing`` with a reason.
   No download, no cloud fallback.

Text appearing only between two sampled frames (shorter than 1/sample_fps)
can be missed; that limit is documented, not hidden.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from services.analyze import pixels as px
from services.analyze.cache import encode_vector
from services.analyze.embeddings import CHUNK_OVERLAP_REGIONS, CHUNK_TOKENS
from services.analyze.objects import OBJECTS_VERSION, STORE_THRESHOLD
from services.analyze.ocr import (
    OCR_VERSION,
    normalize_for_search,
    reading_order,
    run_ocr,
)
from services.analyze.pipeline import (
    Ctx,
    Prepared,
    Stage,
    StageResult,
    _prep_ocr,
)
from services.analyze.providers import ProviderUnavailable
from services.analyze.vectors_registry import CLIP_PREPROCESS, OCR_CHUNK_PREPROCESS
from services.analyze.videoio import (  # noqa: F401  (re-exported)
    KEYFRAME_POLICY,
    VIDEO_SUFFIXES,
    VideoAdmissionError,
    probe_video,
    sample_keyframes,
)

KEYFRAMES_VERSION = "keyframes/1.1"
VIDEO_EMBED_VERSION = "video-embed/1.0"
TRANSCRIPT_VERSION = "transcript/1.0"

# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def _keyframe_dir(ctx: Ctx, key: str) -> tuple[Path, str]:
    h = ctx.asset.content_hash
    rel = f"derived/keyframes/{h[:2]}/{h}_{key[:12]}"
    return ctx.cfg.library_root / rel, rel


def _prep_keyframes(ctx: Ctx) -> Prepared:
    lim = ctx.cfg.limits
    return Prepared({"sample_fps": lim.video_sample_fps, "max_gap_s": lim.video_max_gap_s,
                     "max_keyframes": lim.video_max_keyframes, "long_edge": lim.video_frame_long_edge,
                     "policy": KEYFRAME_POLICY, "thumb_long_edge": lim.thumb_long_edge}, None)


def _run_keyframes(ctx: Ctx, prep: Prepared) -> StageResult:
    from services.analyze.cache import stage_key

    src = ctx.original_path()
    lim = ctx.cfg.limits
    try:
        probe = probe_video(src, lim.max_video_bytes, lim.max_video_seconds)
    except VideoAdmissionError as e:
        from models.media_metadata import StageError

        return StageResult("error", error=StageError(stage="keyframes", code=e.code, message=str(e), retryable=False))
    # Directory keyed like the stage itself, so a policy change never reuses stale frames.
    key = stage_key(ctx.asset.content_hash, "keyframes", KEYFRAMES_VERSION, prep.params, None, [])
    out_dir, rel = _keyframe_dir(ctx, key)
    p = prep.params
    res = sample_keyframes(src, probe, out_dir, p["sample_fps"], p["max_gap_s"], p["max_keyframes"],
                           p["long_edge"], cancel_check=ctx.check_cancel)
    for k in res["keyframes"]:
        k["frame_ref"] = f"{rel}/{k['frame_id']}.jpg"
    poster = ctx.cfg.library_root / res["keyframes"][0]["frame_ref"]
    thumb_rel = f"derived/thumbs/{ctx.asset.content_hash[:2]}/{ctx.asset.content_hash}_{p['thumb_long_edge']}.webp"
    thumb_path = ctx.cfg.library_root / thumb_rel
    if not thumb_path.exists():
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = thumb_path.with_suffix(".part")
        tmp.write_bytes(px.make_thumbnail(_read_frame(poster), p["thumb_long_edge"]))
        tmp.replace(thumb_path)
    status = "complete" if res["complete"] else "partial"
    return StageResult(status, payload={"probe": probe, **res, "thumb_ref": thumb_rel, "poster_ref":
                                        res["keyframes"][0]["frame_ref"]},
                       detail=f"{len(res['keyframes'])} keyframe(s) from {res['frames_decoded']} sampled frame(s)"
                       + ("" if res["complete"] else f"; {res['incomplete_reason']}"))


def _read_frame(path: Path) -> np.ndarray:
    import cv2

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError("keyframe missing on disk")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _frames(ctx: Ctx):
    """Yield (keyframe, rgb) one at a time (bounded memory)."""
    for k in ctx.results["keyframes"].payload["keyframes"]:
        ctx.check_cancel()
        yield k, _read_frame(ctx.cfg.library_root / k["frame_ref"])


def _run_frame_ocr(ctx: Ctx, prep: Prepared) -> StageResult:
    engine = prep.provider
    lim = ctx.cfg.limits
    kf = ctx.results["keyframes"].payload
    regions, tiles = [], []
    complete = True
    reasons = []
    order = 0
    t_total = 0.0
    tiles_done = tiles_all = 0
    for k, rgb in _frames(ctx):
        run = run_ocr(rgb, engine, lim.ocr_tile_edge, lim.ocr_tile_overlap, lim.ocr_max_tiles, lim.ocr_max_seconds,
                      cancel_check=ctx.check_cancel)
        t_total += run.elapsed_s
        H, W = rgb.shape[:2]
        fid = k["frame_id"]
        for line, _, group in reading_order(run.lines):
            poly = [(min(max(x / W, 0.0), 1.0), min(max(y / H, 0.0), 1.0)) for x, y in line.polygon_px]
            regions.append({
                "region_id": f"{fid}-r{order:04d}", "raw_text": line.text,
                "norm_text": normalize_for_search(line.text), "polygon": poly, "reading_order": order,
                "line_group": group, "language": None, "granularity": "line",
                "recognizer_score": None if line.score is None else round(min(max(line.score, 0.0), 1.0), 5),
                "tile_ids": [f"{fid}-{line.tile_id}"], "frame_id": fid, "t_s": k["t_s"],
            })
            order += 1
        for t in run.tiles:
            tiles.append({"tile_id": f"{fid}-{t.tile_id}", "box_px": [t.x0, t.y0, t.x1, t.y1], "scale": t.scale,
                          "status": t.status})
        tiles_done += sum(1 for t in run.tiles if t.status == "complete")
        tiles_all += len(run.tiles)
        if not run.complete:
            complete = False
            reasons.append(f"{fid}: {run.incomplete_reason}")
    if not kf["complete"]:
        complete = False
        reasons.append(kf["incomplete_reason"])
    payload = {
        "engine": run.engine, "engine_version": run.engine_version, "model_ids": run.model_ids,
        "languages": list(ctx.cfg.ocr_languages), "script_scope": run.script_scope,
        "tiles": tiles, "regions": regions,
        "coverage_fraction": round(tiles_done / tiles_all, 4) if tiles_all else 1.0,
        "complete": complete, "incomplete_reason": "; ".join(reasons)[:500] if reasons else None,
        "elapsed_s": round(t_total, 3), "fallback_note": getattr(engine, "fallback_note", None),
    }
    n_frames = len(kf["keyframes"])
    return StageResult("complete" if complete else "partial", payload=payload,
                       detail=f"{len(regions)} lines over {n_frames} keyframe(s)")


def _prep_frame_embed(ctx: Ctx) -> Prepared:
    clip = ctx.providers.clip()
    return Prepared({"preprocess": CLIP_PREPROCESS, "view": "frame_global"}, clip.model_digest, clip)


def _run_frame_embed(ctx: Ctx, prep: Prepared) -> StageResult:
    clip = prep.provider
    vectors = []
    for k, rgb in _frames(ctx):
        v = clip.image_views(rgb, 0)[0]  # letterboxed global view only: same preprocessing as images
        vectors.append({"namespace": clip.namespace, "space": clip.space, "view_id": k["frame_id"],
                        "view_kind": "frame_global", "region": None, "source_refs": [],
                        "vector": encode_vector(v["vector"]), "frame_id": k["frame_id"], "t_s": k["t_s"]})
    return StageResult("complete", {"vectors": vectors, "model_digest": clip.model_digest, "dim": clip.dim},
                       detail=f"{len(vectors)} frame vector(s)")


def _prep_frame_text_embed(ctx: Ctx) -> Prepared:
    enc = ctx.providers.text_encoder()
    return Prepared({"preprocess": OCR_CHUNK_PREPROCESS, "chunk_tokens": CHUNK_TOKENS,
                     "overlap_regions": CHUNK_OVERLAP_REGIONS, "scope": "per_keyframe"}, enc.model_digest, enc)


def _run_frame_text_embed(ctx: Ctx, prep: Prepared) -> StageResult:
    enc = prep.provider
    regions = sorted(ctx.results["ocr"].payload.get("regions", []), key=lambda r: r["reading_order"])
    if not regions:
        return StageResult("not_applicable", {"vectors": []}, detail="no OCR text to embed")
    by_frame: dict[str, list[dict]] = {}
    for r in regions:
        by_frame.setdefault(r["frame_id"], []).append(r)
    items = []
    for fid, regs in by_frame.items():
        for c in enc.chunk_regions(regs):
            items.append((fid, regs[0]["t_s"], c))
    vecs = enc.encode([c["text"] for _, _, c in items])
    vectors = [{"namespace": enc.namespace, "space": enc.space, "view_id": f"{fid}:{c['view_id']}",
                "view_kind": "ocr_chunk", "region": None, "source_refs": c["region_ids"],
                "vector": encode_vector(v), "frame_id": fid, "t_s": t}
               for (fid, t, c), v in zip(items, vecs)]
    return StageResult("complete", {"vectors": vectors, "model_digest": enc.model_digest, "dim": enc.dim},
                       detail=f"{len(vectors)} chunk(s) over {len(by_frame)} keyframe(s)")


def _prep_frame_objects(ctx: Ctx) -> Prepared:
    from services.analyze.stages_semantic import _prep_objects

    p = _prep_objects(ctx)
    p.params = dict(p.params, scope="per_keyframe")
    return p


def _run_frame_objects(ctx: Ctx, prep: Prepared) -> StageResult:
    obs = []
    for k, rgb in _frames(ctx):
        for o in prep.provider.detect(rgb):
            obs.append(dict(o, obs_id=f"{k['frame_id']}-{o['obs_id']}", frame_id=k["frame_id"], t_s=k["t_s"]))
    return StageResult("complete", {"observations": obs, "model": prep.provider.model,
                                    "ontology_version": prep.provider.ontology_version,
                                    "score_threshold": STORE_THRESHOLD},
                       detail=f"{len(obs)} detection(s)")


def _prep_transcript(ctx: Ctx) -> Prepared:
    if not ctx.cfg.features.asr:
        raise ProviderUnavailable("disabled", "speech transcription disabled (ANALYSIS_ASR=0)")
    kf = ctx.results.get("keyframes")
    has_audio = bool(kf and kf.payload.get("probe", {}).get("has_audio"))
    if not has_audio:
        return Prepared({"has_audio": False}, None)
    from models.schemas import TranscriptionError
    from models.settings import settings
    from services import transcribe as asr

    try:
        model = asr._get_model(settings.whisper_model_size)  # local files only; never downloads
    except TranscriptionError as e:
        raise ProviderUnavailable("model_missing", str(e)) from e
    return Prepared({"has_audio": True, "model_size": settings.whisper_model_size, "engine": "faster-whisper"},
                    f"whisper:{settings.whisper_model_size}", model)


def _run_transcript(ctx: Ctx, prep: Prepared) -> StageResult:
    if not prep.params.get("has_audio"):
        return StageResult("not_applicable", {"segments": []}, detail="no audio stream")
    from services.ingest import extract_audio
    from services.transcribe import transcribe

    with tempfile.TemporaryDirectory(dir=ctx.cfg.temp_root) as tmp:
        wav = extract_audio(str(ctx.original_path()), tmp)
        segs = transcribe(wav, model_size=prep.params["model_size"])
    return StageResult("complete", {"segments": [{"start_s": round(s.start, 3), "end_s": round(s.end, 3),
                                                  "text": s.text} for s in segs],
                                    "engine": "faster-whisper", "model": prep.params["model_size"]},
                       detail=f"{len(segs)} segment(s)")


VIDEO_STAGES: dict[str, Stage] = {
    "keyframes": Stage("keyframes", KEYFRAMES_VERSION, (), _prep_keyframes, _run_keyframes, "cpu_pixels"),
    "ocr": Stage("ocr", f"{OCR_VERSION}+{VIDEO_EMBED_VERSION}", ("keyframes",), _prep_ocr, _run_frame_ocr,
                 "cpu_ocr", requires=("keyframes",)),
    "image_embed": Stage("image_embed", VIDEO_EMBED_VERSION, ("keyframes",), _prep_frame_embed, _run_frame_embed,
                         "cpu_embed", requires=("keyframes",)),
    "ocr_text_embed": Stage("ocr_text_embed", VIDEO_EMBED_VERSION, ("ocr",), _prep_frame_text_embed,
                            _run_frame_text_embed, "cpu_embed", requires=("ocr",)),
    "objects": Stage("objects", f"{OBJECTS_VERSION}+{VIDEO_EMBED_VERSION}", ("keyframes",), _prep_frame_objects,
                     _run_frame_objects, "cpu_detect", requires=("keyframes",)),
    "transcript": Stage("transcript", TRANSCRIPT_VERSION, ("keyframes",), _prep_transcript, _run_transcript,
                        "cpu_asr", requires=("keyframes",)),
}
