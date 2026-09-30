from __future__ import annotations

from pathlib import Path

import pytest

import app
from models.schemas import TranscriptSegment


def test_run_pipeline_renders_clip_with_real_ffmpeg(
    source_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_dir = tmp_path / "temp"
    output_dir = tmp_path / "outputs"
    temp_dir.mkdir()
    output_dir.mkdir()

    monkeypatch.setattr("app.make_session_dirs", lambda: (str(temp_dir), str(output_dir)))
    monkeypatch.setattr(
        "app.transcribe",
        lambda wav_path, model_size: [
            TranscriptSegment(0.0, 3.0, "Here is the reason this app pipeline test works."),
            TranscriptSegment(3.0, 6.0, "You need a real render path without model downloads."),
        ],
    )
    monkeypatch.setattr("app.build_style_profile", lambda refs: None)

    clip1, clip2, clip3, downloads, status = app.run_pipeline(
        str(source_video),
        None,
        progress=lambda *args, **kwargs: None,
    )

    assert clip1 is not None
    assert clip2 is None
    assert clip3 is None
    assert downloads == [clip1]
    assert status == "Generated 1 clip(s)."
    assert Path(clip1).exists()
    assert not temp_dir.exists()
