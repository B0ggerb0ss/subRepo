"""Model change -> shadow namespace -> atomic promotion when coverage is complete."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from services.analyze.vectors_registry import active_namespace, promote_ready
from services.library.config import config_from_env
from services.library.registry import Library


def _asset(c, aid: str) -> None:
    c.execute("INSERT INTO assets(id, library_id, content_hash, kind, mime, byte_size, original_ref, created_at,"
              " metadata_revision) VALUES (?,?,?,?,?,?,?,?,1)",
              (aid, "local", aid.ljust(64, "0"), "image", "image/png", 1, f"originals/{aid}.png", time.time()))


def test_shadow_namespace_is_promoted_only_when_complete(tmp_path: Path) -> None:
    lib = Library(config_from_env(tmp_path / "lib"))
    old = active_namespace(lib.repo, "image")
    assert old is not None
    vec = np.ones(512, np.float32) / np.sqrt(512)
    with lib.repo.write() as c:
        for aid in ("a1", "a2"):
            _asset(c, aid)
            c.execute("INSERT INTO vectors(namespace, asset_id, view_id, view_kind, region, source_refs, vector,"
                      " metadata_revision) VALUES (?,?,?,?,?,?,?,?)",
                      (old["namespace"], aid, "global", "global_letterbox", None, "[]", vec.tobytes(), 1))
        c.execute("INSERT INTO vector_namespaces(namespace, space, model, model_digest, preprocess_version, dim,"
                  " normalization, kind, state, created_at) VALUES ('clip-new:x','clip-new','m','d','v2',512,'l2',"
                  "'image','building',?)", (time.time(),))
        c.execute("INSERT INTO vectors(namespace, asset_id, view_id, view_kind, region, source_refs, vector,"
                  " metadata_revision) VALUES ('clip-new:x','a1','global','global_letterbox',NULL,'[]',?,1)",
                  (vec.tobytes(),))
    assert promote_ready(lib.repo) == []                       # a2 not covered yet: old stays active
    assert active_namespace(lib.repo, "image")["namespace"] == old["namespace"]
    with lib.repo.write() as c:
        c.execute("INSERT INTO vectors(namespace, asset_id, view_id, view_kind, region, source_refs, vector,"
                  " metadata_revision) VALUES ('clip-new:x','a2','global','global_letterbox',NULL,'[]',?,1)",
                  (vec.tobytes(),))
    assert promote_ready(lib.repo) == ["clip-new:x"]
    assert active_namespace(lib.repo, "image")["namespace"] == "clip-new:x"
    states = {r["namespace"]: r["state"] for r in lib.repo.query("SELECT namespace, state FROM vector_namespaces")}
    assert states[old["namespace"]] == "retired"                # old rows kept, no longer queried
    lib.close()
