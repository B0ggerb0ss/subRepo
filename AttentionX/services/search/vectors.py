"""Semantic retrieval channels over namespaced vector matrices.

- ``visual``: CLIP text query (or a reference image / crop vector) against
  CLIP image views of the active image namespace;
- ``ocr_semantic``: MiniLM text query against OCR chunk vectors of the active
  OCR-text namespace.
Each channel compares vectors of exactly one namespace. Region/chunk hits are
reduced to one candidate per asset (best view) *before* fusion, so long
documents do not win by having many chunks.

Retrieval is exact cosine over a normalized float32 matrix (10k assets x ~5
views x 512 floats ~ 100 MB worst case; see the benchmark report). An ANN
backend is deferred until measurements justify it (ADR-004).
Minimum-similarity cut-offs are validation-tuned settings, not truths.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

import numpy as np

from models.search import MatchEvidence, SearchRequest
from services.analyze.providers import ProviderUnavailable, get_providers
from services.analyze.vectors_registry import active_namespace
from services.library.config import LibraryConfig
from services.library.repository import Repository

# Tuned on the synthetic dev split (reports/evaluation.md); keep in sync.
CHANNEL_PARAMS = {
    "visual": {"min_cos": 0.22, "top_k": 150, "rel_window": 0.10},
    "ocr_semantic": {"min_cos": 0.38, "top_k": 150, "rel_window": 0.25},
    "similar": {"min_cos": 0.55, "top_k": 150, "rel_window": 1.0},
}


@dataclass
class _Matrix:
    namespace: str
    revision: int
    keys: list[tuple[str, str, str, str | None, str]]   # asset, view, kind, region json, source_refs json
    mat: np.ndarray
    asset_rows: dict[str, list[int]] = field(default_factory=dict)


_MATS: dict[tuple[str, str], _Matrix] = {}
_LOCK = threading.Lock()


def load_matrix(repo: Repository, namespace: str) -> _Matrix | None:
    ns = repo.query_one("SELECT revision, dim FROM vector_namespaces WHERE namespace=?", (namespace,))
    if ns is None:
        return None
    key = (str(repo.db_path), namespace)
    with _LOCK:
        cached = _MATS.get(key)
        if cached is not None and cached.revision == ns["revision"]:
            return cached
        rows = repo.query("SELECT v.asset_id, v.view_id, v.view_kind, v.region, v.source_refs, v.vector FROM vectors v"
                          " JOIN assets a ON a.id=v.asset_id WHERE v.namespace=? AND a.deleted_at IS NULL"
                          " ORDER BY v.asset_id, v.view_id", (namespace,))
        dim = ns["dim"]
        mat = np.zeros((len(rows), dim), dtype=np.float32)
        keys = []
        asset_rows: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            mat[i] = np.frombuffer(r["vector"], dtype=np.float32)
            keys.append((r["asset_id"], r["view_id"], r["view_kind"], r["region"], r["source_refs"]))
            asset_rows.setdefault(r["asset_id"], []).append(i)
        m = _Matrix(namespace, ns["revision"], keys, mat, asset_rows)
        _MATS[key] = m
        return m


def rank_assets(m: _Matrix, q: np.ndarray, eligible: set[str] | None, params: dict,
                exclude: set[str] = frozenset(), view_kinds: set[str] | None = None) -> list[tuple[str, float, int]]:
    """Return [(asset_id, best_cos, row_index)] sorted by cosine, after cut-offs."""
    if m.mat.shape[0] == 0:
        return []
    sims = m.mat @ q.astype(np.float32)
    best: dict[str, tuple[float, int]] = {}
    for i, s in enumerate(sims):
        aid, _, kind, _, _ = m.keys[i]
        if aid in exclude or (eligible is not None and aid not in eligible):
            continue
        if view_kinds is not None and kind not in view_kinds:
            continue
        if aid not in best or s > best[aid][0]:
            best[aid] = (float(s), i)
    ranked = sorted(((a, s, i) for a, (s, i) in best.items()), key=lambda t: (-t[1], t[0]))
    if not ranked:
        return []
    top = ranked[0][1]
    cut = max(params["min_cos"], top - params["rel_window"])
    return [t for t in ranked if t[1] >= cut][:params["top_k"]]


@dataclass
class SemanticResult:
    ranked: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    evidence: dict[str, list[MatchEvidence]] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)


def _crop_vector(repo: Repository, cfg: LibraryConfig, asset_id: str, crop: tuple) -> np.ndarray:
    from services.analyze.embeddings import crop_normalized
    from services.analyze.pixels import decode_image

    row = repo.query_one("SELECT original_ref FROM assets WHERE id=?", (asset_id,))
    rgb = decode_image(cfg.library_root / row["original_ref"], cfg.limits.max_image_pixels).rgb
    region = crop_normalized(rgb, crop)
    if region.shape[0] < 8 or region.shape[1] < 8:
        raise ValueError("crop is too small (needs at least 8x8 pixels)")
    return get_providers(cfg).clip().encode_images([region])[0]


def _ocr_semantic_evidence(repo: Repository, asset_id: str, region_ids: list[str], score: float) -> MatchEvidence:
    regs = repo.query(
        f"SELECT region_id, raw_text, polygon FROM ocr_regions WHERE asset_id=? AND region_id IN "
        f"({','.join('?' * len(region_ids))}) ORDER BY order_idx", (asset_id, *region_ids)) if region_ids else []
    return MatchEvidence(
        reason="OCR_SEMANTIC", detail="OCR passage is semantically related (similarity, not a quote match)",
        region_ids=[r["region_id"] for r in regs], polygons=[json.loads(r["polygon"]) for r in regs],
        excerpt=" / ".join(r["raw_text"] for r in regs)[:600], score=round(score, 4), score_kind="cosine")


def semantic_channels(repo: Repository, cfg: LibraryConfig, free_text: str, eligible: set[str],
                      req: SearchRequest, similar_ref: str | None) -> SemanticResult:
    out = SemanticResult()
    providers = get_providers(cfg)

    if similar_ref:
        ns = active_namespace(repo, "image")
        m = load_matrix(repo, ns["namespace"]) if ns else None
        if m is None or similar_ref not in m.asset_rows:
            out.degraded.append("visual similarity unavailable: the reference image has no image embedding yet")
            return out
        if req.crop is not None:
            try:
                q = _crop_vector(repo, cfg, similar_ref, req.crop)
            except ProviderUnavailable as e:
                out.degraded.append(f"crop similarity unavailable: {e}")
                return out
            detail = f"visually similar to the selected crop {tuple(round(v, 3) for v in req.crop)}"
            exclude: set[str] = set()
        else:
            gi = next(i for i in m.asset_rows[similar_ref] if m.keys[i][1] == "global")
            q = m.mat[gi]
            detail = "visually similar to the reference image"
            exclude = {similar_ref}
        res = rank_assets(m, q, eligible, CHANNEL_PARAMS["similar"], exclude=exclude)
        out.ranked["visual"] = [(a, s) for a, s, _ in res]
        for a, s, i in res:
            view = m.keys[i][1]
            out.evidence.setdefault(a, []).append(MatchEvidence(
                reason="VISUAL_SIMILARITY", detail=detail + ("" if view == "global" else f" (best view: {view})"),
                score=round(s, 4), score_kind="cosine"))
        return out

    if not free_text:
        return out

    if "visual" in req.channels:
        ns = active_namespace(repo, "image")
        try:
            clip = providers.clip()
            if ns is None or ns["model_digest"] != clip.model_digest:
                raise ProviderUnavailable("namespace_mismatch", "no image index for the loaded CLIP model")
            m = load_matrix(repo, ns["namespace"])
            q = clip.encode_texts([free_text])[0]
            res = rank_assets(m, q, eligible, CHANNEL_PARAMS["visual"])
            out.ranked["visual"] = [(a, s) for a, s, _ in res]
            for a, s, i in res:
                view = m.keys[i][1]
                out.evidence.setdefault(a, []).append(MatchEvidence(
                    reason="VISUAL_SIMILARITY",
                    detail="image content resembles the description" + ("" if view == "global" else f" (best: {view})"),
                    score=round(s, 4), score_kind="cosine"))
        except ProviderUnavailable as e:
            out.degraded.append(f"visual search unavailable: {e}")

    if "ocr_semantic" in req.channels:
        ns = active_namespace(repo, "ocr_text")
        try:
            enc = providers.text_encoder()
            if ns is None or ns["model_digest"] != enc.model_digest:
                raise ProviderUnavailable("namespace_mismatch", "no OCR-text index for the loaded text model")
            m = load_matrix(repo, ns["namespace"])
            q = enc.encode_queries([free_text])[0]
            res = rank_assets(m, q, eligible, CHANNEL_PARAMS["ocr_semantic"])
            out.ranked["ocr_semantic"] = [(a, s) for a, s, _ in res]
            for a, s, i in res:
                out.evidence.setdefault(a, []).append(
                    lambda a=a, s=s, refs=m.keys[i][4]: [_ocr_semantic_evidence(repo, a, json.loads(refs), s)])
        except ProviderUnavailable as e:
            out.degraded.append(f"OCR meaning search unavailable: {e}")
    return out
