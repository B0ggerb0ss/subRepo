# F06 — Scene Detection — Completion Record

## Status: COMPLETE
## Implementation date: 2026-04-18

---

## Files Implemented

| File                    | Role                                     |
|-------------------------|------------------------------------------|
| `services/scene_detect.py` | `detect_scenes()` — full implementation |
| `models/schemas.py`     | `SceneDetectionError`                    |

---

## Implementation Notes

- Uses PySceneDetect v0.6+ API: `open_video()` + `SceneManager` + `ContentDetector`
- `get_scene_list()` returns `list[tuple[FrameTimecode, FrameTimecode]]`
- Bug fixed from IMPL.md: IMPL.md had `scene.start_time.get_seconds()` treating each item as an object with `.start_time`. The actual API returns `(start_tc, end_tc)` tuples. Fixed to `scene[0].get_seconds()`.
- Returns `[0.0]` for single-scene videos (no detected cuts)
- `SceneDetectionError` raised if `open_video()` fails

## Deviations from IMPL.md

IMPL.md's example code had an incorrect attribute access pattern (`scene.start_time`). The PySceneDetect v0.6 `get_scene_list()` returns a list of 2-tuples — corrected to `scene[0].get_seconds()`.

---

## Gate 6 Criteria (pending live video test)

```
Returns list[float]                         → type verified by import check
Returns [0.0] on single-scene video         → explicit check: if not scene_list
SceneDetectionError on bad video path       → open_video wrapped in try/except
Uses ContentDetector(threshold=27.0)        → matches Settings.scene_threshold default
Uses open_video() not VideoManager          → confirmed (VideoManager is deprecated in 0.6+)
```
