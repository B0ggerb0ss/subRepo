# ADR-003 — Durable jobs, leases and generation fencing

**Decision.** UI actions enqueue jobs (`jobs`, `job_stages`) and return immediately. A worker (spawned process by default; thread or inline for tests/CLI) claims jobs with a lease, reports every stage's *real* status (`planned/running/cached/complete/skipped/disabled/missing/not_applicable/partial/error/cancelled`), heartbeats (which also observes cancellation), and finishes with `complete/partial/error/cancelled/superseded`.

Enqueuing analysis increments `assets.analysis_generation`; a job may activate metadata only if its generation is still current and the asset is not deleted. Older jobs still write immutable stage-cache rows (reused later) but finish as `superseded`. User annotations/overrides/memberships live in separate tables and are never written by analysis.

On startup `Library.recover()` requeues running jobs (lease lost), fails them after `job_max_attempts`, clears temp debris and *reports* orphaned originals (never deletes them). A hard cancel restarts the worker process.

**Alternatives.** Celery/Redis (unnecessary infra locally); in-request analysis (blocks UI).

**Validation.** `test_corrections_persist_through_reanalysis_and_restart` (late job superseded, exclusion survives), M2 restart test, e2e retry/cancel flow.
