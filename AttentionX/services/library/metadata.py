"""Commit and read the active metadata revision.

``commit_metadata`` is the only writer of active machine metadata. In one
transaction it: checks fencing (asset alive, job generation current), appends
an immutable revision, points the asset at it, and rebuilds every derived
search row (OCR regions/docs + FTS, objects, decisions, vectors). Readers see
either the old or the new revision, never a mixture.

User annotations and overrides live in separate tables and are never touched
here, so re-analysis cannot overwrite a user correction.
"""
from __future__ import annotations

import json
import time

import numpy as np

from models.asset import Asset, Job
from models.media_metadata import MediaMetadata, load_metadata
from services.analyze.cache import decode_vector
from services.library.config import LibraryConfig
from services.library.repository import Repository


def commit_metadata(repo: Repository, cfg: LibraryConfig, asset: Asset, meta: MediaMetadata,
                    results: dict, job: Job | None) -> int | None:
    payload = meta.model_dump_json()
    now = time.time()
    with repo.write() as c:
        row = c.execute("SELECT deleted_at, analysis_generation, metadata_revision FROM assets WHERE id=?",
                        (asset.id,)).fetchone()
        if row is None or row["deleted_at"] is not None:
            return None
        if job is not None and job.generation != row["analysis_generation"]:
            return None
        rev = row["metadata_revision"] + 1
        c.execute(
            "INSERT INTO metadata_revisions(asset_id, revision, schema_version, payload, job_id, created_at)"
            " VALUES (?,?,?,?,?,?)", (asset.id, rev, meta.schema_version, payload, job.id if job else None, now))
        thumb = results.get("pixels").payload.get("thumb_ref") if results.get("pixels") else None
        if meta.image is not None:
            c.execute("UPDATE assets SET metadata_revision=?, thumb_ref=COALESCE(?, thumb_ref), width=?, height=?"
                      " WHERE id=?", (rev, thumb, meta.image.display_width, meta.image.display_height, asset.id))
        else:
            c.execute("UPDATE assets SET metadata_revision=? WHERE id=?", (rev, asset.id))
        _rebuild_derived(c, asset.id, rev, meta, results)
    return rev


def _rebuild_derived(c, asset_id: str, rev: int, meta: MediaMetadata, results: dict) -> None:
    for table in ("ocr_regions", "ocr_docs", "object_observations", "decisions"):
        c.execute(f"DELETE FROM {table} WHERE asset_id=?", (asset_id,))
    c.execute("DELETE FROM ocr_doc_words WHERE asset_id=?", (asset_id,))
    c.execute("DELETE FROM ocr_doc_tri WHERE asset_id=?", (asset_id,))

    if meta.ocr is not None and meta.ocr.regions:
        parts = []
        offset = 0
        rows = []
        for r in sorted(meta.ocr.regions, key=lambda r: r.reading_order):
            start = offset
            end = start + len(r.norm_text)
            rows.append((asset_id, rev, r.region_id, r.reading_order, r.raw_text, r.norm_text, start, end,
                         json.dumps(r.polygon), r.recognizer_score))
            parts.append(r.norm_text)
            offset = end + 1  # "\n" separator (one char, so offsets survive "\n" -> " ")
        doc = "\n".join(parts)
        c.executemany(
            "INSERT INTO ocr_regions(asset_id, revision, region_id, order_idx, raw_text, norm_text,"
            " char_start, char_end, polygon, score) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        c.execute("INSERT INTO ocr_docs(asset_id, revision, norm_text) VALUES (?,?,?)", (asset_id, rev, doc))
        # FTS sees line breaks as spaces so phrases spanning OCR lines match;
        # the replacement is length-preserving, so char offsets stay valid.
        flat = doc.replace("\n", " ")
        c.execute("INSERT INTO ocr_doc_words(norm_text, asset_id) VALUES (?,?)", (flat, asset_id))
        c.execute("INSERT INTO ocr_doc_tri(norm_text, asset_id) VALUES (?,?)", (flat, asset_id))

    if meta.objects is not None:
        c.executemany(
            "INSERT INTO object_observations(asset_id, revision, obs_id, label, score, box, model)"
            " VALUES (?,?,?,?,?,?,?)",
            [(asset_id, rev, o.obs_id, o.label, o.detector_score, json.dumps(o.box), meta.objects.model)
             for o in meta.objects.observations])

    for qid, d in meta.decisions.items():
        value = None if d.value is None else (d.value if isinstance(d.value, str) else f"{d.value:.6f}")
        p_value = None
        if d.status == "complete":
            p_value = d.probs.get(d.value) if isinstance(d.value, str) else float(d.value)
        c.execute(
            "INSERT INTO decisions(asset_id, revision, question_id, dtype, value, p_value, probs, status, model)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (asset_id, rev, qid, d.dtype, value, p_value, json.dumps(d.probs, sort_keys=True), d.status, d.model))

    # Vectors: replace this asset's rows in every namespace present in the new
    # metadata. Namespaces absent from this revision keep no stale rows.
    c.execute("DELETE FROM vectors WHERE asset_id=?", (asset_id,))
    by_view = {}
    for stage in ("image_embed", "ocr_text_embed"):
        r = results.get(stage)
        if r is None or r.status not in {"complete", "cached"}:
            continue
        for v in r.payload.get("vectors", []):
            by_view[(v["namespace"], v["view_id"])] = v
    for e in meta.embeddings:
        v = by_view.get((e.namespace, e.view_id))
        if v is None:
            continue
        vec = decode_vector(v["vector"])
        if vec.shape[0] != e.dim or not np.isfinite(vec).all():
            raise ValueError(f"invalid vector for {e.namespace}/{e.view_id}")
        c.execute(
            "INSERT INTO vectors(namespace, asset_id, view_id, view_kind, region, source_refs, vector,"
            " metadata_revision) VALUES (?,?,?,?,?,?,?,?)",
            (e.namespace, asset_id, e.view_id, e.view_kind, json.dumps(e.region) if e.region else None,
             json.dumps(e.source_refs), vec.astype(np.float32).tobytes(), rev))
        c.execute("UPDATE vector_namespaces SET revision = revision + 1 WHERE namespace=?", (e.namespace,))


def active_metadata(repo: Repository, asset_id: str) -> MediaMetadata | None:
    row = repo.query_one(
        "SELECT m.payload FROM assets a JOIN metadata_revisions m ON m.asset_id=a.id AND"
        " m.revision=a.metadata_revision WHERE a.id=?", (asset_id,))
    return load_metadata(row["payload"]) if row else None


def metadata_history(repo: Repository, asset_id: str) -> list[dict]:
    return [dict(r) for r in repo.query(
        "SELECT revision, schema_version, job_id, created_at FROM metadata_revisions WHERE asset_id=?"
        " ORDER BY revision", (asset_id,))]
