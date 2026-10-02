"""F10 — Vertical Crop and Render

Spec reference: Features/F10-vertical-render/SPEC.md

Range contract: the output covers exactly [start, end) of the source. Trim,
crop and caption burn-in happen in one re-encoding pass with input seeking, so
the subtitle clock starts at 0 together with the clip (no keyframe-aligned
stream copy that can start early or run long).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from models.schemas import FaceTrack, RenderError, ScoredSegment
from utils.ffmpeg_utils import get_video_dimensions, probe_streams, run_ffmpeg

OUTPUT_WIDTH = 720
OUTPUT_HEIGHT = 1280


@dataclass(frozen=True)
class VerticalGeometry:
    mode: str      # "crop" when the source is wider than 9:16, else "pad"
    crop_w: int
    crop_h: int
    crop_x: int
    filter: str    # ffmpeg filter chain producing OUTPUT_WIDTH x OUTPUT_HEIGHT


def plan_vertical_geometry(width: int, height: int, face_cx: float) -> VerticalGeometry:
    """Aspect-fit a source frame into 9:16.

    Wider sources get a face-anchored 9:16 crop. Sources that are already
    narrower than 9:16 cannot be cropped to that ratio; they are scaled to fit
    and padded instead (the audit reproduced a crash here).
    """
    if width <= 0 or height <= 0:
        raise RenderError(f"invalid source dimensions {width}x{height}")
    crop_w = (int(height * 9 / 16) // 2) * 2
    if crop_w >= 2 and crop_w <= width:
        cx_px = min(max(face_cx, 0.0), 1.0) * width
        crop_x = int(max(0, min(cx_px - crop_w / 2, width - crop_w)))
        chain = f"crop={crop_w}:{height}:{crop_x}:0,scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
        return VerticalGeometry("crop", crop_w, height, crop_x, chain)
    chain = (
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )
    return VerticalGeometry("pad", width, height, 0, chain)


def _escape_filter_path(path: Path) -> str:
    # Escape characters that are special inside an ffmpeg filter argument.
    s = str(path)
    for ch in ("\\", ":", "'", ",", "[", "]", ";"):
        s = s.replace(ch, "\\" + ch)
    return s


def render_vertical_clip(
    norm_path: str,
    scored_seg: ScoredSegment,
    srt_path: str,
    face_track: FaceTrack,
    clip_index: int,
    temp_dir: str,
    output_dir: str,
) -> str:
    """Trim, crop/pad to 9:16, burn captions, export H.264 MP4.

    Returns path to the final clip. Raises RenderError on failure.
    """
    c = scored_seg.candidate
    if not c.end > c.start >= 0:
        raise RenderError(f"invalid clip range [{c.start}, {c.end})")
    output = Path(output_dir) / f"clip_{clip_index}.mp4"

    W, H = get_video_dimensions(norm_path)
    geometry = plan_vertical_geometry(W, H, _mean_face_cx(face_track, c.start, c.end))
    has_audio = _has_audio(norm_path)

    vf = geometry.filter
    srt_abs = Path(srt_path).resolve()
    if srt_abs.exists() and srt_abs.stat().st_size > 0:
        vf += f",subtitles={_escape_filter_path(srt_abs)}"

    args = [
        "-ss", f"{c.start:.3f}",
        "-i", norm_path,
        "-t", f"{c.end - c.start:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
    ]
    args += ["-c:a", "aac", "-b:a", "128k"] if has_audio else ["-an"]
    args += ["-movflags", "+faststart", "-y", str(output)]
    run_ffmpeg(args)

    _verify_output(str(output), OUTPUT_WIDTH, OUTPUT_HEIGHT, require_audio=has_audio)
    return str(output.resolve())


def _has_audio(path: str) -> bool:
    streams = probe_streams(path).get("streams", [])
    return any(s.get("codec_type") == "audio" for s in streams)


def _mean_face_cx(face_track: FaceTrack, start: float, end: float) -> float:
    mask = face_track.detection_mask()
    visible = [
        cx
        for t, cx, detected in zip(face_track.frame_times, face_track.centers_x, mask)
        if detected and start <= t <= end
    ]
    if visible:
        return float(np.mean(visible))
    return 0.5


def _verify_output(path: str, expected_w: int, expected_h: int, require_audio: bool = True) -> None:
    streams = probe_streams(path)
    video = next(
        (s for s in streams.get("streams", []) if s["codec_type"] == "video"), None
    )
    audio = next(
        (s for s in streams.get("streams", []) if s["codec_type"] == "audio"), None
    )
    if not video:
        raise RenderError(f"no video stream in rendered output: {path}")
    if require_audio and audio is None:
        raise RenderError(f"no audio stream in rendered output: {path}")
    if video.get("codec_name") != "h264":
        raise RenderError(
            f"rendered output codec is not h264: {video.get('codec_name')}"
        )
    w = int(video["width"])
    h = int(video["height"])
    if (w, h) != (expected_w, expected_h):
        raise RenderError(
            f"output size is not {expected_w}x{expected_h} 9:16 — got {w}x{h}"
        )
