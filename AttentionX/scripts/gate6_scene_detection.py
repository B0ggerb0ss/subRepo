"""Gate 6 — Scene detection validation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from gate_common import check, summarize
from services.scene_detect import detect_scenes
from tests.support.media_factory import make_scene_cut_video


def main() -> int:
    print("\n=== Gate 6 — Scene Detection ===\n")
    with tempfile.TemporaryDirectory(prefix="attentionx_gate6_") as tmp:
        video_path = make_scene_cut_video(Path(tmp) / "cut.mp4", duration=6.0, cut_at=3.0)
        boundaries = detect_scenes(str(video_path), threshold=10.0)

    false_positives = max(0, len(boundaries) - 2)
    results = [
        check(
            "non-empty scene boundary list",
            lambda: len(boundaries) > 0 or (_ for _ in ()).throw(RuntimeError("no boundaries found")),
        ),
        check(
            "detected boundary aligns with visible cut",
            lambda: any(abs(boundary - 3.0) <= 0.6 for boundary in boundaries[1:])
            or (_ for _ in ()).throw(RuntimeError(f"boundaries={boundaries}")),
        ),
        check(
            "false-positive rate stays acceptable on stable footage",
            lambda: false_positives <= 1 or (_ for _ in ()).throw(RuntimeError(f"{false_positives} extra cuts")),
        ),
    ]
    return summarize(6, results)


if __name__ == "__main__":
    sys.exit(main())
