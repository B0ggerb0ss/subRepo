# F06 — Scene Detection

## Purpose

Detect shot transitions in the normalized MP4 to produce scene-boundary timestamps.
These boundaries are used by the segment builder (F07) to construct candidate clips
that avoid starting or ending mid-cut, and to penalize segments spanning many scene changes.

## Inputs

| Name        | Type  | Description                       |
|-------------|-------|-----------------------------------|
| norm_path   | str   | Path to `output_norm.mp4` (F01)   |
| threshold   | float | ContentDetector threshold (default: 27.0) |

## Outputs

| Name             | Type         | Description                              |
|------------------|--------------|------------------------------------------|
| scene_boundaries | list[float]  | Scene-change timestamps in seconds       |

## Behavior

1. Open `norm_path` with PySceneDetect `open_video`.
2. Run `ContentDetector(threshold=27.0)` on the video.
3. Extract scene list via `SceneManager.get_scene_list()`.
4. Convert each scene's start timecode to seconds.
5. Return sorted list of boundary timestamps.

## Scene Boundary Definition

Each scene-change point is returned as a single float (seconds from start).
The first scene starts at 0.0 (not included in output; implicit).
The last frame of the video is not included (also implicit).

Example: `[0.0, 12.4, 28.1, 45.6]` means cuts at 12.4s, 28.1s, and 45.6s.

## Error Handling

- Video open failure → raise `SceneDetectionError`
- No scenes detected (entire video treated as one scene) → return `[0.0]`
  This is valid for uncut footage; the segment builder handles it gracefully.

## Threshold Tuning

| Threshold | Sensitivity | Use Case                         |
|-----------|-------------|----------------------------------|
| 15–20     | High        | Many cuts, may over-detect       |
| 27        | Medium      | Default, balanced                |
| 35–40     | Low         | Fewer detections, misses soft cuts |

Configurable via `Settings.scene_threshold`.

## Constraints

- Do not use PySceneDetect's built-in video splitter. All rendering uses FFmpeg (F10).
- Return timestamps only; do not write any files.
- Sort output ascending.
