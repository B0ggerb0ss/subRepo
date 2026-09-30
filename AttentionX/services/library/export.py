"""Deterministic, versioned library/collection snapshots.

The JSON is canonical (sorted keys, fixed separators, no wall-clock fields
unless requested), so exporting the same state twice yields identical bytes.
Privacy defaults: no original filenames, no folder path hints, no EXIF-derived
camera fields and no user notes unless the caller opts in. The file is written
to the managed exports root via temp file + atomic rename.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from models.media_metadata import load_metadata, project_to_v1
from services.library.config import LibraryConfig
from services.library.repository import Repository

SNAPSHOT_VERSION = "AttentionXLibrarySnapshot/1"


class ExportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_filenames: bool = False
    include_path_hints: bool = False
    include_notes: bool = False
    include_camera_exif: bool = False
    include_corrections: bool = True
    include_generated_at: bool = False
    metadata_format: str = "1.1"      # "1.1" | "1.0-projection" | "none"


class ManagedExportRef(BaseModel):
    export_id: str
    relative_path: str
    sha256: str
    bytes: int
    assets: int
    collections: int


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def build_snapshot(repo: Repository, cfg: LibraryConfig, asset_ids: list[str] | None = None,
                   collection_ids: list[str] | None = None, options: ExportOptions | None = None) -> dict:
    opt = options or ExportOptions()
    lib = cfg.library_id
    if collection_ids:
        ids = set()
        for cid in collection_ids:
            ids |= {r["asset_id"] for r in repo.query(
                "SELECT asset_id FROM memberships WHERE collection_id=? AND state!='excluded'", (cid,))}
        ids = sorted(ids | set(asset_ids or []))
    elif asset_ids is not None:
        ids = sorted(set(asset_ids))
    else:
        ids = [r["id"] for r in repo.query("SELECT id FROM assets WHERE library_id=? AND deleted_at IS NULL ORDER BY id",
                                           (lib,))]
    assets = []
    for aid in ids:
        a = repo.query_one("SELECT * FROM assets WHERE id=? AND deleted_at IS NULL", (aid,))
        if a is None:
            continue
        entry = {"asset_id": aid, "content_hash": a["content_hash"], "mime": a["mime"], "byte_size": a["byte_size"],
                 "width": a["width"], "height": a["height"], "metadata_revision": a["metadata_revision"]}
        imports = repo.query("SELECT original_filename, path_hint, imported_at FROM import_instances WHERE asset_id=?"
                             " ORDER BY imported_at, id", (aid,))
        entry["import_count"] = len(imports)
        if opt.include_filenames:
            entry["filenames"] = [i["original_filename"] for i in imports]
        if opt.include_path_hints:
            entry["path_hints"] = [i["path_hint"] for i in imports if i["path_hint"]]
        ann = repo.query_one("SELECT title, notes, tags, revision FROM user_annotations WHERE asset_id=?", (aid,))
        if ann:
            entry["annotations"] = {"title": ann["title"], "tags": json.loads(ann["tags"]), "revision": ann["revision"]}
            if opt.include_notes:
                entry["annotations"]["notes"] = ann["notes"]
        entry["overrides"] = {r["question_id"]: r["value"] for r in repo.query(
            "SELECT question_id, value FROM metadata_overrides WHERE asset_id=? ORDER BY question_id", (aid,))}
        m = repo.query_one("SELECT payload FROM metadata_revisions WHERE asset_id=? AND revision=?",
                           (aid, a["metadata_revision"]))
        if m and opt.metadata_format != "none":
            meta = load_metadata(m["payload"])
            if opt.metadata_format == "1.0-projection":
                doc = project_to_v1(meta)
            else:
                doc = json.loads(meta.model_dump_json())
                doc.pop("embeddings", None)  # vectors are not exported; refs only below
                doc["embedding_refs"] = [{"namespace": e.namespace, "view_id": e.view_id, "dim": e.dim}
                                         for e in meta.embeddings]
            if not opt.include_camera_exif and doc.get("image"):
                img = doc["image"].get("value", doc["image"])
                if isinstance(img, dict):
                    img.pop("camera_exif", None)
            entry["metadata"] = doc
        assets.append(entry)
    present = {a["asset_id"] for a in assets}
    cols = []
    crow = repo.query("SELECT * FROM collections WHERE library_id=? AND retired_at IS NULL ORDER BY id", (lib,))
    for c in crow:
        if collection_ids and c["id"] not in collection_ids:
            continue
        members = [{"asset_id": r["asset_id"], "state": r["state"], "method": r["method"],
                    "affinity": r["affinity"], "affinity_kind": r["affinity_kind"]}
                   for r in repo.query("SELECT * FROM memberships WHERE collection_id=? ORDER BY asset_id", (c["id"],))
                   if r["asset_id"] in present]
        if not members and not collection_ids:
            continue
        cols.append({"id": c["id"], "type": c["ctype"], "key": c["key"], "parent_id": c["parent_id"],
                     "label": c["user_label"] or c["suggested_label"], "suggested_label": c["suggested_label"],
                     "user_label": c["user_label"], "pinned": bool(c["pinned"]), "revision": c["revision"],
                     "representative_asset": c["representative_asset"], "members": members})
    snap = {"snapshot_version": SNAPSHOT_VERSION, "library_id": lib, "metadata_format": opt.metadata_format,
            "options": opt.model_dump(), "assets": assets, "collections": cols}
    if opt.include_corrections:
        snap["corrections"] = [
            {k: r[k] for k in ("id", "actor", "target_type", "target_id", "field", "previous", "new", "scope", "revision")}
            for r in repo.query("SELECT * FROM corrections ORDER BY at, id")
            if r["target_type"] != "asset" or r["target_id"] in present]
    if opt.include_generated_at:
        snap["generated_at"] = datetime.now(timezone.utc).isoformat()
    snap["content_sha256"] = hashlib.sha256(_canonical({k: v for k, v in snap.items() if k != "generated_at"})).hexdigest()
    return snap


def export_library_snapshot(repo: Repository, cfg: LibraryConfig, asset_ids: list[str] | None = None,
                            collection_ids: list[str] | None = None,
                            options: ExportOptions | None = None) -> ManagedExportRef:
    snap = build_snapshot(repo, cfg, asset_ids, collection_ids, options)
    data = _canonical(snap)
    export_id = f"exp_{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}_{uuid.uuid4().hex[:6]}"
    cfg.exports_root.mkdir(parents=True, exist_ok=True)
    out = cfg.exports_root / f"{export_id}.json"
    tmp = out.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(out)
    return ManagedExportRef(export_id=export_id, relative_path=str(out.relative_to(cfg.library_root)),
                            sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), assets=len(snap["assets"]),
                            collections=len(snap["collections"]))
