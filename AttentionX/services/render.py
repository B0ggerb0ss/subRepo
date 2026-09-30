"""F10 — Vertical Crop and Render

Spec reference: Features/F10-vertical-render/SPEC.md
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from models.schemas import FaceTrack, RenderError, ScoredSegment
from utils.ffmpeg_utils import get_video_dimensions, probe_streams, run_ffmpeg

OUTPUT_WIDTH = 720
OUTPUT_HEIGHT = 1280


def render_vertical_clip(
    norm_path: str,
    scored_seg: ScoredSegment,
    srt_path: str,
    face_track: FaceTrack,
    clip_index: int,
    temp_dir: str,
    output_dir: str,
) -> str:
    """Trim, crop to 9:16, burn captions, export H.264 MP4.

    Returns path to the final clip. Raises RenderError on failure.
    """
    c = scored_seg.candidate
    temp_seg = Path(temp_dir) / f"seg_{clip_index}.mp4"
    output = Path(output_dir) / f"clip_{clip_index}.mp4"

    # Step 1: Trim segment from normalized source
    run_ffmpeg([
        "-ss", str(c.start), "-to", str(c.end),
        "-i", norm_path,
        "-c", "copy", "-y", str(temp_seg),
    ])

    # Step 2: Compute face-aware crop rectangle
    W, H = get_video_dimensions(norm_path)
    crop_w = max(2, (int(H * 9 / 16) // 2) * 2)
    crop_h = H
    cx = _mean_face_cx(face_track, c.start, c.end)
    cx_px = cx * W
    crop_x = int(max(0, min(cx_px - crop_w / 2, W - crop_w)))

    # Step 3: Crop + burn captions + transcode to final output
    srt_abs = Path(srt_path).resolve()
    vf = (
        f"crop={crop_w}:{crop_h}:{crop_x}:0,"
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
        f"subtitles={srt_abs}"
    )
    run_ffmpeg([
        "-i", str(temp_seg),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", str(output),
    ])

    _verify_output(str(output), OUTPUT_WIDTH, OUTPUT_HEIGHT)
    return str(output.resolve())


def _mean_face_cx(face_track: FaceTrack, start: float, end: float) -> float:
    in_window = [
        cx
        for t, cx in zip(face_track.frame_times, face_track.centers_x)
        if start <= t <= end
    ]
    # Filter out fallback center values (0.5) to avoid biasing the crop
    visible = [cx for cx in in_window if abs(cx - 0.5) > 1e-6]
    if visible:
        return float(np.mean(visible))
    return 0.5


def _verify_output(path: str, expected_w: int, expected_h: int) -> None:
    streams = probe_streams(path)
    video = next(
        (s for s in streams.get("streams", []) if s["codec_type"] == "video"), None
    )
    audio = next(
        (s for s in streams.get("streams", []) if s["codec_type"] == "audio"), None
    )
    if not video:
        raise RenderError(f"no video stream in rendered output: {path}")
    if audio is None:
        raise RenderError(f"no audio stream in rendered output: {path}")
    if video.get("codec_name") != "h264":
        raise RenderError(
            f"rendered output codec is not h264: {video.get('codec_name')}"
        )
    w = int(video["width"])
    h = int(video["height"])
    if w * 16 != h * 9:
        raise RenderError(
            f"output aspect ratio is not 9:16 — got {w}x{h} "
            f"(expected {expected_w}x{expected_h})"
        )
