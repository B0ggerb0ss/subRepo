"""Shared helpers for AttentionX validation gates."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.media_factory import ensure_mplconfig, make_scene_cut_video

ensure_mplconfig()
Path("/tmp/attentionx-numba").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/attentionx-numba")

DEFAULT_TEST_VIDEO = REPO_ROOT / "data" / "test" / "test_video.mp4"


def check(label: str, fn) -> bool:
    try:
        detail = fn()
        suffix = f" ({detail})" if detail else ""
        print(f"  [PASS] {label}{suffix}")
        return True
    except Exception as exc:
        print(f"  [FAIL] {label}: {exc}")
        return False


def summarize(gate_number: int, results: list[bool]) -> int:
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"\nGATE {gate_number}: PASS ({passed}/{total})")
        return 0
    print(f"\nGATE {gate_number}: FAIL ({passed}/{total} passed)")
    return 1


def ensure_test_video(path: str | None = None) -> Path:
    target = Path(path) if path else DEFAULT_TEST_VIDEO
    if target.exists() and target.stat().st_size > 0:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    return make_scene_cut_video(target, duration=6.0, cut_at=3.0)
