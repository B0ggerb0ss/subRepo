from __future__ import annotations

from pathlib import Path

import pytest

from models.schemas import AudioExtractionError, NormalizationError
from services.ingest import extract_audio, normalize_video


def test_normalize_video_returns_absolute_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_file = tmp_path / "output_norm.mp4"

    def fake_run_ffmpeg(args: list[str]) -> None:
        output_file.write_bytes(b"mp4")

    monkeypatch.setattr("services.ingest.run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        "services.ingest.probe_streams",
        lambda path: {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        },
    )

    normalized = normalize_video("input.mov", str(tmp_path))

    assert normalized == str(output_file.resolve())


def test_normalize_video_raises_when_codec_is_not_h264(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "output_norm.mp4").write_bytes(b"mp4")
    monkeypatch.setattr("services.ingest.run_ffmpeg", lambda args: None)
    monkeypatch.setattr(
        "services.ingest.probe_streams",
        lambda path: {
            "streams": [
                {"codec_type": "video", "codec_name": "vp9"},
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        },
    )

    with pytest.raises(NormalizationError):
        normalize_video("input.mov", str(tmp_path))


def test_extract_audio_raises_when_output_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("services.ingest.run_ffmpeg", lambda args: None)

    with pytest.raises(AudioExtractionError):
        extract_audio("norm.mp4", str(tmp_path))
