# F06 — Scene Detection — Implementation

## File Location

`services/scene_detect.py`

## Dependencies

- `scenedetect` — `open_video`, `SceneManager`, `ContentDetector`
- `models/schemas.py` — `SceneDetectionError`
- `models/settings.py` — `Settings.scene_threshold`

## Core Function Signature

```python
def detect_scenes(norm_path: str, threshold: float = 27.0) -> list[float]:
    """
    Run ContentDetector on norm_path.
    Returns sorted list of scene-boundary timestamps in seconds.
    Returns [0.0] if no cuts detected (single-scene video).
    Raises SceneDetectionError on video open failure.
    """
```

## Implementation

```python
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector

def detect_scenes(norm_path: str, threshold: float = 27.0) -> list[float]:
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
    
    boundaries = sorted(
        scene.start_time.get_seconds()
        for scene in scene_list
    )
    return boundaries
```

## Notes

- `open_video` is the PySceneDetect v0.6+ API. Do not use the deprecated `VideoManager`.
- `get_seconds()` returns float seconds from the FrameTimecode object.
- The first scene always starts at 0.0; include it explicitly for completeness.
- For AdaptiveDetector as an alternative: `from scenedetect.detectors import AdaptiveDetector`.
  Use only if ContentDetector produces too many false positives on the test footage.
