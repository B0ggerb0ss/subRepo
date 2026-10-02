"""F06 — Scene Detection

Spec reference: Features/F06-scene-detection/SPEC.md
"""
from __future__ import annotations

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector

from models.schemas import SceneDetectionError


def detect_scenes(norm_path: str, threshold: float = 27.0) -> list[float]:
    """Run ContentDetector on norm_path.

    Returns sorted list of scene-boundary timestamps in seconds.
    Returns [0.0] if no cuts detected (single-scene video).
    Raises SceneDetectionError on video open failure.
    """
    try:
        video = open_video(norm_path)
    except Exception as e:
        raise SceneDetectionError(f"cannot open video: {e}") from e

    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold))
    manager.detect_scenes(video)

    scene_list = manager.get_scene_list()
    if not scene_list:
        return [0.0]

    # Each item in scene_list is a (start_timecode, end_timecode) tuple
    boundaries = sorted(scene[0].get_seconds() for scene in scene_list)
    return boundaries
