"""Native FFmpeg checks for the legacy video fixes (no mocks of ffmpeg)."""
from __future__ import annotations

from pathlib import Path

import pytest

import app
from models.schemas import CandidateSegment, FaceTrack, ScoredSegment, TranscriptSegment
from services.captions import generate_srt
from services.render import render_vertical_clip
from tests.support.media_factory import ffprobe_json, make_testsrc_video


def _no_face() -> FaceTrack:
    return FaceTrack([0.0], [0.5], [0.5], 0.0, 1.0, detected=[False])


def _scored(start: float, end: float) -> ScoredSegment:
    seg = TranscriptSegment(start, end, "exact range caption check with every token kept")
    cand = CandidateSegment(start, end, seg.text, [seg], 0.0, 0.0, 1.0, end - start)
    return ScoredSegment(cand, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def _duration(path: str) -> float:
    return float(ffprobe_json(path, "format=duration")["format"]["duration"])


def test_narrow_portrait_source_renders_padded_clip(media_dir: Path, tmp_path: Path) -> None:
    src = make_testsrc_video(media_dir / "narrow.mp4", duration=3.0, width=360, height=720)
    srt = generate_srt(_scored(0.5, 2.0), 0, str(tmp_path))
    out = render_vertical_clip(str(src), _scored(0.5, 2.0), srt, _no_face(), 0, str(tmp_path), str(tmp_path))
    video = next(s for s in ffprobe_json(out, "stream=codec_type,width,height")["streams"]
                 if s["codec_type"] == "video")
    assert (int(video["width"]), int(video["height"])) == (720, 1280)


def test_render_covers_requested_range(source_video: Path, tmp_path: Path) -> None:
    # Audit: a requested 1.5 s range produced a 1.625 s container via stream copy.
    scored = _scored(1.0, 2.5)
    srt = generate_srt(scored, 0, str(tmp_path))
    out = render_vertical_clip(str(source_video), scored, srt, _no_face(), 0, str(tmp_path), str(tmp_path))
    # One frame at 24 fps (plus AAC priming) is the tolerance of a re-encoded cut.
    assert abs(_duration(out) - 1.5) <= 0.07


def test_generate_workflow_accepts_silent_video(media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    silent = make_testsrc_video(media_dir / "silent.mp4", duration=8.0, with_audio=False)
    temp_dir, output_dir = tmp_path / "temp", tmp_path / "out"
    temp_dir.mkdir()
    output_dir.mkdir()
    monkeypatch.setattr("app.make_session_dirs", lambda: (str(temp_dir), str(output_dir)))

    def _fail_asr(*args, **kwargs):
        raise AssertionError("ASR must not run for a silent source")

    monkeypatch.setattr("app.transcribe", _fail_asr)
    clip1, clip2, clip3, downloads, status = app.run_pipeline(
        str(silent), None, progress=lambda *a, **k: None
    )
    assert clip1 is not None, status
    assert downloads == [clip1]
    assert "silent source" in status
    streams = ffprobe_json(clip1, "stream=codec_type")["streams"]
    assert {s["codec_type"] for s in streams} == {"video"}


def test_generate_degrades_visibly_without_asr_weights(source_video: Path, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    temp_dir, output_dir = tmp_path / "temp", tmp_path / "out"
    temp_dir.mkdir()
    output_dir.mkdir()
    monkeypatch.setattr("app.make_session_dirs", lambda: (str(temp_dir), str(output_dir)))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("ATTENTIONX_WHISPER_DIR", str(tmp_path / "no-whisper-weights"))
    clip1, _, _, downloads, status = app.run_pipeline(str(source_video), None, progress=lambda *a, **k: None)
    assert clip1 is not None and downloads == [clip1]
    assert "ASR unavailable" in status and "without transcript" in status
