"""SQLite persistence: connections, migrations and bounded transactions.

The database is the single authority for assets, import records, the active
metadata revision, jobs, annotations, derived search rows, vectors and index
manifests. Sidecar JSON is only ever an export.

Concurrency model: WAL journal; one serialized writer per process (a lock
around ``write()``) and short-lived reader connections. Cross-process writers
(UI process and worker process) are serialized by SQLite itself with a busy
timeout; all writes are short transactions.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 6

_MIGRATIONS: dict[int, str] = {
    1: """
CREATE TABLE libraries (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE assets (
  id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL REFERENCES libraries(id),
  content_hash TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('image','video')),
  mime TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  width INTEGER,
  height INTEGER,
  original_ref TEXT NOT NULL,
  thumb_ref TEXT,
  created_at REAL NOT NULL,
  deleted_at REAL,
  metadata_revision INTEGER NOT NULL DEFAULT 0,
  analysis_generation INTEGER NOT NULL DEFAULT 0,
  UNIQUE (library_id, content_hash)
);
CREATE INDEX idx_assets_library ON assets(library_id, deleted_at);

CREATE TABLE import_batches (
  id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL REFERENCES libraries(id),
  created_at REAL NOT NULL,
  source_kind TEXT NOT NULL,
  total INTEGER NOT NULL DEFAULT 0,
  admitted INTEGER NOT NULL DEFAULT 0,
  reused INTEGER NOT NULL DEFAULT 0,
  rejected INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL
);

CREATE TABLE import_instances (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL REFERENCES assets(id),
  batch_id TEXT NOT NULL REFERENCES import_batches(id),
  library_id TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  path_hint TEXT,
  source_note TEXT,
  imported_at REAL NOT NULL
);
CREATE INDEX idx_import_asset ON import_instances(asset_id);

CREATE TABLE import_rejections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL REFERENCES import_batches(id),
  filename TEXT NOT NULL,
  code TEXT NOT NULL,
  message TEXT NOT NULL
);

CREATE TABLE metadata_revisions (
  asset_id TEXT NOT NULL REFERENCES assets(id),
  revision INTEGER NOT NULL,
  schema_version TEXT NOT NULL,
  payload TEXT NOT NULL,
  job_id TEXT,
  created_at REAL NOT NULL,
  PRIMARY KEY (asset_id, revision)
);

CREATE TABLE stage_cache (
  cache_key TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  stage_version TEXT NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at REAL NOT NULL,
  hits INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_stage_cache_hash ON stage_cache(content_hash, stage);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  asset_id TEXT REFERENCES assets(id),
  kind TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN
    ('queued','running','complete','partial','error','cancelled','superseded')),
  generation INTEGER NOT NULL DEFAULT 0,
  params TEXT NOT NULL DEFAULT '{}',
  attempts INTEGER NOT NULL DEFAULT 0,
  lease_owner TEXT,
  lease_expires REAL,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  error_code TEXT,
  error_message TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX idx_jobs_status ON jobs(status, created_at);
CREATE INDEX idx_jobs_asset ON jobs(asset_id);

CREATE TABLE job_stages (
  job_id TEXT NOT NULL REFERENCES jobs(id),
  stage TEXT NOT NULL,
  seq INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN
    ('planned','running','cached','complete','skipped','disabled','missing','not_applicable',
     'partial','error','cancelled')),
  cache_key TEXT,
  detail TEXT,
  started_at REAL,
  finished_at REAL,
  PRIMARY KEY (job_id, stage)
);

CREATE TABLE user_annotations (
  asset_id TEXT PRIMARY KEY REFERENCES assets(id),
  title TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '[]',
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);

-- Derived search rows: rebuilt from the active metadata revision in the same
-- transaction that activates it.
CREATE TABLE ocr_regions (
  asset_id TEXT NOT NULL REFERENCES assets(id),
  revision INTEGER NOT NULL,
  region_id TEXT NOT NULL,
  order_idx INTEGER NOT NULL,
  raw_text TEXT NOT NULL,
  norm_text TEXT NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  polygon TEXT NOT NULL,
  score REAL,
  PRIMARY KEY (asset_id, region_id)
);

CREATE TABLE ocr_docs (
  asset_id TEXT PRIMARY KEY REFERENCES assets(id),
  revision INTEGER NOT NULL,
  norm_text TEXT NOT NULL
);

CREATE VIRTUAL TABLE ocr_doc_words USING fts5(
  norm_text, asset_id UNINDEXED,
  tokenize = "unicode61 remove_diacritics 2 tokenchars '+#'"
);
CREATE VIRTUAL TABLE ocr_doc_tri USING fts5(
  norm_text, asset_id UNINDEXED,
  tokenize = 'trigram'
);
CREATE VIRTUAL TABLE annotation_fts USING fts5(
  body, asset_id UNINDEXED,
  tokenize = "unicode61 remove_diacritics 2 tokenchars '+#'"
);

CREATE TABLE schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
""",
    2: """
CREATE TABLE vector_namespaces (
  namespace TEXT PRIMARY KEY,
  space TEXT NOT NULL,
  model TEXT NOT NULL,
  model_digest TEXT NOT NULL,
  preprocess_version TEXT NOT NULL,
  dim INTEGER NOT NULL,
  normalization TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('image','ocr_text')),
  state TEXT NOT NULL CHECK (state IN ('building','active','retired')),
  revision INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);

CREATE TABLE vectors (
  namespace TEXT NOT NULL REFERENCES vector_namespaces(namespace),
  asset_id TEXT NOT NULL REFERENCES assets(id),
  view_id TEXT NOT NULL,
  view_kind TEXT NOT NULL,
  region TEXT,
  source_refs TEXT NOT NULL DEFAULT '[]',
  vector BLOB NOT NULL,
  metadata_revision INTEGER NOT NULL,
  PRIMARY KEY (namespace, asset_id, view_id)
);
CREATE INDEX idx_vectors_asset ON vectors(asset_id);

CREATE TABLE object_observations (
  asset_id TEXT NOT NULL REFERENCES assets(id),
  revision INTEGER NOT NULL,
  obs_id TEXT NOT NULL,
  label TEXT NOT NULL,
  score REAL NOT NULL,
  box TEXT NOT NULL,
  model TEXT NOT NULL,
  PRIMARY KEY (asset_id, obs_id)
);
CREATE INDEX idx_objects_label ON object_observations(label, score);

CREATE TABLE decisions (
  asset_id TEXT NOT NULL REFERENCES assets(id),
  revision INTEGER NOT NULL,
  question_id TEXT NOT NULL,
  dtype TEXT NOT NULL,
  value TEXT,
  p_value REAL,
  probs TEXT NOT NULL,
  status TEXT NOT NULL,
  model TEXT NOT NULL,
  PRIMARY KEY (asset_id, question_id)
);
CREATE INDEX idx_decisions_q ON decisions(question_id, value);
""",
    3: """
CREATE TABLE collections (
  id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  ctype TEXT NOT NULL CHECK (ctype IN ('smart','similarity','duplicate','user')),
  key TEXT,
  parent_id TEXT,
  suggested_label TEXT NOT NULL,
  user_label TEXT,
  pinned INTEGER NOT NULL DEFAULT 0,
  hidden INTEGER NOT NULL DEFAULT 0,
  rule TEXT NOT NULL DEFAULT '{}',
  representative_asset TEXT,
  snapshot_id TEXT,
  revision INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  retired_at REAL
);
CREATE INDEX idx_collections_type ON collections(library_id, ctype, retired_at);

CREATE TABLE memberships (
  collection_id TEXT NOT NULL REFERENCES collections(id),
  asset_id TEXT NOT NULL REFERENCES assets(id),
  method TEXT NOT NULL,
  affinity REAL,
  affinity_kind TEXT NOT NULL,
  evidence TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL CHECK (state IN ('suggested','confirmed','excluded')),
  snapshot_id TEXT,
  updated_at REAL NOT NULL,
  PRIMARY KEY (collection_id, asset_id)
);
CREATE INDEX idx_memberships_asset ON memberships(asset_id);

CREATE TABLE cluster_snapshots (
  id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  method TEXT NOT NULL,
  params TEXT NOT NULL,
  stats TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE collection_aliases (
  old_id TEXT NOT NULL,
  new_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY (old_id, new_id)
);

CREATE TABLE corrections (
  id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  at REAL NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  field TEXT NOT NULL,
  previous TEXT,
  new TEXT,
  scope TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL
);
CREATE INDEX idx_corrections_target ON corrections(target_type, target_id);

-- User overrides of machine metadata (e.g. capture_type), kept separate from
-- the machine revision so re-analysis never overwrites them.
CREATE TABLE metadata_overrides (
  asset_id TEXT NOT NULL REFERENCES assets(id),
  question_id TEXT NOT NULL,
  value TEXT NOT NULL,
  correction_id TEXT NOT NULL REFERENCES corrections(id),
  updated_at REAL NOT NULL,
  PRIMARY KEY (asset_id, question_id)
);
""",
    4: """
ALTER TABLE decisions ADD COLUMN prob_kind TEXT;
ALTER TABLE decisions ADD COLUMN calibration_version TEXT;
""",
    5: """
ALTER TABLE assets ADD COLUMN phash64 TEXT;
ALTER TABLE assets ADD COLUMN dhash64 TEXT;
""",
    # 6: video assets. Frame anchors on derived rows (NULL for images).
    6: """
ALTER TABLE assets ADD COLUMN duration_s REAL;
ALTER TABLE ocr_regions ADD COLUMN frame_id TEXT;
ALTER TABLE ocr_regions ADD COLUMN t_s REAL;
ALTER TABLE object_observations ADD COLUMN frame_id TEXT;
ALTER TABLE object_observations ADD COLUMN t_s REAL;
ALTER TABLE vectors ADD COLUMN frame_id TEXT;
ALTER TABLE vectors ADD COLUMN t_s REAL;
""",
}


class RepositoryError(RuntimeError):
    pass


class StaleRevisionError(RepositoryError):
    """Raised when a write's expected revision no longer matches."""


def _connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30, check_same_thread=False)
    else:
        conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False,
                               isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def check_fts5() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
    except sqlite3.OperationalError as e:
        raise RepositoryError(
            f"SQLite {sqlite3.sqlite_version} lacks FTS5 with the trigram tokenizer "
            "(needs >= 3.34 compiled with FTS5)"
        ) from e
    finally:
        conn.close()


class Repository:
    def __init__(self, db_path: Path) -> None:
        check_fts5()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._writer = _connect(self.db_path)
        self._writer.execute("PRAGMA journal_mode = WAL")
        self._writer.execute("PRAGMA synchronous = NORMAL")
        self._local = threading.local()
        self.migrate()

    # ------------------------------------------------------------------
    def migrate(self) -> int:
        with self._write_lock:
            conn = self._writer
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise RepositoryError(
                    f"database schema {current} is newer than this build ({SCHEMA_VERSION})"
                )
            for version in range(current + 1, SCHEMA_VERSION + 1):
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_sql(_MIGRATIONS[version]):
                        conn.execute(stmt)
                    conn.execute(f"PRAGMA user_version = {version}")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            return SCHEMA_VERSION

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Serialized, bounded write transaction (BEGIN IMMEDIATE)."""
        with self._write_lock:
            conn = self._writer
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                # O(1) change marker for read-side caches (search results).
                conn.execute("INSERT INTO schema_meta(key, value) VALUES ('write_seq', '1') ON CONFLICT(key)"
                             " DO UPDATE SET value = CAST(value AS INTEGER) + 1")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def read(self) -> sqlite3.Connection:
        """Per-thread reader connection (never used for writes)."""
        conn = getattr(self._local, "reader", None)
        if conn is None:
            conn = _connect(self.db_path)
            conn.execute("PRAGMA query_only = ON")
            self._local.reader = conn
        return conn

    def write_seq(self) -> int:
        r = self.read().execute("SELECT value FROM schema_meta WHERE key='write_seq'").fetchone()
        return int(r[0]) if r else 0

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.read().execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.read().execute(sql, params).fetchone()

    def close(self) -> None:
        with self._write_lock:
            self._writer.close()
        reader = getattr(self._local, "reader", None)
        if reader is not None:
            reader.close()
            self._local.reader = None

    def ensure_library(self, library_id: str, name: str | None = None) -> None:
        with self.write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO libraries(id, name, created_at) VALUES (?,?,?)",
                (library_id, name or library_id, time.time()),
            )


def _split_sql(script: str) -> list[str]:
    """Split a migration script into statements (no triggers/strings with ';')."""
    out: list[str] = []
    buf: list[str] = []
    for line in script.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        out.append(tail)
    return out
