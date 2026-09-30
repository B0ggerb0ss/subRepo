"""Gate 5 — Face tracking validation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from gate_common import check, summarize
from tests.support.media_factory import make_scene_cut_video

import services.face_track as face_track_module


class _DummyDetector:
    def close(self) -> None:
        return None


def main() -> int:
    print("\n=== Gate 5 — Face Analysis ===\n")
    with tempfile.TemporaryDirectory(prefix="attentionx_gate5_") as tmp:
        video_path = make_scene_cut_video(Path(tmp) / "no-face.mp4", duration=4.0, cut_at=2.0)

        fallback_track = face_track_module.track_faces(str(video_path), sample_fps=1.0)

        original_build = face_track_module._build_detector
        original_detect = face_track_module._detect_face_center
        coords = iter(
            [
                (0.42, 0.48, True),
                (0.50, 0.48, True),
                (0.58, 0.47, True),
                (0.60, 0.47, True),
            ]
        )
        face_track_module._build_detector = lambda: _DummyDetector()
        face_track_module._detect_face_center = lambda frame, detector: next(coords, (0.60, 0.47, True))
        try:
            detected_track = face_track_module.track_faces(str(video_path), sample_fps=1.0)
        finally:
            face_track_module._build_detector = original_build
            face_track_module._detect_face_center = original_detect

    max_jump = max(
        abs(right - left)
        for left, right in zip(detected_track.centers_x, detected_track.centers_x[1:])
    )
    results = [
        check(
            "fallback activates without exception on a no-face clip",
            lambda: fallback_track.visibility_ratio == 0.0 and set(fallback_track.centers_x) == {0.5}
            or (_ for _ in ()).throw(RuntimeError("fallback centers not applied")),
        ),
        check(
            "face centers returned for a speaking clip path",
            lambda: detected_track.visibility_ratio > 0.5 or (_ for _ in ()).throw(RuntimeError("visibility ratio too low")),
        ),
        check(
            "centers change smoothly",
            lambda: max_jump <= 0.2 or (_ for _ in ()).throw(RuntimeError(f"max jump {max_jump:.3f} exceeds threshold")),
        ),
    ]
    return summarize(5, results)


if __name__ == "__main__":
    sys.exit(main())
