"""Vector namespaces: one per (model digest, preprocessing, kind).

A namespace id embeds the model digest prefix and preprocessing version, so a
model or preprocessing change creates a *new* namespace that is built in the
shadow (state='building') while the old one stays 'active' and searchable.
``promote_ready`` switches atomically once the shadow covers every analyzed
asset. Query vectors are only ever compared with rows of the same namespace.
"""
from __future__ import annotations

import hashlib
import time

from services.library.config import LibraryConfig, load_manifest
from services.library.repository import Repository

CLIP_MODEL = "clip_vit_b32_laion2b_s34b_b79k"
MINILM_MODEL = "minilm_l6_v2"
CLIP_PREPROCESS = "clip-views/1"       # see services/analyze/embeddings.py
OCR_CHUNK_PREPROCESS = "ocr-chunks/1"


def model_digest(model: str) -> str:
    files = load_manifest()["models"][model]["files"]
    return hashlib.sha256("".join(files[f]["sha256"] for f in sorted(files)).encode()).hexdigest()


def clip_namespace() -> dict:
    d = model_digest(CLIP_MODEL)
    return {"namespace": f"clip-b32-laion2b:{d[:12]}:{CLIP_PREPROCESS}", "space": f"clip-b32-laion2b:{d[:12]}",
            "model": CLIP_MODEL, "model_digest": d, "preprocess_version": CLIP_PREPROCESS, "dim": 512,
            "normalization": "l2", "kind": "image"}


def minilm_namespace() -> dict:
    d = model_digest(MINILM_MODEL)
    return {"namespace": f"minilm-l6-v2:{d[:12]}:{OCR_CHUNK_PREPROCESS}", "space": f"minilm-l6-v2:{d[:12]}",
            "model": MINILM_MODEL, "model_digest": d, "preprocess_version": OCR_CHUNK_PREPROCESS, "dim": 384,
            "normalization": "l2", "kind": "ocr_text"}


def ensure_namespaces(repo: Repository, cfg: LibraryConfig) -> list[str]:
    created = []
    with repo.write() as c:
        for ns in (clip_namespace(), minilm_namespace()):
            if c.execute("SELECT 1 FROM vector_namespaces WHERE namespace=?", (ns["namespace"],)).fetchone():
                continue
            other_active = c.execute("SELECT 1 FROM vector_namespaces WHERE kind=? AND state='active'",
                                     (ns["kind"],)).fetchone()
            state = "building" if other_active else "active"
            c.execute(
                "INSERT INTO vector_namespaces(namespace, space, model, model_digest, preprocess_version, dim,"
                " normalization, kind, state, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ns["namespace"], ns["space"], ns["model"], ns["model_digest"], ns["preprocess_version"],
                 ns["dim"], ns["normalization"], ns["kind"], state, time.time()))
            created.append(ns["namespace"])
    return created


def active_namespace(repo: Repository, kind: str) -> dict | None:
    r = repo.query_one("SELECT * FROM vector_namespaces WHERE kind=? AND state='active'", (kind,))
    return dict(r) if r else None


def promote_ready(repo: Repository) -> list[str]:
    """Activate any building namespace that now covers all analyzed assets."""
    promoted = []
    with repo.write() as c:
        for ns in c.execute("SELECT namespace, kind FROM vector_namespaces WHERE state='building'").fetchall():
            active = c.execute("SELECT namespace FROM vector_namespaces WHERE kind=? AND state='active'",
                               (ns["kind"],)).fetchone()
            need = c.execute(
                "SELECT COUNT(DISTINCT v.asset_id) FROM vectors v JOIN assets a ON a.id=v.asset_id"
                " WHERE v.namespace=? AND a.deleted_at IS NULL", (active["namespace"],)).fetchone()[0] if active else 0
            have = c.execute(
                "SELECT COUNT(DISTINCT v.asset_id) FROM vectors v JOIN assets a ON a.id=v.asset_id"
                " WHERE v.namespace=? AND a.deleted_at IS NULL", (ns["namespace"],)).fetchone()[0]
            if have >= need:
                if active:
                    c.execute("UPDATE vector_namespaces SET state='retired' WHERE namespace=?", (active["namespace"],))
                c.execute("UPDATE vector_namespaces SET state='active' WHERE namespace=?", (ns["namespace"],))
                promoted.append(ns["namespace"])
    return promoted
