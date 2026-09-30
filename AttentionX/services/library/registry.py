"""Library application service: the only API the UI and CLI call.

UI handlers never call OCR/model APIs or SQL directly; they call these
methods, which return plain typed data quickly (heavy work is enqueued).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from models.asset import Asset, ImportBatch, ImportInstance, Job
from services.library.config import LibraryConfig, get_config
from services.library.ingest import cleanup_temp_root, import_assets
from services.library.jobs import JobQueue
from services.library.metadata import active_metadata, metadata_history
from services.library.repository import Repository, StaleRevisionError


class Library:
    def __init__(self, cfg: LibraryConfig | None = None, worker_mode: str | None = "none") -> None:
        self.cfg = cfg or get_config()
        self.cfg.ensure_dirs()
        self.repo = Repository(self.cfg.db_path)
        self.repo.ensure_library(self.cfg.library_id)
        self.queue = JobQueue(self.repo, self.cfg.library_id, self.cfg.limits.job_lease_seconds,
                              self.cfg.limits.job_max_attempts)
        self._search = None
        self.supervisor = None
        self.recovery = self.recover()
        if worker_mode and worker_mode != "none":
            from services.library.worker import WorkerSupervisor

            self.supervisor = WorkerSupervisor(self.cfg, worker_mode)
            self.supervisor.start()

    # -- lifecycle ---------------------------------------------------------
    def recover(self) -> dict:
        """Startup reconciliation: stale leases back to queue, temp debris removed.

        Never deletes originals; orphaned original files are only reported.
        """
        jobs = self.queue.reconcile(all_running=True)
        removed = cleanup_temp_root(self.cfg, older_than_s=0)
        known = {r["original_ref"] for r in self.repo.query("SELECT original_ref FROM assets")}
        orphans = []
        if self.cfg.originals_root.is_dir():
            for p in self.cfg.originals_root.rglob("*"):
                if p.is_file() and str(p.relative_to(self.cfg.library_root)) not in known:
                    orphans.append(str(p.relative_to(self.cfg.library_root)))
        from services.analyze.vectors_registry import ensure_namespaces

        ensure_namespaces(self.repo, self.cfg)
        return {"jobs": jobs, "temp_removed": removed, "orphan_originals": orphans}

    def close(self) -> None:
        if self.supervisor is not None:
            self.supervisor.stop()
        self.repo.close()

    # -- import ------------------------------------------------------------
    def import_files(self, paths: list[str | Path], display_names: dict[str, str] | None = None,
                     source_note: str | None = None) -> ImportBatch:
        return import_assets([Path(p) for p in paths], self.repo, self.cfg, self.queue, "files",
                             display_names=display_names, source_note=source_note)

    def import_folder(self, folder: str | Path, source_note: str | None = None) -> ImportBatch:
        return import_assets(Path(folder), self.repo, self.cfg, self.queue, "folder", source_note=source_note)

    # -- browse ------------------------------------------------------------
    def list_assets(self, offset: int = 0, limit: int = 60, include_deleted: bool = False) -> list[dict]:
        rows = self.repo.query(
            "SELECT a.*, (SELECT original_filename FROM import_instances i WHERE i.asset_id=a.id"
            " ORDER BY imported_at LIMIT 1) AS filename FROM assets a WHERE library_id=?"
            + ("" if include_deleted else " AND deleted_at IS NULL")
            + " ORDER BY created_at DESC, id LIMIT ? OFFSET ?", (self.cfg.library_id, limit, offset))
        from services.search.service import asset_status

        return [dict(Asset.from_row(r).model_dump(), filename=r["filename"], status=asset_status(self.repo, r["id"]))
                for r in rows]

    def count_assets(self) -> int:
        return self.repo.query_one("SELECT COUNT(*) n FROM assets WHERE library_id=? AND deleted_at IS NULL",
                                   (self.cfg.library_id,))["n"]

    def get_asset(self, asset_id: str) -> Asset | None:
        row = self.repo.query_one("SELECT * FROM assets WHERE id=?", (asset_id,))
        return Asset.from_row(row) if row else None

    def asset_detail(self, asset_id: str) -> dict | None:
        asset = self.get_asset(asset_id)
        if asset is None:
            return None
        imports = [ImportInstance.from_row(r).model_dump() for r in self.repo.query(
            "SELECT * FROM import_instances WHERE asset_id=? ORDER BY imported_at", (asset_id,))]
        meta = active_metadata(self.repo, asset_id)
        ann = self.annotations(asset_id)
        jobs = [j.model_dump() for j in self.jobs_for(asset_id)]
        overrides = {r["question_id"]: r["value"] for r in self.repo.query(
            "SELECT question_id, value FROM metadata_overrides WHERE asset_id=?", (asset_id,))}
        memberships = [dict(r) for r in self.repo.query(
            "SELECT c.id, c.ctype, COALESCE(c.user_label, c.suggested_label) AS label, m.state, m.method,"
            " m.affinity, m.affinity_kind FROM memberships m JOIN collections c ON c.id=m.collection_id"
            " WHERE m.asset_id=? AND c.retired_at IS NULL", (asset_id,))]
        from services.search.service import asset_status

        return {
            "asset": asset.model_dump(), "imports": imports,
            "metadata": meta.model_dump(mode="json") if meta else None,
            "history": metadata_history(self.repo, asset_id), "annotations": ann, "jobs": jobs,
            "overrides": overrides, "memberships": memberships, "status": asset_status(self.repo, asset_id),
        }

    def path_of(self, ref: str | None) -> Path | None:
        """Resolve a managed relative ref inside the library root (containment enforced)."""
        if not ref:
            return None
        p = (self.cfg.library_root / ref).resolve()
        root = self.cfg.library_root.resolve()
        if root not in p.parents:
            raise ValueError("reference escapes the library root")
        return p if p.is_file() else None

    # -- annotations ---------------------------------------------------------
    def annotations(self, asset_id: str) -> dict:
        r = self.repo.query_one("SELECT * FROM user_annotations WHERE asset_id=?", (asset_id,))
        if r is None:
            return {"title": "", "notes": "", "tags": [], "revision": 0}
        return {"title": r["title"], "notes": r["notes"], "tags": json.loads(r["tags"]), "revision": r["revision"]}

    def set_annotations(self, asset_id: str, expected_revision: int, title: str | None = None,
                        notes: str | None = None, tags: list[str] | None = None, actor: str = "local-user") -> dict:
        """Optimistic-concurrency update. Touches no analysis stage."""
        now = time.time()
        with self.repo.write() as c:
            r = c.execute("SELECT * FROM user_annotations WHERE asset_id=?", (asset_id,)).fetchone()
            if r is None:
                raise KeyError(asset_id)
            if r["revision"] != expected_revision:
                raise StaleRevisionError(f"annotations changed (revision {r['revision']} != {expected_revision})")
            new = {
                "title": r["title"] if title is None else title.strip()[:500],
                "notes": r["notes"] if notes is None else notes.strip()[:10000],
                "tags": json.loads(r["tags"]) if tags is None else sorted({t.strip()[:64] for t in tags if t.strip()}),
            }
            prev = {"title": r["title"], "notes": r["notes"], "tags": json.loads(r["tags"])}
            c.execute("UPDATE user_annotations SET title=?, notes=?, tags=?, revision=revision+1, updated_at=?"
                      " WHERE asset_id=?", (new["title"], new["notes"], json.dumps(new["tags"]), now, asset_id))
            c.execute("DELETE FROM annotation_fts WHERE asset_id=?", (asset_id,))
            from services.analyze.ocr import normalize_for_search

            body = normalize_for_search(" ".join([new["title"], new["notes"], " ".join(new["tags"])]))
            if body:
                c.execute("INSERT INTO annotation_fts(body, asset_id) VALUES (?,?)", (body, asset_id))
            c.execute(
                "INSERT INTO corrections(id, actor, at, target_type, target_id, field, previous, new, scope, revision)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"cor_{uuid.uuid4().hex[:16]}", actor, now, "asset", asset_id, "annotations",
                 json.dumps(prev), json.dumps(new), "asset", expected_revision + 1))
        return self.annotations(asset_id)

    # -- lifecycle of assets ---------------------------------------------------
    def delete_asset(self, asset_id: str) -> None:
        """Tombstone: immediately ineligible for search; the managed original copy
        is retained (the user's own source file is never touched)."""
        now = time.time()
        with self.repo.write() as c:
            c.execute("UPDATE assets SET deleted_at=?, analysis_generation=analysis_generation+1 WHERE id=?",
                      (now, asset_id))
            for t in ("ocr_regions", "ocr_docs", "object_observations", "decisions", "vectors"):
                c.execute(f"DELETE FROM {t} WHERE asset_id=?", (asset_id,))
            c.execute("DELETE FROM ocr_doc_words WHERE asset_id=?", (asset_id,))
            c.execute("DELETE FROM ocr_doc_tri WHERE asset_id=?", (asset_id,))
            c.execute("DELETE FROM annotation_fts WHERE asset_id=?", (asset_id,))
            c.execute("UPDATE jobs SET cancel_requested=1 WHERE asset_id=? AND status IN ('queued','running')",
                      (asset_id,))
            c.execute("UPDATE jobs SET status='cancelled' WHERE asset_id=? AND status='queued'", (asset_id,))

    def restore_asset(self, asset_id: str) -> str | None:
        with self.repo.write() as c:
            c.execute("UPDATE assets SET deleted_at=NULL WHERE id=?", (asset_id,))
        return self.retry_asset(asset_id)

    def retry_asset(self, asset_id: str) -> str | None:
        """Re-run analysis; unchanged stages are served from cache."""
        from services.analyze.pipeline import planned_stages

        active = self.queue.active_job_for(asset_id)
        if active:
            return active
        return self.queue.enqueue("analyze_image", asset_id, planned_stages(), {"reset_providers": True})

    def retry_failed(self) -> list[str]:
        from services.search.service import asset_status

        ids = [r["id"] for r in self.repo.query("SELECT id FROM assets WHERE library_id=? AND deleted_at IS NULL",
                                                (self.cfg.library_id,))]
        return [j for aid in ids if asset_status(self.repo, aid) in {"partial", "error"}
                for j in [self.retry_asset(aid)] if j]

    # -- jobs --------------------------------------------------------------
    def jobs_for(self, asset_id: str) -> list[Job]:
        ids = [r["id"] for r in self.repo.query("SELECT id FROM jobs WHERE asset_id=? ORDER BY created_at DESC LIMIT 5",
                                               (asset_id,))]
        return [j for j in (self.queue.get(i) for i in ids) if j]

    def cancel_job(self, job_id: str) -> bool:
        return self.queue.request_cancel(job_id)

    def job_summary(self) -> dict:
        return self.queue.counts()

    # -- search ------------------------------------------------------------
    @property
    def search_service(self):
        if self._search is None:
            from services.search.service import SearchService

            self._search = SearchService(self.repo, self.cfg)
        return self._search

    def search(self, query: str, limit: int = 40, offset: int = 0, collapse_duplicates: bool = True,
               channels: list[str] | None = None):
        from models.search import SearchRequest

        req = SearchRequest(query=query, library_id=self.cfg.library_id, limit=limit, offset=offset,
                            collapse_duplicates=collapse_duplicates,
                            **({"channels": channels} if channels else {}))
        return self.search_service.search(req)

    def find_similar(self, asset_id: str, crop=None, query: str = "", limit: int = 40):
        return self.search_service.find_similar(asset_id, crop=crop, query=query, limit=limit)

    def capabilities(self) -> list[dict]:
        from services.analyze.providers import get_providers

        return [a.__dict__ for a in get_providers(self.cfg).availability()]

    # -- organization & corrections --------------------------------------------
    def collections(self, ctype: str | None = None, parent_id: str | None = None, with_members: bool = False,
                    include_hidden: bool = False):
        from services.organize.overrides import list_collections

        return list_collections(self.repo, self.cfg.library_id, ctype=ctype, parent_id=parent_id,
                                include_hidden=include_hidden, with_members=with_members)

    def collection(self, collection_id: str):
        from services.organize.overrides import list_collections, resolve_collection_id

        cid = resolve_collection_id(self.repo, collection_id)
        if cid is None:
            return None
        return next((c for c in list_collections(self.repo, self.cfg.library_id, include_hidden=True,
                                                 with_members=True) if c.id == cid), None)

    def correct(self, command: dict, expected_revision: int | None = None, actor: str = "local-user"):
        from models.collections import CorrectionCommand
        from services.organize.overrides import apply_correction

        return apply_correction(self.repo, self.cfg.library_id, CorrectionCommand(**command), expected_revision, actor)

    def refresh_organization(self, inline: bool = False):
        """Rebuild smart sets, duplicate candidates and similarity groups."""
        from services.organize.service import enqueue_refresh, refresh_all

        if inline:
            return refresh_all(self.repo, self.cfg)
        return enqueue_refresh(self.queue)

    def corrections(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.repo.query("SELECT * FROM corrections ORDER BY at DESC LIMIT ?", (limit,))]

    # -- export --------------------------------------------------------------
    def export_snapshot(self, asset_ids: list[str] | None = None, collection_ids: list[str] | None = None,
                        **options):
        from services.library.export import ExportOptions, export_library_snapshot

        return export_library_snapshot(self.repo, self.cfg, asset_ids, collection_ids, ExportOptions(**options))
