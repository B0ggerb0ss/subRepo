"""Deterministic test videos rendered with FFmpeg (lavfi + drawtext).

Text overlays have known content, time windows and pixel boxes, so tests can
check timestamps and highlight geometry. Plumbing evidence only: rendered text
says nothing about OCR quality on real footage.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def make_text_video(path: Path, overlays: list[dict], duration: float = 12.0, size: tuple[int, int] = (960, 540),
                    fps: int = 25, audio: bool = False, background: str = "0x1e2a3a", rotate: int = 0) -> dict:
    """overlays: [{"text", "start", "end", "x", "y", "size"}] (pixel position of the text's top-left)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    filters = []
    for o in overlays:
        filters.append(
            f"drawtext=fontfile={FONT}:text='{_esc(o['text'])}':fontsize={o.get('size', 48)}:fontcolor=white:"
            f"x={o['x']}:y={o['y']}:enable='between(t,{o['start']},{o['end']})'")
    vf = ",".join(filters) or "null"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
           "-i", f"color=c={background}:s={w}x{h}:r={fps}:d={duration}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=22050:duration={duration}"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    if rotate:
        cmd += ["-metadata:s:v:0", f"rotate={rotate}"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True)
    return {"path": path, "duration": duration, "size": size, "overlays": overlays}
