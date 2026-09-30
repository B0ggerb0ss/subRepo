"""Organization use cases: incremental per-asset updates and full refreshes.

Per asset (after its metadata commit; no model inference here):
  smart memberships for that asset, duplicate check of that asset against the
  library (vectorized hash scan + verification), incremental group assignment.
Full refresh (explicit job): smart memberships for all assets, duplicate
groups recomputed, similarity groups rebuilt per scope with stable ids.
"""
from __future__ import annotations

import json
import time
import uuid

from services.library.config import LibraryConfig
from services.library.repository import Repository
from services.organize import clustering, duplicates
from services.organize.collections import refresh_smart_memberships


def _write_duplicate_groups(repo: Repository, library_id: str, groups: list[dict], full: bool) -> dict:
    now = time.time()
    existing = {}
    for r in repo.query("SELECT id, representative_asset FROM collections WHERE ctype='duplicate' AND library_id=?"
                        " AND retired_at IS NULL", (library_id,)):
        mem = {m["asset_id"] for m in repo.query("SELECT asset_id FROM memberships WHERE collection_id=?", (r["id"],))}
        existing[r["id"]] = mem
    created = updated = retired = 0
    touched = set()
    with repo.write() as c:
        for g in groups:
            members = {g["representative"], *g["members"]}
            match = max(existing.items(), key=lambda kv: len(kv[1] & members), default=(None, set()))
            gid = match[0] if match[0] and match[1] & members else None
            if gid is None:
                gid = f"col_dup_{uuid.uuid4().hex[:12]}"
                c.execute("INSERT INTO collections(id, library_id, ctype, key, suggested_label, rule,"
                          " representative_asset, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                          (gid, library_id, "duplicate", None, "Near-duplicate candidates",
                           json.dumps({"method": duplicates.METHOD}), g["representative"], now, now))
                created += 1
            else:
                c.execute("UPDATE collections SET representative_asset=?, updated_at=?, revision=revision+1 WHERE id=?",
                          (g["representative"], now, gid))
                updated += 1
            touched.add(gid)
            user_rows = {r["asset_id"]: r["state"] for r in c.execute(
                "SELECT asset_id, state FROM memberships WHERE collection_id=? AND state!='suggested'", (gid,))}
            if full:
                # Incremental updates only add; a full refresh re-derives suggestions.
                c.execute("DELETE FROM memberships WHERE collection_id=? AND state='suggested'", (gid,))
            rows = [(g["representative"], "representative", None, {})] + [
                (m, "near_duplicate", g["evidence"][m].get("ssim64"), g["evidence"][m]) for m in g["members"]]
            for aid, method, aff, ev in rows:
                if aid in user_rows:
                    continue
                c.execute("INSERT INTO memberships(collection_id, asset_id, method, affinity, affinity_kind, evidence,"
                          " state, updated_at) VALUES (?,?,?,?,?,?,'suggested',?) ON CONFLICT(collection_id, asset_id)"
                          " DO UPDATE SET method=excluded.method, affinity=excluded.affinity,"
                          " evidence=excluded.evidence, updated_at=excluded.updated_at",
                          (gid, aid, method, aff, "ssim64_to_representative" if aff is not None else "representative",
                           json.dumps(ev, sort_keys=True), now))
        if full:
            for gid in set(existing) - touched:
                has_user = c.execute("SELECT 1 FROM memberships WHERE collection_id=? AND state='confirmed'",
                                     (gid,)).fetchone()
                if not has_user:
                    c.execute("UPDATE collections SET retired_at=? WHERE id=?", (now, gid))
                    c.execute("DELETE FROM memberships WHERE collection_id=? AND state='suggested'", (gid,))
                    retired += 1
    return {"created": created, "updated": updated, "retired": retired}


def organize_asset(repo: Repository, cfg: LibraryConfig, asset_id: str) -> dict:
    lib = cfg.library_id
    out = {"smart": refresh_smart_memberships(repo, lib, [asset_id])}
    if not cfg.features.clustering:
        out["note"] = "clustering disabled"
        return out
    groups = duplicates.find_duplicate_groups(repo, lib, focus={asset_id}, library_root=cfg.library_root)
    out["duplicates"] = _write_duplicate_groups(repo, lib, groups, full=False)
    out["similarity"] = clustering.assign_incremental(repo, lib, asset_id)
    return out


def refresh_all(repo: Repository, cfg: LibraryConfig, job=None, queue=None) -> dict:
    lib = cfg.library_id

    def stage(name, status, detail=None):
        if job is not None and queue is not None:
            queue.set_stage(job.id, name, status, detail=detail)
            queue.heartbeat(job.id)

    ids = [r["id"] for r in repo.query("SELECT id FROM assets WHERE library_id=?", (lib,))]
    stage("smart", "running")
    smart = refresh_smart_memberships(repo, lib, ids)
    stage("smart", "complete", json.dumps(smart))
    out = {"smart": smart}
    if not cfg.features.clustering:
        stage("duplicates", "disabled")
        stage("similarity", "disabled")
        return out
    stage("duplicates", "running")
    groups = duplicates.find_duplicate_groups(repo, lib, library_root=cfg.library_root)
    out["duplicates"] = _write_duplicate_groups(repo, lib, groups, full=True)
    stage("duplicates", "complete", json.dumps(out["duplicates"]))
    stage("similarity", "running")
    out["similarity"] = [clustering.rebuild_scope(repo, lib, s) for s in clustering.SCOPES]
    stage("similarity", "complete", f"{sum(s['groups'] for s in out['similarity'])} group(s)")
    return out


def enqueue_refresh(queue) -> str:
    return queue.enqueue("refresh_organization", None, ["smart", "duplicates", "similarity"])
