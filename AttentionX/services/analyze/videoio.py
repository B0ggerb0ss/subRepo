"""Video probing and bounded keyframe sampling (FFmpeg/ffprobe + OpenCV).

Light module (no model imports) so ingest can validate videos cheaply.
See services/analyze/video.py for the analysis stages.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from services.analyze import pixels as px

KEYFRAME_POLICY = "fps-sample+content-change(64x36, |d|>25 on >=1% px)+budgeted-min-gap+max-gap"
CHANGE_PIXEL_DELTA = 25
CHANGE_FRACTION = 0.01
VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
_MIME = {"mov,mp4,m4a,3gp,3g2,mj2": "video/mp4", "matroska,webm": "video/webm"}


class VideoAdmissionError(px.ImageAdmissionError):
    pass


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def _rotation(stream: dict) -> int:
    rot = 0
    tag = (stream.get("tags") or {}).get("rotate")
    if tag:
        try:
            rot = int(float(tag))
        except ValueError:
            rot = 0
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    return rot % 360


def _rate(s: str | None) -> float | None:
    if not s or s in {"0/0", "0"}:
        return None
    try:
        n, _, d = s.partition("/")
        v = float(n) / float(d or 1)
        return round(v, 4) if v > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe_video(path: Path, max_bytes: int, max_seconds: float) -> dict:
    """Validate a video file with ffprobe. Raises VideoAdmissionError (sanitized)."""
    try:
        size = path.stat().st_size
    except OSError as e:
        raise VideoAdmissionError("io_error", "file could not be read") from e
    if size > max_bytes:
        raise VideoAdmissionError("too_large", f"video exceeds {max_bytes // (1024 * 1024)} MB")
    if size == 0:
        raise VideoAdmissionError("empty_file", "empty file")
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=False)
    except FileNotFoundError as e:
        raise VideoAdmissionError("ffprobe_missing", "ffprobe is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise VideoAdmissionError("probe_timeout", "video probe timed out") from e
    if res.returncode != 0:
        raise VideoAdmissionError("corrupt_video", "not a readable video file")
    try:
        info = json.loads(res.stdout or "{}")
    except json.JSONDecodeError as e:
        raise VideoAdmissionError("corrupt_video", "not a readable video file") from e
    streams = info.get("streams", [])
    fmt = info.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    if v is None or not v.get("width") or not v.get("height"):
        raise VideoAdmissionError("no_video_stream", "file has no video stream")
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float(fmt.get("duration") or v.get("duration") or 0)
    except ValueError:
        duration = 0.0
    if duration <= 0:
        raise VideoAdmissionError("unknown_duration", "video duration could not be determined")
    if duration > max_seconds:
        raise VideoAdmissionError("too_long", f"video longer than {int(max_seconds // 60)} minutes")
    rot = _rotation(v)
    w, h = int(v["width"]), int(v["height"])
    if rot in (90, 270):
        w, h = h, w
    container = fmt.get("format_name", "unknown")
    return {
        "container": container, "mime": _MIME.get(container, "video/x-unknown"),
        "ext": path.suffix.lower().lstrip(".") or "mp4",
        "duration_s": round(duration, 3), "fps": _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate")),
        "width": w, "height": h, "rotation": rot, "video_codec": v.get("codec_name"),
        "has_audio": a is not None, "audio_codec": a.get("codec_name") if a else None,
    }


# ---------------------------------------------------------------------------
# Keyframe sampling (one bounded streaming decode)
# ---------------------------------------------------------------------------

def _analysis_size(w: int, h: int, long_edge: int) -> tuple[int, int]:
    s = min(1.0, long_edge / max(w, h))
    return max(2, round(w * s / 2) * 2), max(2, round(h * s / 2) * 2)


def _signature(rgb: np.ndarray) -> np.ndarray:
    import cv2

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)


def sample_keyframes(src: Path, probe: dict, out_dir: Path, sample_fps: float, max_gap_s: float,
                     max_keyframes: int, long_edge: int, cancel_check=None) -> dict:
    """Decode once at ``sample_fps`` and keep keyframes. Returns frames + coverage.

    The keyframe budget is spread over the whole video instead of being spent at
    the start: consecutive keyframes are at least ``min_gap`` apart, with
    ``min_gap = max(1/sample_fps, duration / (max_keyframes - 1))``. Busy footage
    (constant motion) is therefore sampled more sparsely but *completely*; the
    effective density is returned and recorded. The cap remains a hard guard.
    """
    import cv2

    duration = float(probe["duration_s"])
    min_gap = max(1.0 / sample_fps, duration / max(1, max_keyframes - 1))
    max_gap_s = max(max_gap_s, min_gap)

    W, H = _analysis_size(probe["width"], probe["height"], long_edge)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-an", "-sn",
           "-vf", f"fps={sample_fps},scale={W}:{H}:flags=area", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = W * H * 3
    kept: list[dict] = []
    last_sig = None
    last_t = -1e9
    i = 0
    complete = True
    reason = None
    t_reached = 0.0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            t = round(i / sample_fps, 3)
            i += 1
            t_reached = t
            rgb = np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 3)
            sig = _signature(rgb)
            why = None
            if last_sig is None:
                why = "first"
            elif t - last_t < min_gap - 1e-6:
                continue  # a change seen now is still visible (and kept) at the next allowed sample
            elif (np.abs(sig - last_sig) > CHANGE_PIXEL_DELTA).mean() >= CHANGE_FRACTION:
                why = "content_change"
            elif t - last_t >= max_gap_s:
                why = "max_gap"
            if why is None:
                continue
            if len(kept) >= max_keyframes:
                complete = False
                reason = f"keyframe cap ({max_keyframes}) reached at {t:.1f}s of {probe['duration_s']:.1f}s"
                t_reached = t
                break
            fid = f"f{len(kept):04d}"
            path = out_dir / f"{fid}.jpg"
            if not path.exists():
                ok, enc = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
                if not ok:
                    raise RuntimeError("keyframe encode failed")
                tmp = path.with_suffix(".part")
                tmp.write_bytes(enc.tobytes())
                tmp.replace(path)
            kept.append({"frame_id": fid, "t_s": t, "reason": why, "width": W, "height": H,
                         "dhash64": px.dhash64(rgb)})
            last_sig, last_t = sig, t
            if cancel_check is not None and len(kept) % 8 == 0:
                cancel_check()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        err = proc.stderr.read().decode("utf-8", "replace")[-400:] if proc.stderr else ""
        proc.stderr.close()
        proc.wait()
    if not kept:
        raise RuntimeError("no frames decoded" + (f": {err.strip().splitlines()[-1]}" if err.strip() else ""))
    dur = float(probe["duration_s"])
    end = dur if complete else t_reached
    for k, nxt in zip(kept, kept[1:] + [None]):
        k["t_end_s"] = round(nxt["t_s"] if nxt else max(end, k["t_s"] + 1.0 / sample_fps), 3)
    return {"keyframes": kept, "complete": complete, "incomplete_reason": reason,
            "coverage_end_s": round(end, 3), "frames_decoded": i, "size": [W, H],
            "min_gap_s": round(min_gap, 3), "max_gap_s": round(max_gap_s, 3)}


