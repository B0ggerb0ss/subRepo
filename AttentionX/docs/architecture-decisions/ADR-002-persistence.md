# ADR-002 — SQLite is the single authority; sidecars are exports

**Status:** accepted

**Decision.** One SQLite database per library (`library.sqlite3`, WAL, `foreign_keys=ON`) holds assets, import instances, jobs/stages, immutable metadata revisions (+ active pointer), annotations, overrides, corrections, collections/memberships, derived search rows (OCR regions/docs + FTS5 `unicode61` and `trigram`), object/decision rows and **vectors as float32 BLOBs** with namespace manifests. Stage outputs are content-addressed rows in `stage_cache`. Originals are immutable, read-only, content-addressed files; thumbnails/previews are derived files written via temp + atomic rename. JSON sidecars exist only as versioned exports (`AttentionXLibrarySnapshot/1`).

**Why vectors in SQLite.** Activation of a metadata revision and its vectors happens in one transaction, so readers can never see a partially written vector snapshot and deletes remove eligibility atomically. 10k assets × ~5 views × 512 × 4 B ≈ 100 MB — acceptable (measured: `reports/benchmark.json`).

**Concurrency.** One serialized writer per process (`BEGIN IMMEDIATE`), short-lived per-thread readers, `busy_timeout` for the UI↔worker process pair. FTS5 + trigram availability is checked at startup (`check_fts5`).

**Alternatives.** Separate vector service / FAISS files (extra consistency protocol, not justified at 10k); JSON sidecars as authority (two writers that can disagree).

**Consequences.** Hosted multi-user would need a server DB + ownership filtering (not in scope). Migrations are forward-only (`PRAGMA user_version`); the unreleased v1 schema was edited once before release (job-stage statuses).

**Validation.** `tests/integration/test_m2_ocr_search_slice.py` (restart without re-OCR), `test_m3_m6…` (delete removes eligibility; export determinism).
