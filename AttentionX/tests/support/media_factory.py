from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import wave
from pathlib import Path


def ensure_mplconfig(path: str | Path = "/tmp/attentionx-mpl") -> str:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(target))
    return str(target)


def run_checked(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed with rc={result.returncode}: {' '.join(cmd)}\n{result.stderr}"
        )


def ffprobe_json(path: str | Path, show_entries: str) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            show_entries,
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe failed for {path}")
    return json.loads(result.stdout)


def write_pattern_wav(
    path: str | Path,
    duration: float = 3.0,
    sample_rate: int = 22050,
    base_amplitude: float = 0.18,
    peak_amplitude: float = 0.85,
    frequency: float = 440.0,
    loud_windows: list[tuple[float, float]] | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    windows = loud_windows or [(1.0, 1.6), (2.2, 2.7)]
    total_samples = int(duration * sample_rate)

    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)

        frames = bytearray()
        for index in range(total_samples):
            t = index / sample_rate
            amplitude = base_amplitude
            for start, end in windows:
                if start <= t <= end:
                    amplitude = peak_amplitude
                    break
            value = amplitude * math.sin(2 * math.pi * frequency * t)
            clipped = max(-1.0, min(1.0, value))
            frames.extend(struct.pack("<h", int(clipped * 32767)))

        handle.writeframes(frames)

    return target


def make_testsrc_video(
    path: str | Path,
    duration: float = 6.0,
    width: int = 1280,
    height: int = 720,
    rate: int = 24,
    with_audio: bool = True,
    audio_frequency: int = 440,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=s={width}x{height}:r={rate}:d={duration}",
    ]
    if with_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={audio_frequency}:sample_rate=22050:duration={duration}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )
    else:
        cmd.extend(["-map", "0:v:0"])

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
    )
    if with_audio:
        cmd.extend(["-c:a", "aac", "-shortest"])
    cmd.extend(["-y", str(target)])
    run_checked(cmd)
    return target


def make_scene_cut_video(
    path: str | Path,
    duration: float = 6.0,
    cut_at: float = 3.0,
    width: int = 1280,
    height: int = 720,
    rate: int = 24,
    with_audio: bool = True,
    colors: tuple[str, str] = ("navy", "orange"),
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    first = max(0.5, min(cut_at, duration - 0.5))
    second = duration - first

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={colors[0]}:s={width}x{height}:r={rate}:d={first}",
        "-f",
        "lavfi",
        "-i",
        f"color=c={colors[1]}:s={width}x{height}:r={rate}:d={second}",
    ]
    if with_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=660:sample_rate=22050:duration={duration}",
            ]
        )

    cmd.extend(["-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]"])
    if with_audio:
        cmd.extend(["-map", "2:a:0"])

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
    )
    if with_audio:
        cmd.extend(["-c:a", "aac", "-shortest"])
    cmd.extend(["-y", str(target)])
    run_checked(cmd)
    return target


def parse_srt(path: str | Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []

    blocks: list[dict] = []
    for raw_block in text.split("\n\n"):
        lines = raw_block.splitlines()
        if len(lines) < 3:
            continue
        start_text, end_text = lines[1].split(" --> ", maxsplit=1)
        blocks.append(
            {
                "index": int(lines[0]),
                "start": srt_time_to_seconds(start_text),
                "end": srt_time_to_seconds(end_text),
                "lines": lines[2:],
            }
        )
    return blocks


def srt_time_to_seconds(value: str) -> float:
    hhmmss, millis = value.split(",", maxsplit=1)
    hours, minutes, seconds = hhmmss.split(":")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )
