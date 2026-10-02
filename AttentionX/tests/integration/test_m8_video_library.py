"""M8: video assets in the shared library, end to end with real FFmpeg, RapidOCR,
ONNX CLIP/MiniLM, the MediaPipe detector and SQLite.

The rendered drawtext overlays prove plumbing and timing (known text, known
time windows, known pixel boxes); they are not evidence of OCR quality on real
footage.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from models.media_metadata import load_metadata, project_to_v1
from models.media_metadata_v1 import MediaMetadata as V10
from services.library.config import config_from_env
from services.library.registry import Library
from services.library.worker import Worker
from tests.support.video_factory import make_text_video

W, H = 960, 540
OVERLAYS = [
    {"text": "quarterly roadmap review", "start": 4, "end": 8, "x": 120, "y": 220, "size": 48},
    {"text": "launch", "start": 4, "end": 8, "x": 120, "y": 420, "size": 40},
    {"text": "window", "start": 8.5, "end": 12, "x": 500, "y": 60, "size": 40},
]


@pytest.fixture(scope="module")
def video(tmp_path_factory) -> dict:
    d = tmp_path_factory.mktemp("vid")
    return make_text_video(d / "VID_20261002_k2.mp4", OVERLAYS, duration=12.0, size=(W, H), audio=True)


def _cfg(root: Path):
    return config_from_env(root)


def _run(lib: Library) -> list[str]:
    return Worker(lib.cfg, lib.repo).run_until_idle()


def _stages(lib: Library, job_id: str) -> dict[str, str]:
    return {s.stage: s.status for s in lib.queue.get(job_id).stages}


@pytest.fixture(scope="module")
def analyzed(video, tmp_path_factory):
    root = tmp_path_factory.mktemp("lib") / "lib"
    lib = Library(_cfg(root))
    batch = lib.import_files([video["path"]])
    assert batch.admitted == 1 and batch.rejected == 0
    assert _run(lib) == ["complete"]
    return root, batch


def test_video_text_is_found_at_its_time_with_frame_geometry(analyzed) -> None:
    root, batch = analyzed
    lib = Library(_cfg(root))
    aid = batch.asset_ids[0]
    asset = lib.get_asset(aid)
    assert asset.kind == "video" and abs(asset.duration_s - 12.0) < 0.2 and (asset.width, asset.height) == (W, H)
    st = _stages(lib, batch.job_ids[0])
    assert st["keyframes"] == "complete" and st["ocr"] == "complete" and st["image_embed"] == "complete"
    # ASR is off by default: reported as disabled, never faked; context questions do not apply.
    assert st["transcript"] == "disabled"

    resp = lib.search('text:"roadmap review"')
    assert [h.asset_id for h in resp.hits] == [aid]
    ev = next(e for e in resp.hits[0].reasons if e.reason == "OCR_PHRASE")
    assert ev.frame_id and 3.0 <= ev.t_s <= 8.0, ev
    xs = [p[0] for p in ev.polygons[0]]
    ys = [p[1] for p in ev.polygons[0]]
    assert abs(min(xs) - 120 / W) < 0.03 and abs(min(ys) - 220 / H) < 0.05

    later = lib.search('text:"window"').hits[0]
    ev2 = next(e for e in later.reasons if e.reason == "OCR_PHRASE")
    assert ev2.t_s >= 8.0 and ev2.frame_id != ev.frame_id


def test_phrase_never_matches_across_keyframes(analyzed) -> None:
    root, _ = analyzed
    lib = Library(_cfg(root))
    # "launch" (4-8 s) and "window" (8.5-12 s) are on different keyframes.
    assert lib.search('text:"launch"').hits
    assert lib.search('text:"launch window"').hits == []


def test_video_metadata_is_1_2_and_projects_to_timed_v1(analyzed) -> None:
    root, batch = analyzed
    lib = Library(_cfg(root))
    detail = lib.asset_detail(batch.asset_ids[0])
    meta = load_metadata(detail["metadata"])
    assert meta.schema_version == "MediaMetadata/1.2" and meta.asset_kind == "video"
    v = meta.video
    assert v.coverage_complete and v.has_audio and len(v.keyframes) >= 3
    times = [k.t_s for k in v.keyframes]
    assert times == sorted(times) and times[0] == 0.0
    for k in v.keyframes:
        assert (root / k.frame_ref).is_file() and k.t_end_s > k.t_s
    assert all(r.frame_id and r.t_s is not None for r in meta.ocr.regions)
    assert any(e.view_kind == "frame_global" for e in meta.embeddings)
    assert meta.stage_status["context"] == "not_applicable"
    v1 = V10.model_validate(project_to_v1(meta))
    timed = [t for t in v1.text_layers if "roadmap" in t.text.lower()]
    assert timed and timed[0].t_start is not None and timed[0].t_end > timed[0].t_start
    assert v1.technical.value["duration_s"] == v.duration_s


def test_restart_reuses_analysis_and_filters_and_similarity_work(analyzed, tmp_path: Path) -> None:
    root, batch = analyzed
    aid = batch.asset_ids[0]
    lib = Library(_cfg(root))  # a fresh process view of the same library
    lib.recover()
    assert [h.asset_id for h in lib.search('type:video text:"roadmap"').hits] == [aid]
    assert lib.search('type:image text:"roadmap"').hits == []
    assert [h.asset_id for h in lib.search("format:mp4").hits] == [aid]
    # Retry after restart: every analysis stage is served from the stage cache.
    job = lib.retry_asset(aid)
    assert _run(lib) == ["complete"]
    st = _stages(lib, job)
    assert all(st[s] == "cached" for s in ("keyframes", "ocr", "image_embed", "ocr_text_embed", "objects")), st
    # Videos are in their own smart set, never in "needs review".
    cols = {m["label"] for m in lib.asset_detail(aid)["memberships"]}
    assert "Videos" in cols and not any("Needs review" in c for c in cols)

    # Similarity from a video keyframe and from a crop of it (other assets compete).
    from tests.support.image_factory import make_text_image

    img = make_text_image(tmp_path / "slide.png", ["quarterly roadmap review"])
    lib.import_files([img["path"]])
    _run(lib)
    meta = lib.asset_detail(aid)["metadata"]
    fid = meta["video"]["keyframes"][1]["frame_id"]
    sim = lib.find_similar(aid, frame_id=fid)
    assert sim.hits and all(h.asset_id != aid for h in sim.hits)
    assert "video frame at" in sim.hits[0].reasons[0].detail
    crop = lib.find_similar(aid, crop=(0.1, 0.35, 0.9, 0.55), frame_id=fid)
    assert crop.hits


def test_bad_videos_are_rejected_without_sinking_the_batch(tmp_path: Path, video) -> None:
    lib = Library(_cfg(tmp_path / "lib"))
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x13" * 4000)
    audio_only = tmp_path / "voice.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=1",
                    "-c:a", "aac", str(audio_only)], check=True)
    batch = lib.import_files([bad, audio_only, video["path"]])
    codes = {r.filename: r.code for r in batch.rejections}
    assert codes == {"broken.mp4": "corrupt_video", "voice.mp4": "no_video_stream"}
    assert batch.admitted == 1

    short = dataclasses.replace(lib.cfg, limits=dataclasses.replace(lib.cfg.limits, max_video_seconds=5.0))
    lib2 = Library(dataclasses.replace(short, library_root=tmp_path / "lib2"))
    b2 = lib2.import_files([video["path"]])
    assert [r.code for r in b2.rejections] == ["too_long"]
    assert video["path"].is_file()  # the source is never moved or deleted


def test_keyframe_budget_is_spread_over_the_whole_video(tmp_path: Path, video) -> None:
    """A small budget samples sparsely but completely; the effective spacing is recorded."""
    base = _cfg(tmp_path / "lib")
    cfg = dataclasses.replace(base, limits=dataclasses.replace(base.limits, video_max_keyframes=3))
    lib = Library(cfg)
    batch = lib.import_files([video["path"]])
    assert _run(lib) == ["complete"]
    meta = load_metadata(lib.asset_detail(batch.asset_ids[0])["metadata"])
    v = meta.video
    assert v.coverage_complete and len(v.keyframes) <= 3
    assert v.min_gap_s == pytest.approx(6.0) and v.coverage_end_s == pytest.approx(12.0, abs=0.2)
    gaps = [b.t_s - a.t_s for a, b in zip(v.keyframes, v.keyframes[1:])]
    assert all(g >= 6.0 - 1e-6 for g in gaps)
    # The keyframe at >= 6 s shows the 4-8 s text; text shorter than the spacing can be missed (documented).
    assert lib.search('text:"roadmap review"').hits


def test_cancel_mid_video_then_retry_reuses_completed_stages(tmp_path: Path, video, monkeypatch) -> None:
    import services.analyze.video as vmod

    lib = Library(_cfg(tmp_path / "lib"))
    batch = lib.import_files([video["path"]])
    job_id = batch.job_ids[0]
    real = vmod.run_ocr
    calls = {"n": 0}

    def ocr_then_cancel(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            lib.queue.request_cancel(job_id)  # user presses Cancel while frame 1 is being read
        return real(*a, **k)

    monkeypatch.setattr(vmod, "run_ocr", ocr_then_cancel)
    assert _run(lib) == ["cancelled"]
    assert lib.get_asset(batch.asset_ids[0]).metadata_revision == 0  # nothing half-committed
    monkeypatch.setattr(vmod, "run_ocr", real)
    job = lib.retry_asset(batch.asset_ids[0])
    assert _run(lib) == ["complete"]
    st = _stages(lib, job)
    assert st["keyframes"] == "cached" and st["ocr"] == "complete"


def test_interrupted_video_job_is_recovered(tmp_path: Path, video) -> None:
    root = tmp_path / "lib"
    lib = Library(_cfg(root))
    batch = lib.import_files([video["path"]])
    claimed = lib.queue.claim("crashed-worker")  # a worker took the job and died
    assert claimed is not None and claimed.id == batch.job_ids[0]
    lib2 = Library(_cfg(root))
    rec = lib2.recover()
    assert rec["jobs"]
    assert _run(lib2) == ["complete"]
    assert lib2.search('text:"roadmap review"').hits


def test_generate_from_library_reuses_normalized_source(analyzed, monkeypatch, tmp_path: Path) -> None:
    import app

    import tempfile

    root, batch = analyzed
    lib = Library(_cfg(root))
    # Fresh session dirs per run, like the real helper (each run cleans its temp dir).
    monkeypatch.setattr("app.make_session_dirs",
                        lambda: (tempfile.mkdtemp(dir=tmp_path), tempfile.mkdtemp(dir=tmp_path)))
    calls = {"normalize": 0}
    real = app.normalize_video

    def counting(*a, **k):
        calls["normalize"] += 1
        return real(*a, **k)

    monkeypatch.setattr("app.normalize_video", counting)
    quiet = lambda *a, **k: None  # noqa: E731
    first = app.generate_from_library(lib, batch.asset_ids[0], None, progress=quiet)
    assert len(first) == 5 and first[3], first[4]
    second = app.generate_from_library(lib, batch.asset_ids[0], None, progress=quiet)
    assert calls["normalize"] == 1, "second run must reuse the cached normalized proxy"
    assert "reused the library's normalized source" in second[4]
    for clip in second[3]:
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                          "json", clip], capture_output=True, text=True, check=True).stdout)
        assert 0 < float(info["format"]["duration"]) <= 12.5
    # The managed original is untouched (read-only, same bytes).
    orig = lib.path_of(lib.get_asset(batch.asset_ids[0]).original_ref)
    import hashlib

    assert hashlib.sha256(orig.read_bytes()).hexdigest() == lib.get_asset(batch.asset_ids[0]).content_hash
    assert app.generate_from_library(lib, "ast_missing", None, progress=quiet)[4].startswith("Error")


def test_known_transcript_skips_asr(tmp_path: Path, video, monkeypatch) -> None:
    import app
    from models.schemas import TranscriptSegment

    temp_dir, out_dir = tmp_path / "t", tmp_path / "o"
    temp_dir.mkdir()
    out_dir.mkdir()
    monkeypatch.setattr("app.make_session_dirs", lambda: (str(temp_dir), str(out_dir)))

    def no_asr(*a, **k):
        raise AssertionError("ASR must not run when the library already has the transcript")

    monkeypatch.setattr("app.transcribe", no_asr)
    seg = [TranscriptSegment(1.0, 6.0, "our quarterly roadmap review starts now")]
    out = app.run_pipeline(str(video["path"]), None, progress=lambda *a, **k: None, known_transcript=seg)
    assert "reused the library transcript (1 segment(s))" in out[4], out[4]
