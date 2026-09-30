"""Background analysis worker.

Modes (``ATTENTIONX_WORKER``):
- ``process`` (default for the app): a spawned process owns the warmed
  providers; the UI process never runs model inference for analysis. A hard
  cancel can terminate and restart it.
- ``thread``: same loop in a daemon thread (useful where spawning is costly).
- ``none``: no background worker (CLI/tests call ``Worker.run_until_idle``).
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import threading
import time
import uuid
from pathlib import Path

from models.asset import Asset
from services.analyze.pipeline import Ctx, analyze_asset
from services.analyze.providers import get_providers
from services.library.config import LibraryConfig
from services.library.jobs import JobCancelled, JobQueue
from services.library.repository import Repository

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, cfg: LibraryConfig, repo: Repository | None = None, worker_id: str | None = None) -> None:
        self.cfg = cfg
        self.repo = repo or Repository(cfg.db_path)
        self.queue = JobQueue(self.repo, cfg.library_id, cfg.limits.job_lease_seconds, cfg.limits.job_max_attempts)
        self.providers = get_providers(cfg)
        self.worker_id = worker_id or f"w_{os.getpid()}_{uuid.uuid4().hex[:6]}"

    def run_once(self) -> str | None:
        job = self.queue.claim(self.worker_id)
        if job is None:
            return None
        try:
            if job.kind == "analyze_image":
                status = self._analyze(job)
            elif job.kind == "refresh_organization":
                from services.organize.service import refresh_all

                refresh_all(self.repo, self.cfg, job=job, queue=self.queue)
                status = "complete"
            else:
                self.queue.finish(job.id, "error", "unknown_job_kind", f"unknown job kind {job.kind}")
                return "error"
        except JobCancelled:
            self.queue.finish(job.id, "cancelled")
            return "cancelled"
        except Exception as e:
            log.exception("job %s failed", job.id)
            self.queue.finish(job.id, "error", "exception", f"{type(e).__name__}")
            return "error"
        err = None
        if status == "error":
            j = self.queue.get(job.id)
            err = next((s.detail for s in j.stages if s.status == "error"), None) if j else None
        self.queue.finish(job.id, status, "stage_error" if status == "error" else None, err)
        return status

    def _analyze(self, job) -> str:
        if job.params.get("reset_providers"):
            # A retry after provisioning must re-probe providers that failed before.
            self.providers.reset_errors()
        row = self.repo.query_one("SELECT * FROM assets WHERE id=?", (job.asset_id,))
        if row is None or row["deleted_at"] is not None:
            return "superseded"
        ctx = Ctx(cfg=self.cfg, repo=self.repo, providers=self.providers, asset=Asset.from_row(row),
                  job=job, queue=self.queue)
        status, _ = analyze_asset(ctx)
        return status

    def run_until_idle(self, max_jobs: int | None = None) -> list[str]:
        out = []
        while max_jobs is None or len(out) < max_jobs:
            s = self.run_once()
            if s is None:
                break
            out.append(s)
        return out

    def serve(self, stop: threading.Event | None = None, poll_s: float = 0.5) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                if self.run_once() is None:
                    stop.wait(poll_s)
            except Exception:
                log.exception("worker loop error")
                stop.wait(poll_s)


def _process_main(library_root: str, stop_file: str) -> None:
    from services.library.config import config_from_env

    cfg = config_from_env(library_root)
    worker = Worker(cfg)
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            if Path(stop_file).exists():
                stop.set()
            time.sleep(0.5)

    threading.Thread(target=watch, daemon=True).start()
    worker.serve(stop)


class WorkerSupervisor:
    """Owns the background worker for the app process."""

    def __init__(self, cfg: LibraryConfig, mode: str | None = None) -> None:
        self.cfg = cfg
        self.mode = mode or os.getenv("ATTENTIONX_WORKER", "process")
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._proc: mp.Process | None = None
        self._stop_file = cfg.temp_root / f"worker-stop-{os.getpid()}"

    def start(self) -> None:
        if self.mode == "none":
            return
        if self.mode == "thread":
            w = Worker(self.cfg)
            self._thread = threading.Thread(target=w.serve, args=(self._stop,), daemon=True, name="ax-worker")
            self._thread.start()
            return
        self._stop_file.unlink(missing_ok=True)
        ctx = mp.get_context("spawn")
        self._proc = ctx.Process(target=_process_main, args=(str(self.cfg.library_root), str(self._stop_file)),
                                 daemon=True, name="ax-worker")
        self._proc.start()

    def alive(self) -> bool:
        if self._proc is not None:
            return self._proc.is_alive()
        if self._thread is not None:
            return self._thread.is_alive()
        return False

    def hard_restart(self) -> None:
        """Terminate a stuck worker (e.g. hung native call) and start a fresh one."""
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(10)
            if self._proc.is_alive():
                self._proc.kill()
        repo = Repository(self.cfg.db_path)
        JobQueue(repo, self.cfg.library_id).reconcile(all_running=True)
        repo.close()
        self.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            self._stop_file.parent.mkdir(parents=True, exist_ok=True)
            self._stop_file.touch()
            self._proc.join(5)
            if self._proc.is_alive():
                self._proc.terminate()
