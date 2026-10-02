"""Gate 1 — Environment smoke test.

Run from the repo root:
    python scripts/gate1_smoke.py

Checks every Gate 1 criterion from roadmap.md and prints PASS/FAIL per item.
Exit code 0 = all pass. Exit code 1 = one or more failures.
"""
from __future__ import annotations

import subprocess
import sys


def check(label: str, fn) -> bool:
    try:
        fn()
        print(f"  [PASS] {label}")
        return True
    except Exception as e:
        print(f"  [FAIL] {label}: {e}")
        return False


def _import(name: str):
    __import__(name)


def _cmd_ok(cmd: list[str]):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"exit code {r.returncode}")


def main() -> int:
    print("\n=== Gate 1 — Environment ===\n")
    results = [
        check("import gradio",         lambda: _import("gradio")),
        check("import librosa",        lambda: _import("librosa")),
        check("import mediapipe",      lambda: _import("mediapipe")),
        check("import cv2",            lambda: _import("cv2")),
        check("import scenedetect",    lambda: _import("scenedetect")),
        check("ffmpeg -version",       lambda: _cmd_ok(["ffmpeg", "-version"])),
        check("ffprobe -version",      lambda: _cmd_ok(["ffprobe", "-version"])),
    ]
    print()
    passed = sum(results)
    total  = len(results)
    if passed == total:
        print(f"GATE 1: PASS ({passed}/{total})")
        return 0
    else:
        print(f"GATE 1: FAIL ({passed}/{total} passed)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
