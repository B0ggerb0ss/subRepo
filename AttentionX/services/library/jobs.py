"""Durable job queue: leases, stage progress, cancellation, fencing, recovery.

Status progress is real: each planned stage is a row whose status moves
planned -> running -> {complete, cached, skipped, missing, partial, error,
cancelled}. The UI shows these rows; there is no synthetic percentage.

Fencing: enqueueing analysis bumps ``assets.analysis_generation`` and stamps
the job with it. Only a job whose generation still matches may activate a
metadata revision; an older job finishes as ``superseded`` (its immutable
stage outputs stay in the cache and are reused).
"""
from __future__ import annotations

import json
import time
import uuid

from models.asset import Job
from services.library.repository import Repository

TERMINAL = {"complete", "partial", "error", "cancelled", "superseded"}


class JobCancelled(Exception):
    pass


class JobQueue:
    def __init__(self, repo: Repository, library_id: str, lease_seconds: int = 300,
                 max_attempts: int = 3) -> None:
        self.repo = repo
        self.library_id = library_id
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    # -- enqueue ---------------------------------------------------------
    def enqueue(self, kind: str, asset_id: str | None, stages: list[str],
                params: dict | None = None, conn=None) -> str:
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        now = time.time()

        def _do(c):
            gen = 0
            if asset_id is not None and kind == "analyze_image":
                c.execute("UPDATE assets SET analysis_generation = analysis_generation + 1 WHERE id=?",
                          (asset_id,))
                gen = c.execute("SELECT analysis_generation FROM assets WHERE id=?",
                                (asset_id,)).fetchone()[0]
            c.execute(
                "INSERT INTO jobs(id, library_id, asset_id, kind, status, generation, params,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (job_id, self.library_id, asset_id, kind, "queued", gen,
                 json.dumps(params or {}, sort_keys=True), now, now),
            )
            c.executemany(
                "INSERT INTO job_stages(job_id, stage, seq, status) VALUES (?,?,?,'planned')",
                [(job_id, s, i) for i, s in enumerate(stages)],
            )

        if conn is not None:
            _do(conn)
        else:
            with self.repo.write() as c:
                _do(c)
        return job_id

    def active_job_for(self, asset_id: str) -> str | None:
        row = self.repo.query_one(
            "SELECT id FROM jobs WHERE asset_id=? AND status IN ('queued','running')"
            " ORDER BY created_at DESC LIMIT 1", (asset_id,))
        return row["id"] if row else None

    # -- worker side -----------------------------------------------------
    def claim(self, worker_id: str) -> Job | None:
        now = time.time()
        with self.repo.write() as c:
            row = c.execute(
                "SELECT id FROM jobs WHERE status='queued' AND library_id=?"
                " ORDER BY created_at LIMIT 1", (self.library_id,)).fetchone()
            if row is None:
                return None
            c.execute(
                "UPDATE jobs SET status='running', lease_owner=?, lease_expires=?,"
                " attempts=attempts+1, updated_at=? WHERE id=?",
                (worker_id, now + self.lease_seconds, now, row["id"]),
            )
        return self.get(row["id"])

    def heartbeat(self, job_id: str) -> None:
        """Extend the lease; raise JobCancelled if cancellation was requested."""
        now = time.time()
        with self.repo.write() as c:
            c.execute("UPDATE jobs SET lease_expires=?, updated_at=? WHERE id=?",
                      (now + self.lease_seconds, now, job_id))
            row = c.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row and row["cancel_requested"]:
            raise JobCancelled(job_id)

    def set_stage(self, job_id: str, stage: str, status: str, detail: str | None = None,
                  cache_key: str | None = None) -> None:
        now = time.time()
        with self.repo.write() as c:
            if status == "running":
                c.execute("UPDATE job_stages SET status=?, started_at=?, detail=? WHERE job_id=? AND stage=?",
                          (status, now, detail, job_id, stage))
            else:
                c.execute(
                    "UPDATE job_stages SET status=?, finished_at=?, detail=?, cache_key=COALESCE(?, cache_key)"
                    " WHERE job_id=? AND stage=?",
                    (status, now, detail, cache_key, job_id, stage))
            c.execute("UPDATE jobs SET updated_at=? WHERE id=?", (now, job_id))

    def finish(self, job_id: str, status: str, error_code: str | None = None,
               error_message: str | None = None) -> None:
        assert status in TERMINAL
        now = time.time()
        with self.repo.write() as c:
            c.execute(
                "UPDATE jobs SET status=?, error_code=?, error_message=?, lease_owner=NULL,"
                " lease_expires=NULL, updated_at=? WHERE id=?",
                (status, error_code, error_message, now, job_id))
            if status in {"cancelled", "error", "superseded"}:
                c.execute(
                    "UPDATE job_stages SET status='cancelled', finished_at=? WHERE job_id=?"
                    " AND status IN ('planned','running')", (now, job_id))

    # -- control ---------------------------------------------------------
    def request_cancel(self, job_id: str) -> bool:
        with self.repo.write() as c:
            row = c.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["status"] in TERMINAL:
                return False
            if row["status"] == "queued":
                c.execute("UPDATE jobs SET status='cancelled', cancel_requested=1, updated_at=? WHERE id=?",
                          (time.time(), job_id))
                c.execute("UPDATE job_stages SET status='cancelled' WHERE job_id=? AND status='planned'",
                          (job_id,))
            else:
                c.execute("UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?",
                          (time.time(), job_id))
        return True

    def is_current(self, job: Job) -> bool:
        """True while this job's generation is still the asset's newest analysis."""
        if job.asset_id is None:
            return True
        row = self.repo.query_one("SELECT analysis_generation, deleted_at FROM assets WHERE id=?",
                                  (job.asset_id,))
        return bool(row) and row["deleted_at"] is None and row["analysis_generation"] == job.generation

    def reconcile(self, now: float | None = None, all_running: bool = False) -> dict:
        """Recover after a crash/restart.

        Running jobs whose lease expired (or, with ``all_running``, every
        running job because no worker survived the restart) go back to the
        queue until ``max_attempts`` is spent; then they fail visibly.
        """
        now = now or time.time()
        requeued = failed = 0
        with self.repo.write() as c:
            rows = c.execute(
                "SELECT id, attempts, cancel_requested FROM jobs WHERE status='running'"
                + ("" if all_running else " AND (lease_expires IS NULL OR lease_expires < ?)"),
                () if all_running else (now,)).fetchall()
            for r in rows:
                if r["cancel_requested"]:
                    c.execute("UPDATE jobs SET status='cancelled', lease_owner=NULL, updated_at=? WHERE id=?",
                              (now, r["id"]))
                    c.execute("UPDATE job_stages SET status='cancelled' WHERE job_id=? AND status IN ('planned','running')",
                              (r["id"],))
                elif r["attempts"] >= self.max_attempts:
                    c.execute(
                        "UPDATE jobs SET status='error', error_code='lease_expired', error_message=?,"
                        " lease_owner=NULL, updated_at=? WHERE id=?",
                        (f"worker lost {r['attempts']} times; retry manually", now, r["id"]))
                    c.execute("UPDATE job_stages SET status='error' WHERE job_id=? AND status='running'",
                              (r["id"],))
                    failed += 1
                else:
                    c.execute("UPDATE jobs SET status='queued', lease_owner=NULL, lease_expires=NULL,"
                              " updated_at=? WHERE id=?", (now, r["id"]))
                    c.execute("UPDATE job_stages SET status='planned', started_at=NULL WHERE job_id=?"
                              " AND status='running'", (r["id"],))
                    requeued += 1
        return {"requeued": requeued, "failed": failed}

    # -- queries ---------------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        row = self.repo.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if row is None:
            return None
        stages = self.repo.query("SELECT * FROM job_stages WHERE job_id=? ORDER BY seq", (job_id,))
        return Job.from_row(row, stages)

    def list(self, statuses: tuple[str, ...] | None = None, limit: int = 100) -> list[Job]:
        sql = "SELECT * FROM jobs WHERE library_id=?"
        params: list = [self.library_id]
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            params += list(statuses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        out = []
        for row in self.repo.query(sql, tuple(params)):
            stages = self.repo.query("SELECT * FROM job_stages WHERE job_id=? ORDER BY seq", (row["id"],))
            out.append(Job.from_row(row, stages))
        return out

    def counts(self) -> dict[str, int]:
        rows = self.repo.query("SELECT status, COUNT(*) n FROM jobs WHERE library_id=? GROUP BY status",
                               (self.library_id,))
        return {r["status"]: r["n"] for r in rows}
