# F10 — Vertical Crop and Render — Implementation

## File Location

`services/render.py`

## Dependencies

- `subprocess` (stdlib)
- `json` (stdlib)
- `pathlib` (stdlib)
- `utils/ffmpeg_utils.py` — `run_ffmpeg()`, `probe_streams()`, `get_video_dimensions()`
- `models/schemas.py` — `ScoredSegment`, `FaceTrack`, `RenderError`

## Core Function Signature

```python
def render_vertical_clip(
    norm_path: str,
    scored_seg: ScoredSegment,
    srt_path: str,
    face_track: FaceTrack,
    clip_index: int,
    temp_dir: str,
    output_dir: str,
) -> str:
    """
    Trim, crop to 9:16, burn captions, export MP4.
    Returns path to final clip. Raises RenderError on failure.
    """
```

## Step-by-Step Implementation

```python
from pathlib import Path
import numpy as np

def render_vertical_clip(norm_path, scored_seg, srt_path, face_track,
                          clip_index, temp_dir, output_dir):
    c = scored_seg.candidate
    temp_seg = Path(temp_dir) / f"seg_{clip_index}.mp4"
    output   = Path(output_dir) / f"clip_{clip_index}.mp4"
    
    # Step 1: Trim
    run_ffmpeg([
        "-ss", str(c.start), "-to", str(c.end),
        "-i", norm_path,
        "-c", "copy", "-y", str(temp_seg)
    ])
    
    # Step 2: Compute crop
    W, H = get_video_dimensions(norm_path)
    crop_w = int(H * 9 / 16)
    crop_h = H
    cx = _mean_face_cx(face_track, c.start, c.end)
    cx_px = cx * W
    crop_x = int(max(0, min(cx_px - crop_w / 2, W - crop_w)))
    
    # Step 3: Crop + captions + export
    srt_abs = Path(srt_path).resolve()
    vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,subtitles={srt_abs}"
    run_ffmpeg([
        "-i", str(temp_seg),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", str(output)
    ])
    
    # Step 4: Verify
    _verify_output(str(output), crop_w, crop_h)
    return str(output)


def _mean_face_cx(face_track: FaceTrack, start: float, end: float) -> float:
    in_window = [
        cx for t, cx in zip(face_track.frame_times, face_track.centers_x)
        if start <= t <= end
    ]
    visible = [cx for cx in in_window if cx != 0.5]
    if visible:
        return float(np.mean(visible))
    return 0.5   # center fallback


def _verify_output(path, expected_w, expected_h):
    streams = probe_streams(path)
    video = next((s for s in streams["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise RenderError("no video stream in output")
    w = int(video["width"])
    h = int(video["height"])
    if w * 16 != h * 9:
        raise RenderError(f"output not 9:16: {w}x{h}")
```

## utils/ffmpeg_utils.py Interface

```python
def run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with args. Raises RenderError on non-zero exit."""

def probe_streams(path: str) -> dict:
    """Return ffprobe JSON output for path."""

def get_video_dimensions(path: str) -> tuple[int, int]:
    """Return (width, height) of first video stream."""
```

## Notes

- SRT path is resolved to absolute before passing to FFmpeg subtitles filter —
  the filter does not handle relative paths consistently across platforms.
- `_mean_face_cx` filters out fallback (0.5) values so center crop doesn't average with tracked positions.
- `shell=False` is enforced in `run_ffmpeg`; args must be a list, never a string.
- The subtitles filter may require `libass` to be compiled into the FFmpeg binary.
  On HF Spaces, use `packages.txt: ffmpeg` which includes libass by default.
