"""M3-M6 acceptance: semantic retrieval, objects/context, organization, corrections.

Real models (CLIP ViT-B-32 laion2b ONNX, MiniLM ONNX, EfficientDet-Lite0,
RapidOCR) on committed fixtures: Chromium-rendered screenshots of fictitious
content and real photos (tests/fixtures/images/manifest.json).
Skips cleanly when the models are not provisioned.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from services.library.config import config_from_env
from services.library.registry import Library
from services.library.repository import StaleRevisionError
from services.library.worker import Worker
from services.search.service import SearchError

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "images"
MANIFEST = json.loads((FIX / "manifest.json").read_text())


def _need_models():
    cfg = config_from_env()
    for m in ("clip_vit_b32_laion2b_s34b_b79k", "minilm_l6_v2", "efficientdet_lite0"):
        if cfg.model_path(m) is None:
            pytest.skip(f"model {m} not provisioned")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    _need_models()
    root = tmp_path_factory.mktemp("m3m6")
    src = root / "in"
    src.mkdir()
    for key, rec in MANIFEST.items():
        shutil.copy(FIX / rec["file"], src / rec["file"])
    cfg = config_from_env(root / "lib")
    lib = Library(cfg)
    files = [src / MANIFEST[k]["file"] for k in MANIFEST]
    batch = lib.import_files(files)
    ids = dict(zip(MANIFEST, batch.asset_ids))
    statuses = Worker(cfg, lib.repo).run_until_idle()
    lib.refresh_organization(inline=True)
    yield {"lib": lib, "ids": ids, "cfg": cfg, "root": root, "statuses": statuses}
    lib.close()


def _ids(resp):
    return [h.asset_id for h in resp.hits]


def test_all_fixture_analyses_complete(env):
    assert env["statuses"] and all(s == "complete" for s in env["statuses"]), env["statuses"]


# -- M3: contextual retrieval ------------------------------------------------------

def test_description_query_finds_untagged_photo(env):
    lib, ids = env["lib"], env["ids"]
    assert _ids(lib.search("a cat"))[0] == ids["cat"]
    assert _ids(lib.search("a cup of coffee"))[0] == ids["coffee"]
    assert lib.annotations(ids["cat"])["tags"] == []   # no hidden hints


def test_ocr_meaning_query_returns_verbatim_evidence(env):
    lib, ids = env["lib"], env["ids"]
    resp = lib.search("problems when offline features differ from production features")
    top = resp.hits[0]
    assert top.asset_id in {ids["li_skew"], ids["li_skew_variant"]}
    sem = [e for e in top.reasons if e.reason == "OCR_SEMANTIC"]
    assert sem, top.reasons
    stored = "\n".join(r["raw_text"] for r in lib.asset_detail(top.asset_id)["metadata"]["ocr"]["regions"])
    for part in sem[0].excerpt.split(" / "):
        assert part in stored                     # verbatim, never generated
    assert all(e.reason != "OCR_PHRASE" for e in top.reasons)  # not claimed as a quote


def test_vectors_never_cross_namespaces(env):
    lib = env["lib"]
    rows = lib.repo.query("SELECT namespace, kind, dim FROM vector_namespaces WHERE state='active'")
    kinds = {r["kind"]: (r["namespace"], r["dim"]) for r in rows}
    assert kinds["image"][1] == 512 and kinds["ocr_text"][1] == 384
    for r in lib.repo.query("SELECT namespace, length(vector) n FROM vectors"):
        dim = {v[0]: v[1] for v in kinds.values()}[r["namespace"]]
        assert r["n"] == dim * 4
    # A query encoder whose model digest does not match the index is refused, visibly.
    with lib.repo.write() as c:
        c.execute("UPDATE vector_namespaces SET model_digest='deadbeef' WHERE kind='ocr_text'")
    try:
        resp = lib.search("feature consistency between training and serving")
        assert "ocr_semantic" not in resp.channels_used
        assert any("OCR meaning search unavailable" in d for d in resp.degraded)
    finally:
        with lib.repo.write() as c:
            c.execute("UPDATE vector_namespaces SET model_digest=? WHERE kind='ocr_text'",
                      (__import__("services.analyze.vectors_registry", fromlist=["x"]).minilm_namespace()["model_digest"],))
        lib.search_service._cache.clear()


def test_query_grammar_errors_are_useful(env):
    lib = env["lib"]
    with pytest.raises(SearchError, match="unknown filter"):
        lib.search("colour:red")
    with pytest.raises(SearchError, match="not in the detector's supported vocabulary"):
        lib.search("object:oscilloscope")


def test_punctuation_sensitive_and_short_literals(env):
    lib, ids = env["lib"], env["ids"]
    # "PyTorch" is in the hiring post; "py" alone must not match it as a word.
    assert ids["li_hiring_python"] in _ids(lib.search('text:"python"'))
    assert ids["li_hiring_python"] not in _ids(lib.search('text:"py"'))


# -- M4: objects / scenes / source -------------------------------------------------

def test_object_filter_returns_real_boxes(env):
    lib, ids = env["lib"], env["ids"]
    resp = lib.search("object:cat")
    assert ids["cat"] in _ids(resp)
    ev = next(e for e in resp.hits[0].reasons if e.reason == "OBJECT_DETECTION")
    x0, y0, x1, y1 = ev.box
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1 and ev.score_kind == "raw_detector"
    assert ids["cat"] not in _ids(lib.search("object:car"))


def test_linkedin_ui_vs_brand_mentions(env):
    lib, ids = env["lib"], env["ids"]
    got = set(_ids(lib.search("source:linkedin", collapse_duplicates=False)))  # expanded: include dup members
    assert {ids["li_hiring_python"], ids["li_skew"], ids["li_career"]} <= got
    assert ids["slide_linkedin"] not in got     # LinkedIn mentioned in a slide is not LinkedIn UI
    assert ids["adversarial"] not in got        # instruction text is data, not authority
    combo = _ids(lib.search('source:linkedin text:"hiring"'))
    assert ids["li_hiring_python"] in combo and ids["li_career"] not in combo


def test_adversarial_text_is_preserved_but_powerless(env):
    lib, ids = env["lib"], env["ids"]
    assert _ids(lib.search('text:"ignore previous instructions"')) == [ids["adversarial"]]
    mem = {m["label"] for m in lib.asset_detail(ids["adversarial"])["memberships"]}
    assert "LinkedIn screenshots" not in mem and "Movie / TV frames" not in mem


def test_black_bars_alone_are_not_a_film_frame(env):
    lib, ids = env["lib"], env["ids"]
    d = lib.asset_detail(ids["pillarbox"])["metadata"]["decisions"]["context.film_tv_frame"]
    assert d["value"] < 0.8
    assert ids["pillarbox"] not in {m.asset_id for m in lib.collection("movie_tv_frames").members}


def test_source_app_not_applicable_for_photos(env):
    lib, ids = env["lib"], env["ids"]
    d = lib.asset_detail(ids["cat"])["metadata"]["decisions"]["source_app"]
    assert d["status"] == "not_applicable" and d["value"] is None


# -- M5: organization --------------------------------------------------------------

def test_linkedin_collection_and_dual_membership(env):
    lib, ids = env["lib"], env["ids"]
    li = {m.asset_id for m in lib.collection("linkedin_screenshots").members if m.state != "excluded"}
    assert {ids["li_hiring_python"], ids["li_skew"], ids["li_career"]} <= li
    jobs = {m.asset_id for m in lib.collection("linkedin_job_posts").members}
    assert ids["li_hiring_python"] in jobs and ids["li_career"] not in jobs


def test_near_duplicates_but_not_shared_chrome(env):
    lib, ids = env["lib"], env["ids"]
    dups = lib.collections(ctype="duplicate", with_members=True)
    groups = [{m.asset_id for m in c.members} for c in dups]
    assert any({ids["li_skew"], ids["li_skew_variant"]} <= g for g in groups), groups
    for g in groups:
        assert not ({ids["li_skew"], ids["li_career"]} <= g)       # common LinkedIn chrome is not duplication
        assert not ({ids["li_skew"], ids["li_hiring_python"]} <= g)
    # Duplicates never hide results: they are collapsed with a count, and expandable.
    q = 'text:"train-serving skew"'
    collapsed = lib.search(q)
    expanded = lib.search(q, collapse_duplicates=False)
    assert set(_ids(expanded)) >= {ids["li_skew"], ids["li_skew_variant"]}
    assert len(collapsed.hits) == len(expanded.hits) - 1
    leader = next(h for h in collapsed.hits if h.asset_id in {ids["li_skew"], ids["li_skew_variant"]})
    assert leader.duplicate_count == 1


def test_film_frames_of_one_scene_group_together(env):
    lib, ids = env["lib"], env["ids"]
    groups = [{m.asset_id for m in c.members} for c in lib.collections(ctype="similarity", with_members=True)]
    assert any({ids["film_a"], ids["film_b"]} <= g for g in groups), groups


def test_reference_and_crop_similarity(env):
    lib, ids = env["lib"], env["ids"]
    resp = lib.find_similar(ids["film_a"])
    assert ids["film_a"] not in _ids(resp)
    assert _ids(resp)[0] == ids["film_b"]
    assert all(e.reason == "VISUAL_SIMILARITY" and e.box is None for h in resp.hits for e in h.reasons)
    crop = lib.find_similar(ids["coffee"], crop=(0.1, 0.1, 0.9, 0.9))
    assert crop.hits and "crop" in crop.hits[0].reasons[0].detail


# -- M6: corrections survive re-analysis, reclustering and restart --------------------

def test_corrections_persist_through_reanalysis_and_restart(env):
    lib, ids, cfg = env["lib"], env["ids"], env["cfg"]
    col = lib.collection("linkedin_screenshots")
    target = ids["li_k8s_mobile"]
    res = lib.correct({"op": "exclude", "collection_id": col.id, "asset_ids": [target]}, expected_revision=col.revision)
    with pytest.raises(StaleRevisionError):
        lib.correct({"op": "rename", "collection_id": col.id, "label": "stale"}, expected_revision=col.revision)
    lib.correct({"op": "rename", "collection_id": col.id, "label": "LinkedIn (mine)"}, expected_revision=res.new_revision)
    # Late job: enqueue two analyses; the older one must not activate metadata.
    old_job = lib.queue.enqueue("analyze_image", target, ["pixels"], {})
    assert lib.retry_asset(target) == old_job    # no duplicate job while one is pending
    new_job = lib.queue.enqueue("analyze_image", target, ["pixels"], {})  # e.g. a newer explicit re-run
    assert old_job != new_job
    statuses = Worker(cfg, lib.repo).run_until_idle()
    assert "superseded" in statuses
    lib.refresh_organization(inline=True)
    lib.close()

    lib2 = Library(cfg)
    env["lib"] = lib2
    col2 = lib2.collection(col.id)
    assert col2.label == "LinkedIn (mine)"
    states = {m.asset_id: m.state for m in col2.members}
    assert states[target] == "excluded"          # not silently re-added
    assert target not in _ids(lib2.search(f"collection:{col.id}"))
    hist = [c for c in lib2.corrections() if c["target_id"] in {col.id, f"{col.id}:{target}"}]
    assert len(hist) >= 2


def test_metadata_override_drives_filters_and_sets(env):
    lib, ids = env["lib"], env["ids"]
    aid = ids["chat"]
    assert aid not in _ids(lib.search("source:linkedin"))
    lib.correct({"op": "set_decision", "asset_id": aid, "question_id": "source_app", "value": "linkedin"})
    assert aid in _ids(lib.search("source:linkedin"))
    raw = lib.asset_detail(aid)["metadata"]["decisions"]["source_app"]
    assert raw["value"] != "linkedin"            # raw model output stays inspectable
    lib.correct({"op": "clear_decision", "asset_id": aid, "question_id": "source_app"})
    assert aid not in _ids(lib.search("source:linkedin"))


def test_merge_split_and_group_ids_are_stable(env):
    lib, ids = env["lib"], env["ids"]
    groups = lib.collections(ctype="similarity", with_members=True)
    film = next(g for g in groups if ids["film_a"] in {m.asset_id for m in g.members})
    lib.correct({"op": "pin", "collection_id": film.id, "value": True}, expected_revision=film.revision)
    split = lib.correct({"op": "split", "collection_id": film.id, "asset_ids": [ids["film_b"]], "label": "B only"})
    lib.refresh_organization(inline=True)
    after = lib.collection(film.id)
    assert after is not None and after.pinned        # pinned group keeps its id through a rebuild
    assert {m.asset_id: m.state for m in after.members}[ids["film_b"]] == "excluded"
    new = lib.collection(split.collection_id)
    assert new.label == "B only" and [m.asset_id for m in new.members] == [ids["film_b"]]
    merged = lib.correct({"op": "merge", "into": film.id, "collection_ids": [new.id]})
    assert lib.collection(new.id).id == film.id      # alias resolves the retired group to its successor
    assert merged.ok


def test_export_is_deterministic_and_round_trips(env):
    lib = env["lib"]
    a = lib.export_snapshot()
    b = lib.export_snapshot()
    assert a.sha256 == b.sha256 and a.export_id != b.export_id
    snap = json.loads((lib.cfg.library_root / a.relative_path).read_text())
    assert snap["snapshot_version"] == "AttentionXLibrarySnapshot/1"
    assert all("filenames" not in x for x in snap["assets"])
    states = {m["state"] for c in snap["collections"] for m in c["members"]}
    assert "excluded" in states
    v1 = lib.export_snapshot(metadata_format="1.0-projection")
    from models.media_metadata_v1 import MediaMetadata as V10

    snap1 = json.loads((lib.cfg.library_root / v1.relative_path).read_text())
    for x in snap1["assets"]:
        V10.model_validate(x["metadata"])


def test_delete_removes_eligibility_immediately(env):
    lib, ids = env["lib"], env["ids"]
    assert ids["astronaut"] in _ids(lib.search("an astronaut"))
    lib.delete_asset(ids["astronaut"])
    assert ids["astronaut"] not in _ids(lib.search("an astronaut"))
    assert ids["astronaut"] not in _ids(lib.search("object:person"))
    assert (lib.cfg.library_root / lib.get_asset(ids["astronaut"]).original_ref).exists()  # never auto-deleted
