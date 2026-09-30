# F05 — Face Detection and Tracking — Implementation

## File Location

`services/face_track.py`

## Dependencies

- `mediapipe` — `mp.solutions.face_detection`
- `cv2` (opencv-python-headless)
- `numpy`
- `models/schemas.py` — `FaceTrack`
- `models/settings.py` — `Settings.face_sample_fps`, `Settings.face_confidence`

## Core Function Signature

```python
def track_faces(norm_path: str, sample_fps: float = 2.0) -> FaceTrack:
    """
    Sample frames at sample_fps, detect dominant face, return FaceTrack.
    Always returns a valid FaceTrack (fallback center on no-face frames).
    """
```

## Implementation Outline

```python
import cv2
import mediapipe as mp
import numpy as np

def track_faces(norm_path: str, sample_fps: float = 2.0) -> FaceTrack:
    cap = cv2.VideoCapture(norm_path)
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    interval = max(1, int(video_fps / sample_fps))
    
    detector = mp.solutions.face_detection.FaceDetection(
        model_selection=0,          # short-range model, good for talking heads
        min_detection_confidence=0.5
    )
    
    frame_times, cx_list, cy_list, visible_count = [], [], [], 0
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % interval == 0:
            t = frame_idx / video_fps
            cx, cy, detected = _detect_face_center(frame, detector)
            frame_times.append(t)
            cx_list.append(cx)
            cy_list.append(cy)
            if detected:
                visible_count += 1
        frame_idx += 1
    
    cap.release()
    detector.close()
    
    total = len(frame_times)
    visibility_ratio = visible_count / total if total > 0 else 0.0
    stability_score = _compute_stability(cx_list, cy_list)
    
    return FaceTrack(
        frame_times=frame_times,
        centers_x=cx_list,
        centers_y=cy_list,
        visibility_ratio=visibility_ratio,
        stability_score=stability_score,
    )


def _detect_face_center(frame, detector):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = frame.shape[:2]
    result = detector.process(rgb)
    if result.detections:
        bbox = result.detections[0].location_data.relative_bounding_box
        cx = bbox.xmin + bbox.width / 2
        cy = bbox.ymin + bbox.height / 2
        return cx, cy, True
    return 0.5, 0.5, False


def _compute_stability(cx_list, cy_list):
    if len(cx_list) < 2:
        return 1.0
    var_x = float(np.var(cx_list))
    var_y = float(np.var(cy_list))
    raw_stability = 1.0 - min(1.0, (var_x + var_y) * 10)
    return max(0.0, raw_stability)
```

## Notes

- `model_selection=0` is the short-range model; adequate for typical talking-head framing.
- `detector.close()` must be called to release MediaPipe resources.
- `cap.release()` must be called regardless of exception (consider try/finally).
- The `* 10` scaling in stability is empirical — adjust if results are poorly differentiated.
