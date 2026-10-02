"""Content-addressed stage cache.

Key = sha256(canonical JSON of {content_hash, stage, stage_version, params,
model_digest, upstream_keys}). A renamed file, moved folder or edited user tag
changes none of these, so no pixel/model stage re-runs. Changing the OCR
language changes the OCR key and therefore every key downstream of OCR, but
not the image-embedding key.

Payloads are immutable once written; commits are idempotent (INSERT OR IGNORE).
Stale jobs may still write here: it never affects the *active* metadata.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

import numpy as np

from services.library.repository import Repository


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stage_key(content_hash: str, stage: str, stage_version: str, params: dict,
              model_digest: str | None, upstream: list[str]) -> str:
    material = {
        "content_hash": content_hash,
        "stage": stage,
        "stage_version": stage_version,
        "params": params,
        "model_digest": model_digest,
        "upstream": sorted(upstream),
    }
    return hashlib.sha256(canonical(material).encode()).hexdigest()


def encode_vector(v: np.ndarray) -> str:
    return base64.b64encode(np.asarray(v, dtype=np.float32).tobytes()).decode()


def decode_vector(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=np.float32)


class StageCache:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def get(self, key: str) -> dict | None:
        row = self.repo.query_one("SELECT payload, status FROM stage_cache WHERE cache_key=?", (key,))
        if row is None:
            return None
        with self.repo.write() as conn:
            conn.execute("UPDATE stage_cache SET hits = hits + 1 WHERE cache_key=?", (key,))
        payload = json.loads(row["payload"])
        payload["_cache_status"] = row["status"]
        return payload

    def put(self, key: str, stage: str, content_hash: str, stage_version: str,
            status: str, payload: dict) -> None:
        # Only reusable outcomes are cached; errors are retried next time.
        if status not in {"complete", "partial", "not_applicable"}:
            return
        with self.repo.write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO stage_cache(cache_key, stage, content_hash, stage_version,"
                " status, payload, created_at) VALUES (?,?,?,?,?,?,?)",
                (key, stage, content_hash, stage_version, status, canonical(payload), time.time()),
            )

    def stats(self) -> dict:
        rows = self.repo.query("SELECT stage, COUNT(*) n, SUM(hits) hits FROM stage_cache GROUP BY stage")
        return {r["stage"]: {"entries": r["n"], "hits": r["hits"] or 0} for r in rows}
