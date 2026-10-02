"""M3/M4 pipeline stages: image_embed, ocr_text_embed, objects, context.

Registered into ``services.analyze.pipeline`` on import. Each stage's cache key
covers its model digest, preprocessing and upstream keys (see pipeline.py).
"""
from __future__ import annotations

import hashlib

import numpy as np

from models.media_metadata import Decision, EmbeddingRecord, ObjectObservation, ObjectResult, Provenance
from services.analyze import context as ctxmod
from services.analyze.cache import decode_vector, encode_vector
from services.analyze.catalog import catalog
from services.analyze.embeddings import CHUNK_OVERLAP_REGIONS, CHUNK_TOKENS
from services.analyze.objects import MAX_RESULTS, OBJECTS_VERSION, STORE_THRESHOLD
from services.analyze.pipeline import (
    Ctx,
    Prepared,
    Stage,
    StageResult,
    register_assemble_hook,
    register_stage,
)
from services.analyze.providers import ProviderUnavailable
from services.analyze.vectors_registry import CLIP_PREPROCESS, OCR_CHUNK_PREPROCESS

EMBED_VERSION = "embed/1.1"
BODY_MIN_WORDS = 4


# -- image_embed ---------------------------------------------------------------

def _prep_image_embed(ctx: Ctx) -> Prepared:
    clip = ctx.providers.clip()
    return Prepared({"preprocess": CLIP_PREPROCESS, "max_regions": ctx.cfg.limits.region_views_max},
                    clip.model_digest, clip)


def _run_image_embed(ctx: Ctx, prep: Prepared) -> StageResult:
    clip = prep.provider
    views = clip.image_views(ctx.decoded().rgb, ctx.cfg.limits.region_views_max)
    vectors = [{"namespace": clip.namespace, "space": clip.space, "view_id": v["view_id"],
                "view_kind": v["view_kind"], "region": v["region"], "source_refs": [],
                "vector": encode_vector(v["vector"])} for v in views]
    return StageResult("complete", {"vectors": vectors, "model_digest": clip.model_digest, "dim": clip.dim},
                       detail=f"{len(vectors)} view(s)")


# -- ocr_text_embed ------------------------------------------------------------

def _prep_ocr_text_embed(ctx: Ctx) -> Prepared:
    enc = ctx.providers.text_encoder()
    return Prepared({"preprocess": OCR_CHUNK_PREPROCESS, "chunk_tokens": CHUNK_TOKENS,
                     "overlap_regions": CHUNK_OVERLAP_REGIONS}, enc.model_digest, enc)


def _run_ocr_text_embed(ctx: Ctx, prep: Prepared) -> StageResult:
    enc = prep.provider
    regions = sorted(ctx.results["ocr"].payload.get("regions", []), key=lambda r: r["reading_order"])
    if not regions:
        return StageResult("not_applicable", {"vectors": []}, detail="no OCR text to embed")
    chunks = enc.chunk_regions(regions)
    # "body": the OCR text without short UI labels (Like/Comment/nav items), used
    # for topical grouping so shared interface chrome cannot dominate.
    body = [r for r in regions if len(r["raw_text"].split()) >= BODY_MIN_WORDS]
    body_chunk = enc.chunk_regions(body)[0] if body else None
    texts = [c["text"] for c in chunks] + ([body_chunk["text"]] if body_chunk else [])
    vecs = enc.encode(texts)
    vectors = [{"namespace": enc.namespace, "space": enc.space, "view_id": c["view_id"], "view_kind": "ocr_chunk",
                "region": None, "source_refs": c["region_ids"], "vector": encode_vector(v)}
               for c, v in zip(chunks, vecs)]
    if body_chunk:
        vectors.append({"namespace": enc.namespace, "space": enc.space, "view_id": "body", "view_kind": "ocr_body",
                        "region": None, "source_refs": body_chunk["region_ids"], "vector": encode_vector(vecs[-1])})
    return StageResult("complete", {"vectors": vectors, "model_digest": enc.model_digest, "dim": enc.dim},
                       detail=f"{len(chunks)} chunk(s)")


# -- objects -------------------------------------------------------------------

def _prep_objects(ctx: Ctx) -> Prepared:
    det = ctx.providers.detector()
    digest = hashlib.sha256(f"{det.model}|{det.ontology_version}".encode()).hexdigest()
    from services.analyze.vectors_registry import model_digest

    return Prepared({"store_threshold": STORE_THRESHOLD, "max_results": MAX_RESULTS,
                     "ontology": det.ontology_version}, model_digest("efficientdet_lite0") + digest[:8], det)


def _run_objects(ctx: Ctx, prep: Prepared) -> StageResult:
    obs = prep.provider.detect(ctx.decoded().rgb)
    return StageResult("complete", {"observations": obs, "model": prep.provider.model,
                                    "ontology_version": prep.provider.ontology_version,
                                    "score_threshold": STORE_THRESHOLD}, detail=f"{len(obs)} detection(s)")


# -- context -------------------------------------------------------------------

def _prep_context(ctx: Ctx) -> Prepared:
    if not ctx.cfg.features.context:
        raise ProviderUnavailable("disabled", "context decisions disabled by ANALYSIS_CONTEXT=0")
    clip = ctx.providers.clip()
    try:
        minilm = ctx.providers.text_encoder()
        mdig = minilm.model_digest
    except ProviderUnavailable:
        minilm, mdig = None, "none"
    digest = hashlib.sha256(f"{clip.model_digest}|{mdig}".encode()).hexdigest()
    return Prepared({"catalog": catalog()["catalog_version"], "prompts": ctxmod.PROMPTS_VERSION,
                     "context_version": ctxmod.CONTEXT_VERSION,
                     "calibration": ctxmod.load_calibration().get("version")},
                    digest, ctxmod.ContextDecider(clip, minilm))


def _global_vec(ctx: Ctx) -> np.ndarray | None:
    r = ctx.results.get("image_embed")
    if r is None or r.status not in {"complete", "cached"}:
        return None
    for v in r.payload["vectors"]:
        if v["view_id"] == "global":
            return decode_vector(v["vector"])
    return None


def _run_context(ctx: Ctx, prep: Prepared) -> StageResult:
    ocr = ctx.results.get("ocr")
    ocr_status = ocr.status if ocr else "missing"
    te = ctx.results.get("ocr_text_embed")
    chunk_vecs = None
    if te and te.status in {"complete", "cached"} and te.payload.get("vectors"):
        chunk_vecs = np.stack([decode_vector(v["vector"]) for v in te.payload["vectors"]])
    px = ctx.results.get("pixels")
    img_vec = _global_vec(ctx)
    decisions = ctxmod.decide(prep.provider if img_vec is not None else None, ctx.asset.id, img_vec,
                              ocr.payload if ocr and ocr.status in {"complete", "cached", "partial"} else None,
                              ocr_status, chunk_vecs,
                              px.payload if px and px.status in {"complete", "cached"} else None)
    n_ok = sum(1 for d in decisions.values() if d["status"] == "complete")
    status = "complete" if img_vec is not None else "missing"
    return StageResult(status, {"decisions": decisions}, detail=f"{n_ok}/{len(decisions)} heads decided")


register_stage(Stage("image_embed", EMBED_VERSION, ("pixels",), _prep_image_embed, _run_image_embed,
                     "cpu_embed", requires=("pixels",)))
register_stage(Stage("ocr_text_embed", EMBED_VERSION, ("ocr",), _prep_ocr_text_embed, _run_ocr_text_embed,
                     "cpu_embed", requires=("ocr",)))
register_stage(Stage("objects", OBJECTS_VERSION, ("pixels",), _prep_objects, _run_objects, "cpu_detect",
                     requires=("pixels",)))
register_stage(Stage("context", ctxmod.CONTEXT_VERSION, ("pixels", "ocr", "image_embed", "ocr_text_embed"),
                     _prep_context, _run_context, "cpu_decide", requires=("pixels",)))


def _prov(ctx: Ctx, stage: str, kind: str, extractor: str, version: str, modes: list[str],
          modality: str = "image") -> Provenance:
    r = ctx.results[stage]
    if ctx.asset.kind == "video" and modality == "image":
        modality = "video"
    return Provenance(
        producer=f"services.analyze.{stage}", source_modality=modality, source_refs=[f"asset:{ctx.asset.id}"],
        extractor=extractor, extractor_version=version,
        model_digest=r.payload.get("_prepared", {}).get("model_digest"), confidence_kind=kind,
        cost_class="cached" if r.status == "cached" else {"image_embed": "cpu_embed", "ocr_text_embed": "cpu_embed",
                                                           "objects": "cpu_detect", "context": "cpu_decide"}[stage],
        cache_key=r.payload["_cache_key"], failure_modes=modes, status=r.status)


def _assemble(ctx: Ctx, prov: dict) -> dict:
    extra: dict = {"embeddings": [], "decisions": {}}
    for stage, kind in (("image_embed", "image"), ("ocr_text_embed", "ocr_text")):
        r = ctx.results.get(stage)
        if r is None or r.status not in {"complete", "cached"}:
            continue
        prov[stage] = _prov(ctx, stage, "unavailable", "onnxruntime", EMBED_VERSION,
                            ["out_of_domain_imagery", "english_only_text" if kind == "ocr_text" else "center_bias"],
                            modality="text" if kind == "ocr_text" else "image")
        for v in r.payload["vectors"]:
            extra["embeddings"].append(EmbeddingRecord(
                embedding_id=f"{ctx.asset.id}:{v['namespace']}:{v['view_id']}", namespace=v["namespace"],
                space=v["space"], model=stage, model_digest=r.payload["model_digest"], dim=r.payload["dim"],
                normalization="l2",
                preprocess_version=CLIP_PREPROCESS if kind == "image" else OCR_CHUNK_PREPROCESS,
                view_kind=v["view_kind"], view_id=v["view_id"],
                region=tuple(v["region"]) if v["region"] else None, source_refs=v["source_refs"],
                storage_ref=f"sqlite:vectors/{v['namespace']}/{ctx.asset.id}/{v['view_id']}",
                frame_id=v.get("frame_id"), t_s=v.get("t_s")))
    r = ctx.results.get("objects")
    if r and r.status in {"complete", "cached"}:
        prov["objects"] = _prov(ctx, "objects", "raw_detector", "mediapipe-tasks", OBJECTS_VERSION,
                                ["closed_coco_vocabulary", "small_objects_missed", "uncalibrated_scores"])
        extra["objects"] = ObjectResult(
            model=r.payload["model"], ontology_version=r.payload["ontology_version"],
            score_threshold=r.payload["score_threshold"],
            observations=[ObjectObservation(**{k: (tuple(v) if k == "box" else v) for k, v in o.items()})
                          for o in r.payload["observations"]],
            provenance=prov["objects"])
    r = ctx.results.get("context")
    if r and r.status in {"complete", "cached"}:
        prov["context"] = _prov(ctx, "context", "zero_shot_softmax_uncalibrated", "clip-zero-shot",
                                ctxmod.CONTEXT_VERSION, ["uncalibrated_probabilities", "prompt_sensitivity",
                                                         "ui_rule_coverage"])
        extra["decisions"] = {qid: Decision(**d) for qid, d in r.payload["decisions"].items()}
    return extra


register_assemble_hook(_assemble)
