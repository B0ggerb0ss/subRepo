"""F01 — Input Normalization  |  F02 — Audio Extraction

Both functions live here because they are the two tightly coupled ingestion steps
that always run sequentially at the start of every pipeline execution.

Spec references:
  Features/F01-input-normalization/SPEC.md
  Features/F02-audio-extraction/SPEC.md
"""
from __future__ import annotations

from pathlib import Path

from models.schemas import AudioExtractionError, NormalizationError, RenderError
from utils.ffmpeg_utils import probe_streams, run_ffmpeg


# ---------------------------------------------------------------------------
# F01 — Input Normalization
# ---------------------------------------------------------------------------

def normalize_video(input_path: str, output_dir: str) -> str:
    """Transcode input_path to H.264/AAC MP4 in output_dir.

    Returns the absolute path to output_norm.mp4.
    Raises NormalizationError on any failure.

    TC-03 decision: videos with no audio stream raise NormalizationError.
    Silent-track injection is out of scope for this MVP.
    """
    norm_path = Path(output_dir) / "output_norm.mp4"
    cmd = [
        "-i", input_path,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", str(norm_path),
    ]
    try:
        run_ffmpeg(cmd)
    except RenderError as e:
        raise NormalizationError(str(e)) from e

    if not norm_path.exists():
        raise NormalizationError("output_norm.mp4 was not created by ffmpeg")

    streams = probe_streams(str(norm_path))
    codec_types = {s.get("codec_type") for s in streams.get("streams", [])}

    if "video" not in codec_types:
        raise NormalizationError("no video stream in normalized output")
    if "audio" not in codec_types:
        raise NormalizationError(
            "no audio stream in normalized output — "
            "input video may have no audio track"
        )
    video_codec = next(
        (
            stream.get("codec_name")
            for stream in streams.get("streams", [])
            if stream.get("codec_type") == "video"
        ),
        None,
    )
    if video_codec != "h264":
        raise NormalizationError(
            f"normalized video codec is not h264: {video_codec}"
        )

    return str(norm_path.resolve())


# ---------------------------------------------------------------------------
# F02 — Audio Extraction
# ---------------------------------------------------------------------------

def extract_audio(norm_path: str, output_dir: str) -> str:
    """Extract mono WAV at 22050 Hz from norm_path.

    Returns the absolute path to audio.wav.
    Raises AudioExtractionError on failure.

    22050 Hz is the librosa default sample rate (F04) and matches
    the expected input for faster-whisper (F03).
    """
    wav_path = Path(output_dir) / "audio.wav"
    cmd = [
        "-i", norm_path,
        "-vn",
        "-ar", "22050",
        "-ac", "1",
        "-y", str(wav_path),
    ]
    try:
        run_ffmpeg(cmd)
    except RenderError as e:
        raise AudioExtractionError(str(e)) from e

    if not wav_path.exists() or wav_path.stat().st_size == 0:
        raise AudioExtractionError("audio.wav was not created or is empty")

    return str(wav_path.resolve())
