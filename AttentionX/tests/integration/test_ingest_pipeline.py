from __future__ import annotations

from pathlib import Path

from services.ingest import extract_audio, normalize_video
from tests.support.media_factory import ffprobe_json


def test_normalize_video_and_extract_audio_real_ffmpeg(source_video: Path, tmp_path: Path) -> None:
    normalized = normalize_video(str(source_video), str(tmp_path))
    streams = ffprobe_json(normalized, "stream=codec_type,codec_name")
    stream_types = {stream["codec_type"] for stream in streams["streams"]}
    video_codec = next(
        stream["codec_name"]
        for stream in streams["streams"]
        if stream["codec_type"] == "video"
    )

    assert Path(normalized).exists()
    assert stream_types == {"video", "audio"}
    assert video_codec == "h264"

    wav_path = extract_audio(normalized, str(tmp_path))
    audio_streams = ffprobe_json(wav_path, "stream=codec_type,sample_rate,channels")
    audio = next(
        stream for stream in audio_streams["streams"] if stream["codec_type"] == "audio"
    )

    assert Path(wav_path).exists()
    assert audio["sample_rate"] == "22050"
    assert audio["channels"] == 1
