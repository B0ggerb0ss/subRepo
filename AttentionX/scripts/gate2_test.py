"""Gate 2 — Video ingestion test (F01 + F02).

Run from the repo root with any video file:
    python scripts/gate2_test.py /path/to/test_video.mp4

Tests normalize_video() and extract_audio() against a real file,
then verifies output with ffprobe and librosa.

Exit code 0 = Gate 2 PASS. Exit code 1 = one or more failures.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow running from repo root without installing as a package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import subprocess
import json

from gate_common import ensure_test_video


def ffprobe_streams(path: str) -> list[dict]:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name",
        "-of", "json", path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout).get("streams", [])


def main(video_path: str) -> int:
    print(f"\n=== Gate 2 — Video Ingestion ===")
    print(f"Input: {video_path}\n")
    failures = []

    with tempfile.TemporaryDirectory(prefix="attentionx_gate2_") as tmp:

        # --- F01: normalize_video ---
        print("[ F01 ] normalize_video()")
        try:
            from services.ingest import normalize_video
            norm_path = normalize_video(video_path, tmp)
            print(f"        output: {norm_path}")

            streams = ffprobe_streams(norm_path)
            codec_types = {s["codec_type"] for s in streams}
            codec_names = {s.get("codec_name") for s in streams}

            if "video" not in codec_types:
                failures.append("F01: no video stream in output")
            elif "h264" not in codec_names:
                failures.append(f"F01: video codec is not h264 (got {codec_names})")
            else:
                print("        ffprobe: video=h264 ✓")

            if "audio" not in codec_types:
                failures.append("F01: no audio stream in output")
            else:
                print("        ffprobe: audio stream present ✓")

        except Exception as e:
            failures.append(f"F01: normalize_video raised {type(e).__name__}: {e}")

        # --- F02: extract_audio ---
        print("\n[ F02 ] extract_audio()")
        try:
            from services.ingest import extract_audio
            wav_path = extract_audio(norm_path, tmp)
            size_kb = Path(wav_path).stat().st_size // 1024
            print(f"        output: {wav_path} ({size_kb} KB)")

            if size_kb == 0:
                failures.append("F02: audio.wav is empty")
            else:
                print(f"        size: {size_kb} KB ✓")

            # Verify with librosa
            import librosa
            y, sr = librosa.load(wav_path, sr=22050, mono=True)
            duration = len(y) / sr
            if sr != 22050:
                failures.append(f"F02: sample rate is {sr}, expected 22050")
            else:
                print(f"        librosa: sr={sr}, duration={duration:.1f}s ✓")

        except Exception as e:
            failures.append(f"F02: extract_audio raised {type(e).__name__}: {e}")

    print()
    if not failures:
        print("GATE 2: PASS")
        return 0
    else:
        print("GATE 2: FAIL")
        for f in failures:
            print(f"  ✗ {f}")
        return 1


if __name__ == "__main__":
    video_path = sys.argv[1] if len(sys.argv) >= 2 else str(ensure_test_video())
    sys.exit(main(video_path))
