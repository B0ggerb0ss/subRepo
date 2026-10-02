from __future__ import annotations

from services.scene_detect import detect_scenes


def test_scene_detection_finds_hard_cut(scene_video) -> None:
    boundaries = detect_scenes(str(scene_video), threshold=10.0)

    assert boundaries
    assert boundaries[0] == 0.0
    assert any(abs(boundary - 3.0) <= 0.6 for boundary in boundaries[1:])
