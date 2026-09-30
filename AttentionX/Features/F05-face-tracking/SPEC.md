# F05 — Face Detection and Tracking

## Purpose

Sample frames from the normalized MP4, detect the dominant speaker's face per frame,
and produce crop-anchor coordinates for the 9:16 vertical render stage (F10).
Also computes face visibility and stability scores as engagement signals for the scorer (F08).

## Inputs

| Name       | Type  | Description                       |
|------------|-------|-----------------------------------|
| norm_path  | str   | Path to `output_norm.mp4` (F01)   |
| sample_fps | float | Frames per second to sample (default: 2.0) |

## Outputs

| Name       | Type      | Description                            |
|------------|-----------|----------------------------------------|
| face_track | FaceTrack | Per-frame centers, visibility, stability |

## Data Schemas

```python
@dataclass
class FaceTrack:
    frame_times:       list[float]   # sampled frame timestamps in seconds
    centers_x:         list[float]   # normalized [0,1] horizontal face center per frame
    centers_y:         list[float]   # normalized [0,1] vertical face center per frame
    visibility_ratio:  float         # fraction of frames where a face was detected
    stability_score:   float         # 1 - normalized_variance(centers_x, centers_y)
```

## Behavior

1. Open `norm_path` with `cv2.VideoCapture`.
2. Compute sampling interval: `interval = fps / sample_fps`.
3. For each sampled frame:
   a. Run `mp.solutions.face_detection.FaceDetection`.
   b. If face detected: extract bounding box, compute normalized center (cx, cy).
   c. If no face: use fallback center (0.5, 0.5), mark as not-visible.
4. Compute `visibility_ratio = visible_frames / total_sampled_frames`.
5. Compute `stability_score` from variance of cx and cy over visible frames.
6. Return `FaceTrack`.

## Crop Anchor Derivation

The face center `(cx, cy)` is in normalized [0, 1] coordinates.
The render stage (F10) converts to pixel coordinates:
```
pixel_cx = cx * frame_width
crop_x   = clamp(pixel_cx - crop_width / 2, 0, frame_width - crop_width)
```

## Fallback Behavior

- No face in any frame → all centers = (0.5, 0.5), visibility_ratio = 0.0
- No face in a single frame → that frame uses (0.5, 0.5)
- FaceTrack is always returned (never None); fallback is always active

## Constraints

- Sample at 2 fps by default; do not process every frame (CPU budget).
- Use `mp.solutions.face_detection` — not Face Mesh (too heavy for sampling pass).
- Face Landmarker/expressions are optional bonus signals only.
- Confidence threshold: 0.5 (MediaPipe default).
