"""M2 acceptance slice: import -> OCR -> exact text search -> highlight -> restart.

Uses the real RapidOCR engine and a real SQLite library on disk. The synthetic
PNG proves plumbing only; OCR quality evidence lives in the evaluation report.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from services.library.config import Features, config_from_env
from services.library.registry import Library
from services.library.worker import Worker
from tests.support.image_factory import make_corrupt_png, make_not_an_image, make_text_image

M2_FEATURES = Features(embeddings=False, ocr_text_embeddings=False, objects=False, context=False,
                       clustering=False)


@pytest.fixture
def cfg(tmp_path: Path):
    base = config_from_env(tmp_path / "lib")
    return dataclasses.replace(base, features=M2_FEATURES)


def _run(lib: Library) -> list[str]:
    return Worker(lib.cfg, lib.repo).run_until_idle()


def _stage_rows(lib: Library, job_id: str) -> dict[str, str]:
    return {s.stage: s.status for s in lib.queue.get(job_id).stages}


def test_feature_store_is_found_by_ocr_text_and_survives_restart(cfg, tmp_path: Path) -> None:
    fx = make_text_image(tmp_path / "in" / "IMG_20260930_x7f3k.png", ["feature store", "online serving"])
    lib = Library(cfg)
    batch = lib.import_files([fx["path"]])
    assert batch.admitted == 1 and batch.rejected == 0
    assert _run(lib) == ["complete"]
    stages = _stage_rows(lib, batch.job_ids[0])
    assert stages["ocr"] == "complete" and stages["pixels"] == "complete"
    # Stages that are not built/enabled are reported, never faked as complete.
    assert all(v in {"complete", "disabled", "missing", "not_applicable", "skipped"} for v in stages.values())

    resp = lib.search('text:"feature store"')
    assert [h.asset_id for h in resp.hits] == batch.asset_ids
    ev = [e for e in resp.hits[0].reasons if e.reason == "OCR_PHRASE"]
    assert ev and "feature store" in ev[0].excerpt.lower()
    # Highlight polygon lies on the rendered text (normalized original coords).
    expected = fx["boxes"][0][1]
    xs = [p[0] for p in ev[0].polygons[0]]
    ys = [p[1] for p in ev[0].polygons[0]]
    assert abs(min(xs) - expected[0]) < 0.05 and abs(min(ys) - expected[1]) < 0.08
    assert abs(max(ys) - expected[3]) < 0.08
    # Filename contains none of the query text; annotations are empty.
    assert "feature" not in fx["path"].name
    assert lib.annotations(batch.asset_ids[0])["tags"] == []
    # Semantic-only neighbours never masquerade as literal matches.
    assert lib.search('text:"feature stores"').hits == []
    cache_before = {r["cache_key"]: r["hits"] for r in lib.repo.query("SELECT cache_key, hits FROM stage_cache")}
    lib.close()

    # --- restart: new process-level objects, same library root -------------
    lib2 = Library(cfg)
    resp2 = lib2.search('text:"feature store"')
    assert [h.asset_id for h in resp2.hits] == batch.asset_ids
    assert _run(lib2) == []                      # nothing pending, nothing re-OCRed
    job = lib2.retry_asset(batch.asset_ids[0])   # explicit re-analysis: served from cache
    assert _run(lib2) == ["complete"]
    stages2 = _stage_rows(lib2, job)
    assert stages2["pixels"] == "cached" and stages2["ocr"] == "cached"
    cache_after = {r["cache_key"]: r["hits"] for r in lib2.repo.query("SELECT cache_key, hits FROM stage_cache")}
    assert set(cache_after) == set(cache_before)  # no new stage outputs computed
    lib2.close()


def test_annotation_edit_persists_and_reruns_no_stage(cfg, tmp_path: Path) -> None:
    fx = make_text_image(tmp_path / "in" / "a.png", ["quarterly roadmap"])
    lib = Library(cfg)
    aid = lib.import_files([fx["path"]]).asset_ids[0]
    _run(lib)
    jobs_before = lib.repo.query_one("SELECT COUNT(*) n FROM jobs")["n"]
    cache_before = lib.repo.query("SELECT cache_key FROM stage_cache")
    rev_before = lib.get_asset(aid).metadata_revision
    ann = lib.set_annotations(aid, expected_revision=0, title="Roadmap slide", tags=["planning", "q3"])
    assert ann["revision"] == 1
    from services.library.repository import StaleRevisionError

    with pytest.raises(StaleRevisionError):
        lib.set_annotations(aid, expected_revision=0, title="stale write")
    lib.close()

    lib2 = Library(cfg)
    assert lib2.annotations(aid) == {"title": "Roadmap slide", "notes": "", "tags": ["planning", "q3"], "revision": 1}
    assert lib2.repo.query_one("SELECT COUNT(*) n FROM jobs")["n"] == jobs_before
    assert lib2.repo.query("SELECT cache_key FROM stage_cache") == cache_before
    assert lib2.get_asset(aid).metadata_revision == rev_before
    assert [h.asset_id for h in lib2.search("tag:planning").hits] == [aid]
    assert [h.asset_id for h in lib2.search("roadmap", channels=["lexical"]).hits] == [aid]
    lib2.close()


def test_same_bytes_reuse_extraction_but_keep_import_records(cfg, tmp_path: Path) -> None:
    fx = make_text_image(tmp_path / "in" / "one.png", ["duplicate bytes"])
    copy = tmp_path / "in" / "renamed_copy.png"
    copy.write_bytes(fx["path"].read_bytes())
    lib = Library(cfg)
    b1 = lib.import_files([fx["path"]])
    _run(lib)
    b2 = lib.import_files([copy])
    assert b2.admitted == 0 and b2.reused == 1 and b2.asset_ids == b1.asset_ids
    assert b2.job_ids == []                                  # already analyzed: nothing re-runs
    names = [i["original_filename"] for i in lib.asset_detail(b1.asset_ids[0])["imports"]]
    assert names == ["one.png", "renamed_copy.png"]
    lib.close()


def test_corrupt_and_unsupported_items_do_not_sink_the_batch(cfg, tmp_path: Path) -> None:
    good = make_text_image(tmp_path / "in" / "good.png", ["still searchable"])["path"]
    corrupt = make_corrupt_png(tmp_path / "in" / "corrupt.png")
    junk = make_not_an_image(tmp_path / "in" / "notes.png")
    lib = Library(cfg)
    batch = lib.import_files([good, corrupt, junk])
    codes = {r.filename: r.code for r in batch.rejections}
    assert codes.get("notes.png") == "unreadable"
    assert batch.status == "partial"
    results = sorted(_run(lib))
    assert "complete" in results
    good_id = next(a for a in batch.asset_ids if lib.asset_detail(a)["imports"][0]["original_filename"] == "good.png")
    assert [h.asset_id for h in lib.search('text:"still searchable"').hits] == [good_id]
    if "corrupt.png" not in codes:  # admitted on header, failed on decode: visible error
        bad = next(a for a in batch.asset_ids if a != good_id)
        detail = lib.asset_detail(bad)
        assert detail["status"] == "error"
        err = detail["metadata"]["errors"][0]
        assert err["stage"] == "pixels" and "/" not in err["message"]  # sanitized, no paths
    lib.close()


def test_missing_ocr_weights_are_reported_not_faked(cfg, tmp_path: Path, monkeypatch) -> None:
    empty = tmp_path / "no-weights"
    empty.mkdir()
    monkeypatch.setenv("ATTENTIONX_RAPIDOCR_MODEL_DIR", str(empty))
    cfg_no_fallback = dataclasses.replace(cfg, features=dataclasses.replace(cfg.features, ocr_fallback_tesseract=False))
    fx = make_text_image(tmp_path / "in" / "w.png", ["weights missing"])
    lib = Library(cfg_no_fallback)
    batch = lib.import_files([fx["path"]])
    assert _run(lib) == ["partial"]
    detail = lib.asset_detail(batch.asset_ids[0])
    meta = detail["metadata"]
    assert meta["stage_status"]["ocr"] == "missing"
    assert meta["ocr"] is None and meta["partial"] is True
    assert any(e["code"] == "ocr_model_missing" for e in meta["errors"])
    assert detail["status"] == "partial"
    assert lib.search('text:"weights missing"').hits == []
    assert [h.asset_id for h in lib.search("status:partial").hits] == batch.asset_ids

    # Provision (restore weights) and retry: only the failed stage runs.
    monkeypatch.delenv("ATTENTIONX_RAPIDOCR_MODEL_DIR")
    job = lib.retry_asset(batch.asset_ids[0])
    assert _run(lib) == ["complete"]
    st = _stage_rows(lib, job)
    assert st["pixels"] == "cached" and st["ocr"] == "complete"
    assert [h.asset_id for h in lib.search('text:"weights missing"').hits] == batch.asset_ids
    lib.close()


def test_tesseract_fallback_is_explicit_in_provenance(cfg, tmp_path: Path, monkeypatch) -> None:
    import shutil

    if shutil.which("tesseract") is None:
        pytest.skip("tesseract not installed")
    empty = tmp_path / "no-weights"
    empty.mkdir()
    monkeypatch.setenv("ATTENTIONX_RAPIDOCR_MODEL_DIR", str(empty))
    fx = make_text_image(tmp_path / "in" / "t.png", ["fallback engine text"], font_size=44)
    lib = Library(cfg)
    batch = lib.import_files([fx["path"]])
    _run(lib)
    meta = lib.asset_detail(batch.asset_ids[0])["metadata"]
    assert meta["ocr"]["engine"] == "tesseract"
    assert meta["stage_provenance"]["ocr"]["extractor"] == "tesseract"
    assert [h.asset_id for h in lib.search('text:"fallback engine"').hits] == batch.asset_ids
    lib.close()


def test_metadata_projects_to_strict_v1(cfg, tmp_path: Path) -> None:
    from models.media_metadata import load_metadata, project_to_v1
    from models.media_metadata_v1 import MediaMetadata as V10

    fx = make_text_image(tmp_path / "in" / "p.png", ["projection check"])
    lib = Library(cfg)
    aid = lib.import_files([fx["path"]]).asset_ids[0]
    _run(lib)
    meta = load_metadata(lib.asset_detail(aid)["metadata"])
    v1 = V10.model_validate(project_to_v1(meta))
    assert v1.schema_version == "MediaMetadata/1.0"
    assert any("projection" in t.text.lower() for t in v1.text_layers)
    with pytest.raises(Exception):
        V10.model_validate(json.loads(meta.model_dump_json()))  # 1.1 is not silently accepted by 1.0
    lib.close()
