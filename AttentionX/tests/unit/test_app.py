from __future__ import annotations

from pathlib import Path

import pytest

from app import _coerce_file_paths, build_demo, run_pipeline
from models.schemas import EnergyPeak, FaceTrack, TranscriptSegment


def test_build_demo_exposes_complete_ui() -> None:
    demo = build_demo()
    labels = {
        getattr(component, "label", None)
        for component in demo.blocks.values()
        if getattr(component, "label", None)
    }

    assert "Upload Long-Form Video" in labels
    assert "Reference Shorts (optional — for style matching)" in labels
    assert "Status" in labels
    assert "Clip 1" in labels
    assert "Clip 2" in labels
    assert "Clip 3" in labels
    assert "Download All Clips" in labels


def test_run_pipeline_requires_video() -> None:
    result = run_pipeline(None, None, progress=lambda *args, **kwargs: None)

    assert result[-1] == "Error: no video uploaded."


def test_coerce_file_paths_handles_strings_and_named_files() -> None:
    class NamedFile:
        def __init__(self, name: str) -> None:
            self.name = name

    assert _coerce_file_paths(["a.mp4", NamedFile("b.mp4")]) == ["a.mp4", "b.mp4"]


def test_run_pipeline_success_with_mocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_segment,
    scored_segment,
) -> None:
    temp_dir = tmp_path / "temp"
    output_dir = tmp_path / "outputs"
    temp_dir.mkdir()
    output_dir.mkdir()
    final_clip = output_dir / "clip_0.mp4"
    final_clip.write_bytes(b"clip")

    cleanup_calls: list[str] = []

    monkeypatch.setattr("app.make_session_dirs", lambda: (str(temp_dir), str(output_dir)))
    monkeypatch.setattr(
        "app.cleanup_temp",
        lambda path: cleanup_calls.append(path) or __import__("shutil").rmtree(path, ignore_errors=True),
    )
    monkeypatch.setattr("app.normalize_video", lambda path, out: str(tmp_path / "norm.mp4"))
    monkeypatch.setattr("app.has_audio_stream", lambda path: True)
    monkeypatch.setattr("app.extract_audio", lambda path, out: str(tmp_path / "audio.wav"))
    monkeypatch.setattr(
        "app.transcribe",
        lambda wav_path, model_size: [
            TranscriptSegment(0.0, 2.0, "You need this test to pass."),
            TranscriptSegment(2.0, 4.0, "Here is the second line."),
        ],
    )
    monkeypatch.setattr(
        "app.analyze_audio_energy",
        lambda *args, **kwargs: ([EnergyPeak(0.5, 1.5, 0.8)], None),
    )
    monkeypatch.setattr(
        "app.track_faces",
        lambda *args, **kwargs: FaceTrack(
            frame_times=[0.0, 1.0],
            centers_x=[0.5, 0.52],
            centers_y=[0.5, 0.5],
            visibility_ratio=1.0,
            stability_score=1.0,
        ),
    )
    monkeypatch.setattr("app.detect_scenes", lambda *args, **kwargs: [0.0, 5.0])
    monkeypatch.setattr("app.get_duration", lambda path: 8.0)
    monkeypatch.setattr("app.build_candidates", lambda **kwargs: [candidate_segment])
    monkeypatch.setattr("app.build_style_profile", lambda refs: None)
    monkeypatch.setattr("app.score_candidates", lambda *args, **kwargs: [scored_segment])
    monkeypatch.setattr(
        "app.generate_srt",
        lambda *args, **kwargs: str(temp_dir / "clip_0.srt"),
    )
    monkeypatch.setattr(
        "app.render_vertical_clip",
        lambda **kwargs: str(final_clip),
    )

    result = run_pipeline(
        str(tmp_path / "input.mp4"),
        ["ref.mp4"],
        progress=lambda *args, **kwargs: None,
    )

    assert result[0] == str(final_clip)
    assert result[3] == [str(final_clip)]
    assert result[4] == "Generated 1 clip(s)."
    assert cleanup_calls == [str(temp_dir)]
