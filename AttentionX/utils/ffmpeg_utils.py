from __future__ import annotations

import json
import subprocess
from pathlib import Path

from models.schemas import RenderError


def run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with the given argument list. shell=False is mandatory.

    Raises RenderError with stderr content on non-zero exit.
    Wraps FileNotFoundError so callers get a clean domain exception.
    """
    cmd = ["ffmpeg"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RenderError("ffmpeg not found — ensure ffmpeg is installed and on PATH")
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed (rc={result.returncode}):\n{result.stderr}")


def probe_streams(path: str) -> dict:
    """Return ffprobe stream info as a parsed dict.

    Keys include codec info plus common dimension/audio fields when present.
    Raises RenderError if ffprobe fails or output is not valid JSON.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height,sample_rate,channels",
        "-of", "json",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RenderError("ffprobe not found — ensure ffmpeg is installed and on PATH")
    if result.returncode != 0:
        raise RenderError(f"ffprobe failed (rc={result.returncode}):\n{result.stderr}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RenderError(f"ffprobe output not valid JSON: {e}") from e


def get_video_dimensions(path: str) -> tuple[int, int]:
    """Return (width, height) of the first video stream.

    Raises RenderError if no video stream found.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RenderError("ffprobe not found")
    if result.returncode != 0:
        raise RenderError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise RenderError(f"no video stream found in {path}")
    return int(streams[0]["width"]), int(streams[0]["height"])


def get_duration(path: str) -> float:
    """Return duration of the media file in seconds.

    Raises RenderError if duration cannot be determined.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RenderError("ffprobe not found")
    if result.returncode != 0:
        raise RenderError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)
    try:
        return float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError) as e:
        raise RenderError(f"could not parse duration from {path}: {e}") from e
